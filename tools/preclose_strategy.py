r"""14:40 尾盘预生成 TPO_M5 下个交易日名单（tools/preclose_strategy.py）。

两阶段（总超时 120s）：
1) AIData/1D 静态过滤（秒级）：T-3 首板放量涨停 + T-2 放量上涨未涨停 → 候选池；
2) 候选池用 tqcenter.get_pricevol 批量取实时价量，应用 T-1 条件（涨幅≤3%、缩量、>MA5、MA5 预测、市值 200~1300 亿）；
3) 按 T-2 市值倒序取首选 + 前 6；输出 AIData/NEXT_DAY/preclose_strategy.json。
"""
import datetime as _dt
import json
import os
import sys
import time
import traceback
from collections import deque

ROOT = os.environ.get("MARCO_ROOT", r"C:/MarcoAI")
AIDATA = os.path.join(ROOT, "AIData")
LOGDIR = os.path.join(ROOT, "logs")
OUT = os.path.join(AIDATA, "NEXT_DAY", "preclose_strategy.json")
TOTAL_TIMEOUT_S = 120
BATCH_SIZE = 400


def _log(msg=""):
    os.makedirs(LOGDIR, exist_ok=True)
    path = os.path.join(LOGDIR, f"preclose_strategy_{_dt.date.today():%Y%m%d}.log")
    line = f"[{_dt.datetime.now():%H:%M:%S}] {msg}\n"
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass
    print(line, end="")


def _read_text(path):
    raw = open(path, "rb").read()
    for enc in ("utf-8", "gbk", "gb2312", "latin-1"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("latin-1", "ignore")


def _f(v):
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def _next_weekday(d):
    n = d + _dt.timedelta(days=1)
    while n.weekday() >= 5:
        n += _dt.timedelta(days=1)
    return n


def _limit_pct(code):
    c = str(code).split(".")[0]
    if c.startswith(("688", "689", "300", "301")):
        return 20
    if c.startswith(("8", "4")):
        return 30
    return 10


def _limit_price(code, prev_close):
    if not prev_close or prev_close <= 0:
        return None
    return round(prev_close * (1 + _limit_pct(code) / 100.0), 2)


def _stock_info_map():
    """code -> (name, 流通股本)。"""
    out = {}
    p = os.path.join(AIDATA, "STOCK_CODES_ALL")
    try:
        for line in _read_text(p).splitlines():
            parts = line.split("|")
            if len(parts) < 3:
                continue
            code = parts[0].strip().upper()
            sh = _f(parts[2])
            if code and sh:
                out[code] = (parts[1].strip(), sh)
    except OSError:
        pass
    return out


def _codes():
    folder = os.path.join(AIDATA, "1D")
    codes = []
    try:
        for name in os.listdir(folder):
            c = name.strip().upper()
            if len(c) == 9 and c[6] == "." and c[:6].isdigit():
                codes.append(c)
    except OSError:
        return []
    return sorted(codes)


def _daily(code):
    """最后 8 根日线 (date, open, high, low, close, volume)。"""
    p = os.path.join(AIDATA, "1D", code)
    rows = []
    try:
        with open(p, "r", encoding="utf-8", errors="ignore") as f:
            lines = deque(f, maxlen=8)
    except OSError:
        return rows
    for line in lines:
        parts = line.strip().split("|")
        if len(parts) < 6:
            continue
        try:
            rows.append((parts[0], float(parts[1]), float(parts[2]), float(parts[3]),
                         float(parts[4]), float(parts[5])))
        except ValueError:
            continue
    return rows


def _is_limit_up(code, close, prev_close):
    lim = _limit_price(code, prev_close)
    return lim is not None and close >= lim - 0.005


def _static_candidates(codes, info, today_ymd, deadline=None):
    """T-3 首板放量涨停 + T-2 放量上涨未涨停 → 候选池（只读 1D，秒级）。"""
    out = []
    for i, code in enumerate(codes):
        if deadline is not None and i % 100 == 0 and time.time() > deadline:
            raise TimeoutError("总超时（静态过滤阶段）")
        rows = [r for r in _daily(code) if r[0] < today_ymd]
        if len(rows) < 5:
            continue
        t4, t3, t2 = rows[-3], rows[-2], rows[-1]
        # T-3 首板放量涨停：T-3 涨停、T-4 未涨停、T-3 量>T-4 量
        if not _is_limit_up(code, t3[4], t4[4]):
            continue
        if len(rows) >= 4 and _is_limit_up(code, t4[4], rows[-4][4]):
            continue
        if not (t3[5] > t4[5]):
            continue
        # T-2 放量上涨未涨停
        if not (t2[4] > t3[4]):
            continue
        lim2 = _limit_price(code, t3[4])
        if lim2 is not None and t2[4] >= lim2 - 0.005:
            continue
        if not (t2[5] > t3[5]):
            continue
        name, shares = info.get(code, ("", 0))
        if not shares:
            continue
        mv = t2[4] * shares
        if not (200e8 <= mv <= 1300e8):
            continue
        out.append({
            "code": code, "name": name, "shares": shares, "marketValue": mv,
            "t2Close": t2[4], "closes": [r[4] for r in rows[-4:]], "t2Volume": t2[5],
        })
    return out


def _tq_pricevol(codes, deadline):
    """批量实时价量（get_pricevol，分批 400），不逐只 snapshot。"""
    if not codes:
        return {}
    tools_dir = os.path.dirname(os.path.abspath(__file__))
    plugin = os.environ.get("TDX_PLUGIN_PATH", r"C:/new_tdx64/PYPlugins/user")
    for p in (os.path.dirname(tools_dir), plugin):
        if p not in sys.path:
            sys.path.insert(0, p)
    from tqcenter import tq  # type: ignore
    tq.initialize(__file__)
    out = {}
    for i in range(0, len(codes), BATCH_SIZE):
        if time.time() > deadline:
            raise TimeoutError("总超时（实时批量取数阶段）")
        batch = codes[i:i + BATCH_SIZE]
        try:
            part = tq.get_pricevol(stock_list=batch) or {}
        except BaseException as exc:  # noqa: BLE001
            _log(f"get_pricevol 批次 {i//BATCH_SIZE + 1} 失败: {type(exc).__name__}: {exc}")
            continue
        if isinstance(part, dict):
            out.update(part)
        elif isinstance(part, list):
            for item in part:
                if isinstance(item, dict):
                    c = item.get("Code") or item.get("code") or item.get("stock_code")
                    if c:
                        out[str(c).upper()] = item
    return out


def _load_env():
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import bplus_engine as be
        idx = be._load_index_data(ROOT, "s6", "s6")
        days = idx["dates"]
        if not days:
            return {"t1": None, "above": None, "total": 3, "date": None,
                    "mode": "three", "details": []}
        d = days[-1]
        score = idx["env_score"].get(d)
        details = idx["env_details"].get(d) or []
        sell_rule = "持有到14:55" if (score or 0) >= 2 else ("10:00看300+创指宽度" if score == 1 else ("10:00卖出" if score == 0 else "回退满仓·持有到14:55"))
        return {"t1": ("好" if (score or 0) >= 2 else "差") if score is not None else None,
                "score": score, "state": f"S{score}" if score is not None else "不可用",
                "sellRule": sell_rule, "above": sum(1 for x in details if x.get("above")),
                "total": 3, "date": d, "mode": "s6",
                "rule": "S6：沪深300上+1、创业板指上+1、中证银行≤MA60+1", "details": details}
    except BaseException as exc:  # noqa: BLE001
        _log(f"env 计算失败: {type(exc).__name__}: {exc}")
        return {"t1": None, "above": None, "total": 3, "date": None,
                "mode": "three", "details": []}


def _elapsed_minutes(now):
    mins = now.hour * 60 + now.minute
    if mins <= 11 * 60 + 30:
        return max(1, mins - 9 * 60 - 30)
    if mins >= 13 * 60:
        return min(240, 120 + (mins - 13 * 60))
    return 120


def generate(force=False):
    today = _dt.date.today()
    now = _dt.datetime.now()
    if not force and (today.weekday() >= 5 or now.hour * 60 + now.minute < 14 * 60 + 40):
        _log("非交易日/未到 14:40，跳过")
        return {"ok": False, "skipped": True, "reason": "非交易日或未到14:40"}
    if os.path.isfile(OUT) and not force:
        try:
            old = json.loads(_read_text(OUT))
            if str(old.get("buyDate")) == today.strftime("%Y%m%d"):
                _log("今日已生成，跳过")
                return {"ok": True, "skipped": True, "path": OUT, "cached": True}
        except (OSError, ValueError):
            pass
    t0 = time.time()
    deadline = t0 + TOTAL_TIMEOUT_S
    today_ymd = today.strftime("%Y%m%d")
    stage = "static"
    try:
        _log(f"开始预生成（两阶段，总超时 {TOTAL_TIMEOUT_S}s，今天={today_ymd}）")
        codes = _codes()
        info = _stock_info_map()
        cands = _static_candidates(codes, info, today_ymd, deadline)
        _log(f"[static] 1D 全市场 {len(codes)} 只 → 候选 {len(cands)} 只，耗时 {time.time()-t0:.1f}s")
        if time.time() > deadline:
            raise TimeoutError("总超时（静态过滤后）")
        stage = "realtime"
        quotes = _tq_pricevol([c["code"] for c in cands], deadline)
        _log(f"[realtime] 候选 {len(cands)} 只 → 批量快照 {len(quotes)} 只，耗时 {time.time()-t0:.1f}s")
        picks = []
        elapsed = _elapsed_minutes(now)
        for c in cands:
            q = quotes.get(c["code"]) or quotes.get(c["code"].upper())
            if not q:
                continue
            now_p = _f(q.get("Now") or q.get("now"))
            pre = _f(q.get("LastClose") or q.get("last_close") or q.get("PreClose"))
            vol = _f(q.get("Volume") or q.get("volume"))
            if not (now_p and pre and pre > 0):
                continue
            if now_p / pre - 1 > 0.03:
                continue
            volumes = [r for r in c.get("closes", [])]
            if len(volumes) < 4:
                continue
            closes = volumes
            ma5 = (now_p + sum(closes[-4:])) / 5.0
            if now_p <= ma5:
                continue
            ma5pred = (now_p * 2 + closes[-1] + closes[-2] + closes[-3]) / 5.0
            if now_p < ma5pred:
                continue
            # 缩量：当前/折算成交量 < T-2 全天量
            vol_shares = vol * 100.0 if vol and vol < 1e9 else vol
            proj_vol = vol_shares * 240.0 / max(1, elapsed) if vol_shares else 0
            if not (vol_shares and c["t2Volume"] and min(vol_shares, proj_vol) < c["t2Volume"]):
                continue
            picks.append({
                "code": c["code"], "name": c["name"] or c["code"],
                "buyPrice": round(now_p, 3),
                "marketValue": round(c["marketValue"] / 1e8, 2),
                "ma5Pred": True, "zaf": round((now_p / pre - 1) * 100, 2),
            })
        picks.sort(key=lambda x: (-x["marketValue"], x["code"]))
        picks = picks[:6]
        for p in picks:
            p.pop("zaf", None)
        env = _load_env()
        payload = {
            "generatedAt": _dt.datetime.now().isoformat(timespec="seconds"),
            "buyDate": today.strftime("%Y%m%d"),
            "forTradeDate": _next_weekday(today).strftime("%Y%m%d"),
            "approx": True, "preclose": True, "strategy": "TPO_M5",
            "env": env,
            "firstPick": picks[0] if picks else None,
            "buyList": picks,
            "candidates": [],
            "source": "preclose-14:40",
            "note": "14:40 预生成（尾盘买入用）；15:50 后以正式 strategy.json 为准",
        }
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        tmp = OUT + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        os.replace(tmp, OUT)
        duration = time.time() - t0
        _log(f"生成完成 候选池={len(cands)} 快照={len(quotes)} 入选={len(picks)} duration_s={duration:.1f} env={env}")
        return {"ok": True, "path": OUT, "count": len(picks), "env": env,
                "elapsed": round(duration, 1), "duration_s": round(duration, 1)}
    except TimeoutError as exc:
        duration = time.time() - t0
        _log(f"中止 timeout=True stage={stage} duration_s={duration:.1f}：{exc}")
        return {"ok": False, "timeout": True, "stage": stage,
                "elapsed": round(duration, 1), "error": str(exc)}
    except BaseException as exc:  # noqa: BLE001
        duration = time.time() - t0
        _log(f"失败 stage={stage} duration_s={duration:.1f}: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return {"ok": False, "stage": stage, "elapsed": round(duration, 1),
                "error": f"{type(exc).__name__}: {exc}"}


if __name__ == "__main__":
    force = "--force" in sys.argv or os.environ.get("PRECLOSE_FORCE") == "1"
    try:
        print(json.dumps(generate(force=force), ensure_ascii=False))
    except BaseException as exc:  # noqa: BLE001
        _log(f"失败: {type(exc).__name__}: {exc}")
