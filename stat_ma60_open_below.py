import os, glob, datetime as _dt, statistics

ROOT    = r"C:/MarcoAI"
SIG_DIR = os.path.join(ROOT, "AIData", "TOP_FIRST_VOL_MA60")
ONE_D   = os.path.join(ROOT, "AIData", "1D")
FIVE_M  = os.path.join(ROOT, "AIData", "5M")

_1d_cache, _5m_cache = {}, {}

def load_1d(code):
    if code in _1d_cache:
        return _1d_cache[code]
    p = os.path.join(ONE_D, code); s = {}
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            for ln in f:
                ps = ln.strip().split("|")
                if len(ps) < 5:
                    continue
                try:
                    s[ps[0]] = (float(ps[1]), float(ps[2]), float(ps[3]), float(ps[4]))  # o,h,l,c
                except ValueError:
                    continue
    _1d_cache[code] = s
    return s

def load_5m(code):
    if code in _5m_cache:
        return _5m_cache[code]
    p = os.path.join(FIVE_M, code); bars = []
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            for ln in f:
                ps = ln.strip().split("|")
                if len(ps) < 6:
                    continue
                try:
                    dt = _dt.datetime.strptime(ps[0], "%Y-%m-%d %H:%M:%S")
                    bars.append((dt, float(ps[1]), float(ps[2]), float(ps[3]), float(ps[4])))
                except (ValueError, TypeError):
                    continue
        bars.sort(key=lambda x: x[0])
    _5m_cache[code] = bars
    return bars

def nth_after(series, date, n):
    keys = sorted(series.keys())
    if date not in series:
        for k in keys:
            if k >= date:
                date = k
                break
        else:
            return None
    i = keys.index(date); j = i + n
    return keys[j] if 0 <= j < len(keys) else None

def first_t1_open_and_ma60(bars, t1_date):
    first = None
    for b in bars:
        if b[0].date() == t1_date and (first is None or b[0] < first[0]):
            first = b
    if first is None:
        return None
    idx = bars.index(first)
    if idx < 59:
        return None
    ma60 = sum(bars[i][4] for i in range(idx - 59, idx + 1)) / 60.0
    return first[1], ma60   # (首根开盘价, MA60)

signals = {}
for fp in glob.glob(os.path.join(SIG_DIR, "*")):
    d = os.path.basename(fp)
    if not (len(d) == 8 and d.isdigit()):
        continue
    with open(fp, encoding="utf-8") as f:
        codes = [ln.split("|")[0].split()[0].strip() for ln in f if ln.strip()]
    if codes:
        signals[d] = codes

rows, total = [], 0
for T, codes in signals.items():
    for code in codes:
        s1 = load_1d(code)
        if T not in s1:
            continue
        close_T = s1[T][3]
        t1 = nth_after(s1, T, 1)
        if t1 is None or t1 not in s1:
            continue
        o1, h1, l1, c1 = s1[t1]
        t2 = nth_after(s1, t1, 1); t3 = nth_after(s1, t1, 2)
        c2 = s1[t2][3] if (t2 and t2 in s1) else None
        c3 = s1[t3][3] if (t3 and t3 in s1) else None
        bars = load_5m(code)
        res = first_t1_open_and_ma60(bars, _dt.datetime.strptime(t1, "%Y%m%d").date())
        total += 1
        if res is None:
            continue
        open_t1_5m, ma60 = res
        if not (open_t1_5m < ma60):     # 条件：T+1 首根5m开盘 < 该根MA60
            continue
        rows.append({
            "T": T, "code": code, "t1": t1, "month": T[:6],
            "gap": o1 / close_T - 1,        # T+1开盘缺口(对T收)
            "hi":  h1 / close_T - 1,        # T+1最高涨幅(对T收)
            "lo":  l1 / close_T - 1,        # T+1最低跌幅(对T收)
            "ret": c1 / close_T - 1,        # T+1收盘涨跌(对T收)
            "oc":  c1 / o1 - 1,             # T+1开->收(日内)
            "ma60dist": open_t1_5m / ma60 - 1,  # 首根开/MA60-1(必为负)
            "ret2": (c2 / close_T - 1) if c2 else None,  # T+2收盘(对T收)
            "ret3": (c3 / close_T - 1) if c3 else None,  # T+3收盘(对T收)
        })

print(f"[脚本2] 首板+MA60 中 T+1首根5m开盘<MA60 统计")
print(f"有T+1数据的信号数={total}  命中(首根5m开<MA60)={len(rows)}  命中率={len(rows)/total*100:.1f}%" if total else "无数据")

def pct(vals, p):
    vs = sorted(vals); k = (len(vs) - 1) * p
    f = int(k); c = min(f + 1, len(vs) - 1)
    return vs[f] + (vs[c] - vs[f]) * (k - f)

def summarize(name, vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        print(f"  {name}: 无数据"); return
    m, md, sd = statistics.mean(vals), statistics.median(vals), statistics.pstdev(vals)
    print(f"  {name:<14} n={len(vals):>4} 均值={m*100:>7.2f}% 中位={md*100:>7.2f}% 标准差={sd*100:>6.2f}% "
          f"min={min(vals)*100:>7.2f}% max={max(vals)*100:>7.2f}% 赢率={sum(1 for x in vals if x>0)/len(vals)*100:>5.1f}%")
    print(f"  {'':<14} p10={pct(vals,.1)*100:>7.2f}% p25={pct(vals,.25)*100:>7.2f}% p50={pct(vals,.5)*100:>7.2f}% "
          f"p75={pct(vals,.75)*100:>7.2f}% p90={pct(vals,.9)*100:>7.2f}%")

def hist(name, vals, edges):
    vals = [v for v in vals if v is not None]
    print(f"  {name} 分布:")
    for i in range(len(edges) - 1):
        lo, hi = edges[i], edges[i + 1]
        n = sum(1 for x in vals if lo <= x < hi)
        pp = n / len(vals) * 100 if vals else 0
        print(f"    [{lo*100:>6.1f}%,{hi*100:>6.1f}%) {n:>4} ({pp:>5.1f}%) {'#'*int(pp/2)}")

if rows:
    gap  = [r["gap"] for r in rows]; hi = [r["hi"] for r in rows]; lo = [r["lo"] for r in rows]
    ret  = [r["ret"] for r in rows]; oc = [r["oc"] for r in rows]; md = [r["ma60dist"] for r in rows]
    ret2 = [r["ret2"] for r in rows]; ret3 = [r["ret3"] for r in rows]
    print("\n=== 汇总统计（基准=T日收盘）===")
    summarize("T+1开盘缺口", gap); summarize("T+1最高涨幅", hi); summarize("T+1最低跌幅", lo)
    summarize("T+1收盘涨跌", ret); summarize("T+1开->收", oc); summarize("首根开/MA60-1", md)
    summarize("T+2收盘涨跌", ret2); summarize("T+3收盘涨跌", ret3)
    edges = [-0.11, -0.09, -0.05, -0.02, 0, 0.02, 0.05, 0.09, 0.11, 1.0]
    print("\n=== 分布（基准=T日收盘）===")
    hist("T+1收盘涨跌", ret, edges); hist("T+1开盘缺口", gap, edges); hist("T+1最高涨幅", hi, edges)
    print("\n=== 按月（命中样本）===")
    mm = {}
    for r in rows:
        mm.setdefault(r["month"], []).append(r["ret"])
    for m in sorted(mm):
        rs = mm[m]
        print(f"  {m}: n={len(rs)} 平均收盘涨跌={sum(rs)/len(rs)*100:.2f}% 赢率={sum(1 for x in rs if x>0)/len(rs)*100:.1f}%")
