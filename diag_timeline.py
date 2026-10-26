import os, glob
from stat_ma60_limitup import load_1d, SIG_DIR  # 复用已验证的加载

def is_lu(series, d):
    if d not in series or d not in series: return None
    # 用 D-1 作为前收
    ks = sorted(series)
    if d not in ks: return None
    i = ks.index(d)
    if i < 1: return None
    prev = series[ks[i-1]]["c"]
    c = series[d]["c"]
    return c/prev - 1 >= 0.095  # 主板近似涨停

cnt = dict(Dm1=0, D=0, Dp1=0, Dp2=0, total=0)
ex = []
for fp in glob.glob(os.path.join(SIG_DIR, "*"))[:40]:  # 先看40个信号日
    d = os.path.basename(fp)
    if not (len(d)==8 and d.isdigit()): continue
    with open(fp, encoding="utf-8") as f:
        codes = [ln.split("|")[0].split()[0].strip() for ln in f if ln.strip()]
    for code in codes[:6]:  # 每文件取前6只样例
        s1 = load_1d(code)
        if d not in s1: continue
        ks = sorted(s1)
        i = ks.index(d)
        Dm1 = ks[i-1] if i>=1 else None
        Dp1 = ks[i+1] if i+1 < len(ks) else None
        Dp2 = ks[i+2] if i+2 < len(ks) else None
        cnt["total"] += 1
        if Dm1 and is_lu(s1, Dm1): cnt["Dm1"] += 1
        if is_lu(s1, d): cnt["D"] += 1
        if Dp1 and is_lu(s1, Dp1): cnt["Dp1"] += 1
        if Dp2 and is_lu(s1, Dp2): cnt["Dp2"] += 1
        if len(ex) < 6:
            ex.append((code, d,
                       (s1[Dm1]["c"]/s1[ks[i-1]]["c"]-1) if Dm1 else None,
                       is_lu(s1,d),
                       (s1[Dp1]["c"]/s1[d]["c"]-1) if Dp1 else None,
                       is_lu(s1,Dp1) if Dp1 else None,
                       (s1[Dp2]["c"]/s1[Dp1]["c"]-1) if (Dp1 and Dp2) else None,
                       is_lu(s1,Dp2) if Dp2 else None))

n = cnt["total"]
print(f"样本 {n} 只 (信号日文件前40个, 每只前6只)")
print(f"  信号日D前一日(D-1)是涨停: {cnt['Dm1']}/{n} = {cnt['Dm1']/n*100:.1f}%")
print(f"  信号日D本身是涨停     : {cnt['D']}/{n} = {cnt['D']/n*100:.1f}%")
print(f"  信号日D+1是涨停       : {cnt['Dp1']}/{n} = {cnt['Dp1']/n*100:.1f}%")
print(f"  信号日D+2是涨停       : {cnt['Dp2']}/{n} = {cnt['Dp2']/n*100:.1f}%")
print("\n样例 (code, D, D-1涨幅/是否板, D是否板, D+1涨幅/是否板, D+2涨幅/是否板):")
for e in ex:
    print("  ", e[0], e[1],
          f"D-1涨={e[2]:.1%}" if e[2] is not None else "D-1=无",
          "板" if e[3] else "非板",
          f"D+1涨={e[4]:.1%}" if e[4] is not None else "D+1=无",
          "板" if e[5] else "非板",
          f"D+2涨={e[6]:.1%}" if e[6] is not None else "D+2=无",
          "板" if e[7] else "非板")
