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
                    d = ps[0]
                    o, h, l, c = float(ps[1]), float(ps[2]), float(ps[3]), float(ps[4])
                    vol = float(ps[5]); prev = float(ps[7]); turn = float(ps[10])
                    s[d] = dict(o=o, h=h, l=l, c=c, vol=vol, prev=prev, turn=turn)
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

# 取合格样本(首根5m开<MA60) + T日特征 + T+1目标
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
        # 取T+1首根5m
        first_bars = [b for b in bars if b[0].date()==t1d]
        if not first_bars: continue
        first = first_bars[0]
        fi = bars.index(first)
        if fi < 59: continue
        ma60 = sum(bars[j][4] for j in range(fi-59, fi+1))/60.0
        if not (first[1] < ma60): continue
        # T日特征
        Td = s1[T]; prev = Td["prev"]
        if prev <= 0: continue
        limup = Tc >= prev*1.095
        yizi = limup and (Td["h"] - Td["l"])/Td["l"] < 0.003   # 一字板(全天无量一字)
        close_str = Tc/Td["h"]                                  # 收盘强度(1=收最高)
        gap_t = Td["o"]/prev - 1                                # T日自身跳空
        turn = Td["turn"]                                       # 换手率%
        # 量比
        keys = sorted(s1.keys()); ki = keys.index(T)
        prev_vols = [s1[keys[j]]["vol"] for j in range(max(0,ki-11), ki) if s1[keys[j]]["vol"]>0]
        vol_ratio = Td["vol"]/statistics.mean(prev_vols) if prev_vols else 0
        # T+1 目标
        touch_limit = (l1/Tc - 1) <= -0.095                     # 盘中触-10%跌停
        deep_gap    = (o1/Tc - 1) <= -0.02                      # 开盘深跳空(止损无效)
        ret1        = c1/Tc - 1
        rows.append(dict(code=code, T=T, yizi=yizi, close_str=close_str, gap_t=gap_t,
                         turn=turn, vol_ratio=vol_ratio, limup=limup,
                         touch_limit=touch_limit, deep_gap=deep_gap, ret1=ret1,
                         o1gap=o1/Tc-1))

n = len(rows)
print(f"合格样本={n}  其中T日是一字板={sum(r['yizi'] for r in rows)} ({sum(r['yizi'] for r in rows)/n*100:.1f}%)")
print(f"目标: 触跌停(T+1低<=-10%)={sum(r['touch_limit'] for r in rows)} ({sum(r['touch_limit'] for r in rows)/n*100:.1f}%)  "
      f"深跳空(开<=-2%)={sum(r['deep_gap'] for r in rows)} ({sum(r['deep_gap'] for r in rows)/n*100:.1f}%)")

def badrate(rs, key):
    if not rs: return 0, 0
    b = sum(1 for r in rs if r[key]); return b, b/len(rs)*100

def bucket(name, fn, edges, key):
    print(f"\n--- {name} vs {key} ---")
    for i in range(len(edges)-1):
        lo, hi = edges[i], edges[i+1]
        sub = [r for r in rows if lo <= fn(r) < hi]
        if not sub: continue
        b, p = badrate(sub, key)
        print(f"  [{lo:>7.2f},{hi:>7.2f})  n={len(sub):>4}  {key}率={p:>5.1f}%")

for tgt in ["touch_limit", "deep_gap"]:
    print(f"\n########## 目标={tgt} ##########")
    bucket("T日收盘强度close/high", lambda r: r["close_str"], [0.0,0.95,0.97,0.99,1.0001], tgt)
    bucket("T日跳空gap_t", lambda r: r["gap_t"], [-1,0.0,0.05,0.09,0.098,0.11], tgt)
    bucket("T日换手率%", lambda r: r["turn"], [-1,0.5,1,2,3,5,100], tgt)
    bucket("T日量比", lambda r: r["vol_ratio"], [-1,0.5,1,2,5,100], tgt)

# 换手率阈值扫描(主过滤特征)
print("\n=== 换手率阈值扫描(保留: 换手率<thr) ===")
print(f"{'thr':>5}{'保留%':>8}{'触跌停%':>9}{'深跳空%':>9}{'开盘>-2%占比':>13}{'T+1均收益%':>12}")
for thr in [1, 2, 3, 4, 5, 6]:
    kept = [r for r in rows if r["turn"] < thr]
    if not kept: continue
    tl, _ = badrate(kept, "touch_limit"); dg, _ = badrate(kept, "deep_gap")
    mild = sum(1 for r in kept if r["o1gap"] > -0.02)/len(kept)*100
    avg = statistics.mean([r["ret1"] for r in kept])*100
    print(f"{thr:>5}{len(kept)/n*100:>8.1f}{tl:>9.1f}{dg:>9.1f}{mild:>13.1f}{avg:>12.2f}")

# 选定过滤: 换手率<3% 且 收盘强度>=0.95 且 T日跳空<0.09
def filt(r):
    return r["turn"] < 3.0 and r["close_str"] >= 0.95 and r["gap_t"] < 0.09
kept = [r for r in rows if filt(r)]
tl, tlp = badrate(kept, "touch_limit"); dg, dgp = badrate(kept, "deep_gap")
mild = sum(1 for r in kept if r["o1gap"] > -0.02)/len(kept)*100
print(f"\n=== 选定过滤: 换手率<3% 且 收盘强度>=0.95 且 T日跳空<0.09 ===")
print(f"  过滤前: n={n}  触跌停率={sum(r['touch_limit'] for r in rows)/n*100:.1f}%  "
      f"深跳空率={sum(r['deep_gap'] for r in rows)/n*100:.1f}%  T+1均收益={statistics.mean([r['ret1'] for r in rows])*100:.2f}%")
print(f"  过滤后: 保留 n={len(kept)} ({len(kept)/n*100:.1f}%)  触跌停率={tlp:.1f}%  "
      f"深跳空率={dgp:.1f}%  开盘>-2%占比={mild:.1f}%  T+1均收益={statistics.mean([r['ret1'] for r in kept])*100:.2f}%  "
      f"最惨={min(r['ret1'] for r in kept)*100:.2f}%")
rej = [r for r in rows if not filt(r)]
print(f"  被剔除的 {len(rej)} 只里: 触跌停率={badrate(rej,'touch_limit')[1]:.1f}%  深跳空率={badrate(rej,'deep_gap')[1]:.1f}%  "
      f"T+1均收益={statistics.mean([r['ret1'] for r in rej])*100:.2f}%")
