import os, glob, datetime as _dt, statistics

ROOT    = r"C:/MarcoAI"
SIG_DIR = os.path.join(ROOT, "AIData", "TOP_FIRST_VOL_MA60")
ONE_D   = os.path.join(ROOT, "AIData", "1D")
FIVE_M  = os.path.join(ROOT, "AIData", "5M")
IDX     = os.path.join(ROOT, "AIData", "INDEX", "000001.SH")
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

# 上证指数收盘 + MA60
idx = {}; idx_ma = {}
with open(IDX, encoding="utf-8") as f:
    for ln in f:
        ps = ln.strip().split("|")
        if len(ps) < 5: continue
        try: idx[ps[0]] = float(ps[4])
        except ValueError: continue
idates = sorted(idx)
for i, d in enumerate(idates):
    if i >= 59: idx_ma[d] = sum(idx[idates[j]] for j in range(i-59, i+1)) / 60.0

def env_ok(T):
    if T in idx_ma: return idx[T] >= idx_ma[T]
    return None   # MA60 预热期(2026初60日内)无定义

# 取全量1862
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
        fbars = [b for b in bars if b[0].date() == t1d]
        if not fbars: continue
        fi = bars.index(fbars[0])
        if fi < 59: continue
        day = [{"dt": b[0], "l": b[3], "c": b[4], "ma": ma[i]}
               for i, b in enumerate(bars) if b[0].date() == t1d]
        Td = s1[T]; prev = Td["prev"]
        if prev <= 0: continue
        cs = Tc/Td["h"]; gt = Td["o"]/prev - 1; turn = Td["turn"]
        r2, _ = sell_real(Tc, o1, day, 0.02)
        e = env_ok(T)
        rows.append(dict(T=T, t1=t1, r2=r2, turn=turn, cs=cs, gt=gt, env=e))

def is_kept(r, thr=3.0): return r["turn"] < thr and r["cs"] >= 0.95 and r["gt"] < 0.09

def stats(label, items):
    if not items:
        print(f"  {label}: 无"); return
    rs = [r["r2"] for r in items]
    print(f"  {label:<34} n={len(items):>4} 均={statistics.mean(rs)*100:>6.2f}% 胜率={sum(1 for x in rs if x>0)/len(rs)*100:>5.1f}% 最大亏={min(rs)*100:>6.2f}%")

H1 = [r for r in rows if r["T"][:6] <= "202605"]
H2 = [r for r in rows if r["T"][:6] >= "202606"]
print(f"全量={len(rows)}  H1(01-05)={len(H1)}  H2(06-10)={len(H2)}")

# ---------- A) WALK-FORWARD: 在H1定换手阈值, H2当样本外 ----------
print("\n########## A) WALK-FORWARD ##########")
print("A1) H1(训练集) 换手率阈值扫描(保留=换手<thr & 收强>=0.95 & 跳空<9%):")
print(f"  {'thr':>5}{'H1保留%':>9}{'H1均%':>9}{'H1触跌停近似':>13}")
for thr in [1.0,1.5,2.0,2.5,3.0,4.0,5.0]:
    k = [r for r in H1 if is_kept(r, thr)]
    if not k: continue
    print(f"  {thr:>5}{len(k)/len(H1)*100:>9.1f}{statistics.mean([r['r2'] for r in k])*100:>9.2f}{'':>13}")

print("\nA2) 样本外 H2: 不过滤 vs 过滤(thr=3, 原定) vs 过滤(thr=2, H1较优):")
stats("  H2 不过滤", H2)
stats("  H2 过滤 thr=3", [r for r in H2 if is_kept(r, 3.0)])
stats("  H2 过滤 thr=2", [r for r in H2 if is_kept(r, 2.0)])

# ---------- B) 大盘环境过滤(上证 MA60) ----------
print("\n########## B) 大盘环境过滤 (T日上证>=MA60 才做) ##########")
def split_env(items):
    ok = [r for r in items if r["env"] is True]
    bad = [r for r in items if r["env"] is False]
    na = [r for r in items if r["env"] is None]
    return ok, bad, na
print("B1) 全量1862 按环境:")
ok, bad, na = split_env(rows)
stats("  环境=多头(上证>=MA60)", ok)
stats("  环境=空头(上证< MA60)", bad)
stats("  环境=未定义(预热期)", na)

print("\nB2) 过滤后(换手<3等) 按环境:")
fok = [r for r in ok if is_kept(r, 3.0)]
fbad = [r for r in bad if is_kept(r, 3.0)]
stats("  过滤+多头环境", fok)
stats("  过滤+空头环境", fbad)

print("\nB3) H2(06-10) 分环境看坑在哪:")
h2ok = [r for r in H2 if r["env"] is True]
h2bad = [r for r in H2 if r["env"] is False]
stats("  H2 多头环境(不过滤)", h2ok)
stats("  H2 空头环境(不过滤)", h2bad)
stats("  H2 过滤+多头环境", [r for r in h2ok if is_kept(r,3.0)])
stats("  H2 过滤+空头环境", [r for r in h2bad if is_kept(r,3.0)])

# 环境过滤对全样本的最终提升(过滤版 + 只在多头环境)
print("\nB4) 最终组合: 过滤(thr=3) + 仅多头环境, 全样本:")
final = [r for r in rows if is_kept(r, 3.0) and r["env"] is True]
stats("  过滤+多头环境(全样本)", final)
print(f"  (注: 预热期{len(na)}只环境未定义, 未计入此组合)")
