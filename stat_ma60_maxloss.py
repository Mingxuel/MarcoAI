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

def sell_real(Tc, o1, day, stop):
    if o1/Tc - 1 <= -stop:
        return o1, "OPEN_CUT"
    for b in day:
        after = b["dt"].hour >= 14
        if b["l"] <= Tc*(1-stop):
            return Tc*(1-stop), "STOP"
        if after and b["ma"] is not None and b["c"] >= b["ma"]:
            return b["c"], "MA60"
        if (not after) and b["c"] >= Tc:
            return b["c"], "BREAKEVEN"
    return day[-1]["c"], "CLOSE"

# 取全量1862 + T日特征 + T+1开盘裂口
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
        close_str = Tc/Td["h"]; gap_t = Td["o"]/prev - 1; turn = Td["turn"]
        rows.append(dict(t1=t1, Tc=Tc, o1=o1, day=day, turn=turn, close_str=close_str, gap_t=gap_t,
                         ogap=o1/Tc-1))

print(f"全量={len(rows)}")

def stats(rs):
    if not rs: return
    rets = [r["ret"] for r in rs]
    print(f"  n={len(rs):>4}  均收益={statistics.mean(rets)*100:>6.2f}%  胜率={sum(1 for x in rets if x>0)/len(rets)*100:>5.1f}%  "
          f"中位={statistics.median(rets)*100:>6.2f}%  最大亏={min(rets)*100:>6.2f}%")

# ① 朴素: 只放宽止损(入场不过滤), 看最大亏是否被钉住
print("\n########## ① 只放宽止损, 入口不过滤(深跳空仍按开盘成交) ##########")
for s in [0.02, 0.03, 0.04, 0.05]:
    rs = []
    for r in rows:
        sp, _ = sell_real(r["Tc"], r["o1"], r["day"], s)
        rs.append({"ret": sp/r["Tc"]-1})
    print(f"  止损=-{int(s*100)}%:", end=""); stats(rs)

# ② 真正手段: 入口按换手率过滤(同时保留收盘强度/跳空条件), 看最大亏能被钉到哪
print("\n########## ② 入口过滤(换手率<thr & 收盘强度>=0.95 & 跳空<9%), 止损-2% ##########")
print(f"  {'thr':>5}{'保留%':>8}{'n':>5}{'均收益%':>9}{'胜率%':>8}{'最大亏%':>9}{'深跳空只数':>11}")
for thr in [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0]:
    kept = [r for r in rows if r["turn"] < thr and r["close_str"] >= 0.95 and r["gap_t"] < 0.09]
    if not kept: continue
    rs = []
    for r in kept:
        sp, _ = sell_real(r["Tc"], r["o1"], r["day"], 0.02)
        rs.append(sp/r["Tc"]-1)
    dg = sum(1 for r in kept if r["ogap"] <= -0.02)
    print(f"  {thr:>5}{len(kept)/len(rows)*100:>8.1f}{len(kept):>5}{statistics.mean(rs)*100:>9.2f}"
          f"{sum(1 for x in rs if x>0)/len(rs)*100:>8.1f}{min(rs)*100:>9.2f}{dg:>11}")

# ③ 针对目标3/4/5%: 选thr使最大亏≈目标, 报告
print("\n########## ③ 单笔最大亏目标 3%/4%/5% 对应方案 ##########")
for target in [0.03, 0.04, 0.05]:
    best = None
    for thr in [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0]:
        kept = [r for r in rows if r["turn"] < thr and r["close_str"] >= 0.95 and r["gap_t"] < 0.09]
        if not kept: continue
        rs = [sell_real(r["Tc"], r["o1"], r["day"], 0.02)[0]/r["Tc"]-1 for r in kept]
        ml = min(rs)
        if ml >= -target:   # 最大亏不超过目标
            cand = (thr, len(kept), statistics.mean(rs)*100, sum(1 for x in rs if x>0)/len(rs)*100, ml*100)
            if best is None or len(kept) > best[1]:   # 选保留最多(最宽松)且满足的
                best = cand
    if best:
        thr, n, avg, win, ml = best
        print(f"  目标最大亏=-{int(target*100)}%: 换手率<{thr}  保留n={n}({n/len(rows)*100:.1f}%)  "
              f"均收益={avg:.2f}% 胜率={win:.1f}% 实际最大亏={ml:.2f}%")
    else:
        print(f"  目标最大亏=-{int(target*100)}%: 现有条件无法达成(需更严过滤)")
