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

# ---- 取“T+1首根5m开盘<MA60”的样本，并带回 T+1 整日5m bars + 每根MA60 ----
def get_qualified():
    out = []
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
            bars = load_5m(code)
            if len(bars) < 60: continue
            # 全局滚动 MA60（收盘）
            ma = [None]*len(bars)
            for i in range(len(bars)):
                if i >= 59:
                    ma[i] = sum(bars[j][4] for j in range(i-59, i+1)) / 60.0
            # T+1 当日 bars
            t1d = _dt.datetime.strptime(t1, "%Y%m%d").date()
            day = [{"dt": b[0], "o": b[1], "h": b[2], "l": b[3], "c": b[4], "ma": ma[i]}
                   for i, b in enumerate(bars) if b[0].date() == t1d]
            if not day: continue
            first = day[0]
            if first["ma"] is None or not (first["o"] < first["ma"]):
                continue   # ★ 条件：T+1首根5m开盘<该根MA60
            out.append(day)
    return out

def walk_open_entry(B, stop=None, take_ma60=False):
    """开盘即买(首根open)。stop=硬止损比例; take_ma60=碰到收盘>=MA60即止盈。"""
    ep = B[0]["o"]; worst = 0.0
    for b in B:
        adv = b["l"]/ep - 1
        if adv < worst: worst = adv
        if stop is not None and b["l"] <= ep*(1-stop):
            return -stop, worst
        if take_ma60 and b["ma"] is not None and b["c"] >= b["ma"]:
            return b["c"]/ep - 1, worst
    return B[-1]["c"]/ep - 1, worst

def walk_reclaim_entry(B, stop=None):
    """等首根收盘>=MA60后，下一根open买入；stop=硬止损。"""
    ei = None
    for i, b in enumerate(B):
        if b["ma"] is not None and b["c"] >= b["ma"]:
            ei = i; break
    if ei is None or ei+1 >= len(B):
        return None   # 当天未收回MA60 -> 不交易
    ep = B[ei+1]["o"]; worst = 0.0
    for i in range(ei+1, len(B)):
        b = B[i]; adv = b["l"]/ep - 1
        if adv < worst: worst = adv
        if stop is not None and b["l"] <= ep*(1-stop):
            return -stop, worst
    return B[-1]["c"]/ep - 1, worst

def agg(rows):
    rs = [r[0] for r in rows]
    mae = [r[1] for r in rows]
    rs_sorted = sorted(rs)
    def pct(p):
        k = (len(rs_sorted)-1)*p; f=int(k); c=min(f+1,len(rs_sorted)-1)
        return rs_sorted[f] + (rs_sorted[c]-rs_sorted[f])*(k-f)
    n=len(rs)
    return dict(n=n, avg=statistics.mean(rs)*100, med=statistics.median(rs)*100,
                win=sum(1 for x in rs if x>0)/n*100,
                worst=min(rs)*100, p10=pct(.1)*100, mae=statistics.mean(mae)*100)

print("[回测] 首板+MA60 / T+1首根5m开<MA60 / T+1必卖 / 用5m MA60进出")
qual = get_qualified()
print(f"合格样本(个股)={len(qual)}\n")

strategies = []
# A 开盘买-收盘卖
strategies.append(("A 开盘买-收盘卖(无止损)", [walk_open_entry(b) for b in qual]))
# B 开盘买+硬止损
strategies.append(("B 开盘买-止损2%", [walk_open_entry(b, stop=0.02) for b in qual]))
strategies.append(("B 开盘买-止损3%", [walk_open_entry(b, stop=0.03) for b in qual]))
# C 开盘买-碰MA60止盈
strategies.append(("C 开盘买-碰MA60止盈", [walk_open_entry(b, take_ma60=True) for b in qual]))
# F 开盘买-止损或碰MA60止盈(二选一)
strategies.append(("F 开盘买-止损2%或止盈", [walk_open_entry(b, stop=0.02, take_ma60=True) for b in qual]))
strategies.append(("F 开盘买-止损3%或止盈", [walk_open_entry(b, stop=0.03, take_ma60=True) for b in qual]))
# D 等回MA60再买-收盘卖
strategies.append(("D 等回MA60再买-收盘卖", [r for r in (walk_reclaim_entry(b) for b in qual) if r]))
# E 等回MA60再买-止损
strategies.append(("E 等回MA60再买-止损2%", [r for r in (walk_reclaim_entry(b, stop=0.02) for b in qual) if r]))
strategies.append(("E 等回MA60再买-止损3%", [r for r in (walk_reclaim_entry(b, stop=0.03) for b in qual) if r]))

print(f"{'策略':<26}{'笔数':>5}{'赢率%':>8}{'均收益%':>9}{'中位%':>8}{'最大亏%':>9}{'P10亏%':>9}{'均回撤%':>9}")
print("-"*83)
ranked = []
for name, rows in strategies:
    a = agg(rows)
    ranked.append((a["worst"], name, a))
    print(f"{name:<24}{a['n']:>5}{a['win']:>8.1f}{a['avg']:>9.2f}{a['med']:>8.2f}{a['worst']:>9.2f}{a['p10']:>9.2f}{a['mae']:>9.2f}")
print("\n=== 按最大回撤(最大单笔亏损)从小到大排 ===")
for w, name, a in sorted(ranked):
    print(f"  {name:<24} 最大亏={w:>7.2f}%  均收益={a['avg']:>7.2f}%  赢率={a['win']:>5.1f}%  笔数={a['n']}")
