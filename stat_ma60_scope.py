import os, glob, datetime as _dt

ROOT    = r"C:/MarcoAI"
SIG_DIR = os.path.join(ROOT, "AIData", "TOP_FIRST_VOL_MA60")
ONE_D   = os.path.join(ROOT, "AIData", "1D")
FIVE_M  = os.path.join(ROOT, "AIData", "5M")

def load_1d(code):
    p = os.path.join(ONE_D, code); s = {}
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            for ln in f:
                ps = ln.strip().split("|")
                if len(ps) < 5: continue
                try: s[ps[0]] = (float(ps[1]), float(ps[2]), float(ps[3]), float(ps[4]))
                except ValueError: continue
    return s

def load_5m(code):
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
    return bars

def nth_after(series, date, n):
    keys = sorted(series.keys())
    if date not in series:
        for k in keys:
            if k >= date: date = k; break
        else: return None
    i = keys.index(date); j = i + n
    return keys[j] if 0 <= j < len(keys) else None

tot = weak = 0
for fp in glob.glob(os.path.join(SIG_DIR, "*")):
    d = os.path.basename(fp)
    if not (len(d) == 8 and d.isdigit()): continue
    with open(fp, encoding="utf-8") as f:
        codes = [ln.split("|")[0].split()[0].strip() for ln in f if ln.strip()]
    for code in codes:
        s1 = load_1d(code)
        if d not in s1: continue
        t1 = nth_after(s1, d, 1)
        if t1 is None or t1 not in s1: continue
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
        tot += 1
        if fb[0][1] < ma60: weak += 1

print(f"首板+MA60 全量信号(有T+1数据)= {tot}")
print(f"  其中 T+1首根5m开<MA60(我回测的子集)= {weak} ({weak/tot*100:.1f}%)")
print(f"  其中 T+1首根5m开>=MA60(我从没分析的)= {tot-weak} ({(tot-weak)/tot*100:.1f}%)")
