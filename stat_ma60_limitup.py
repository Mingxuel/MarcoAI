import os, glob, datetime as _dt, statistics

ROOT    = r"C:/MarcoAI"
SIG_DIR = os.path.join(ROOT, "AIData", "TOP_FIRST_VOL_MA60")
ONE_D   = os.path.join(ROOT, "AIData", "1D")
FIVE_M  = os.path.join(ROOT, "AIData", "5M")
_1d_cache, _5m_cache = {}, {}

def board(code):
    if code.startswith(("600","601","603","605","000","001","002","003")): return "MAIN"
    if code.startswith(("300","301")): return "CYB"
    if code.startswith("688"): return "KCB"
    return "OTHER"

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

# 真实卖出(含涨停止盈): 深跳空开盘割; 当日摸涨停(日线最高>=1.10*Tc)->卖(+lu); 温和: 回本线/-stop止损; 午后转MA60/收盘
def sell_real(Tc, o1, day, stop, lu, lu_hit):
    if o1/Tc - 1 <= -0.02:
        return o1/Tc-1, "OPEN_CUT"
    if lu_hit:                      # 当日摸到涨停 -> 按涨停价卖(+lu), 优先于其余规则
        return lu, "LIMIT_UP"
    for b in day:
        after = b["dt"].hour >= 14
        if b["l"] <= Tc*(1-stop):
            return -stop, "STOP"
        if after and b["ma"] is not None and b["c"] >= b["ma"]:
            return b["c"]/Tc-1, "MA60"
        if (not after) and b["c"] >= Tc:
            return b["c"]/Tc-1, "BREAKEVEN"
    return day[-1]["c"]/Tc-1, "CLOSE"

# 对照组: 完全一样的规则但不含涨停止盈
def sell_nolu(Tc, o1, day, stop):
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

rows = []; boards = {}
sig = {}
for fp in glob.glob(os.path.join(SIG_DIR, "*")):
    d = os.path.basename(fp)
    if not (len(d) == 8 and d.isdigit()): continue
    with open(fp, encoding="utf-8") as f:
        codes = [ln.split("|")[0].split()[0].strip() for ln in f if ln.strip()]
    if codes: sig[d] = codes
skipped = 0
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
        day = [{"dt": b[0], "h": b[2], "l": b[3], "c": b[4], "ma": ma[i]}
               for i, b in enumerate(bars) if b[0].date() == t1d]
        # 数据守卫: 主板T+1价格不可能超出成本±10%(涨跌停), 5M若严重偏离1D说明未复权对齐 -> 剔除
        hi = max(b["h"] for b in day); lo = min(b["l"] for b in day)
        if hi > Tc*1.13 or lo < Tc*0.87:
            skipped += 1; continue
        Td = s1[T]; prev = Td["prev"]
        if prev <= 0: continue
        cs = Tc/Td["h"]; gt = Td["o"]/prev - 1; turn = Td["turn"]
        bd = board(code); boards[bd] = boards.get(bd, 0) + 1
        lu = 0.10 if bd == "MAIN" else 0.20
        # 摸涨停判定: 用日线T+1最高价(权威源), 摸到涨停价(>=1.10*Tc)即算
        lu_hit = (t1 in s1) and (s1[t1]["h"] >= Tc*(1+lu)*0.999)
        r2, w2 = sell_real(Tc, o1, day, 0.02, lu, lu_hit)
        r3, w3 = sell_real(Tc, o1, day, 0.03, lu, lu_hit)
        rn, _ = sell_nolu(Tc, o1, day, 0.02)
        rows.append(dict(t1=t1, code=code, Tc=Tc, o1=o1, r2=r2, w2=w2, r3=r3, w3=w3, rn=rn, turn=turn, cs=cs, gt=gt, lu=lu, lu_hit=lu_hit, weak=(o1 < ma[fi])))

print(f"全量信号={len(rows)+skipped}  有效(剔除5M未复权脏数据)={len(rows)}  跳过={skipped}  板块分布={boards}")
def is_kept(r): return r["turn"] < 3.0 and r["cs"] >= 0.95 and r["gt"] < 0.09

def overall(name, items):
    rs = [r["r2"] for r in items]; eq=1.0; peak=1.0; mdd=0.0; by_d={}
    for d,r in [(r["t1"], r["r2"]) for r in items]: by_d.setdefault(d,[]).append(r)
    for d in sorted(by_d): eq*=(1+statistics.mean(by_d[d])); peak=max(peak,eq); mdd=min(mdd,eq/peak-1)
    print(f"  {name}: n={len(items)} 均={statistics.mean(rs)*100:.2f}% 胜率={sum(1 for x in rs if x>0)/len(rs)*100:.1f}% "
          f"最大亏={min(rs)*100:.2f}% 累计={(eq-1)*100:.1f}% 回撤={mdd*100:.1f}%")

def reasons(name, items):
    from collections import Counter
    c = Counter(r["w2"] for r in items)
    print(f"  卖出原因({name}): " + "  ".join(f"{k}={v}({v/len(items)*100:.0f}%)" for k,v in c.most_common()))

def monthly(name, items):
    months={}
    for r in items: months.setdefault(r["t1"][:6], {}).setdefault(r["t1"], []).append(r["r2"])
    print(f"\n=== {name} 每月收益(含涨停止盈) ===")
    print(f"  {'月份':>7}{'笔数':>6}{'均收益%':>9}{'月收益%':>12}{'累计%':>10}")
    eq=1.0; peak=1.0; mdd=0.0
    for ym in sorted(months):
        days=months[ym]; mr=1.0
        for d,rs in days.items(): mr*=(1+statistics.mean(rs))
        eq*=mr; peak=max(peak,eq); mdd=min(mdd,eq/peak-1)
        n=sum(len(rs) for rs in days.values()); avg=statistics.mean([x for rs in days.values() for x in rs])*100
        print(f"  {ym:>7}{n:>6}{avg:>9.2f}{(mr-1)*100:>12.2f}{(eq-1)*100:>10.1f}")
    print(f"  -> 总累计={(eq-1)*100:.1f}%  最大回撤={mdd*100:.1f}%")

print("\n[全量1862 不过滤, 含涨停止盈]")
overall("  真实卖 -2%止损", rows)
reasons("  全量", rows)
monthly("全量1862", rows)

print("\n[过滤后(换手<3%&收强>=0.95&跳空<9%), 含涨停止盈]")
fk=[r for r in rows if is_kept(r)]
overall("  真实卖 -2%止损", fk)
reasons("  过滤", fk)
monthly("过滤后", fk)

# 涨停止盈贡献
lu_all=sum(1 for r in rows if r["w2"]=="LIMIT_UP")
lu_fk =sum(1 for r in fk  if r["w2"]=="LIMIT_UP")
print(f"\n涨停止盈命中: 全量 {lu_all}只({lu_all/len(rows)*100:.1f}%)  过滤后 {lu_fk}只({lu_fk/len(fk)*100:.1f}%)")

def overall_v(name, items, key):
    rs=[r[key] for r in items]; eq=1.0; peak=1.0; mdd=0.0; by_d={}
    for r in items: by_d.setdefault(r["t1"],[]).append(r[key])
    for d in sorted(by_d): eq*=(1+statistics.mean(by_d[d])); peak=max(peak,eq); mdd=min(mdd,eq/peak-1)
    print(f"  {name:<28} n={len(items)} 均={statistics.mean(rs)*100:.2f}% 胜率={sum(1 for x in rs if x>0)/len(rs)*100:.1f}% "
          f"最大亏={min(rs)*100:.2f}% 累计={(eq-1)*100:.1f}% 回撤={mdd*100:.1f}%")

print("\n=== 涨停止盈的增量贡献(对比: 同样规则但不含涨停止盈) ===")
overall_v("  全量 含涨停(r2)", rows, "r2")
overall_v("  全量 不含涨停(rn)", rows, "rn")
overall_v("  过滤 含涨停(r2)", fk, "r2")
overall_v("  过滤 不含涨停(rn)", fk, "rn")
