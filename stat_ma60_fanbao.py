import os, glob, statistics
from stat_ma60_limitup import load_1d, nth_after, board, SIG_DIR

# 断板日 = 信号文件日期 D (已验证 D-1 是首板, D 是非涨停买入日=断板日)
# 反包 = D+1 或 D+2 重新摸到涨停(日线最高>=1+lu 倍 D收)
rows = []
for fp in glob.glob(os.path.join(SIG_DIR, "*")):
    d = os.path.basename(fp)
    if not (len(d) == 8 and d.isdigit()): continue
    with open(fp, encoding="utf-8") as f:
        codes = [ln.split("|")[0].split()[0].strip() for ln in f if ln.strip()]
    for code in codes:
        s1 = load_1d(code)
        if d not in s1: continue
        Dp1 = nth_after(s1, d, 1); Dp2 = nth_after(s1, d, 2)
        if Dp1 is None or Dp2 is None or Dp1 not in s1 or Dp2 not in s1: continue
        ks = sorted(s1); i = ks.index(d)
        if i < 1: continue
        Dm1 = ks[i-1]
        Tc = s1[d]["c"]                     # 断板日收盘=入场价
        Dm1c = s1[Dm1]["c"]                 # 首板收盘
        lu = 0.10 if board(code) == "MAIN" else 0.20
        o, h, l, c, turn = (s1[d][k] for k in ("o", "h", "l", "c", "turn"))
        # MA60(1D, 取可用历史)
        ma60 = statistics.mean([s1[k]["c"] for k in ks[max(0, i-59):i+1]])
        gap = o / Dm1c - 1                  # 断板日开盘相对首板收盘的跳空
        cstr = c / h                        # 收盘强度(1=收在最高)
        body = (c - o) / o                  # 实体
        dret = c / Dm1c - 1                 # 断板日相对首板收益
        above = c > ma60
        # 反包判定(日线最高)
        lu1 = s1[Dp1]["h"] >= (1+lu)*Tc*0.999
        lu2 = (not lu1) and (s1[Dp2]["h"] >= (1+lu)*Tc*0.999)
        fb1, fb2, fb = lu1, lu2, (lu1 or lu2)
        # 收益: 次日卖 / 持有等反包(带止损)
        r_next = s1[Dp1]["c"]/Tc - 1
        def hold_fb(stop):
            if s1[Dp1]["l"] <= Tc*(1-stop): return -stop
            if lu1: return lu
            if s1[Dp2]["l"] <= Tc*(1-stop): return -stop
            if lu2: return lu
            return s1[Dp2]["c"]/Tc - 1
        rows.append(dict(code=code, D=d, Tc=Tc, lu=lu, gap=gap, cstr=cstr, body=body,
                         dret=dret, turn=turn, above=above, fb1=fb1, fb2=fb2, fb=fb,
                         r_next=r_next, r05=hold_fb(0.05), r03=hold_fb(0.03),
                         r_imm=(lu if lu1 else s1[Dp1]["c"]/Tc-1)))

n = len(rows)
def rate(key): return sum(1 for r in rows if r[key])/n
def avg(key): return statistics.mean(r[key] for r in rows)
print(f"断板日样本 n={n}  (D-1=首板, D=断板日, 入场=D收)")
print(f"\n[1] 反包基础概率")
print(f"  D+1 当日反包(立即): {rate('fb1')*100:.1f}%   (n={sum(1 for r in rows if r['fb1'])})")
print(f"  D+2 延迟反包       : {rate('fb2')*100:.1f}%   (n={sum(1 for r in rows if r['fb2'])})")
print(f"  D+1或D+2 任一反包  : {rate('fb')*100:.1f}%   (n={sum(1 for r in rows if r['fb'])})")

print(f"\n[2] 两种卖法收益对比 (断板日收盘买入)")
print(f"  次日收盘卖        : 均={avg('r_next')*100:.2f}%  胜率={sum(1 for r in rows if r['r_next']>0)/n*100:.1f}%  最大亏={min(r['r_next'] for r in rows)*100:.1f}%")
print(f"  持有等反包(-5%止损): 均={avg('r05')*100:.2f}%  胜率={sum(1 for r in rows if r['r05']>0)/n*100:.1f}%  最大亏={min(r['r05'] for r in rows)*100:.1f}%")
print(f"  持有等反包(-3%止损): 均={avg('r03')*100:.2f}%  胜率={sum(1 for r in rows if r['r03']>0)/n*100:.1f}%  最大亏={min(r['r03'] for r in rows)*100:.1f}%")

print(f"\n[3] 反包率 & 收益 按 断板日特征分箱")
def binstat(title, key, edges, labels):
    print(f"  -- {title} --")
    for lo, hi, lab in zip(edges[:-1], edges[1:], labels):
        sub = [r for r in rows if lo <= r[key] < hi]
        if not sub: continue
        print(f"    {lab:<14} n={len(sub):4d} 反包率={sum(r['fb'] for r in sub)/len(sub)*100:5.1f}%  "
              f"持有-5%止损均={statistics.mean(r['r05'] for r in sub)*100:6.2f}%  "
              f"次日卖均={statistics.mean(r['r_next'] for r in sub)*100:6.2f}%")
binstat("开盘跳空(gap=开/首板收-1)", "gap", [-9, -0.03, 0, 0.02, 0.05, 9],
        ["<-3%","-3~0%","0~2%","2~5%",">5%"])
binstat("收盘强度(cstr=收/高)", "cstr", [-9, 0.5, 0.7, 9], ["<0.5","0.5~0.7",">=0.7"])
binstat("断板日收益(dret)", "dret", [-9, -0.03, 0, 0.03, 9], ["<-3%","-3~0%","0~3%",">3%"])
print(f"  -- 是否站上MA60 --")
for lab, crit in [("站上MA60", True), ("跌破MA60", False)]:
    sub=[r for r in rows if r["above"]==crit]
    print(f"    {lab:<10} n={len(sub):4d} 反包率={sum(r['fb'] for r in sub)/len(sub)*100:5.1f}%  "
          f"持有-5%止损均={statistics.mean(r['r05'] for r in sub)*100:6.2f}%")

print(f"\n[4] 高概率反包组合筛选 (同时满足)")
for desc, cond in [
    ("强开+收强>=0.7", lambda r: r["gap"]>=0.02 and r["cstr"]>=0.7),
    ("强开+收强>=0.7+站MA60", lambda r: r["gap"]>=0.02 and r["cstr"]>=0.7 and r["above"]),
    ("温和开0~5%+收强>=0.7", lambda r: 0<=r["gap"]<0.05 and r["cstr"]>=0.7),
    ("收强>=0.7+站MA60", lambda r: r["cstr"]>=0.7 and r["above"]),
]:
    sub=[r for r in rows if cond(r)]
    if not sub: continue
    print(f"  {desc:<22} n={len(sub):4d} 反包率={sum(r['fb'] for r in sub)/len(sub)*100:5.1f}%  "
          f"持有-5%均={statistics.mean(r['r05'] for r in sub)*100:6.2f}%  "
          f"次日卖均={statistics.mean(r['r_next'] for r in sub)*100:6.2f}%")
