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

# 取样本：T日尾盘买(T收) / T+1首根5m开<MA60 / 回测T+1卖点
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
        o1, h1, l1, c1 = s1[t1]            # T+1 日线 OHLC
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
        if first["ma"] is None or not (first["o"] < first["ma"]):
            continue
        qual.append((s1[T][3], o1, h1, l1, c1, day))   # T_close, T+1 OHLC, 5m

print(f"[回测] 首板+MA60 / T日尾盘买(T收) / T+1必须卖 / T+1首根5m开<MA60")
print(f"合格样本(个股)={len(qual)}\n")

O, C, H, L, R, RK2, RK3 = [], [], [], [], [], [], []
BE, BEK2, BEK3 = [], [], []
reclaim_cnt = 0
be_cnt = 0
for T_close, o1, h1, l1, c1, day in qual:
    O.append(o1/T_close - 1)
    C.append(c1/T_close - 1)
    H.append(h1/T_close - 1)
    L.append(l1/T_close - 1)
    # MA60 收复卖
    rp = None
    for b in day:
        if b["ma"] is not None and b["c"] >= b["ma"]:
            rp = b["c"]; break
    if rp is not None: reclaim_cnt += 1
    R.append((rp/T_close - 1) if rp else c1/T_close - 1)
    # 回本线(T收)收复卖
    bp = None
    for b in day:
        if b["c"] >= T_close:
            bp = b["c"]; break
    if bp is not None: be_cnt += 1
    BE.append((bp/T_close - 1) if bp else c1/T_close - 1)
    # 带止损版本
    for k, rk, bek in [(0.02, RK2, BEK2), (0.03, RK3, BEK3)]:
        p1 = None
        for b in day:
            if b["l"] <= T_close*(1-k):
                p1 = T_close*(1-k); break
            if b["ma"] is not None and b["c"] >= b["ma"]:
                p1 = b["c"]; break
        if p1 is None: p1 = c1
        rk.append(p1/T_close - 1)
        p2 = None
        for b in day:
            if b["l"] <= T_close*(1-k):
                p2 = T_close*(1-k); break
            if b["c"] >= T_close:
                p2 = b["c"]; break
        if p2 is None: p2 = c1
        bek.append(p2/T_close - 1)

def agg(rs):
    rs = sorted(rs); n = len(rs)
    def pct(p):
        k = (n-1)*p; f = int(k); c = min(f+1, n-1)
        return rs[f] + (rs[c]-rs[f])*(k-f)
    return dict(n=n, avg=statistics.mean(rs)*100, med=statistics.median(rs)*100,
               win=sum(1 for x in rs if x>0)/n*100, worst=min(rs)*100, p10=pct(.1)*100)

print(f"盘中曾收回MA60的比例 = {reclaim_cnt/len(qual)*100:.1f}%   曾回到T收(回本)的比例 = {be_cnt/len(qual)*100:.1f}%\n")
print(f"{'卖点策略':<24}{'笔数':>5}{'赢率%':>8}{'均收益%':>9}{'中位%':>8}{'最大亏%':>9}{'P10亏%':>9}")
print("-"*73)
for name, rs in [("O 开盘就卖", O), ("C 收盘才卖", C),
                 ("R 收回MA60卖", R), ("RK 收回MA60或-2%止损", RK2), ("RK 收回MA60或-3%止损", RK3),
                 ("BE 回本线(回T收)卖", BE), ("BEK 回本或-2%止损", BEK2), ("BEK 回本或-3%止损", BEK3),
                 ("H 卖在盘中最高(上界)", H), ("L 卖在盘中最低(下界)", L)]:
    a = agg(rs)
    print(f"{name:<22}{a['n']:>5}{a['win']:>8.1f}{a['avg']:>9.2f}{a['med']:>8.2f}{a['worst']:>9.2f}{a['p10']:>9.2f}")
