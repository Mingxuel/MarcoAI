"""MarcoAI 新 UI v1 —— 零依赖本地服务。

启动：
    python tools/dashboard_server.py --port 8765

职责：
  * 静态托管 dashboard/（免构建，原生 ES Modules）
  * 只读转发 AIData 的 L1 加工数据（复用 AICode/MarcoAPI/UI/MarcoUI/backend_data.py 的口径）
  * 统一把 K 线时间戳规整为「本地挂钟时间按 UTC 表示」，让前端图表/十字光标显示
    与 AIData 的本地日期/时间一致（lightweight-charts 默认按 UTC 渲染）。

API：
  GET /api/health
  GET /api/meta
  GET /api/strategies
  GET /api/dashboard?strategy=TPO_M5[&refresh=1]
  GET /api/picks?strategy=TPO_M5[&refresh=1]
  GET /api/kline?code=000002.SZ&period=1d|5m|15m|30m|60m|1w|1mo&adjust=front&count=600
  GET /api/symbols

约束：不写 AIData、不触碰通达信、不修改 AICode 业务代码；backend_data 不可用时
    服务仍可启动，相关接口降级为空数据（ok=false + degraded=true）。
"""
from __future__ import annotations

import argparse
import calendar
import datetime as _dt
import importlib.util
import json
import mimetypes
import os
import posixpath
import re
import sys
import threading
import time
import traceback
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

APP_NAME = "MarcoAI Dashboard"
APP_VERSION = "1.0.0"
DEFAULT_PORT = 8765
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DASH_DIR = os.path.join(ROOT, "dashboard")
AIDATA_DIR = os.path.join(ROOT, "AIData")
TRADING_DATES_FILE = os.path.join(AIDATA_DIR, "TRADING_DATES")

# 图表库/前端可请求的周期（日线口径来自 1D，分钟口径来自 5M 重采样）
PERIODS = ["1d", "1w", "1mo", "5m", "15m", "30m", "60m"]
PERIOD_LABELS = {
    "1d": "日线", "1w": "周线", "1mo": "月线",
    "5m": "5 分钟", "15m": "15 分钟", "30m": "30 分钟", "60m": "60 分钟",
}
PERIOD_ALIASES = {
    "d": "1d", "day": "1d", "1D": "1d", "日": "1d", "日线": "1d",
    "w": "1w", "week": "1w", "周": "1w", "周线": "1w",
    "m": "1mo", "mo": "1mo", "month": "1mo", "月": "1mo", "月线": "1mo",
    "1m": "1mo",
    "5m": "5m", "15m": "15m", "30m": "30m", "60m": "60m",
    "1h": "60m", "h": "60m", "小时": "60m",
}
COUNT_DEFAULT = 600
COUNT_MAX = 4000
CODE_RE = re.compile(r"^[0-9]{6}\.(SH|SZ|BJ)$", re.IGNORECASE)

# ---------------------------------------------------------------- backend_data

BD = None
BD_ERROR = None
BD_LOCK = threading.Lock()


def load_backend():
    """importlib 加载既有解析器（失败不致命，接口降级为空）。"""
    global BD, BD_ERROR
    with BD_LOCK:
        if BD is not None or BD_ERROR is not None:
            return
        path = os.path.join(ROOT, "AICode", "MarcoAPI", "UI", "MarcoUI", "backend_data.py")
        try:
            if ROOT not in sys.path:
                sys.path.insert(0, ROOT)
            spec = importlib.util.spec_from_file_location("marco_backend_data", path)
            if spec is None or spec.loader is None:
                raise RuntimeError(f"无法加载 {path}")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            BD = mod
            print(f"[backend] loaded backend_data.py -> strategies={safe_strategies()}")
        except BaseException as exc:  # noqa: BLE001 —— 服务必须活着
            BD_ERROR = f"{type(exc).__name__}: {exc}"
            print(f"[backend] load failed, degrade to empty: {BD_ERROR}")


def safe_strategies():
    try:
        if BD is not None:
            return list(BD.get_strategies() or [])
    except BaseException as exc:  # noqa: BLE001
        print(f"[backend] get_strategies failed: {type(exc).__name__}: {exc}")
    return ["TPO_M5"]


# ---------------------------------------------------------------- small utils

def _display_ts(ts):
    """本地挂钟时间 -> 秒；前端按 UTC 渲染即显示本地日期/时间（解决时区偏移）。"""
    try:
        ts = int(ts)
    except (TypeError, ValueError):
        return 0
    if ts <= 0:
        return 0
    try:
        dt = _dt.datetime.fromtimestamp(ts)
        return calendar.timegm((dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, 0, 0, 0))
    except (OverflowError, OSError, ValueError):
        return 0


def _file_mtime(*paths):
    ts = 0.0
    for p in paths:
        try:
            ts = max(ts, os.path.getmtime(p))
        except OSError:
            continue
    return ts


def _latest_trading_date():
    try:
        with open(TRADING_DATES_FILE, "r", encoding="utf-8", errors="replace") as f:
            lines = [ln.strip() for ln in f if ln.strip()]
        return lines[-1] if lines else None
    except OSError:
        return None


def _trading_dates(count=20):
    try:
        with open(TRADING_DATES_FILE, "r", encoding="utf-8", errors="replace") as f:
            lines = [ln.strip() for ln in f if ln.strip()]
        if not count or count <= 0:
            return lines
        return lines[-count:]
    except OSError:
        return []


def _count_5m():
    try:
        return len([f for f in os.listdir(os.path.join(AIDATA_DIR, "5M"))
                    if os.path.isfile(os.path.join(AIDATA_DIR, "5M", f))])
    except OSError:
        return 0


def _session_label(latest):
    """数据日相对当前交易日的状态：数据日 = 今天 -> T-0；否则 T-1。"""
    if not latest:
        return "未找到 AIData/TRADING_DATES"
    today = _dt.date.today().strftime("%Y%m%d")
    tag = "T-0" if str(latest) == today else "T-1"
    return f"数据日 {_fmt_ymd(latest)}（{tag}）· 非实时（EOD）"


def _default_symbol():
    """默认标的：已预热则取最新选股月第一只；否则取看板首个策略股（不硬编码 000001）。"""
    try:
        for payload in list(_PICKS_CACHE.values()):
            months = payload.get("months") or []
            for m in months:
                if not m.get("hasData"):
                    continue
                for d in (payload.get("dates") or []):
                    if str(d)[:6] != m["value"]:
                        continue
                    stocks = (payload.get("picks") or {}).get(d) or []
                    if stocks:
                        return {"code": stocks[0].get("code"), "name": stocks[0].get("name") or ""}
    except BaseException:  # noqa: BLE001
        pass
    try:
        syms = get_dashboard(safe_strategies()[0] if safe_strategies() else "TPO_M5").get("syms") or []
        if syms:
            return {"code": syms[0].get("code"), "name": syms[0].get("name") or ""}
    except BaseException:  # noqa: BLE001
        pass
    return {"code": "600118.SH", "name": "中国卫星"}


def _data_version():
    ts = _file_mtime(
        TRADING_DATES_FILE,
        os.path.join(AIDATA_DIR, "1D"),
        os.path.join(AIDATA_DIR, "5M"),
        os.path.join(AIDATA_DIR, "STRATEGY", "TPO_M5"),
        os.path.join(AIDATA_DIR, "STRATEGY"),
    )
    if not ts:
        return "unknown", None
    return time.strftime("%Y%m%d-%H%M%S", time.localtime(ts)), int(ts)


def _json_default(obj):
    if isinstance(obj, (set, tuple)):
        return list(obj)
    if isinstance(obj, (_dt.datetime, _dt.date)):
        return obj.isoformat()
    return str(obj)


# ---------------------------------------------------------------- kline data

def _daily_file(code):
    for sub in ("1D", "INDEX"):
        p = os.path.join(AIDATA_DIR, sub, code)
        if os.path.isfile(p):
            return p
    return None


def _five_min_file(code):
    p = os.path.join(AIDATA_DIR, "5M", code)
    return p if os.path.isfile(p) else None


def _merge_bars(payload):
    """backend.load_kline 返回 {data:[{time,open,high,low,close}], vol:[{time,value}]}。"""
    data = (payload or {}).get("data") or []
    vol = (payload or {}).get("vol") or []
    vmap = {}
    for v in vol:
        try:
            vmap[v.get("time")] = float(v.get("value") or 0)
        except (TypeError, ValueError):
            continue
    bars = []
    for b in data:
        if not isinstance(b, dict):
            continue
        try:
            bars.append({
                "time": int(b["time"]),
                "open": float(b["open"]), "high": float(b["high"]),
                "low": float(b["low"]), "close": float(b["close"]),
                "volume": vmap.get(b["time"], 0.0),
            })
        except (KeyError, TypeError, ValueError):
            continue
    bars.sort(key=lambda x: x["time"])
    return bars


def _resample_by_local_day(bars, n):
    """5m -> 15m/30m/60m：按本地交易日分桶，每 n 根合并，避免跨日拼接。"""
    out, group, cur_day = [], [], None
    for b in bars:
        try:
            day = _dt.datetime.fromtimestamp(b["time"]).date()
        except (OverflowError, OSError, ValueError):
            continue
        if cur_day is None:
            cur_day = day
        if day != cur_day:
            if group:
                out.append(_agg(group))
            group, cur_day = [], day
        group.append(b)
        if len(group) == n:
            out.append(_agg(group))
            group = []
    if group:
        out.append(_agg(group))
    return out


def _agg(group):
    return {
        "time": group[0]["time"],
        "open": group[0]["open"],
        "high": max(x["high"] for x in group),
        "low": min(x["low"] for x in group),
        "close": group[-1]["close"],
        "volume": sum(x["volume"] for x in group),
    }


def _resample_calendar(bars, kind):
    """日线 -> 周线/月线（按本地日期归组）。"""
    out, cur_key, group = [], None, []
    for b in bars:
        try:
            dt = _dt.datetime.fromtimestamp(b["time"])
        except (OverflowError, OSError, ValueError):
            continue
        if kind == "week":
            iso = dt.isocalendar()
            key = (iso[0], iso[1])
        else:
            key = (dt.year, dt.month)
        if cur_key is None:
            cur_key = key
        if key != cur_key:
            if group:
                out.append(_agg(group))
            group, cur_key = [], key
        group.append(b)
    if group:
        out.append(_agg(group))
    return out


def _normalize_times(bars):
    for b in bars:
        b["time"] = _display_ts(b["time"])
    return bars


# ---------------------------------------------------------------- caches

_CACHE_LOCK = threading.Lock()
_KL_CACHE = {}        # (code, period, count) -> (ts, payload)
_KL_TTL = 300
_DASH_CACHE = {}      # strategy -> (ts, payload)
_DASH_TTL = 120
_PICKS_CACHE = {}     # strategy -> payload
_PICKS_LOCKS = {}
_PICKS_LOCK = threading.Lock()
_SYMS_CACHE = {"ts": 0.0, "payload": None}
_SYMS_TTL = 300

# 实时看盘数据源（tqcenter 轮询线程；None 表示未启动/依赖缺失）
FEED = None


def _picks_lock_for(strategy):
    with _PICKS_LOCK:
        lock = _PICKS_LOCKS.get(strategy)
        if lock is None:
            lock = _PICKS_LOCKS[strategy] = threading.Lock()
        return lock


def _degraded_picks(strategy, error):
    return {
        "ok": False, "degraded": True, "strategy": strategy,
        "dates": [], "picks": {}, "cand_group_dates": [],
        "latest_cand_date": None, "tpoWindow": {},
        "months": [],
        "error": error,
    }


def _add_pick_months(payload):
    """补充月份索引 / 日期元信息（T-2 按交易日历反查，不按自然日）。"""
    dates = payload.get("dates") or []
    picks = payload.get("picks") or {}
    months = {}
    for d in dates:
        if not d or len(str(d)) < 6:
            continue
        ym = str(d)[:6]
        m = months.setdefault(ym, {"value": ym, "label": ym[:4] + "-" + ym[4:6], "dates": 0, "count": 0})
        m["dates"] += 1
        m["count"] += len(picks.get(d) or [])
    out = []
    for ym in sorted(months, reverse=True):
        item = months[ym]
        item["hasData"] = item["count"] > 0
        out.append(item)
    payload["months"] = out

    # 选股日 T-2：以 AIData/TRADING_DATES 的交易日序号反查（不是自然日）
    td = _trading_dates(count=0)  # count=0 -> 取全量（见实现）
    pos = {d: i for i, d in enumerate(td)}
    meta = {}
    for d in dates:
        key = str(d)
        idx = pos.get(key)
        t2 = td[idx - 2] if (idx is not None and idx >= 2) else None
        meta[key] = {"date": key, "t0": key, "t2": t2,
                     "t2_label": _fmt_ymd(t2), "t0_label": _fmt_ymd(key)}
    payload["dateMeta"] = meta
    return payload


def _fmt_ymd(d):
    d = str(d or "")
    return d[:4] + "-" + d[4:6] + "-" + d[6:8] if len(d) == 8 else d


def _detail_row(it, date):
    """把 STRATEGY 回测明细行归一化成与历史分支同结构（与 backend_data 历史分组一致）。"""
    def _num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    mcap = None
    try:
        if hasattr(BD, "_mcap_yi"):
            mcap = BD._mcap_yi(it.get("market"))
    except BaseException:  # noqa: BLE001
        mcap = None
    return {
        "code": it.get("code"),
        "name": it.get("name", "") or "",
        "high": _num(it.get("high")),
        "low": _num(it.get("low")),
        "pre": _num(it.get("pre")),
        "chg": _num(it.get("chg")),
        "sell_chg_5m": _num(it.get("sell_chg_5m")),
        "mcap": mcap,
        "date": str(date),
        "cand": False,
    }


def _prev_trading_date(date):
    td = _trading_dates(count=0)
    try:
        i = td.index(str(date))
        return td[i - 1] if i > 0 else None
    except ValueError:
        return None


def _enrich_picks_detail(payload, strategy):
    """修复 backend_data.get_strategy_pick 的口径问题：最新两个候选日若其实有
    STRATEGY 回测明细，却被归入 cand_group_dates 只渲染候选池，导致 picks 为空、
    月份统计为 0（如 20261103 的 600118.SH/600428.SH）。

    只读包装：用 backend_data 可访问的 _load_strategy_detail 补成历史行结构，
    然后按修复后的 picks 重算 months；不改 AICode 业务代码、不写 AIData。
    """
    if BD is None or not payload or payload.get("ok") is False:
        return payload
    try:
        loader = getattr(BD, "_load_strategy_detail", None)
        if not callable(loader):
            sui = getattr(BD, "_SUI", None)
            loader = getattr(sui, "_load_strategy_detail", None)
        if not callable(loader):
            return payload
        detail = loader([strategy]) or {}
        det = detail.get(strategy) or {}
        if not isinstance(det, dict):
            return payload
    except BaseException as exc:  # noqa: BLE001
        print(f"[picks] detail enrich skipped: {type(exc).__name__}: {exc}")
        return payload

    picks = payload.get("picks")
    if not isinstance(picks, dict):
        picks = {}
    dates = [str(d) for d in (payload.get("dates") or [])]
    month_set = {d[:6] for d in dates if len(d) >= 6}
    raw_cand = [str(d) for d in (payload.get("cand_group_dates") or [])]

    added = 0
    for date, items in det.items():
        date = str(date)
        if len(date) < 8:
            continue
        # 与 backend 一致：只看最近 12 个月窗口内的日期（窗口由原 dates 的月份集合决定）
        if month_set and date[:6] not in month_set:
            continue
        if date not in dates:
            dates.append(date)
            added += 1
        rows = [_detail_row(it, date) for it in (items or []) if isinstance(it, dict)]
        # 有回测明细的日期一律以明细为准（覆盖被误当纯候选的 picks[date]）
        if rows or date in det:
            picks[date] = rows

    # 候选日期仅保留「没有回测明细且候选行非空」的日期；空候选日按普通空日期处理
    candidate_dates = []
    for date in sorted(raw_cand, reverse=True):
        if det.get(date):
            continue
        if picks.get(date):
            candidate_dates.append(date)

    # TPO 块的 T-1 基准日 = 基准日的前一个交易日（与前端的「2026-11-02（T-1）」对齐）
    tw = payload.get("tpoWindow") or {}
    today = tw.get("today")
    if today:
        prev = _prev_trading_date(today)
        if prev:
            tw["prev"] = prev
            if prev not in dates:
                dates.append(prev)
    payload["tpoWindow"] = tw

    payload["dates"] = sorted(set(dates), reverse=True)
    payload["picks"] = picks
    payload["candidate_dates"] = candidate_dates
    payload["cand_group_dates"] = candidate_dates  # 旧字段保留但语义修正
    payload["latest_candidate_date"] = candidate_dates[0] if candidate_dates else None
    payload["detailFixedDates"] = added
    return payload


def get_picks(strategy, refresh=False):
    if not refresh and strategy in _PICKS_CACHE:
        return _PICKS_CACHE[strategy]
    lock = _picks_lock_for(strategy)
    with lock:
        if not refresh and strategy in _PICKS_CACHE:
            return _PICKS_CACHE[strategy]
        started = time.time()
        if BD is None:
            payload = _degraded_picks(strategy, BD_ERROR or "backend_data 未加载")
        else:
            try:
                payload = BD.get_strategy_pick(strategy) or {}
                payload["ok"] = True
                payload["degraded"] = False
            except BaseException as exc:  # noqa: BLE001
                traceback.print_exc()
                payload = _degraded_picks(strategy, f"{type(exc).__name__}: {exc}")
        payload["cachedAt"] = int(time.time())
        payload["elapsedMs"] = int((time.time() - started) * 1000)
        # 包装层修正：有 STRATEGY 回测明细的日期不能被候选池逻辑吞掉（2026-11 等）
        _enrich_picks_detail(payload, strategy)
        _add_pick_months(payload)
        _PICKS_CACHE[strategy] = payload
        print(f"[picks] {strategy} ready in {payload['elapsedMs']} ms "
              f"(dates={len(payload.get('dates') or [])})")
        return payload


def get_dashboard(strategy, refresh=False, pick_mode="first", sell_mode="5m"):
    key = (strategy, pick_mode, sell_mode)
    now = time.time()
    hit = _DASH_CACHE.get(key)
    if hit and not refresh and now - hit[0] < _DASH_TTL:
        return hit[1]
    if BD is None:
        return {
            "ok": False, "degraded": True, "strategy": strategy,
            "pick_mode": pick_mode, "sell_mode": sell_mode,
            "syms": [], "klines": {}, "metrics": {}, "monthRet": [], "quarterRet": [],
            "yearRet": [], "capitalKline": [], "dist": {}, "strategies": safe_strategies(),
            "signals": [], "error": BD_ERROR or "backend_data 未加载",
        }
    try:
        payload = BD.get_dashboard(strategy, pick_mode=pick_mode, sell_mode=sell_mode) or {}
        payload["ok"] = True
        payload["degraded"] = False
        payload["strategies"] = safe_strategies()
        payload["pick_mode"] = pick_mode
        payload["sell_mode"] = sell_mode
        _DASH_CACHE[key] = (time.time(), payload)
        return payload
    except BaseException as exc:  # noqa: BLE001
        traceback.print_exc()
        return {
            "ok": False, "degraded": True, "strategy": strategy,
            "syms": [], "klines": {}, "metrics": {}, "monthRet": [], "quarterRet": [],
            "yearRet": [], "capitalKline": [], "dist": {}, "strategies": safe_strategies(),
            "signals": [], "error": f"{type(exc).__name__}: {exc}",
        }


def get_bplus_backtest(strategy, months=12, pick_mode="first", refresh=False, sell_mode="bplus", env_mode="s6", width_mode="s6"):
    """B+ 新卖法回测（tools/bplus_engine.py），失败返回明确错误不阻塞其它接口。"""
    empty = {
        "ok": False, "strategy": strategy, "sell_mode": sell_mode, "pick_mode": pick_mode,
        "months": months, "metrics": {}, "monthRet": [], "quarterRet": [], "yearRet": [],
        "capitalKline": [], "dist": {}, "fallbackDays": 0, "bplusDays": 0,
        "badge": "B+ 卖法 · 2026 年起生效（此前回退现状）",
        "strategies": safe_strategies(),
    }
    mod = _bplus_module()
    if mod is None:
        empty["error"] = "bplus_engine 模块不可用"
        return empty
    try:
        payload = mod.run_bplus(ROOT, strategy, months=months, pick_mode=pick_mode, refresh=refresh, sell_mode=sell_mode, env_mode=env_mode, width_mode=width_mode) or {}
        payload["strategies"] = safe_strategies()
        payload["cachedAt"] = int(time.time())
        return payload
    except BaseException as exc:  # noqa: BLE001
        traceback.print_exc()
        empty["error"] = f"{type(exc).__name__}: {exc}"
        return empty


INDEX_NAME_MAP = {
    "000001.SH": "上证指数", "399001.SZ": "深证成指", "399006.SZ": "创业板指",
    "000300.SH": "沪深300", "000852.SH": "中证1000", "000688.SH": "科创50",
    "000905.SH": "中证500", "000016.SH": "上证50", "399986.SZ": "中证银行",
    "000015.SH": "红利指数",
}
_INDEX_SERIES_CACHE = {}


def _read_index_points(code, start=None, end=None):
    """读指数日线：AIData/INDEX_1D → INDEX → INDEX_5M（按日聚合最后 close）。"""
    name = INDEX_NAME_MAP.get(code)
    if not name:
        return None
    candidates = [
        (os.path.join(AIDATA_DIR, "INDEX_1D", code), "1d"),
        (os.path.join(AIDATA_DIR, "INDEX", code), "1d"),
    ]
    points = []
    source = None
    for path, kind in candidates:
        if not os.path.isfile(path):
            continue
        try:
            text = open(path, "rb").read().decode("utf-8", "ignore")
        except OSError:
            continue
        for line in text.splitlines():
            parts = line.split("|")
            if len(parts) < 5:
                continue
            d = parts[0].strip()[:8]
            try:
                close = float(parts[4])
            except ValueError:
                continue
            if len(d) == 8 and d.isdigit() and close > 0:
                points.append((d, close))
        if points:
            source = kind
            break
    if not points:
        path = os.path.join(AIDATA_DIR, "INDEX_5M", code)
        if os.path.isfile(path):
            try:
                text = open(path, "rb").read().decode("utf-8", "ignore")
            except OSError:
                text = ""
            by_day = {}
            for line in text.splitlines():
                parts = line.split("|")
                if len(parts) < 5 or len(parts[0]) < 10:
                    continue
                d = parts[0][:10].replace("-", "")
                try:
                    close = float(parts[4])
                except ValueError:
                    continue
                if close > 0:
                    by_day[d] = close
            points = sorted(by_day.items())
            if points:
                source = "5m-agg"
    if not points:
        return None
    points.sort(key=lambda x: x[0])
    s = str(start or "").replace("-", "")[:8]
    e = str(end or "").replace("-", "")[:8]
    out = []
    for d, v in points:
        if s and d < s:
            continue
        if e and d > e:
            continue
        out.append({"date": d[:4] + "-" + d[4:6] + "-" + d[6:8], "value": v})
    return {"code": code, "name": name, "source": source, "points": out}


def get_index_series(codes, start=None, end=None):
    codes = [c.strip().upper() for c in (codes or "").split(",") if c.strip().upper()]
    codes = [c for c in codes if c in INDEX_NAME_MAP][:12]
    if not codes:
        return {"ok": False, "error": "codes 需为逗号分隔的指数代码（如 000001.SH,399006.SZ）", "indices": []}
    key = (tuple(codes), str(start or ""), str(end or ""))
    now = time.time()
    hit = _INDEX_SERIES_CACHE.get(key)
    if hit and now - hit[0] < 300:
        return hit[1]
    indices, errors = [], []
    for code in codes:
        try:
            item = _read_index_points(code, start, end)
        except BaseException as exc:  # noqa: BLE001
            traceback.print_exc()
            errors.append({"code": code, "error": f"{type(exc).__name__}: {exc}"})
            continue
        if item and item.get("points"):
            indices.append(item)
        else:
            errors.append({"code": code, "error": "本地无该指数数据"})
    payload = {"ok": True, "indices": indices, "errors": errors,
               "start": start, "end": end, "cachedAt": int(time.time())}
    _INDEX_SERIES_CACHE[key] = (now, payload)
    return payload


def get_symbols(refresh=False):
    now = time.time()
    if not refresh and _SYMS_CACHE["payload"] and now - _SYMS_CACHE["ts"] < _SYMS_TTL:
        return _SYMS_CACHE["payload"]
    seen, out = set(), []
    dash = get_dashboard(safe_strategies()[0] if safe_strategies() else "TPO_M5")
    for s in (dash.get("syms") or []):
        code = s.get("code")
        if code and code not in seen:
            seen.add(code)
            out.append({"code": code, "name": s.get("name") or ""})
    # picks 已预热则追加（未预热不主动触发 39s 计算）
    for payload in list(_PICKS_CACHE.values()):
        for stocks in (payload.get("picks") or {}).values():
            for s in stocks or []:
                code = s.get("code")
                if code and code not in seen:
                    seen.add(code)
                    out.append({"code": code, "name": s.get("name") or ""})
    for rows in ((_PICKS_CACHE.get("TPO_M5") or {}).get("tpoWindow") or {}).values() if _PICKS_CACHE else []:
        if isinstance(rows, list):
            for r in rows:
                if isinstance(r, (list, tuple)) and len(r) >= 2 and r[0] not in seen:
                    seen.add(r[0])
                    out.append({"code": r[0], "name": r[1] or ""})
    payload = {"ok": True, "count": len(out), "symbols": out}
    _SYMS_CACHE.update({"ts": now, "payload": payload})
    return payload


def _bar_ymd(v):
    if isinstance(v, (int, float)):
        try:
            return _dt.datetime.utcfromtimestamp(float(v)).strftime("%Y%m%d")
        except (ValueError, OSError):
            return ""
    m = re.search(r"(\d{4})-?(\d{2})-?(\d{2})", str(v or ""))
    return (m.group(1) + m.group(2) + m.group(3)) if m else ""


def get_kline(code, period, count, end=None):
    end = str(end or "").replace("-", "")[:8]
    key = (code, period, count, end)
    now = time.time()
    hit = _KL_CACHE.get(key)
    if hit and now - hit[0] < _KL_TTL:
        return hit[1]
    source = "5M" if period in ("5m", "15m", "30m", "60m") else "1D"
    payload = {"ok": True, "code": code, "period": period, "count": count, "end": end or None,
               "source": source, "available": False, "bars": [], "message": None}
    if BD is None:
        payload.update({"ok": False, "degraded": True, "exists": False,
                        "reason": BD_ERROR or "backend_data 未加载"})
        _KL_CACHE[key] = (now, payload)
        return payload

    # 文件存在性先判，避免 backend 对缺失 5M 触发通达信按需下载（本 UI 不碰 TDX）
    lc5_ok = False
    try:
        rmod0 = _realtime_module()
        lc5_ok = bool(rmod0 is not None and os.path.isfile(rmod0._lc5_path(code)))
    except BaseException:
        lc5_ok = False
    if period in ("5m", "15m", "30m", "60m"):
        if not _five_min_file(code) and not lc5_ok:
            reason = "暂无K线数据（本地 5M/通达信 lc5 均无该股；未触发补数）"
            payload.update({"ok": False, "exists": False, "reason": reason, "message": reason})
            _KL_CACHE[key] = (now, payload)
            return payload
    else:
        if not _daily_file(code):
            reason = "本地 1D/INDEX 数据集无该股"
            payload.update({"ok": False, "exists": False, "reason": reason, "message": reason})
            _KL_CACHE[key] = (now, payload)
            return payload

    raw_direct = False
    try:
        if end and period == "5m":
            # 按结束日取历史 5m：直接读 vipdoc lc5 原始价，避免 AIData/5M 只给最近一段
            rmod = _realtime_module()
            if rmod is not None:
                raw = rmod._parse_lc5(rmod._lc5_path(code))
                bars = [{"time": b["time"], "open": b["open"], "high": b["high"],
                         "low": b["low"], "close": b["close"], "volume": b.get("volume", 0)}
                        for b in raw if _bar_ymd(b["time"]) <= end]
                raw_direct = True
            else:
                bars = _merge_bars(BD.load_kline(code, "5m"))
        elif period == "1d":
            bars = _merge_bars(BD.load_kline(code, "1d"))
        elif period == "5m":
            bars = _merge_bars(BD.load_kline(code, "5m"))
        elif period == "15m":
            bars = _merge_bars(BD.load_kline(code, "15m"))
        elif period == "30m":
            bars = _merge_bars(BD.load_kline(code, "30m"))
        elif period == "60m":
            bars = _resample_by_local_day(_merge_bars(BD.load_kline(code, "5m")), 12)
        elif period == "1w":
            bars = _resample_calendar(_merge_bars(BD.load_kline(code, "1d")), "week")
        elif period == "1mo":
            bars = _resample_calendar(_merge_bars(BD.load_kline(code, "1d")), "month")
        else:
            bars = []
    except BaseException as exc:  # noqa: BLE001
        traceback.print_exc()
        payload.update({"ok": False, "exists": False, "message": f"{type(exc).__name__}: {exc}"})
        _KL_CACHE[key] = (now, payload)
        return payload

    if not bars and period in ("5m", "15m", "30m", "60m"):
        try:
            rmod = _realtime_module()
            if rmod is not None and lc5_ok:
                raw = rmod._parse_lc5(rmod._lc5_path(code))
                bars = [{"time": b["time"], "open": b["open"], "high": b["high"],
                         "low": b["low"], "close": b["close"], "volume": b.get("volume", 0)}
                        for b in raw]
                raw_direct = True
        except BaseException:
            pass
    if not raw_direct:
        bars = _normalize_times(bars)
    if end and len(end) == 8:
        bars = [b for b in bars if _bar_ymd(b.get("time")) <= end]
    if count and len(bars) > count:
        bars = bars[-count:]
    payload["bars"] = bars
    payload["available"] = bool(bars)
    payload["exists"] = True
    payload["count"] = len(bars)
    # 兼容小A约定的 {data[], vol[]} 形状（bars 为同源数据）
    payload["data"] = [{"time": b["time"], "open": b["open"], "high": b["high"],
                        "low": b["low"], "close": b["close"]} for b in bars]
    payload["vol"] = [{"time": b["time"], "value": b["volume"]} for b in bars]
    payload["reason"] = None
    if not bars:
        payload["reason"] = f"该股无 {PERIOD_LABELS.get(period, period)} 数据"
        payload["message"] = payload["reason"]
    _KL_CACHE[key] = (time.time(), payload)
    return payload


# ---------------------------------------------------------------- HTTP handler

class DashboardHandler(SimpleHTTPRequestHandler):
    server_version = "MarcoDashboard/1.0"
    protocol_version = "HTTP/1.1"

    # 静态资源根由 server 指定
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DASH_DIR, **kwargs)

    # -- logging ---------------------------------------------------------
    def log_message(self, fmt, *args):
        try:
            msg = fmt % args if args else str(fmt)
        except BaseException:  # noqa: BLE001
            msg = " ".join(str(x) for x in ((fmt,) + args))
        if "/api/" in msg:
            sys.stderr.write("[api] %s\n" % msg)
        else:
            sys.stderr.write("[web] %s\n" % msg)

    # -- responses -------------------------------------------------------
    def _send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False, default=_json_default).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_error_json(self, status, message):
        self._send_json({"ok": False, "error": message}, status=status)

    # -- routing ---------------------------------------------------------
    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        path = unquote(parsed.path or "/")
        query = parse_qs(parsed.query or "")
        try:
            if path.startswith("/api/"):
                self._handle_api(path, query)
                return
            self._handle_static(path)
        except (BrokenPipeError, ConnectionResetError):
            return
        except BaseException as exc:  # noqa: BLE001
            traceback.print_exc()
            try:
                self._send_error_json(500, f"{type(exc).__name__}: {exc}")
            except BaseException:  # noqa: BLE001
                pass

    def do_POST(self):  # noqa: N802
        parsed = urlparse(self.path)
        path = unquote(parsed.path or "/")
        try:
            if path == "/api/ths/test-block":
                try:
                    body = self._read_json_body()
                except BaseException as exc:  # noqa: BLE001
                    self._send_error_json(400, f"请求体解析失败: {exc}")
                    return
                month = str((body or {}).get("month") or "").strip()
                mod = _ths_test_module()
                if mod is None:
                    self._send_error_json(503, "ths_test_block 模块不可用")
                    return
                try:
                    res = mod.add_month_to_test(month, restart=True)
                    self._send_json(res)
                except BaseException as exc:  # noqa: BLE001
                    self._send_error_json(400, f"{type(exc).__name__}: {exc}")
                return
            if path == "/api/training/calc":
                mod = _training_module()
                if mod is None:
                    self._send_error_json(503, "training_engine 模块不可用")
                    return
                try:
                    body = self._read_json_body()
                except BaseException as exc:  # noqa: BLE001
                    self._send_error_json(400, f"请求体解析失败: {exc}")
                    return
                items = body.get("items") if isinstance(body, dict) else None
                if not isinstance(items, list):
                    self._send_error_json(400, "items 需为数组")
                    return
                self._send_json(mod.calc(ROOT, items, body.get("strategy") or "TPO_M5"))
                return
            if path == "/api/realtime/holdings":
                self._handle_holdings_post()
                return
            self._send_error_json(404, f"unknown api: {path}")
        except BaseException as exc:  # noqa: BLE001
            traceback.print_exc()
            self._send_error_json(500, f"{type(exc).__name__}: {exc}")

    def _read_json_body(self, limit=1_000_000):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            return None
        if length > limit:
            raise ValueError("请求体过大")
        raw = self.rfile.read(length)
        if not raw:
            return None
        return json.loads(raw.decode("utf-8", errors="replace"))

    def _handle_holdings_post(self):
        if FEED is None:
            self._send_error_json(503, "实时看盘数据源未启动")
            return
        try:
            body = self._read_json_body()
            if isinstance(body, list):
                rows = body
            elif isinstance(body, dict):
                rows = body.get("holdings")
                if rows is None and "code" in body:
                    rows = [body]
            else:
                rows = None
            if rows is None:
                raise ValueError("请求体需为持仓数组或 {\"holdings\": [...]}")
            saved = FEED.set_holdings(rows)
            self._send_json({"ok": True, "holdings": saved, "path": FEED.holdings_path,
                             "serverTime": _dt.datetime.now().isoformat(timespec="seconds")})
        except (ValueError, json.JSONDecodeError) as exc:
            self._send_error_json(400, str(exc))
        except OSError as exc:
            self._send_error_json(500, f"保存失败: {exc}")

    def _handle_api(self, path, query):
        if path == "/api/health":
            feed_info = None
            if FEED is not None:
                st = FEED.snapshot()
                feed_info = {"ok": bool(st.get("ok")), "tqReady": bool((st.get("tq") or {}).get("ready")),
                             "marketState": st.get("marketState"), "time": st.get("time"),
                             "error": st.get("error")}
            self._send_json({"ok": True, "app": APP_NAME, "version": APP_VERSION,
                             "backend": {"ok": BD is not None, "error": BD_ERROR},
                             "realtimeFeed": feed_info,
                             "serverTime": _dt.datetime.now().isoformat(timespec="seconds")})
            return
        if path == "/api/meta":
            self._send_json(self._meta())
            return
        if path == "/api/strategies":
            self._send_json({"ok": True, "strategies": safe_strategies(),
                             "degraded": BD is None, "error": BD_ERROR})
            return
        if path == "/api/dashboard":
            strategy = _q1(query, "strategy") or (safe_strategies() or ["TPO_M5"])[0]
            refresh = _truthy(_q1(query, "refresh"))
            pick_mode = (_q1(query, "pick_mode") or "first").lower()
            sell_mode = (_q1(query, "sell_mode") or "5m").lower()
            if pick_mode not in ("first", "avg", "last"):
                pick_mode = "first"
            if sell_mode not in ("5m", "day"):
                sell_mode = "5m"
            payload = get_dashboard(strategy, refresh=refresh,
                                    pick_mode=pick_mode, sell_mode=sell_mode)
            payload["cachedAt"] = int(time.time())
            self._send_json(payload)
            return
        if path == "/api/backtest/bplus":
            strategy = _q1(query, "strategy") or (safe_strategies() or ["TPO_M5"])[0]
            refresh = _truthy(_q1(query, "refresh"))
            try:
                months = int(_q1(query, "months") or 12)
            except ValueError:
                months = 12
            months = max(1, min(60, months))
            pick_mode = (_q1(query, "pick_mode") or "first").lower()
            if pick_mode not in ("first", "avg", "last"):
                pick_mode = "first"
            sell_mode = (_q1(query, "sell_mode") or "bplus").lower()
            if sell_mode not in ("bplus", "legacy5m", "day"):
                sell_mode = "bplus"
            env_mode = (_q1(query, "env_mode") or "s6").lower()
            if env_mode not in ("s6", "three", "legacy7"):
                env_mode = "s6"
            width_mode = (_q1(query, "width_mode") or "s6").lower()
            if width_mode not in ("s6", "three", "legacy7"):
                width_mode = "s6"
            self._send_json(get_bplus_backtest(strategy, months=months,
                                               pick_mode=pick_mode, refresh=refresh,
                                               sell_mode=sell_mode, env_mode=env_mode,
                                               width_mode=width_mode))
            return
        if path == "/api/index-series":
            codes = _q1(query, "codes") or ""
            start = _q1(query, "start")
            end = _q1(query, "end")
            self._send_json(get_index_series(codes, start, end))
            return
        if path == "/api/training/months":
            mod = _training_module()
            if mod is None:
                self._send_error_json(503, "training_engine 模块不可用")
                return
            strategy = _q1(query, "strategy") or (safe_strategies() or ["TPO_M5"])[0]
            self._send_json(mod.months(ROOT, strategy))
            return
        if path == "/api/training/list":
            mod = _training_module()
            if mod is None:
                self._send_error_json(503, "training_engine 模块不可用")
                return
            month = _q1(query, "month") or ""
            strategy = _q1(query, "strategy") or (safe_strategies() or ["TPO_M5"])[0]
            self._send_json(mod.list_month(ROOT, strategy, month))
            return
        if path == "/api/picks":
            strategy = _q1(query, "strategy") or (safe_strategies() or ["TPO_M5"])[0]
            refresh = _truthy(_q1(query, "refresh"))
            self._send_json(get_picks(strategy, refresh=refresh))
            return
        if path == "/api/kline":
            code = (_q1(query, "code") or "").strip().upper()
            if not CODE_RE.match(code):
                self._send_error_json(400, "code 需形如 000001.SZ / 600000.SH")
                return
            period = _normalize_period(_q1(query, "period") or "1d")
            kend = (_q1(query, "end") or "").replace("-", "")[:8] or None
            if period is None:
                self._send_error_json(400, "period 仅支持 " + "/".join(PERIODS))
                return
            try:
                count = int(_q1(query, "count") or COUNT_DEFAULT)
            except ValueError:
                count = COUNT_DEFAULT
            count = max(20, min(COUNT_MAX, count))
            adjust = (_q1(query, "adjust") or "front").lower()
            payload = get_kline(code, period, count, end=kend)
            payload["adjust"] = adjust
            self._send_json(payload)
            return
        if path == "/api/symbols":
            self._send_json(get_symbols(refresh=_truthy(_q1(query, "refresh"))))
            return
        if path == "/api/realtime":
            if FEED is None:
                self._send_json({"ok": False, "error": "实时看盘数据源未启动",
                                 "time": _dt.datetime.now().isoformat(timespec="seconds"),
                                 "indices": [], "candidates": [], "holdings": [],
                                 "env": {"t1": None, "breadth": None, "label": "未启动"}})
                return
            self._send_json(FEED.snapshot())
            return
        if path == "/api/realtime/holdings":
            if FEED is None:
                self._send_error_json(503, "实时看盘数据源未启动")
                return
            self._send_json({"ok": True, "holdings": FEED.get_holdings(),
                             "path": FEED.holdings_path,
                             "serverTime": _dt.datetime.now().isoformat(timespec="seconds")})
            return
        if path == "/api/realtime/kline":
            code = (_q1(query, "code") or "").strip().upper()
            if not CODE_RE.match(code):
                self._send_error_json(400, "code 需形如 600118.SH / 000001.SZ")
                return
            period = (_q1(query, "period") or "5m").strip().lower()
            if period not in ("5m", "5"):
                self._send_error_json(400, "period 仅支持 5m")
                return
            try:
                days = int(_q1(query, "days") or 10)
            except ValueError:
                days = 10
            mod = _realtime_module()
            if mod is None:
                self._send_error_json(503, "realtime_feed 模块不可用")
                return
            payload = mod.load_realtime_kline(code, ROOT, AIDATA_DIR, days=days)
            if FEED is not None and payload.get("ok"):
                try:
                    payload["name"] = FEED.name_for(code)
                except BaseException:  # noqa: BLE001
                    payload["name"] = None
            self._send_json(payload)
            return
        self._send_error_json(404, f"unknown api: {path}")

    def _meta(self):
        strategies = safe_strategies()
        version, version_ts = _data_version()
        latest = _latest_trading_date()
        periods = []
        for p in PERIODS:
            periods.append({
                "id": p, "label": PERIOD_LABELS[p],
                "source": "5M" if p in ("5m", "15m", "30m", "60m") else "1D",
            })
        self._send_json({
            "ok": True,
            "app": APP_NAME,
            "version": APP_VERSION,
            "root": ROOT,
            "dataDir": AIDATA_DIR,
            "dashboardDir": DASH_DIR,
            "strategies": strategies,
            "latestTradingDate": latest,
            "latest_trading_date": latest,
            "data_mtime": version_ts,
            "dataVersion": version,
            "data_mtime_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(version_ts)) if version_ts else None,
            "dataStatusLabel": _session_label(latest),
            "tMinus": "T-0" if str(latest) == _dt.date.today().strftime("%Y%m%d") else "T-1",
            "has_5m_count": _count_5m(),
            "recentTradingDates": _trading_dates(10),
            "realtime": {
                "available": False,
                "reason": "当前仅读取本地 L1 加工数据（AIData 只读），未接实时行情",
            },
            "realtimeBoard": {
                "enabled": FEED is not None,
                "path": "/api/realtime",
                "note": "「实时看盘」页面使用 tqcenter 快照（2s 轮询），仅判断不下单",
            },
            "klinePeriods": periods,
            "defaultSymbol": _default_symbol(),
            "backend": {"ok": BD is not None, "error": BD_ERROR},
            "serverTime": _dt.datetime.now().isoformat(timespec="seconds"),
        })

    def _handle_static(self, path):
        if path in ("", "/"):
            path = "/index.html"
        rel = posixpath.normpath(path.lstrip("/"))
        if rel.startswith("../") or rel in ("..", "."):
            self._send_error_json(403, "forbidden")
            return
        full = os.path.abspath(os.path.join(DASH_DIR, rel.replace("/", os.sep)))
        dash_abs = os.path.abspath(DASH_DIR)
        if os.path.commonpath([full, dash_abs]) != dash_abs or not os.path.isfile(full):
            self._send_error_json(404, f"not found: /{rel}")
            return
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if full.endswith(".js"):
            ctype = "text/javascript; charset=utf-8"
        elif full.endswith(".css"):
            ctype = "text/css; charset=utf-8"
        elif full.endswith(".html"):
            ctype = "text/html; charset=utf-8"
        try:
            with open(full, "rb") as f:
                body = f.read()
        except OSError as exc:
            self._send_error_json(500, str(exc))
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if rel.split("/")[0] == "vendor":
            self.send_header("Cache-Control", "public, max-age=86400")
        else:
            self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass


def _q1(query, key):
    vals = query.get(key)
    return vals[0] if vals else None


def _truthy(v):
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")


def _normalize_period(raw):
    raw = str(raw or "").strip()
    if raw in PERIODS:
        return raw
    return PERIOD_ALIASES.get(raw) or PERIOD_ALIASES.get(raw.lower())


def warmup():
    """后台预热：策略选股计算昂贵（~40s），先算好再供页面秒开。"""
    load_backend()
    try:
        strategies = safe_strategies() or ["TPO_M5"]
        target = strategies[0]
        started = time.time()
        get_dashboard(target)
        print(f"[warmup] dashboard {target} ok in {time.time() - started:.2f}s")
        get_picks(target)
        get_symbols()
        print(f"[warmup] all caches ready in {time.time() - started:.2f}s")
    except BaseException as exc:  # noqa: BLE001
        print(f"[warmup] failed: {type(exc).__name__}: {exc}")


def _training_module():
    """惰性导入 tools/training_engine.py（选股训练）。"""
    mod = sys.modules.get("training_engine")
    if mod is not None:
        return mod
    try:
        tools_dir = os.path.dirname(os.path.abspath(__file__))
        if tools_dir not in sys.path:
            sys.path.insert(0, tools_dir)
        import training_engine  # noqa: WPS433
        return training_engine
    except BaseException as exc:  # noqa: BLE001
        print(f"[training] import training_engine 失败: {type(exc).__name__}: {exc}")
        return None


def _preclose_module():
    """惰性导入 tools/preclose_strategy.py（14:45 预生成）。"""
    mod = sys.modules.get("preclose_strategy")
    if mod is not None:
        return mod
    try:
        tools_dir = os.path.dirname(os.path.abspath(__file__))
        if tools_dir not in sys.path:
            sys.path.insert(0, tools_dir)
        import preclose_strategy  # noqa: WPS433
        return preclose_strategy
    except BaseException as exc:  # noqa: BLE001
        print(f"[preclose] import preclose_strategy 失败: {type(exc).__name__}: {exc}")
        return None


def _bplus_module():
    """惰性导入 tools/bplus_engine.py（B+ 新卖法回测引擎）。"""
    mod = sys.modules.get("bplus_engine")
    if mod is not None:
        return mod
    try:
        tools_dir = os.path.dirname(os.path.abspath(__file__))
        if tools_dir not in sys.path:
            sys.path.insert(0, tools_dir)
        import bplus_engine  # noqa: WPS433
        return bplus_engine
    except BaseException as exc:  # noqa: BLE001
        print(f"[bplus] import bplus_engine 失败: {type(exc).__name__}: {exc}")
        return None


def _ths_test_module():
    """惰性导入 tools/ths_test_block.py（同花顺 TEST 板块）。"""
    mod = sys.modules.get("ths_test_block")
    if mod is not None:
        return mod
    try:
        import importlib.util
        fp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ths_test_block.py")
        spec = importlib.util.spec_from_file_location("ths_test_block", fp)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        sys.modules["ths_test_block"] = mod
        return mod
    except BaseException as exc:  # noqa: BLE001
        print(f"[ths] import failed: {exc}")
        return None


def _realtime_module():
    """惰性导入 tools/realtime_feed.py（失败返回 None，实时看盘降级但服务照常）。"""
    mod = sys.modules.get("realtime_feed")
    if mod is not None:
        return mod
    try:
        tools_dir = os.path.dirname(os.path.abspath(__file__))
        if tools_dir not in sys.path:
            sys.path.insert(0, tools_dir)
        import realtime_feed  # noqa: WPS433
        return realtime_feed
    except BaseException as exc:  # noqa: BLE001
        print(f"[realtime] import realtime_feed 失败: {type(exc).__name__}: {exc}")
        return None


def _start_realtime_feed():
    """启动 tqcenter 实时看盘轮询线程（失败不影响其它 API）。"""
    global FEED
    try:
        mod = _realtime_module()
        if mod is None:
            raise RuntimeError("realtime_feed 模块不可用")
        RealtimeFeed = mod.RealtimeFeed
        strategy = (safe_strategies() or ["TPO_M5"])[0]

        def _picks_provider():
            # 先看内存缓存，未预热时由 get_picks 串行计算（只阻塞实时线程，不阻塞 API）
            cached = _PICKS_CACHE.get(strategy)
            if cached is not None:
                return cached
            return get_picks(strategy)

        feed = RealtimeFeed(ROOT, DASH_DIR, AIDATA_DIR, get_picks=_picks_provider,
                            interval=2.0, strategy_name=strategy)
        feed.start()
        FEED = feed
        print("[realtime] 实时看盘数据源已启动（tqcenter 快照 2s 轮询）")
    except BaseException as exc:  # noqa: BLE001
        FEED = None
        print(f"[realtime] 启动失败（实时看盘不可用，其它功能正常）: {type(exc).__name__}: {exc}")


def _start_preclose_thread():
    """交易日 14:40–15:50 后台自动调用一次 14:40 预生成（目标 14:45 前完成，本地线程）。"""
    def _loop():
        while True:
            try:
                now = _dt.datetime.now()
                mins = now.hour * 60 + now.minute
                if now.weekday() < 5 and 14 * 60 + 40 <= mins < 15 * 60 + 50:
                    mod = _preclose_module()
                    if mod is not None:
                        res = mod.generate(force=False)
                        print(f"[preclose] 14:40 预生成 duration_s={res.get('duration_s')}: {res}")
            except BaseException as exc:  # noqa: BLE001
                print(f"[preclose] 线程异常（不影响服务）: {type(exc).__name__}: {exc}")
            time.sleep(60)

    try:
        threading.Thread(target=_loop, name="preclose-1440", daemon=True).start()
        print("[preclose] 14:40 预生成线程已启动")
    except BaseException as exc:  # noqa: BLE001
        print(f"[preclose] 线程启动失败: {type(exc).__name__}: {exc}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="MarcoAI 新 UI v1 本地服务（零依赖）")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-warmup", action="store_true", help="不后台预热策略选股缓存")
    args = parser.parse_args(argv)

    load_backend()
    if not args.no_warmup:
        threading.Thread(target=warmup, name="warmup", daemon=True).start()
    _start_realtime_feed()
    _start_preclose_thread()

    httpd = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    httpd.daemon_threads = True
    url = f"http://{args.host}:{args.port}/"
    print("=" * 60)
    print(f"  {APP_NAME} v{APP_VERSION}")
    print(f"  root      : {ROOT}")
    print(f"  dashboard : {DASH_DIR}")
    print(f"  listening : {url}")
    print(f"  strategies: {safe_strategies()}  backend={'ok' if BD else 'DEGRADED: ' + str(BD_ERROR)}")
    print("=" * 60)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[server] bye")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
