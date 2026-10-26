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

# 真实卖出: 深跳空(开盘<=成本-2%)开盘即割; 温和: 上午回本线/-stop止损, 午后转MA60/收盘
def sell_real(Tc, o1, day, stop):
    if o1/Tc - 1 <= -0.02:
        return o1/Tc-1, "OPEN_CUT"
    for b in day:
        after = b["dt"].hour >= 14
        if b["l"] <= Tc*(1-stop):
            return -stop, "STOP"
        if after and b["ma"] is not None and b["c"] >= b["ma"]:
            return b["c"]/Tc-1, "MA60"
        if (not after) and b["c"] >= Tc:
            return b["c"]/Tc-1, "BREAKEVEN"
    return day[-1]["c"]/Tc-1, "CLOSE"

# 取全量1862 + T日特征 + 两种止损(-2%/-3%)真实收益
rows = []
sig = {}
for fp in glob.glob(os.path.join(SIG_DIR, "*")):
    d = os.path.basename(fp)
    if not (len(d) == 8 and d.isdigit()): continue
    with open(fp, encoding="utf-8") as f:
        codes = [ln.split("|")[0].split()[0].strip() for ln in f if ln.strip()]
    if codes: sig[d] = codes
for T, codes in sig.items():
    for code in codes:
        s1 = load_1d(code)
        if T not in s1: continue
        t1 = nth_after(s1, T, 1)
        if t1 is None or t1 not in s1: continue
        Tc = s1[T]["c"]; o1 = s1[t1]["o"]
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
        day = [{"dt": b[0], "l": b[3], "c": b[4], "ma": ma[i]}
               for i, b in enumerate(bars) if b[0].date() == t1d]
        Td = s1[T]; prev = Td["prev"]
        if prev <= 0: continue
        cs = Tc/Td["h"]; gt = Td["o"]/prev - 1; turn = Td["turn"]
        r2, _ = sell_real(Tc, o1, day, 0.02)
        r3, _ = sell_real(Tc, o1, day, 0.03)
        rows.append(dict(t1=t1, Tc=Tc, o1=o1, turn=turn, cs=cs, gt=gt, r2=r2, r3=r3))

def is_kept(r): return r["turn"] < 3.0 and r["cs"] >= 0.95 and r["gt"] < 0.09

def overall(name, items):  # items: list of (t1, ret)
    rs = [r for _, r in items]
    eq = 1.0; peak = 1.0; mdd = 0.0
    by_d = {}
    for d, r in items: by_d.setdefault(d, []).append(r)
    for d in sorted(by_d):
        eq *= (1 + statistics.mean(by_d[d])); peak = max(peak, eq); mdd = min(mdd, eq/peak-1)
    print(f"  {name}: n={len(items)} 均收益={statistics.mean(rs)*100:.2f}% 胜率={sum(1 for x in rs if x>0)/len(rs)*100:.1f}% "
          f"最大亏={min(rs)*100:.2f}% 累计(复利)={(eq-1)*100:.1f}% 回撤={mdd*100:.1f}%")

def monthly(name, items):  # items: list of (t1, ret)
    months = {}
    for d, r in items: months.setdefault(d[:6], {}).setdefault(d, []).append(r)
    print(f"\n=== {name} (每月收益, 按T+1平仓月) ===")
    print(f"  {'月份':>7}{'笔数':>6}{'均收益%':>9}{'月收益%(日均等权复利)':>22}{'累计%':>10}")
    eq = 1.0; peak = 1.0; mdd = 0.0
    for ym in sorted(months):
        days = months[ym]; mr = 1.0
        for d, rs in days.items(): mr *= (1 + statistics.mean(rs))
        eq *= mr; peak = max(peak, eq); mdd = min(mdd, eq/peak-1)
        n = sum(len(rs) for rs in days.values())
        avg = statistics.mean([x for rs in days.values() for x in rs])*100
        print(f"  {ym:>7}{n:>6}{avg:>9.2f}{ (mr-1)*100:>22.2f}{ (eq-1)*100:>10.1f}")
    print(f"  -> 总累计={(eq-1)*100:.1f}%  最大回撤={mdd*100:.1f}%")

print(f"全量首板+MA60(有T+1数据) = {len(rows)}")

# 全量 不过滤
all2 = [(r["t1"], r["r2"]) for r in rows]   # -2%止损
all3 = [(r["t1"], r["r3"]) for r in rows]   # -3%止损
print("\n[全量1862 不过滤]")
overall("  真实卖 -2%止损", all2)
overall("  真实卖 -3%止损", all3)
monthly("全量1862 真实卖(-2%止损)", all2)

# 过滤后
f2 = [(r["t1"], r["r2"]) for r in rows if is_kept(r)]
f3 = [(r["t1"], r["r3"]) for r in rows if is_kept(r)]
print("\n[过滤后: 换手<3% & 收盘强度>=0.95 & 跳空<9%]")
overall("  真实卖 -2%止损", f2)
overall("  真实卖 -3%止损", f3)
monthly("过滤后 真实卖(-2%止损)", f2)
