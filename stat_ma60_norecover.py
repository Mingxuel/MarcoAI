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
                if len(ps) < 5: continue
                try: s[ps[0]] = (float(ps[1]), float(ps[2]), float(ps[3]), float(ps[4]))
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

qual = []
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
        o1, h1, l1, c1 = s1[t1]
        bars = load_5m(code)
        if len(bars) < 60: continue
        ma = [None]*len(bars)
        for i in range(len(bars)):
            if i >= 59: ma[i] = sum(bars[j][4] for j in range(i-59, i+1)) / 60.0
        t1d = _dt.datetime.strptime(t1, "%Y%m%d").date()
        day = [{"dt": b[0], "o": b[1], "h": b[2], "l": b[3], "c": b[4], "ma": ma[i]}
               for i, b in enumerate(bars) if b[0].date() == t1d]
        if not day: continue
        first = day[0]
        if first["ma"] is None or not (first["o"] < first["ma"]): continue
        qual.append((s1[T][3], o1, h1, l1, c1, day))

def agg(rs):
    rs = sorted(rs); n = len(rs)
    def pct(p):
        k = (n-1)*p; f = int(k); c = min(f+1, n-1)
        return rs[f] + (rs[c]-rs[f])*(k-f)
    return dict(n=n, avg=statistics.mean(rs)*100, med=statistics.median(rs)*100,
               win=sum(1 for x in rs if x>0)/n*100, worst=min(rs)*100, p10=pct(.1)*100)

# COMB: 上午等T收或-2%止损；下午(>=14:00)等MA60或-2%止损；否则收盘
def comb(Tc, day):
    for b in day:
        after = b["dt"].hour >= 14
        if b["l"] <= Tc*0.98:
            return Tc*0.98
        if after and b["ma"] is not None and b["c"] >= b["ma"]:
            return b["c"]
        if (not after) and b["c"] >= Tc:
            return b["c"]
    return day[-1]["c"]

all_O, all_C, all_COMB = [], [], []
nr_O, nr_C, nr_Rma, nr_RK2, nr_COMB = [], [], [], [], []   # nr = 未回到T收子组
nr_ma_reclaim = 0
for Tc, o1, h1, l1, c1, day in qual:
    all_O.append(o1/Tc-1); all_C.append(c1/Tc-1); all_COMB.append(comb(Tc, day)/Tc-1)
    reached = any(b["c"] >= Tc for b in day)
    if reached:
        continue
    # 未回到T收的子组
    nr_O.append(o1/Tc-1)
    nr_C.append(c1/Tc-1)
    rma = None
    for b in day:
        if b["ma"] is not None and b["c"] >= b["ma"]:
            rma = b["c"]; break
    if rma is not None: nr_ma_reclaim += 1
    nr_Rma.append((rma/Tc-1) if rma else c1/Tc-1)
    p = None
    for b in day:
        if b["l"] <= Tc*0.98:
            p = Tc*0.98; break
        if b["ma"] is not None and b["c"] >= b["ma"]:
            p = b["c"]; break
    if p is None: p = c1
    nr_RK2.append(p/Tc-1)
    nr_COMB.append(comb(Tc, day)/Tc-1)

print(f"样本={len(qual)}  其中未回到T收(需 fallback)的子组={len(nr_O)} ({len(nr_O)/len(qual)*100:.1f}%)")
print(f"  未回本子组中，盘中曾收回MA60的比例={nr_ma_reclaim/len(nr_O)*100:.1f}%(说明MA60卖对它们可行)\n")

print("=== 全部 622 只 ===")
for name, rs in [("O 开盘卖", all_O), ("C 收盘卖", all_C), ("COMB 分层退出", all_COMB)]:
    a = agg(rs)
    print(f"  {name:<14} 赢率={a['win']:>5.1f}%  均={a['avg']:>6.2f}%  中位={a['med']:>6.2f}%  最大亏={a['worst']:>6.2f}%")

print(f"\n=== 没回到T收的子组({len(nr_O)}只)：当天怎么办 ===")
for name, rs in [("O 开盘就卖", nr_O), ("C 硬扛到收盘", nr_C),
                 ("Rma 碰MA60就卖(反弹 salvage)", nr_Rma),
                 ("RK  MA60或-2%止损", nr_RK2),
                 ("COMB 分层退出", nr_COMB)]:
    a = agg(rs)
    print(f"  {name:<26} 赢率={a['win']:>5.1f}%  均={a['avg']:>6.2f}%  中位={a['med']:>6.2f}%  最大亏={a['worst']:>6.2f}%  P10={a['p10']:>6.2f}%")
