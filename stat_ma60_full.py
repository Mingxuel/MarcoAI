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

def sell_real(Tc, o1, day):
    if o1/Tc - 1 <= -0.02:
        return o1, "OPEN_CUT"
    for b in day:
        after = b["dt"].hour >= 14
        if b["l"] <= Tc*0.98:
            return Tc*0.98, "STOP2"
        if after and b["ma"] is not None and b["c"] >= b["ma"]:
            return b["c"], "MA60"
        if (not after) and b["c"] >= Tc:
            return b["c"], "BREAKEVEN"
    return day[-1]["c"], "CLOSE"

def equity(rets_by_date):
    dates = sorted(rets_by_date); eq = 1.0; peak = 1.0; mdd = 0.0
    for d in dates:
        eq *= (1 + statistics.mean(rets_by_date[d])); peak = max(peak, eq); mdd = min(mdd, eq/peak - 1)
    return eq - 1, mdd

def agg(rs):
    rs = sorted(rs); n = len(rs)
    def pct(p):
        k = (n-1)*p; f = int(k); c = min(f+1, n-1); return rs[f] + (rs[c]-rs[f])*(k-f)
    return dict(n=n, avg=statistics.mean(rs)*100, med=statistics.median(rs)*100,
               win=sum(1 for x in rs if x>0)/n*100, worst=min(rs)*100, p10=pct(.1)*100)

def report_real(name, trades):
    if not trades:
        print(f"  {name}: 无"); return
    rets = [t[1] for t in trades]
    dates = {}
    for d, r, why in trades: dates.setdefault(d, []).append(r)
    tot, mdd = equity(dates)
    print(f"  {name:<34} n={len(trades):>4} 均={statistics.mean(rets)*100:>6.2f}% 胜率={sum(1 for x in rets if x>0)/len(rets)*100:>5.1f}% "
          f"中位={statistics.median(rets)*100:>6.2f}% 最大亏={min(rets)*100:>6.2f}% 累计={tot*100:>7.1f}% 回撤={mdd*100:>6.2f}%")

# 取全量(不强筛选进场), 仅按首根5m开<MA60分组
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
        Tc = s1[T]["c"]; o1, h1, l1, c1 = s1[t1]["o"], s1[t1]["h"], s1[t1]["l"], s1[t1]["c"]
        bars = load_5m(code)
        if len(bars) < 60: continue
        ma = [None]*len(bars)
        for i in range(len(bars)):
            if i >= 59: ma[i] = sum(bars[j][4] for j in range(i-59, i+1)) / 60.0
        t1d = _dt.datetime.strptime(t1, "%Y%m%d").date()
        fb = [b for b in bars if b[0].date() == t1d]
        if not fb: continue
        fi = bars.index(fb[0])
        if fi < 59: continue
        ma60 = sum(bars[j][4] for j in range(fi-59, fi+1)) / 60.0
        weak = fb[0][1] < ma60
        day = [{"dt": b[0], "l": b[3], "c": b[4], "ma": ma[i]}
               for i, b in enumerate(bars) if b[0].date() == t1d]
        Td = s1[T]; prev = Td["prev"]
        if prev <= 0: continue
        close_str = Tc/Td["h"]; gap_t = Td["o"]/prev - 1; turn = Td["turn"]
        keep = (turn < 3.0) and (close_str >= 0.95) and (gap_t < 0.09)
        sp, why = sell_real(Tc, o1, day)
        rows.append(dict(t1=t1, ret=sp/Tc-1, why=why, weak=weak, keep=keep))

print(f"全量首板+MA60(有T+1数据)={len(rows)}  弱开(首根5m开<MA60)={sum(r['weak'] for r in rows)}  强开={sum(not r['weak'] for r in rows)}")

print("\n########## 真实卖出(深跳空开盘割/温和回本线+-2%止损/午后MA60) ##########")
all_t   = [(r["t1"], r["ret"], r["why"]) for r in rows]
strong  = [(r["t1"], r["ret"], r["why"]) for r in rows if not r["weak"]]
weak    = [(r["t1"], r["ret"], r["why"]) for r in rows if r["weak"]]
filt    = [(r["t1"], r["ret"], r["why"]) for r in rows if r["keep"]]
filt_s  = [(r["t1"], r["ret"], r["why"]) for r in rows if r["keep"] and not r["weak"]]
filt_w  = [(r["t1"], r["ret"], r["why"]) for r in rows if r["keep"] and r["weak"]]
report_real("全量1862(不过滤)", all_t)
report_real("  其中 强开1240", strong)
report_real("  其中 弱开622", weak)
report_real("全量+过滤(换手<3%&收强>=0.95&跳空<9%)", filt)
report_real("  过滤后 强开", filt_s)
report_real("  过滤后 弱开", filt_w)

# 经典理想化卖法表(全量1862) 对照
cls={k:[] for k in ["O","C","BE","BEK2","R"]}
for T, codes in sig.items():
    for code in codes:
        s1=load_1d(code)
        if T not in s1: continue
        t1=nth_after(s1,T,1)
        if t1 is None or t1 not in s1: continue
        Tc=s1[T]["c"]; o1,h1,l1,c1=s1[t1]["o"],s1[t1]["h"],s1[t1]["l"],s1[t1]["c"]
        bars=load_5m(code)
        if len(bars)<60: continue
        ma=[None]*len(bars)
        for i in range(len(bars)):
            if i>=59: ma[i]=sum(bars[j][4] for j in range(i-59,i+1))/60.0
        t1d=_dt.datetime.strptime(t1,"%Y%m%d").date()
        fb=[b for b in bars if b[0].date()==t1d]
        if not fb: continue
        fi=bars.index(fb[0])
        if fi<59: continue
        ma60=sum(bars[j][4] for j in range(fi-59,fi+1))/60.0
        day=[{"dt":b[0],"l":b[3],"c":b[4],"ma":ma[i]} for i,b in enumerate(bars) if b[0].date()==t1d]
        O=o1/Tc-1; C=c1/Tc-1
        bp=next((b["c"] for b in day if b["c"]>=Tc),None); BE=(bp/Tc-1) if bp else C
        p2=None
        for b in day:
            if b["l"]<=Tc*0.98: p2=Tc*0.98; break
            if b["c"]>=Tc: p2=b["c"]; break
        BEK2=(p2/Tc-1) if p2 else C
        rp=next((b["c"] for b in day if b["ma"] is not None and b["c"]>=b["ma"]),None); R=(rp/Tc-1) if rp else C
        for k,v in [("O",O),("C",C),("BE",BE),("BEK2",BEK2),("R",R)]: cls[k].append(v)

print("\n########## 经典理想化卖法(全量1862, -2%止损按-2%成交) ##########")
print(f"{'策略':<22}{'笔数':>5}{'赢率%':>8}{'均收益%':>9}{'中位%':>8}{'最大亏%':>9}")
print("-"*61)
for name,k in [("O 开盘卖","O"),("C 收盘卖","C"),("BE 回本线卖","BE"),("BEK2 回本或-2%止损","BEK2"),("R 收回MA60卖","R")]:
    a=agg(cls[k]); print(f"{name:<20}{a['n']:>5}{a['win']:>8.1f}{a['avg']:>9.2f}{a['med']:>8.2f}{a['worst']:>9.2f}")
