"""B+ 新卖法回测引擎（tools/bplus_engine.py）。

数据源：
- AIData/STRATEGY/<strategy>/<YYYYMMDD>：第一行 = T-1 尾盘买入首选（pre_close=第 11 列）
- C:\\new_tdx64\\vipdoc\\{sh,sz}\\fzline\\*.lc5：T-0 的 5 分钟 K 线（涨停价/止损/10:00/14:55）
- AIData/INDEX_5M：成长端 7 宽基日线 MA60 环境 + 10:00 红盘宽度
- 2026-01-05 之前 / MA60 不足 60 日 → 回退现状 5m 卖法，累计 fallbackDays

缓存：AIData/BACKTEST_CACHE/bplus_<strategy>_<months>_<pick>.json（输入 mtime + TTL 失效）。
"""
import bisect
import datetime as _dt
import glob
import json
import os
import struct
import time
import traceback

GROWTH_INDEXES = ["399673.SZ", "399006.SZ", "000688.SH", "399001.SZ", "000300.SH", "000852.SH", "000905.SH"]
# 新 B+ 环境：沪深300 + 创业板指 在 MA60 上，且中证银行 不在 MA60 上
THREE_ENV_INDEXES = [("000300.SH", "沪深300"), ("399006.SZ", "创业板指"), ("399986.SZ", "中证银行")]
INIT_CAPITAL = 100000.0
COMMISSION_RATE = 1e-4
MIN_COMMISSION = 5.0
STAMP_RATE = 5e-4
DEFAULT_STOP = -0.05
CACHE_TTL = 3600.0
ENGINE_VERSION = 9  # 4: 增加回测区间内交易日序列 tradingDates（个股 lc5 前收买入 / 旧卖法涨停优先 / env MA60 不含 T-1）
VDIR = os.environ.get("TDX_VIPDOC", r"C:/new_tdx64/vipdoc")


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


def _limit_ratio(code):
    code = str(code or "").upper()
    if code.startswith(("300", "301", "688")):
        return 0.20
    if code.startswith(("8", "4", "92")):
        return 0.30
    return 0.10


def _limit_price(pre_close, ratio):
    # 参考口径：涨停价 = 买入价 × (1+比例)，不做交易所取整（与 ref_trades 一致）
    return float(pre_close) * (1.0 + float(ratio))


def _trade_net_return(buy_price, sell_price, notional):
    if buy_price <= 0 or notional <= 0:
        return 0.0
    buy_comm = max(notional * COMMISSION_RATE, MIN_COMMISSION)
    shares = (notional - buy_comm) / buy_price
    if shares <= 0:
        return 0.0
    proceeds = shares * sell_price
    if proceeds <= 0:
        return 0.0
    sell_comm = max(proceeds * COMMISSION_RATE, MIN_COMMISSION)
    stamp = proceeds * STAMP_RATE
    return (proceeds - sell_comm - stamp - notional) / notional


# ---------------- STRATEGY ----------------
def _load_strategy(root, strategy):
    folder = os.path.join(root, "AIData", "STRATEGY", strategy)
    out = {}
    if not os.path.isdir(folder):
        return out
    for name in os.listdir(folder):
        d = name.strip()
        if len(d) != 8 or not d.isdigit():
            continue
        p = os.path.join(folder, d)
        if not os.path.isfile(p):
            continue
        rows = []
        try:
            for line in _read_text(p).splitlines():
                parts = line.strip().split("|")
                if len(parts) >= 11 and parts[0]:
                    rows.append(parts)
        except OSError:
            continue
        if rows:
            out[d] = rows
    return out


# ---------------- lc5 ----------------
_LC5_CACHE = {}


def _lc5_days(code):
    """返回 {YYYYMMDD: [(minute, open, high, low, close), ...]}（时间升序）。"""
    code = str(code or "").upper()
    if code in _LC5_CACHE:
        return _LC5_CACHE[code]
    mkt = "sh" if code.endswith(".SH") else ("sz" if code.endswith(".SZ") else "bj")
    path = os.path.join(VDIR, mkt, "fzline", f"{mkt}{code[:6]}.lc5")
    days = {}
    if not os.path.isfile(path):
        _LC5_CACHE[code] = days
        return days
    try:
        raw = open(path, "rb").read()
    except OSError:
        _LC5_CACHE[code] = days
        return days
    for i in range(len(raw) // 32):
        try:
            date, minute, op, hi, lo, cl, _amount, _vol, _r = struct.unpack("<HHfffffII", raw[i * 32:(i + 1) * 32])
            year = date // 2048 + 2004
            rem = date % 2048
            month, day = rem // 100, rem % 100
            _dt.datetime(year, month, day, minute // 60, minute % 60)
        except (struct.error, ValueError):
            continue
        if op <= 0 or cl <= 0:
            continue
        ds = f"{year}{month:02d}{day:02d}"
        days.setdefault(ds, []).append((minute, float(op), float(hi), float(lo), float(cl)))
    for ds in days:
        days[ds].sort(key=lambda x: x[0])
    _LC5_CACHE[code] = days
    return days


# ---------------- 原始价（T-1 收盘 / T-0 日线兜底） ----------------
_LDAY_CACHE = {}


def _lday_bars(code):
    """vipdoc/*/lday/*.lday 原生日线 {YYYYMMDD: (open, high, low, close)}。"""
    code = str(code or "").upper()
    if code in _LDAY_CACHE:
        return _LDAY_CACHE[code]
    mkt = "sh" if code.endswith(".SH") else ("sz" if code.endswith(".SZ") else "bj")
    base = os.path.join(VDIR, mkt, "lday", f"{mkt}{code[:6]}")
    raw = None
    for ext in (".day", ".lday"):
        try:
            raw = open(base + ext, "rb").read()
            break
        except OSError:
            continue
    out = {}
    if raw is None:
        _LDAY_CACHE[code] = out
        return out
    for i in range(len(raw) // 32):
        try:
            date, op, hi, lo, cl, _amount, _vol, _r = struct.unpack("<IIIIIfII", raw[i * 32:(i + 1) * 32])
            y, rem = date // 10000, date % 10000
            if y < 1990 or y > 2100:
                continue
            mo, da = rem // 100, rem % 100
            if not (1 <= mo <= 12 and 1 <= da <= 31) or op <= 0 or cl <= 0:
                continue
            out[f"{y}{mo:02d}{da:02d}"] = (op / 100.0, hi / 100.0, lo / 100.0, cl / 100.0)
        except struct.error:
            continue
    _LDAY_CACHE[code] = out
    return out


def _raw_buy_price(code, trade_date):
    """T-1 原始收盘：该股自己 lc5 日期序列中 < trade_date 的最后一根 5m close；缺失返回 None（跳过该笔）。"""
    if not trade_date:
        return None
    days = _lc5_days(code)
    keys = [k for k in days if k < trade_date]
    if not keys:
        return None
    return days[max(keys)][-1][4]


# ---------------- INDEX_5M ----------------
def _raw_daily_buy(code, trade_date):
    """day 模式买入：该股原始日线 < trade_date 的最后一根收盘（缺失回退 5m 原始前收）。"""
    ld = _lday_bars(code)
    keys = [k for k in ld if k < trade_date]
    if keys:
        return ld[max(keys)][3]
    return _raw_buy_price(code, trade_date)


def _day_ohlc(code, date):
    ld = _lday_bars(code)
    if date in ld:
        return ld[date]
    bars = (_lc5_days(code) or {}).get(date)
    if not bars:
        return None
    return (bars[0][1], max(b[2] for b in bars), min(b[3] for b in bars), bars[-1][4])


def _day_sell(buy, ohlc, code):
    """day 模式：涨停价优先 → 日线开盘/最低跌破止损 → 否则收盘。"""
    if not buy or buy <= 0 or not ohlc:
        return None
    op, hi, lo, cl = ohlc
    limit = _limit_price(buy, _limit_ratio(code))
    stop = buy * 0.95
    if hi >= limit:
        return limit
    if op <= stop:
        return op
    if lo <= stop:
        return stop
    return cl


def _load_index_data(root, env_mode="s6", width_mode="s6"):
    """环境评分/宽度（日线 MA60）。

    S6 四状态：沪深300>MA60 +1、创业板指>MA60 +1、中证银行<=MA60 +1 → score 0~3；
    宽度 S6 只用沪深300+创业板指（10:00 价 > 前一日日线收盘，0~2）。
    保留 env_mode=three/legacy7、width_mode=three/legacy7 供旧口径对比。
    """
    data_dir = os.path.join(root, "AIData", "INDEX_5M")
    three = [("000300.SH", "沪深300"), ("399006.SZ", "创业板指"), ("399986.SZ", "中证银行")]
    all_codes = list(dict.fromkeys([c for c, _n in three] + GROWTH_INDEXES))
    daily = {}
    for code in all_codes:
        per = {d: v[3] for d, v in _lday_bars(code).items() if v and v[3]}
        if not per:
            p = os.path.join(data_dir, code)
            try:
                for line in _read_text(p).splitlines():
                    parts = line.strip().split("|")
                    if len(parts) < 5 or len(parts[0]) < 10:
                        continue
                    d8 = parts[0][:10].replace("-", "")
                    c = _f(parts[4])
                    if c is not None:
                        per[d8] = c
            except OSError:
                pass
        daily[code] = per
    close10 = {}
    for code in all_codes:
        ten = {}
        p = os.path.join(data_dir, code)
        try:
            for line in _read_text(p).splitlines():
                parts = line.strip().split("|")
                if len(parts) < 5 or len(parts[0]) < 19:
                    continue
                if parts[0][11:16] == "10:00":
                    c = _f(parts[4])
                    if c is not None:
                        ten[parts[0][:10].replace("-", "")] = c
        except OSError:
            pass
        close10[code] = ten
    dates = sorted(daily.get("000300.SH") or [])
    if not dates:
        dates = sorted(daily.get(all_codes[0]) or [])
    env_score, env_good, env_above, env_details, width10 = {}, {}, {}, {}, {}
    for ds in dates:
        prior = [d for d in dates if d < ds]
        score = None
        good = None
        above_cnt = None
        details = []
        if len(prior) >= 61:
            t1 = prior[-1]
            series_days = prior[-61:-1]  # T-1 之前 60 日
            valid = True
            flags = {}
            for code, name in three:
                per = daily.get(code) or {}
                series = [per[d] for d in series_days if d in per]
                if len(series) < 60 or t1 not in per:
                    valid = False
                    break
                ma60 = sum(series) / 60.0
                close = per[t1]
                above = close > ma60
                flags[code] = above
                details.append({"code": code, "name": name, "close": round(close, 2),
                                "ma60": round(ma60, 2), "above": bool(above)})
            if valid:
                above_cnt = sum(1 for x in details if x["above"])
                if env_mode == "s6":
                    score = int(bool(flags.get("000300.SH"))) + int(bool(flags.get("399006.SZ"))) + int(not bool(flags.get("399986.SZ")))
                    good = score >= 2
                elif env_mode == "legacy7":
                    cnt = 0
                    ok7 = True
                    for code in GROWTH_INDEXES:
                        per = daily.get(code) or {}
                        series = [per[d] for d in series_days if d in per]
                        if len(series) < 60 or t1 not in per:
                            ok7 = False
                            break
                        if per[t1] > sum(series) / 60.0:
                            cnt += 1
                    if ok7:
                        good = cnt >= 4
                else:
                    good = bool(flags.get("000300.SH")) and bool(flags.get("399006.SZ")) and not bool(flags.get("399986.SZ"))
        env_score[ds] = score
        env_good[ds] = good
        env_above[ds] = above_cnt
        env_details[ds] = details
        w10 = None
        if prior:
            t1 = prior[-1]
            if width_mode == "s6":
                codes = [("000300.SH", "沪深300"), ("399006.SZ", "创业板指")]
            elif width_mode == "legacy7":
                codes = [(c, c) for c in GROWTH_INDEXES]
            else:
                codes = three
            vals = []
            for code, _name in codes:
                ten = close10.get(code) or {}
                per = daily.get(code) or {}
                if ds in ten and t1 in per:
                    vals.append(1 if ten[ds] > per[t1] else 0)
            if len(vals) == len(codes):
                w10 = sum(vals)
        width10[ds] = w10
    return {"dates": dates, "env": env_above, "env_score": env_score, "env_good": env_good,
            "env_details": env_details, "width10": width10,
            "env_mode": env_mode, "width_mode": width_mode}


def _bar_at(bars, hm):
    for b in bars:
        if b[0] == hm:
            return b
    return None


def _bplus_sell(bars, buy, env_good, width10, code="", width_threshold=4, env_mode="s6", score=None):
    """B+ 卖法（全部用原始价）：涨停价优先 → -5% 止损 → 好环境/宽度≥4 持有到14:55 → 否则 10:00 卖。"""
    if not buy or buy <= 0 or not bars:
        return None, "no-bars"
    limit = _limit_price(buy, _limit_ratio(code))
    stop_price = buy * 0.95
    sell = None
    reason = None
    for minute, _o, hi, _lo, cl in bars:
        if minute > 14 * 60 + 55:
            break
        if hi >= limit:
            sell, reason = limit, "涨停价卖"
            break
        if cl <= stop_price:
            sell, reason = cl, "止损卖"
            break
    if sell is None:
        if env_mode == "s6":
            if score is None:
                hold = True
            elif score >= 2:
                hold = True
            elif score == 0:
                hold = False
            else:
                hold = (width10 is not None and width10 >= 2)
        else:
            hold = bool(env_good) or (width10 is not None and width10 >= width_threshold)
        if hold:
            b = _bar_at(bars, 14 * 60 + 55)
            if b is None:
                b = next((x for x in reversed(bars) if x[0] <= 14 * 60 + 55), bars[-1])
            sell, reason = b[4], "S6持有到14:55" if env_mode == "s6" else "持有到14:55"
        else:
            b = _bar_at(bars, 10 * 60)
            if b is None:
                b = next((x for x in bars if x[0] >= 10 * 60), bars[-1])
            sell, reason = b[4], "S6-10:00卖出" if env_mode == "s6" else "10:00卖出"
    return sell, reason


def _fallback_sell(buy, bars):
    """现状 5m 卖法（原始价）：涨停价优先 → -5% 止损 → 14:55 收盘；无 5m 跳过。"""
    if not buy or buy <= 0 or not bars:
        return None
    limit = _limit_price(buy, 0.10)
    stop_price = buy * 0.95
    for minute, _o, hi, _lo, cl in bars:
        if minute > 14 * 60 + 55:
            break
        if hi >= limit:
            return limit
        if cl <= stop_price:
            return cl
    b = _bar_at(bars, 14 * 60 + 55)
    return b[4] if b else bars[-1][4]


def _quarter_of(d):
    return f"{d[:4]}Q{(int(d[4:6]) - 1) // 3 + 1}"


def _metrics(capitals, rets):
    win = sum(1 for r in rets if r > 0)
    loss = sum(1 for r in rets if r < 0)
    out = {
        "win": round(win / (win + loss) * 100, 1) if (win + loss) else 0,
        "count": len(rets),
    }
    peak = trough = None
    mdd = mg = 0.0
    for c in capitals:
        if peak is None or c > peak:
            peak = c
        if peak and c >= 0:
            mdd = max(mdd, (peak - c) / peak)
        if trough is None or c < trough:
            trough = c
        if trough and trough > 0:
            mg = max(mg, (c - trough) / trough)
    out["drawdown"] = round(mdd * 100, 1)
    out["maxProfit"] = round(mg * 100, 1)
    cw = cl = mw = ml = 0
    for r in rets:
        if r > 0:
            cw += 1
            cl = 0
            mw = max(mw, cw)
        elif r < 0:
            cl += 1
            cw = 0
            ml = max(ml, cl)
        else:
            cw = cl = 0
    out["maxWinStreak"] = mw
    out["maxLossStreak"] = ml
    total = capitals[-1] / INIT_CAPITAL - 1.0 if capitals else 0.0
    out["totalReturn"] = round(total * 100, 1)
    out["annual"] = round(((1 + total) ** (250.0 / len(rets)) - 1) * 100, 1) if rets and total > -1 else 0
    return out


def _cache_path(root, strategy, months, pick_mode, sell_mode="bplus", env_mode="s6", width_mode="s6"):
    return os.path.join(root, "AIData", "BACKTEST_CACHE", f"bplus_{strategy}_{months}_{pick_mode}_{sell_mode}_{env_mode}_{width_mode}.json")


def _input_sig(root, strategy):
    folder = os.path.join(root, "AIData", "STRATEGY", strategy)
    sig = 0.0
    try:
        for name in os.listdir(folder)[:2000]:
            p = os.path.join(folder, name)
            if os.path.isfile(p):
                sig = max(sig, os.path.getmtime(p))
    except OSError:
        pass
    idx = os.path.join(root, "AIData", "INDEX_5M")
    try:
        for name in os.listdir(idx):
            p = os.path.join(idx, name)
            if os.path.isfile(p):
                sig = max(sig, os.path.getmtime(p))
    except OSError:
        pass
    return round(sig, 3)


def _load_trading_dates(root):
    path = os.path.join(root, "AIData", "TRADING_DATES")
    out = []
    try:
        for line in _read_text(path).splitlines():
            d = line.strip().replace("-", "")[:8]
            if len(d) == 8 and d.isdigit():
                out.append(d)
    except OSError:
        return []
    return sorted(set(out))


def _load_alignment(root):
    """读 AIData/5M_ALIGN/alignment.json（小美 task-21）；返回 {(code,date): True} 除权日提示。"""
    path = os.path.join(root, "AIData", "5M_ALIGN", "alignment.json")
    out = {}
    if not os.path.isfile(path):
        return out
    try:
        raw = json.loads(_read_text(path))
    except (OSError, ValueError):
        return out

    def _norm_date(v):
        d = str(v or "").replace("-", "")[:8]
        return d if len(d) == 8 and d.isdigit() else None

    def _add(code, date):
        c = str(code or "").upper()
        d = _norm_date(date)
        if c and d:
            out[(c, d)] = True

    items = []
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict):
        for key in ("items", "records", "dates", "trades", "alignment"):
            if isinstance(raw.get(key), list):
                items = raw[key]
                break
        if not items:
            for code, val in raw.items():
                if isinstance(val, list):
                    for x in val:
                        if isinstance(x, dict):
                            items.append({"code": code, **x})
                        else:
                            items.append({"code": code, "date": x})
                elif isinstance(val, dict):
                    items.append({"code": code, **val})
    for it in items:
        if not isinstance(it, dict):
            continue
        code = it.get("code") or it.get("stock") or it.get("symbol")
        changed = it.get("exDate") or it.get("ex_date") or it.get("factorChanged") or it.get("changed")
        dates = it.get("date") or it.get("dates") or it.get("tradeDate") or it.get("t0")
        if isinstance(dates, list):
            for d in dates:
                _add(code, d)
        elif dates:
            _add(code, dates)
        elif changed:
            _add(code, it.get("t0") or it.get("date"))
    return out


def _equity_candle(prev, close, paths):
    """权益蜡烛：open=前一日权益，close=当日权益，high/low 用持仓票 5m 路径折算。"""
    high = max(prev, close)
    low = min(prev, close)
    for buy, bars in paths or []:
        if not buy or buy <= 0 or not bars:
            continue
        for bar in bars:
            try:
                hi = bar[2]
                lo = bar[3]
            except (TypeError, IndexError):
                continue
            if hi is not None:
                high = max(high, prev * (1 + (float(hi) - buy) / buy))
            if lo is not None:
                low = min(low, prev * (1 + (float(lo) - buy) / buy))
    return {"open": round(prev, 2), "high": round(high, 2), "low": round(low, 2), "close": round(close, 2)}


def _sentiment_series(trading_dates):
    """三指数情绪：(MA5-MA60)/MA60；银行反向；三者平均。T-1 数据，缺失=null。"""
    codes = [("000300.SH", 1), ("399006.SZ", 1), ("399986.SZ", -1)]
    daily = {}
    for code, _sign in codes:
        per = {d: v[3] for d, v in _lday_bars(code).items() if v and v[3]}
        daily[code] = per
    anchor = daily.get("000300.SH") or {}
    all_days = sorted(anchor)
    out = []
    for t in trading_dates:
        prior = [d for d in all_days if d < t]
        value = None
        comps = {}
        if len(prior) >= 60:
            vals = []
            ok = True
            for code, sign in codes:
                per = daily.get(code) or {}
                series = [per[d] for d in prior[-60:] if d in per]
                if len(series) < 60:
                    ok = False
                    break
                ma5 = sum(series[-5:]) / 5.0
                ma60 = sum(series) / 60.0
                if not ma60:
                    ok = False
                    break
                c = (ma5 - ma60) / ma60 * 100.0 * sign
                comps[code] = round(c, 3)
                vals.append(c)
            if ok and len(vals) == 3:
                value = round(sum(vals) / 3.0, 3)
                comps["value"] = value
        out.append({"time": t[:4] + "-" + t[4:6] + "-" + t[6:8], "value": value,
                    "h300": comps.get("000300.SH"), "cyb": comps.get("399006.SZ"),
                    "bank": comps.get("399986.SZ")})
    return out


def run_bplus(root, strategy="TPO_M5", months=12, pick_mode="first", refresh=False, sell_mode="bplus", env_mode="s6", width_mode="s6"):
    started = time.time()
    try:
        months = max(1, min(60, int(months or 12)))
    except (TypeError, ValueError):
        months = 12
    if pick_mode not in ("first", "avg", "last"):
        pick_mode = "first"
    if sell_mode not in ("bplus", "legacy5m", "day"):
        sell_mode = "bplus"
    if env_mode not in ("s6", "three", "legacy7"):
        env_mode = "s6"
    if width_mode not in ("s6", "three", "legacy7"):
        width_mode = "s6"
    cache_file = _cache_path(root, strategy, months, pick_mode, sell_mode, env_mode, width_mode)
    sig = _input_sig(root, strategy)
    if not refresh and os.path.isfile(cache_file):
        try:
            cached = json.loads(_read_text(cache_file))
            if (cached.get("engineVersion") == ENGINE_VERSION
                    and cached.get("inputSig") == sig
                    and time.time() - float(cached.get("savedAt") or 0) < CACHE_TTL
                    and cached.get("pick_mode") == pick_mode
                    and cached.get("sell_mode") == sell_mode
                    and cached.get("envMode") == env_mode
                    and cached.get("widthMode") == width_mode):
                cached["cacheHit"] = True
                cached["elapsedMs"] = int((time.time() - started) * 1000)
                return cached
        except (OSError, ValueError, TypeError):
            pass

    daily = _load_strategy(root, strategy)
    if not daily:
        return {"ok": False, "strategy": strategy, "sell_mode": "bplus", "pick_mode": pick_mode,
                "error": f"STRATEGY/{strategy} 无数据", "metrics": {}, "capitalKline": [],
                "monthRet": [], "quarterRet": [], "yearRet": [], "dist": {}, "fallbackDays": 0}
    # 当天的 TPO 文件是给下一交易日的前瞻名单，尚不是已完成的 T-0 交易，回测剔除当天
    _today_ymd = _dt.datetime.now().strftime("%Y%m%d")
    all_dates = [d for d in sorted(daily) if d < _today_ymd]
    if not all_dates:
        all_dates = sorted(daily)
    latest = _dt.datetime.strptime(all_dates[-1], "%Y%m%d")
    cutoff = (latest - _dt.timedelta(days=months * 31)).strftime("%Y%m%d")
    dates = [d for d in all_dates if d >= cutoff]
    idx = _load_index_data(root, env_mode, width_mode)
    all_trade_days = _load_trading_dates(root)
    if dates:
        # 图表时间轴：回测区间首个策略日 → 最新市场交易日（含 11-09），
        # 指标/交易仍只用已完成的策略日期，末尾空仓日资金平盘、情绪取 T-1。
        _today = _dt.date.today().strftime("%Y%m%d")
        _market_last = max([d for d in all_trade_days if d <= _today] or [dates[-1]])
        _chart_end = max(dates[-1], _market_last)
        trading_dates = [d for d in all_trade_days if dates[0] <= d <= _chart_end]
        if not trading_dates:
            trading_dates = list(dates)
    else:
        trading_dates = []
    align = _load_alignment(root)
    ex_dates = []
    all_idx = all_dates
    prev_days = {}
    for i, d in enumerate(all_idx):
        if i > 0:
            prev_days[d] = all_idx[i - 1]
        else:
            prior_idx = [x for x in idx["dates"] if x < d]
            if prior_idx:
                prev_days[d] = prior_idx[-1]

    capital = INIT_CAPITAL
    prev_capital = INIT_CAPITAL
    capitals, rets, kline = [], [], []
    dist = {"open": [], "high": [], "low": [], "close": []}
    month, quarter, year = {}, {}, {}
    fallback_days = 0
    fallback_dates = []
    bplus_days = 0
    reasons = {}
    first_bplus = None
    cap_candle_map = {}
    for date in dates:
        open_capital = capital
        rows = daily.get(date) or []
        if not rows:
            capitals.append(round(capital, 2))
            rets.append(0.0)
            kline.append(None)
            cap_candle_map[date] = {"open": round(capital, 2), "high": round(capital, 2),
                                    "low": round(capital, 2), "close": round(capital, 2)}
            for k in dist:
                dist[k].append(None)
            continue
        if pick_mode == "first":
            selected = [rows[0]]
        elif pick_mode == "last":
            selected = [rows[-1]]
        else:
            selected = list(rows)
        env_above = idx["env"].get(date)
        env_score = idx["env_score"].get(date)
        env_good = idx["env_good"].get(date)
        width10 = idx["width10"].get(date)
        width_threshold = 4 if width_mode == "legacy7" else 2
        bplus_ok = sell_mode == "bplus" and (env_score is not None if env_mode == "s6" else (env_good is not None and width10 is not None))
        if sell_mode == "bplus":
            if bplus_ok:
                bplus_days += 1
                if first_bplus is None:
                    first_bplus = date
            else:
                fallback_days += 1
                fallback_dates.append(date)
        valid = []
        paths = []
        fallback_used = False
        for row in selected:
            code = row[0]
            date_raw = _day_ohlc(code, date)
            if sell_mode == "day":
                buy = _raw_daily_buy(code, date)
            else:
                buy = _raw_buy_price(code, date)
            if not buy or buy <= 0:
                continue
            bars = (_lc5_days(code) or {}).get(date)
            day_raw = date_raw if sell_mode == "day" else None
            if sell_mode == "legacy5m":
                sp, reason = _fallback_sell(buy, bars), "legacy5m"
            elif sell_mode == "day":
                sp, reason = _day_sell(buy, date_raw, code), "day"
            elif bplus_ok and bars:
                sp, reason = _bplus_sell(bars, buy, bool(env_good), width10, code, width_threshold, env_mode, env_score)
            else:
                sp, reason = _fallback_sell(buy, bars), "fallback"
                fallback_used = True
            if sp is None:
                fallback_used = True
                continue
            ret = sp / buy - 1.0
            if (code, date) in align:
                ex_dates.append({"code": code, "date": date, "ret": round(ret * 100, 2)})
            valid.append((row, buy, sp, reason, ret, day_raw))
            paths.append((buy, bars))
            reasons[reason] = reasons.get(reason, 0) + 1
        day_net = 0.0
        if valid:
            day_net = sum(x[4] for x in valid) / len(valid)
        capital *= (1 + day_net)
        capitals.append(round(capital, 2))
        rets.append(day_net)
        ym = date[:6]
        month[ym] = month.get(ym, 1.0) * (1 + day_net)
        quarter[_quarter_of(date)] = quarter.get(_quarter_of(date), 1.0) * (1 + day_net)
        year[date[:4]] = year.get(date[:4], 1.0) * (1 + day_net)
        if valid:
            opcts, hpcts, lpcts, cpcts, vols = [], [], [], [], []
            for row, buy, _sp, _reason, _ret, day_raw in valid:
                if day_raw:
                    op, hp, lp, cp = day_raw
                else:
                    op, hp, lp, cp = _f(row[4]), _f(row[5]), _f(row[6]), _f(row[7])
                if None not in (op, hp, lp, cp) and buy:
                    opcts.append((op - buy) / buy)
                    hpcts.append((hp - buy) / buy)
                    lpcts.append((lp - buy) / buy)
                    cpcts.append((cp - buy) / buy)
                    v = _f(row[8])
                    if v:
                        vols.append(v)
            t = date[:4] + "-" + date[4:6] + "-" + date[6:8]
            k_close = prev_capital * (1 + day_net)
            if opcts:
                kline.append({
                    "time": t,
                    "open": round(prev_capital * (1 + sum(opcts) / len(opcts)), 2),
                    "high": round(prev_capital * (1 + sum(hpcts) / len(hpcts)), 2),
                    "low": round(prev_capital * (1 + sum(lpcts) / len(lpcts)), 2),
                    "close": round(k_close, 2),
                    "volume": round(sum(vols) / len(vols), 2) if vols else 0,
                    "pre_close": round(prev_capital, 2),
                })
                dist["open"].append(sum(opcts) / len(opcts))
                dist["high"].append(sum(hpcts) / len(hpcts))
                dist["low"].append(sum(lpcts) / len(lpcts))
                dist["close"].append(sum(cpcts) / len(cpcts))
            else:
                kline.append(None)
                for k in dist:
                    dist[k].append(None)
            prev_capital = k_close
        else:
            kline.append(None)
            for k in dist:
                dist[k].append(None)
        cap_candle_map[date] = _equity_candle(open_capital, capital, paths)

    metrics = _metrics(capitals, rets)
    capital_candles = []
    last_cap = INIT_CAPITAL
    for d in trading_dates:
        c = cap_candle_map.get(d)
        if not c:
            c = {"open": round(last_cap, 2), "high": round(last_cap, 2),
                 "low": round(last_cap, 2), "close": round(last_cap, 2)}
        capital_candles.append({"time": d[:4] + "-" + d[4:6] + "-" + d[6:8], **c})
        last_cap = c["close"]
    sentiment = _sentiment_series(trading_dates)
    payload = {
        "ok": True,
        "strategy": strategy,
        "sell_mode": sell_mode,
        "pick_mode": pick_mode,
        "envMode": env_mode,
        "widthMode": width_mode,
        "widthThreshold": 2 if width_mode == "s6" else (4 if width_mode == "legacy7" else 3),
        "envRule": ("S6评分：沪深300上+1、创业板指上+1、中证银行≤MA60+1；score≥2持有，score=1看10:00宽度，score=0卖"
                    if env_mode == "s6" else
                    ("日线口径：沪深300上 且 创业板指上 且 中证银行下" if env_mode == "three" else "7 成长宽基 ≥4 在日线 MA60 上")),
        "envScore": (idx["env_score"].get(dates[-1]) if dates else None),
        "envDetails": (idx["env_details"].get(dates[-1]) if dates else []),
        "months": months,
        "metrics": metrics,
        "monthRet": [{"k": k, "ret": round((v - 1) * 100, 1)} for k, v in sorted(month.items())],
        "quarterRet": [{"k": k, "ret": round((v - 1) * 100, 1)} for k, v in sorted(quarter.items())],
        "yearRet": [{"k": k, "ret": round((v - 1) * 100, 1)} for k, v in sorted(year.items())],
        "capitalKline": kline,
        "capitalCandles": capital_candles,
        "sentiment": sentiment,
        "dist": dist,
        "exDateTrades": len(ex_dates),
        "exDateDetails": ex_dates[:20],
        "fallbackDates": fallback_dates[:10],
        "bplusDays": bplus_days,
        "bplusStart": (first_bplus[:4] + "-" + first_bplus[4:6] + "-" + first_bplus[6:8]) if first_bplus else None,
        "reasons": reasons,
        "tradingDates": [d[:4] + "-" + d[4:6] + "-" + d[6:8] for d in trading_dates],
        "dateFrom": dates[0][:4] + "-" + dates[0][4:6] + "-" + dates[0][6:8] if dates else None,
        "dateTo": dates[-1][:4] + "-" + dates[-1][4:6] + "-" + dates[-1][6:8] if dates else None,
        "badge": {"bplus": "B+ 卖法 · 2026 年起生效（此前回退现状）",
                  "legacy5m": "原始价 5m 卖法（毛收益）",
                  "day": "原始价日线卖法（毛收益）"}.get(sell_mode, "原始价回测"),
        "fallbackDays": fallback_days if sell_mode == "bplus" else 0,
        "fallbackNote": "INDEX_5M/MA60 不足的日期回退现状 5m 卖法",
        "inputSig": sig,
        "engineVersion": ENGINE_VERSION,
        "savedAt": time.time(),
        "generatedAt": _dt.datetime.now().isoformat(timespec="seconds"),
        "elapsedMs": int((time.time() - started) * 1000),
        "cacheHit": False,
        "engineVersion": ENGINE_VERSION,
        "strategies": [strategy],
    }
    try:
        os.makedirs(os.path.dirname(cache_file), exist_ok=True)
        tmp = cache_file + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, cache_file)
    except OSError as exc:
        payload["cacheError"] = f"{type(exc).__name__}: {exc}"
    return payload
