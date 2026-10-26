import os, glob
from stat_ma60_limitup import load_1d, load_5m, nth_after, SIG_DIR

hit_1d_h=0; hit_1d_c=0; hit_5m=0; tot=0
ex_5m_bad=0
for fp in glob.glob(os.path.join(SIG_DIR, "*")):
    d = os.path.basename(fp)
    if not (len(d)==8 and d.isdigit()): continue
    with open(fp, encoding="utf-8") as f:
        codes = [ln.split("|")[0].split()[0].strip() for ln in f if ln.strip()]
    for code in codes:
        s1 = load_1d(code)
        if d not in s1: continue
        t1 = nth_after(s1, d, 1)
        if t1 is None or t1 not in s1: continue
        Tc = s1[d]["c"]
        # 日线判定
        if s1[t1]["h"] >= Tc*1.10*0.999: hit_1d_h += 1
        if s1[t1]["c"] >= Tc*1.095: hit_1d_c += 1
        # 5分钟判定(对比)
        bars = load_5m(code)
        t1d = __import__("datetime").datetime.strptime(t1,"%Y%m%d").date()
        db = [b for b in bars if b[0].date()==t1d]
        if db:
            mh = max(b[2] for b in db)
            if mh >= Tc*1.10*0.999: hit_5m += 1
            # 若日线判定为摸板但5分钟最高没到 -> 5m漏数
            if s1[t1]["h"] >= Tc*1.10*0.999 and mh < Tc*1.10*0.999: ex_5m_bad += 1
        tot += 1

print(f"样本(有效)D+1 = {tot}")
print(f"  T+1 摸涨停(日线最高>=1.10*Tc): {hit_1d_h} = {hit_1d_h/tot*100:.1f}%")
print(f"  T+1 收盘涨停(日线收盘>=1.095): {hit_1d_c} = {hit_1d_c/tot*100:.1f}%")
print(f"  T+1 摸涨停(5分钟最高, 旧法)  : {hit_5m} = {hit_5m/tot*100:.1f}%")
print(f"  -> 日线判定为摸板但5分钟漏数的: {ex_5m_bad} 只 (证明5m最高价不可靠)")
