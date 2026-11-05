"""14:45 尾盘预生成 TPO_M5 次日名单（tools/preclose_strategy.py）。

本地自动运行（dashboard_server 后台线程 14:45 调用），不依赖 agent。
输入：AIData/TOP 最新候选池 + AIData/1D 历史 + AIData/STOCK_CODES_ALL 股本 + tqcenter 实时快照。
输出：AIData/NEXT_DAY/preclose_strategy.json（结构同 strategy.json，preclose=true/approx=true）。
近似条件：现价/昨收≤3%、现价>MA5、缩量、T-3 放量、T-2 上涨未涨停、市值 200~1300 亿、MA5 预测。
"""
import datetime as _dt
import json
import os
import sys
import time
import traceback

ROOT = os.environ.get("MARCO_ROOT", r"C:/MarcoAI")
AIDATA = os.path.join(ROOT, "AIData")
LOGDIR = os.path.join(ROOT, "logs")
OUT = os.path.join(AIDATA, "NEXT_DAY", "preclose_strategy.json")
GROWTH = ["399673.SZ", "399006.SZ", "000688.SH", "399001.SZ", "000300.SH", "000852.SH", "000905.SH"]


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


def _latest_top_codes():
    """候选池：AIData/1D 全市场代码（TOP 是涨停池，不适合 TPO 条件，只做兜底）。"""
    folder = os.path.join(AIDATA, "1D")
    codes = []
    try:
        for name in os.listdir(folder):
            c = name.strip().upper()
            if len(c) == 9 and c[6] == "." and c[:6].isdigit():
                codes.append(c)
    except OSError:
        return []
    if codes:
        _log(f"候选池 1D: {len(codes)} 只")
        return sorted(codes)
    folder = os.path.join(AIDATA, "TOP")
    try:
        days = sorted(x for x in os.listdir(folder) if len(x) == 8 and x.isdigit())
    except OSError:
        return []
    for day in reversed(days):
        p = os.path.join(folder, day)
        if os.path.isfile(p):
            for line in _read_text(p).splitlines():
                c = (line.split("|")[0] if "|" in line else line).strip().upper()
                if len(c) == 9 and c[6] == ".":
                    codes.append(c)
            if codes:
                _log(f"候选池 TOP/{day}: {len(codes)} 只")
                return codes
    return []


def _shares_map():
    p = os.path.join(AIDATA, "STOCK_CODES_ALL")
    out = {}
    try:
        for line in _read_text(p).splitlines():
            parts = line.split("|")
            if len(parts) >= 3:
                sh = _f(parts[2])
                if sh:
                    out[parts[0].strip().upper()] = sh
    except OSError:
        pass
    return out


def _daily(code):
    p = os.path.join(AIDATA, "1D", code)
    rows = []
    try:
        for line in _read_text(p).splitlines():
            parts = line.split("|")
            if len(parts) < 6:
                continue
            try:
                rows.append((parts[0], float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4]), float(parts[5])))
            except ValueError:
                continue
    except OSError:
        return rows
    return rows[-8:]


def _tq_snapshots(codes):
    tools_dir = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(tools_dir)
    if root not in sys.path:
        sys.path.insert(0, root)
    plugin = os.environ.get("TDX_PLUGIN_PATH", r"C:/new_tdx64/PYPlugins/user")
    if plugin not in sys.path:
        sys.path.insert(0, plugin)
    from tqcenter import tq  # type: ignore
    tq.initialize(__file__)
    out = {}
    for code in codes:
        try:
            s = tq.get_market_snapshot(stock_code=code)
            if s:
                out[code] = s
        except BaseException:
            continue
    return out


def _load_env():
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import bplus_engine as be
        idx = be._load_index_data(ROOT)
        days = idx["dates"]
        if not days:
            return {"t1": None, "above": 0, "total": 7, "date": None}
        d = days[-1]
        above = idx["env"].get(d)
        return {"t1": ("好" if (above or 0) >= 4 else "差") if above is not None else None,
                "above": above, "total": 7, "date": d}
    except BaseException as exc:
        _log(f"env 计算失败: {type(exc).__name__}: {exc}")
        return {"t1": None, "above": 0, "total": 7, "date": None}


def generate(force=False):
    today = _dt.date.today()
    now = _dt.datetime.now()
    if not force and (today.weekday() >= 5 or now.hour * 60 + now.minute < 14 * 60 + 45):
        _log("非交易日/未到 14:45，跳过")
        return {"ok": False, "skipped": True, "reason": "非交易日或未到14:45"}
    if os.path.isfile(OUT) and not force:
        try:
            old = json.loads(_read_text(OUT))
            if str(old.get("buyDate")) == today.strftime("%Y%m%d"):
                _log("今日已生成，跳过")
                return {"ok": True, "skipped": True, "path": OUT, "cached": True}
        except (OSError, ValueError):
            pass
    t0 = time.time()
    codes = _latest_top_codes()
    shares = _shares_map()
    snaps = _tq_snapshots(codes) if codes else {}
    picks = []
    for code in codes:
        q = snaps.get(code)
        if not q:
            continue
        now_p = _f(q.get("Now"))
        pre = _f(q.get("LastClose"))
        op = _f(q.get("Open"))
        avg = _f(q.get("Average"))
        vol = _f(q.get("Volume"))
        zangsu = _f(q.get("Zangsu"))
        if not (now_p and pre and pre > 0):
            continue
        ratio = now_p / pre - 1
        if not (0.0 < ratio <= 0.03):
            continue
        rows = _daily(code)
        if len(rows) < 5:
            continue
        closes = [r[4] for r in rows]
        vols = [r[5] for r in rows]
        ma5 = (now_p + sum(closes[-4:])) / 5.0
        if now_p <= ma5:
            continue
        # 缩量：当前量 < 昨日全天量（14:45 已交易约 165 分钟，按比例折算）
        prev_vol = vols[-1]
        elapsed = max(30, min(240, (now.hour * 60 + now.minute) - 9 * 60 - 30))
        proj_vol = vol * 240.0 / elapsed if vol else 0
        if not (vol and prev_vol and min(vol, proj_vol) < prev_vol):
            continue
        # T-2 上涨未涨停、T-3 放量
        if len(closes) >= 4:
            c2, c3 = closes[-2], closes[-3]
            if not (c2 > c3 and (c2 / c3 - 1) < 0.10):
                continue
        if len(vols) >= 4 and not (vols[-3] > vols[-4] * 0.8):
            continue
        mv = (pre * shares.get(code, 0)) if shares.get(code) else None
        if mv is not None and not (200e8 <= mv <= 1300e8):
            continue
        score = ratio * 100 + (now_p / op - 1 if op else 0) + (now_p / avg - 1 if avg else 0) + (zangsu or 0) * 0.1
        picks.append({"code": code, "name": str(q.get("Name") or ""), "buyPrice": round(now_p, 3),
                      "marketValue": round(mv / 1e8, 2) if mv else None, "ma5Pred": True,
                      "score": round(score, 3), "zaf": round(ratio * 100, 2)})
    picks.sort(key=lambda x: (-x["score"], x["code"]))
    picks = picks[:6]
    for p in picks:
        p.pop("score", None)
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
        "source": "preclose-14:45",
        "note": "14:45 预生成（尾盘买入用）；15:50 后以正式 strategy.json 为准",
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT)
    _log(f"生成完成 {OUT} 候选池={len(codes)} 快照={len(snaps)} 入选={len(picks)} 耗时={time.time()-t0:.1f}s env={env}")
    return {"ok": True, "path": OUT, "count": len(picks), "env": env, "elapsed": round(time.time() - t0, 1)}


if __name__ == "__main__":
    force = "--force" in sys.argv or os.environ.get("PRECLOSE_FORCE") == "1"
    try:
        print(json.dumps(generate(force=force), ensure_ascii=False))
    except BaseException as exc:
        _log(f"失败: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        sys.exit(1)
