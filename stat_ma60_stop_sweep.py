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

# 深跳空固定: 开盘<=成本-2% -> 按开盘割; 温和批: 止损价=-stop
def sell(Tc, o1, day, stop):
    if o1/Tc - 1 <= -0.02:
        return o1, "OPEN_CUT"          # 深跳空, 止损废了
    for b in day:
        after = b["dt"].hour >= 14
        if b["l"] <= Tc*(1-stop):
            return Tc*(1-stop), "STOP"
        if after and b["ma"] is not None and b["c"] >= b["ma"]:
            return b["c"], "MA60"
        if (not after) and b["c"] >= Tc:
            return b["c"], "BREAKEVEN"
    return day[-1]["c"], "CLOSE"

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
        fb = [b for b in bars if b[0].date() == t1d]
        if not fb: continue
        fi = bars.index(fb[0])
        if fi < 59: continue
        day = [{"dt": b[0], "l": b[3], "c": b[4], "ma": ma[i]}
               for i, b in enumerate(bars) if b[0].date() == t1d]
        Td = s1[T]; prev = Td["prev"]
        if prev <= 0: continue
        cs = Tc/Td["h"]; gt = Td["o"]/prev - 1; turn = Td["turn"]
        rows.append(dict(Tc=Tc, o1=o1, day=day, turn=turn, cs=cs, gt=gt))

def run(name, selected):
    print(f"\n=== {name} (n={len(selected)}) 深跳空固定开盘≤-2%按开盘割, 只拧温和批止损 ===")
    print(f"  {'止损':>5}{'整体均%':>9}{'整体胜率%':>10}{'整体最大亏%':>12}{'温和批均%':>10}{'温和批胜率%':>12}{'温和批最大亏%':>13}")
    for s in [0.02, 0.03, 0.04, 0.05]:
        all_r, mild_r = [], []
        for r in selected:
            sp, why = sell(r["Tc"], r["o1"], r["day"], s)
            ret = sp/r["Tc"]-1
            all_r.append(ret)
            if r["o1"]/r["Tc"]-1 > -0.02:   # 温和批
                mild_r.append(ret)
        ml_all = min(all_r)*100
        ml_mild = min(mild_r)*100 if mild_r else 0
        print(f"  -{int(s*100)}%{statistics.mean(all_r)*100:>9.2f}{sum(1 for x in all_r if x>0)/len(all_r)*100:>10.1f}"
              f"{ml_all:>12.2f}{statistics.mean(mild_r)*100:>10.2f}{sum(1 for x in mild_r if x>0)/len(mild_r)*100:>12.1f}{ml_mild:>13.2f}")

all_sel = rows
filt_sel = [r for r in rows if r["turn"] < 2.5 and r["cs"] >= 0.95 and r["gt"] < 0.09]
run("全量1862(不过滤)", all_sel)
run("过滤后(换手<2.5&收强>=0.95&跳空<9%)", filt_sel)
