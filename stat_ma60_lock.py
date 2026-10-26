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

def board(code):
    c = code.split(".")[0]
    if code.endswith(".SH"):
        return "STAR" if c[:3] in ("688", "689") else "MAIN"
    if code.endswith(".SZ"):
        return "CNEXT" if c[:3] in ("300", "301") else "MAIN"
    return "MAIN"

THR = {"MAIN": 0.10, "STAR": 0.20, "CNEXT": 0.20}

sig = {}
for fp in glob.glob(os.path.join(SIG_DIR, "*")):
    d = os.path.basename(fp)
    if not (len(d) == 8 and d.isdigit()): continue
    with open(fp, encoding="utf-8") as f:
        codes = [ln.split("|")[0].split()[0].strip() for ln in f if ln.strip()]
    if codes: sig[d] = codes

rows = []
for T, codes in sig.items():
    for code in codes:
        s1 = load_1d(code)
        if T not in s1: continue
        t1 = nth_after(s1, T, 1)
        if t1 is None or t1 not in s1: continue
        Tc = s1[T][3]; o1, h1, l1, c1 = s1[t1]
        bars = load_5m(code)
        if len(bars) < 60: continue
        ma = [None]*len(bars)
        for i in range(len(bars)):
            if i >= 59: ma[i] = sum(bars[j][4] for j in range(i-59, i+1)) / 60.0
        t1d = _dt.datetime.strptime(t1, "%Y%m%d").date()
        day = [{"dt": b[0], "o": b[1], "l": b[3], "c": b[4], "ma": ma[i]}
               for i, b in enumerate(bars) if b[0].date() == t1d]
        if not day: continue
        if day[0]["ma"] is None or not (day[0]["o"] < day[0]["ma"]): continue
        thr = THR[board(code)]
        ol, hl, ll, cl = o1/Tc-1, h1/Tc-1, l1/Tc-1, c1/Tc-1
        # 锁死跌停：开/高/收 都在跌停板或更低(从未开板)
        locked = (ol <= -(thr-0.005)) and (hl <= -(thr-0.005)) and (cl <= -(thr-0.005))
        touched = ll <= -(thr-0.005)   # 盘中曾触及跌停(可能开板)
        t2 = nth_after(s1, t1, 1); t3 = nth_after(s1, t1, 2)
        c2 = s1[t2][3] if (t2 and t2 in s1) else None
        c3 = s1[t3][3] if (t3 and t3 in s1) else None
        rows.append(dict(code=code, board=board(code), ol=ol, hl=hl, ll=ll, cl=cl,
                         locked=locked, touched=touched,
                         r2=(c2/Tc-1) if c2 else None, r3=(c3/Tc-1) if c3 else None,
                         c2=c2, c1=c1))

n = len(rows)
locked_rows = [r for r in rows if r["locked"]]
touched_rows = [r for r in rows if r["touched"] and not r["locked"]]
print(f"样本(首根5m开<MA60)={n}")
print(f"  其中 T+1 锁死跌停(开板失败,全天跑不掉)= {len(locked_rows)} ({len(locked_rows)/n*100:.1f}%)")
print(f"  其中 T+1 盘中曾触跌停但开板(白天能跑)= {len(touched_rows)} ({len(touched_rows)/n*100:.1f}%)")
print(f"  从没碰跌停的= {n-len(locked_rows)-len(touched_rows)} ({(n-len(locked_rows)-len(touched_rows))/n*100:.1f}%)")

def show(name, rs):
    if not rs:
        print(f"  {name}: 无"); return
    cls = [r["cl"]*100 for r in rs]
    r2  = [r["r2"]*100 for r in rs if r["r2"] is not None]
    r3  = [r["r3"]*100 for r in rs if r["r3"] is not None]
    # T+2 是否继续跌停(相对T+1收盘再跌一个板)
    cont = [r for r in rs if r["c2"] is not None and (r["c2"]/r["c1"]-1) <= -(THR[r["board"]]-0.005)]
    print(f"  {name} (n={len(rs)}):")
    print(f"    T+1收盘均亏={statistics.mean(cls):.2f}%  中位={statistics.median(cls):.2f}%  最惨={min(cls):.2f}%")
    if r2:
        print(f"    T+2收盘均亏={statistics.mean(r2):.2f}%  中位={statistics.median(r2):.2f}%  最惨={min(r2):.2f}%  "
              f"其中T+2继续跌停比例={len(cont)/len(r2)*100:.1f}%")
    if r3:
        print(f"    T+3收盘均亏={statistics.mean(r3):.2f}%  中位={statistics.median(r3):.2f}%  最惨={min(r3):.2f}%")

print("\n=== 锁死跌停那批(你T+1根本跑不掉,亏损延伸到T+2/T+3) ===")
show("锁死跌停", locked_rows)
print("\n=== 盘中触跌停但开板(白天有机会跑) ===")
show("触板开板", touched_rows)
print("\n=== 从没碰跌停(正常你能在-2%止损或回本线跑掉) ===")
show("正常", [r for r in rows if not r["locked"] and not r["touched"]])

# 锁死批的板块分布
from collections import Counter
print("\n锁死跌停的板块分布:", dict(Counter(r["board"] for r in locked_rows)))
print("样本板块分布:", dict(Counter(r["board"] for r in rows)))

# 触板76只: -2%止损能否救
print("\n=== 触板76只: -2%止损能不能救 ===")
rescued = [r for r in touched_rows if r["ol"] > -0.02]      # 开盘>-2%, 盘中砸穿时止损可成交
gapkill = [r for r in touched_rows if r["ol"] <= -0.02]     # 开盘就<=-2%, 跳空止损救不了
print(f"  开盘>-2%(止损可盘中成交): {len(rescued)}只  -> 若等反弹拿到收盘均亏="
      f"{statistics.mean([r['cl']*100 for r in rescued]):.2f}%, 而-2%止损只亏-2.00%")
print(f"  开盘<=-2%(跳空,止损救不了,≈按开盘成交): {len(gapkill)}只  -> 均开盘亏="
      f"{statistics.mean([r['ol']*100 for r in gapkill]):.2f}%")
