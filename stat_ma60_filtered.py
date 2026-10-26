import os, glob, datetime as _dt, statistics

ROOT    = r"C:/MarcoAI"
SIG_DIR = os.path.join(ROOT, "AIData", "TOP_FIRST_VOL_MA60")
ONE_D   = os.path.join(ROOT, "AIData", "1D")
FIVE_M  = os.path.join(ROOT, "AIData", "5M")
_1d_cache, _5m_cache = {}, {}

def load_1d(code):
    if code in _1d_cache: return _1d_cache[code]
    p = os.path.join(ONE_D, code); s = {}
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            for ln in f:
                ps = ln.strip().split("|")
                if len(ps) < 11: continue
                try:
                    s[ps[0]] = dict(o=float(ps[1]), h=float(ps[2]), l=float(ps[3]), c=float(ps[4]),
                                    vol=float(ps[5]), prev=float(ps[7]), turn=float(ps[10]))
                except ValueError: continue
    _1d_cache[code] = s; return s

def load_5m(code):
    if code in _5m_cache: return _5m_cache[code]
    p = os.path.join(FIVE_M, code); bars = []
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            for ln in f:
                ps = ln.strip().split("|")
                if len(ps) < 6: continue
                try:
                    dt = _dt.datetime.strptime(ps[0], "%Y-%m-%d %H:%M:%S")
                    bars.append((dt, float(ps[1]), float(ps[2]), float(ps[3]), float(ps[4])))
                except (ValueError, TypeError): continue
        bars.sort(key=lambda x: x[0])
    _5m_cache[code] = bars; return bars

def nth_after(series, date, n):
    keys = sorted(series.keys())
    if date not in series:
        for k in keys:
            if k >= date: date = k; break
        else: return None
    i = keys.index(date); j = i + n
    return keys[j] if 0 <= j < len(keys) else None

# 真实卖出: 深跳空(开盘<=-2%)→开盘即割(按开盘价成交); 温和→COMB(回本线/-2%止损,午后转MA60)
def sell_real(Tc, o1, day):
    if o1/Tc - 1 <= -0.02:
        return o1, "OPEN_CUT"          # 真实: 按开盘价
    for b in day:
        after = b["dt"].hour >= 14
        if b["l"] <= Tc*0.98:
            return Tc*0.98, "STOP2"    # 理想化-2%止损(温和开盘可成交)
        if after and b["ma"] is not None and b["c"] >= b["ma"]:
            return b["c"], "MA60"
        if (not after) and b["c"] >= Tc:
            return b["c"], "BREAKEVEN"
    return day[-1]["c"], "CLOSE"

def equity_curve(rets_by_date):
    # rets_by_date: dict date->list of per-name returns; 每日等权组合, 跨日复利
    dates = sorted(rets_by_date)
    eq = 1.0; peak = 1.0; mdd = 0.0
    for d in dates:
        eq *= (1 + statistics.mean(rets_by_date[d]))
        peak = max(peak, eq); mdd = min(mdd, eq/peak - 1)
    return None, mdd, eq - 1

def report(name, trades):
    # trades: list of (date, ret)
    if not trades:
        print(f"{name}: 无"); return
    rets = [t[1] for t in trades]
    dates = {}
    for d, r, why in trades: dates.setdefault(d, []).append(r)
    curve, mdd, tot = equity_curve(dates)
    reasons = {}
    for d, r, why in trades:
        reasons[why] = reasons.get(why, 0) + 1
    print(f"\n=== {name} (n={len(trades)} 交易日={len(dates)}) ===")
    print(f"  单笔: 均收益={statistics.mean(rets)*100:.2f}%  胜率={sum(1 for x in rets if x>0)/len(rets)*100:.1f}%  "
          f"中位={statistics.median(rets)*100:.2f}%  最大亏={min(rets)*100:.2f}%  P10={sorted(rets)[len(rets)//10]*100:.2f}%")
    print(f"  资金曲线: 累计={tot*100:.1f}%  最大回撤={mdd*100:.2f}%  交易日数={len(dates)}")
    print(f"  卖出原因分布: {reasons}")

# 取合格样本 + T日特征
sig = {}
for fp in glob.glob(os.path.join(SIG_DIR, "*")):
    d = os.path.basename(fp)
    if not (len(d) == 8 and d.isdigit()): continue
    with open(fp, encoding="utf-8") as f:
        codes = [ln.split("|")[0].split()[0].strip() for ln in f if ln.strip()]
    if codes: sig[d] = codes

all_trades, filt_trades = [], []
for T, codes in sig.items():
    for code in codes:
        s1 = load_1d(code)
        if T not in s1: continue
        t1 = nth_after(s1, T, 1)
        if t1 is None or t1 not in s1: continue
        Tc = s1[T]["c"]; o1, h1, l1, c1 = s1[t1]["o"], s1[t1]["h"], s1[t1]["l"], s1[t1]["c"]
        bars = load_5m(code)
        if len(bars) < 60: continue
        ma = [None]*len(bars)
        for i in range(len(bars)):
            if i >= 59: ma[i] = sum(bars[j][4] for j in range(i-59, i+1)) / 60.0
        t1d = _dt.datetime.strptime(t1, "%Y%m%d").date()
        first_bars = [b for b in bars if b[0].date() == t1d]
        if not first_bars: continue
        fi = bars.index(first_bars[0])
        if fi < 59: continue
        ma60 = sum(bars[j][4] for j in range(fi-59, fi+1)) / 60.0
        if not (first_bars[0][1] < ma60): continue
        day = [{"dt": b[0], "l": b[3], "c": b[4], "ma": ma[i]}
               for i, b in enumerate(bars) if b[0].date() == t1d]
        # T日特征
        Td = s1[T]; prev = Td["prev"]
        if prev <= 0: continue
        close_str = Tc/Td["h"]; gap_t = Td["o"]/prev - 1; turn = Td["turn"]
        keep = (turn < 3.0) and (close_str >= 0.95) and (gap_t < 0.09)
        sp, why = sell_real(Tc, o1, day)
        ret = sp/Tc - 1
        all_trades.append((t1, ret, why))
        if keep:
            filt_trades.append((t1, ret, why))

report("不过滤(全622, 真实卖出)", all_trades)
report("过滤后(换手<3%&收盘强度>=0.95&跳空<9%, 真实卖出)", filt_trades)
