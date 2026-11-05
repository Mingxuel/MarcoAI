"""新 UI 后端数据适配层（DataAdapter）。

职责：把 AIData 下的 L1 加工数据（1D / 5M / STRATEGY / TARGET / TOP / TOP_FIRST / INDEX /
策略回测汇总 / 情绪）读出来，装配成前端 modules.js 需要的 window.MARCO_DATA 结构，
以及按需提供个股 K 线（1D/5M，5M 缺失时留好「按需补数」钩子）。

设计要点（对应用户诉求）：
- 一条龙更新（Run.py UPDATE_ALL）已经把 L0/L1 落到 AIData；本层只「读」不「写」，不重复加工。
- 个股 K 线按需加载：前端点哪只股、切到哪个周期，后端才读对应文件返回，避免一次性全量。
- 5M 因耗时曾分段下载而残缺；load_kline('5m') 若本地缺文件，保留 refill_tdx 钩子（后续接通达信插件）。
复用 StrategyUI 既有解析器，避免重复造轮子。
"""
import os
import sys
import datetime as _dt

ROOT = r"c:/MarcoAI"
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from AICode.MarcoAPI.Update.Path import (
    PATH_AIDATA_1D, PATH_AIDATA_5M,
    PATH_AIDATA_STRATEGY_TPO_M5, PATH_AIDATA_TOP, PATH_AIDATA_TOP_FIRST,
    PATH_AIDATA_INDEX,
)

# 复用 StrategyUI 的既有解析器（已验证口径，与回测引擎一致）
from AICode.MarcoAPI.StrategyUI import (
    _load_candidates, _load_strategy_detail, _read_text,
)

__all__ = ["get_strategies", "get_dashboard", "load_kline", "get_strategy_pick", "get_index_codes"]


def _safe_import(name):
    try:
        import importlib
        return importlib.import_module("AICode.MarcoAPI.StrategyUI")
    except Exception:
        return None


_SUI = _safe_import("AICode.MarcoAPI.StrategyUI")


def get_strategies():
    try:
        return _SUI._list_strategies() or ["TPO_M5"]
    except Exception:
        return ["TPO_M5"]


def _mcap_yi(mraw):
    """市值列(market，单位：元) ÷1e8 得亿，与离线看板 fmtYi/fmtNum 同口径。"""
    try:
        if mraw not in (None, ""):
            return round(float(mraw) / 1e8, 2)
    except (ValueError, TypeError):
        pass
    return None


def get_strategy_pick(strategy="TPO_M5"):
    """策略选股：照搬离线看板 StrategyUI.loadDetail 的逻辑出表。

      - 候选分组：仅最新两期候选池(latestCandDate=T-1, prevCandDate=T)，
        这两批在「涨停日+3」前还没回测，故涨跌幅等留空（— 暂无数据 —）；
        剔除其中已出现在最新一期策略选股(已回测)的股，避免重复。
      - 历史分组：交易日历取「候选池∪策略选股」的所有日期，但每个日期
        只渲染 det[日期]（策略选股回测结果，都有涨跌幅）；候选池只用于标定
        交易日历，无回测的日期显示「该日无股票」。
      - 市值：候选/明细里的市值列(market，单位元) ÷1e8 得亿（该列本身即按
        入选日/T-2 收盘价计，非当前价）。
    """
    try:
        cand = _load_candidates(strategy) or {}
    except Exception:
        cand = {}
    # 收盘后窗口（与离线看板 / 同花顺板块同口径）：===T===（符合 T-3→T-1）与
    # ===T-1===（符合 T-3→T-2）。today 取该策略最新一期候选日期。
    tpo_window = {}
    try:
        _tw = _SUI._build_tpo_window([strategy], {strategy: cand})
        tpo_window = _tw.get(strategy, {}) or {}
    except Exception:
        tpo_window = {}
    try:
        detail = _load_strategy_detail([strategy]) or {}
        detail = detail.get(strategy, {})
    except Exception:
        detail = {}
    cand_dates = sorted(cand.keys())
    det_dates = sorted(detail.keys())
    latest_cand = cand_dates[-1] if cand_dates else None
    prev_cand = cand_dates[-2] if len(cand_dates) >= 2 else None
    latest_strat = det_dates[-1] if det_dates else None
    # 已在最新一期策略选股(已回测)的股，候选分组里要剔除，避免重复
    strat_codes = set()
    if latest_strat:
        for it in (detail.get(latest_strat) or []):
            c = it.get("code")
            if c:
                strat_codes.add(c)
    cand_group_dates = {latest_cand, prev_cand}

    _all = sorted(set(cand.keys()) | set(detail.keys()), reverse=True)
    # 仅保留最近 12 个月的选股/候选数据，降低「策略选股」TAB 的传输与渲染压力
    _months = sorted({d[:6] for d in _all}, reverse=True)[:12]
    _mset = set(_months)
    all_dates = [d for d in _all if d[:6] in _mset]
    picks = {}
    for date in all_dates:
        if date is not None and date in cand_group_dates:
            # 候选分组：候选池票（剔除已回测），涨跌幅等留空
            stocks = []
            for r in (cand.get(date) or []):
                code = r[0]
                if code in strat_codes:
                    continue
                name = r[1] if len(r) > 1 else ""
                stocks.append({
                    "code": code, "name": name,
                    "high": None, "low": None, "pre": None, "chg": None,
                    "sell_chg_5m": None,
                    "mcap": _mcap_yi(r[2] if len(r) > 2 else ""),
                    "date": date, "cand": True,
                })
            picks[date] = stocks
        else:
            # 历史分组：仅策略选股回测结果 det[日期]（都有涨跌幅）
            stocks = []
            for it in (detail.get(date) or []):
                code = it.get("code")
                chg = it.get("chg")
                high = it.get("high"); low = it.get("low"); pre = it.get("pre")
                sell5 = it.get("sell_chg_5m")
                stocks.append({
                    "code": code, "name": it.get("name", "") or "",
                    "high": high, "low": low, "pre": pre, "chg": chg,
                    "sell_chg_5m": sell5,
                    "mcap": _mcap_yi(it.get("market")),
                    "date": date, "cand": False,
                })
            picks[date] = stocks
    return {
        "dates": all_dates,
        "picks": picks,
        "cand_group_dates": [d for d in (latest_cand, prev_cand) if d],
        "latest_cand_date": latest_cand,
        "tpoWindow": tpo_window,
        "strategy": strategy,
    }


def _date_unix(d):
    """'YYYYMMDD' 或 'YYYY-MM-DD' -> unix 秒（lightweight-charts 日线用 utc 日初）"""
    d = (d or "").replace("-", "").strip()
    if len(d) < 8:
        return 0
    try:
        return int(_dt.datetime(int(d[:4]), int(d[4:6]), int(d[6:8]), 0, 0, 0).timestamp())
    except Exception:
        return 0


def _dt_unix(s):
    """'YYYY-MM-DD HH:MM:SS' -> unix 秒"""
    try:
        return int(_dt.datetime.strptime(s.strip(), "%Y-%m-%d %H:%M:%S").timestamp())
    except Exception:
        return 0


def load_kline(code, period="1d"):
    """返回 {'data':[{time,open,high,low,close,volume}], 'vol':[{time,value}]}。
    code 形如 600118.SH / 399006.SZ。"""
    if period in ("1d", "1w", "1mo"):
        path = os.path.join(PATH_AIDATA_1D(), code)
        if not os.path.isfile(path):
            path = os.path.join(PATH_AIDATA_INDEX(), code)
        if not os.path.isfile(path):
            return {"data": [], "vol": []}
        data, vol = [], []
        for line in _read_text(path).splitlines():
            p = line.split("|")
            if len(p) < 6:
                continue
            try:
                t = _date_unix(p[0])
                o, h, l, c, v = float(p[1]), float(p[2]), float(p[3]), float(p[4]), float(p[5])
            except Exception:
                continue
            data.append({"time": t, "open": o, "high": h, "low": l, "close": c})
            vol.append({"time": t, "value": v})
        return {"data": data, "vol": vol}
    if period == "5m":
        path = os.path.join(PATH_AIDATA_5M(), code)
        if not os.path.isfile(path):
            # 临时下载：新 UI 显示该股 5 分钟时按需从通达信拉取并落盘（需通达信联网）。
            # 失败/未连接时返回空，由前端回退日线或占位提示；不影响其它数据。
            try:
                from AICode.MarcoAPI.Update.SZ2005M import DOWNLOAD_5M_ONE
                DOWNLOAD_5M_ONE(code, recent_days=120)
            except BaseException as exc:
                print(f"  [5m on-demand] {code} 触发失败: {type(exc).__name__}: {exc}")
        if not os.path.isfile(path):
            return {"data": [], "vol": []}
        data, vol = [], []
        for line in _read_text(path).splitlines():
            p = line.split("|")
            if len(p) < 7:
                continue
            try:
                t = _dt_unix(p[0])
                o, h, l, c, v = float(p[1]), float(p[2]), float(p[3]), float(p[4]), float(p[5])
            except Exception:
                continue
            data.append({"time": t, "open": o, "high": h, "low": l, "close": c})
            vol.append({"time": t, "value": v})
        return {"data": data, "vol": vol}
    if period in ("15m", "30m"):
        # 由 5 分钟重采样（3 根→15分，6 根→30分），按交易日分桶避免跨日拼接
        n = 3 if period == "15m" else 6
        base = load_kline(code, "5m")
        src = base.get("data") or []
        vmap = {v["time"]: v.get("value", 0) for v in (base.get("vol") or [])}
        out, volout, group, cur_day = [], [], [], None

        def _flush(g):
            if not g:
                return
            out.append({"time": g[0]["time"], "open": g[0]["open"], "high": max(x["high"] for x in g),
                        "low": min(x["low"] for x in g), "close": g[-1]["close"]})
            volout.append({"time": g[0]["time"], "value": sum(vmap.get(x["time"], 0) for x in g)})

        for b in src:
            day = _dt.datetime.fromtimestamp(b["time"]).date()
            if cur_day is None:
                cur_day = day
            if day != cur_day:
                _flush(group); group = []; cur_day = day
            group.append(b)
            if len(group) == n:
                _flush(group); group = []
        _flush(group)
        return {"data": out, "vol": volout}
    return {"data": [], "vol": []}


def _stub_1d(code):
    """仅取日线最后 2 根，供侧栏/详情卡算涨跌与日期；完整序列由前端按需拉取。"""
    path = os.path.join(PATH_AIDATA_1D(), code)
    if not os.path.isfile(path):
        path = os.path.join(PATH_AIDATA_INDEX(), code)
    if not os.path.isfile(path):
        return None
    bars = []
    try:
        for line in _read_text(path).splitlines():
            line = line.strip()
            if not line:
                continue
            p = line.split("|")
            if len(p) < 6:
                continue
            try:
                bars.append({"time": _date_unix(p[0]), "open": float(p[1]), "high": float(p[2]),
                             "low": float(p[3]), "close": float(p[4]), "volume": float(p[5])})
            except Exception:
                continue
    except Exception:
        return None
    last2 = bars[-2:] if len(bars) >= 2 else bars
    if not last2:
        return None
    return {"data": last2, "vol": [{"time": b["time"], "value": b["volume"]} for b in last2], "_stub": True}


def get_index_codes():
    try:
        return list(PATH_AIDATA_INDEX and set())
    except Exception:
        return []


def _latest_date(dates):
    ds = [d for d in dates if d]
    return max(ds) if ds else None


def _collect_syms(cand, detail):
    """汇总候选池 + 策略选股明细里的所有个股（code/name），去重。"""
    syms = {}
    for _d in cand.values():
        for r in _d:
            if len(r) >= 2:
                syms[r[0]] = r[1]
    for _d in detail.values():
        for it in _d:
            c = it.get("code")
            if c and c not in syms:
                syms[c] = it.get("name", "")
    return syms


def get_dashboard(strategy="TPO_M5", cap=120, pick_mode="first", sell_mode="5m"):
    """装配前端 modules.js 的 window.MARCO_DATA 结构（真实 L1 数据）。

    返回 dict，键与 data.js 的 MARCO_DATA 对齐：
    syms / klines / cand / top / topFirst / volSun / pickGroups /
    breadth / upRatio / sentiment / target / signals / metrics / monthRet / quarterRet / yearRet
    """
    syms_out = []
    klines = {}
    cand = {}
    top = {}
    top_first = {}
    vol_sun = {}
    detail = {}
    metrics = {"win": "", "drawdown": "", "annual": "", "maxProfit": "", "count": 0}
    month_ret = []
    quarter_ret = []
    year_ret = []
    sentiment = []
    breadth = []
    up_ratio = []
    target = []
    signals = []
    pick_groups = []
    capital_kline = []
    dist = {}

    try:
        cand = _load_candidates(strategy) or {}
    except Exception:
        cand = {}
    try:
        detail = _load_strategy_detail([strategy]) or {}
        detail = detail.get(strategy, {})
    except Exception:
        detail = {}

    # —— syms + klines（下发明细所需「最后 2 根日线」即可；完整 K 线由前端按需拉取）——
    sym_map = _collect_syms(cand, detail)
    # 上限保护：看板个股数受控，避免一次性读全市场
    items = list(sym_map.items())[:cap]
    for code, name in items:
        syms_out.append({"code": code, "name": name, "seed": 0, "start": 0})
        st = _stub_1d(code)
        klines[len(syms_out) - 1] = {
            "1d": st if st else {"data": [], "vol": []},
            "5m": {"data": [], "vol": [], "_stub": True},
        }

    # —— 涨停 / 首板 / 首板放量连阳 等列表：当前 UI 模块未使用，已移除（按需可恢复）——


    # —— 回测汇总（与 Backtest 引擎同口径）——
    capital = []
    try:
        bp = _SUI._build_strategy_payload(strategy, sell_mode, pick_mode)
        # 指标算法与离线看板 StrategyUI.renderBtStats 逐字对齐（同一份引擎数据）
        caps = [c for c in (bp.get("capitals") or []) if c]
        rets = [r for r in (bp.get("rets") or []) if r is not None]
        total = bp.get("total")
        if caps and rets:
            win = sum(1 for r in rets if r > 0)
            loss = sum(1 for r in rets if r < 0)
            metrics["win"] = round(win / (win + loss) * 100, 1) if (win + loss) else 0
            peak = 0.0; mdd = 0.0; trough = None; mg = 0.0
            for c in caps:
                if c > peak: peak = c
                if peak > 0: mdd = max(mdd, (peak - c) / peak)
                if trough is None or c < trough: trough = c
                if trough > 0: mg = max(mg, (c - trough) / trough)
            metrics["drawdown"] = round(mdd * 100, 1)
            metrics["maxProfit"] = round(mg * 100, 1)
            curW = 0; curL = 0; maxW = 0; maxL = 0
            for r in rets:
                if r > 0: curW += 1; curL = 0; maxW = max(maxW, curW)
                elif r < 0: curL += 1; curW = 0; maxL = max(maxL, curL)
                else: curW = 0; curL = 0
            metrics["maxWinStreak"] = maxW
            metrics["maxLossStreak"] = maxL
            metrics["count"] = len(rets)
            metrics["totalReturn"] = round(total * 100, 1) if total is not None else 0
            if total is not None and total > -1:
                metrics["annual"] = round((pow(1 + total, 250.0 / len(rets)) - 1) * 100, 1)
        month_ret = [{"k": k, "ret": round(v * 100, 1)} for k, v in (bp.get("month") or {}).items()]
        quarter_ret = [{"k": k, "ret": round(v * 100, 1)} for k, v in (bp.get("quarter") or {}).items()]
        year_ret = [{"k": k, "ret": round(v * 100, 1)} for k, v in (bp.get("year") or {}).items()]
        capital_kline = bp.get("kline") or []
        dist = bp.get("dist") or {}
        # 真实资金曲线（月度累计）：由月度收益推，首月前锚定 100
        _mret = {str(k): v for k, v in (bp.get("month") or {}).items()}
        _base = 100.0
        for _ym in sorted(_mret.keys()):
            _base *= (1 + _mret[_ym] / 100.0)
            try:
                _t = int(_dt.datetime.strptime(_ym + "01", "%Y%m%d").timestamp())
            except Exception:
                _t = 0
            capital.append({"time": _t, "value": round(_base, 2)})
    except Exception:
        pass

    # —— 情绪曲线 等：当前 UI 模块未使用，已移除（按需可恢复）——

    return {
        "strategy": strategy,
        "syms": syms_out,
        "klines": klines,
        "metrics": metrics,
        "monthRet": month_ret,
        "quarterRet": quarter_ret,
        "yearRet": year_ret,
        "capitalKline": capital_kline,
        "dist": dist,
        "strategies": get_strategies(),
        "signals": signals,
    }


def _fmt_date(d):
    d = (d or "").replace("-", "")
    if len(d) == 8:
        return d[:4] + "-" + d[4:6] + "-" + d[6:8]
    return d or ""


def _month_label(ym):
    ym = str(ym)
    if len(ym) == 6:
        return str(int(ym[4:6])) + "月"
    return ym


def _recent_dates(dates, keep=20):
    return set(sorted(dates, reverse=True)[:keep])


def _load_top_safe():
    try:
        top = _SUI._load_top()
        recent = _recent_dates(top.keys())
        out = []
        for date, rows in top.items():
            if date not in recent:
                continue
            for r in rows:
                if isinstance(r, (list, tuple)) and len(r) >= 2:
                    out.append({"code": r[0], "name": r[1], "pickDate": _fmt_date(date),
                                "chg": 0, "up": True, "sig": "涨停"})
        return out
    except Exception:
        return []


def _load_top_first_safe():
    try:
        tf = _SUI._load_top_first()
        recent = _recent_dates(tf.keys())
        out = []
        for date, rows in tf.items():
            if date not in recent:
                continue
            for r in rows:
                if isinstance(r, (list, tuple)) and len(r) >= 2:
                    out.append({"code": r[0], "name": r[1], "pickDate": _fmt_date(date),
                                "chg": 0, "up": True, "sig": "首板"})
        return out
    except Exception:
        return []



