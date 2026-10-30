"""
策略3(mode3) 全面回测：各种「每日选股方式 × 出场方式」组合，重点覆盖每日一股。
方法论沿用 stat_ma60_limitup.py（首板涨停股·关注日）：信号日 T=关注日(涨停日+1)，
  - 5M日内卖(r2)：买 T 收盘，T+1 按5分钟K线规则卖（摸涨停价卖 / 破-2%止损 / 午后回MA60或收盘卖）
  - T+1收盘卖(rc)：买 T 收盘，T+1 收盘卖（不过盘中止损/止盈，纯隔夜持有）

每日选股方式（对 signal[T] 列表，该列表已按流通市值降序）：
  - avg     : 等权买入当天全部入选股（日收益=各股收益均值）
  - first   : 每日一股=列表首只（流通市值最大）
  - last    : 每日一股=列表末只（流通市值最小）
  - random  : 每日一股=当天随机一只（50 个随机种子取日收益均值，作为“随机单股”期望）
信号源：
  - 策略3   : _load_top_first_vol_ma60_mode3()（基于首板涨停股 的 D-4~D-1 量价异动）
  - 基准    : _load_top_first_vol_ma60()（首板MA60 原筛选，仅作参考）
  - 策略4   : _load_top_first_vol_ma60_mode4()（原版筛选3，仅作参考）
收益均为毛收益（未扣佣金印花税）。
"""
import os, sys, datetime as _dt, statistics, random
from collections import defaultdict

ROOT = r"C:/MarcoAI"
ONE_D = os.path.join(ROOT, "AIData", "1D")
FIVE_M = os.path.join(ROOT, "AIData", "5M")
sys.path.insert(0, os.path.join(ROOT, "AICode"))
from AICode.MarcoAPI.StrategyUI import (
    _load_top_first_vol_ma60,
    _load_top_first_vol_ma60_mode3,
    _load_top_first_vol_ma60_mode4,
)

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


def sell_real(Tc, o1, day, stop, lu, lu_hit):
    if o1/Tc - 1 <= -0.02:
        return o1/Tc-1, "OPEN_CUT"
    if lu_hit:
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


def collect_rows(sig):
    """返回 {T: [ {code, Tc, r2(5M日内卖), rc(T+1收盘卖)} ... ]}，顺序=信号列表顺序(市值降序)"""
    rows_by_day = {}; skipped = 0
    for T, codes in sig.items():
        day_rows = []
        for code in codes:
            s1 = load_1d(code)
            if T not in s1: continue
            t1 = nth_after(s1, T, 1)
            if t1 is None or t1 not in s1: continue
            Tc = s1[T]["c"]
            if Tc <= 0: continue
            bars = load_5m(code)
            if len(bars) < 60: continue
            ma = [None] * len(bars)
            for i in range(len(bars)):
                if i >= 59: ma[i] = sum(bars[j][4] for j in range(i-59, i+1)) / 60.0
            t1d = _dt.datetime.strptime(t1, "%Y%m%d").date()
            fbars = [b for b in bars if b[0].date() == t1d]
            if not fbars: continue
            fi = bars.index(fbars[0])
            if fi < 59: continue
            day = [{"dt": b[0], "h": b[2], "l": b[3], "c": b[4], "ma": ma[i]}
                   for i, b in enumerate(bars) if b[0].date() == t1d]
            hi = max(b["h"] for b in day); lo = min(b["l"] for b in day)
            if hi > Tc*1.13 or lo < Tc*0.87:   # 5M 未复权对齐脏数据 -> 剔除
                skipped += 1; continue
            bd = board(code); lu = 0.10 if bd == "MAIN" else 0.20
            lu_hit = (t1 in s1) and (s1[t1]["h"] >= Tc*(1+lu)*0.999)
            r2, _ = sell_real(Tc, s1[t1]["o"], day, 0.02, lu, lu_hit)
            rc = s1[t1]["c"]/Tc - 1
            day_rows.append(dict(code=code, Tc=Tc, r2=r2, rc=rc))
        if day_rows:
            rows_by_day[T] = day_rows
    return rows_by_day, skipped


def daily_series(rows_by_day, method, key, seed=None):
    out = {}
    for T, drs in rows_by_day.items():
        if not drs: continue
        if method == "avg":
            out[T] = statistics.mean(r[key] for r in drs)
        elif method == "first":
            out[T] = drs[0][key]          # 列表首只 = 市值最大
        elif method == "last":
            out[T] = drs[-1][key]         # 列表末只 = 市值最小
        elif method == "random":
            out[T] = random.Random(seed).choice(drs)[key]
    return out


def daily_series_random_avg(rows_by_day, key, nseed=50):
    acc = defaultdict(list)
    for sd in range(nseed):
        d = daily_series(rows_by_day, "random", key, sd)
        for T, v in d.items():
            acc[T].append(v)
    return {T: statistics.mean(vs) for T, vs in acc.items()}


def monthly_cum(daily):
    months = defaultdict(list)
    for T, ret in daily.items():
        months[T[:6]].append(ret)
    month_ret = {}
    eq = 1.0; peak = 1.0; mdd = 0.0
    for m in sorted(months):
        mr = 1.0
        for r in months[m]: mr *= (1 + r)
        month_ret[m] = mr - 1
        eq *= mr; peak = max(peak, eq); mdd = min(mdd, eq/peak - 1)
    n = len(daily)
    wins = sum(1 for r in daily.values() if r > 0)
    mean_daily = statistics.mean(daily.values()) if n else 0.0
    return month_ret, eq - 1, mdd, (wins/n if n else 0.0), mean_daily, n


def compound(month_ret):
    eq = 1.0
    for m in sorted(month_ret):
        eq *= (1 + month_ret[m])
    return eq - 1


def print_summary(title, rows):
    print(f"\n==== {title} ====")
    print(f"  {'变体':<22}{'天数':>6}{'日均%':>9}{'日胜率%':>9}{'累计%':>11}{'回撤%':>9}")
    for label, mr, cum, mdd, win, md, n in rows:
        print(f"  {label:<22}{n:>6}{md*100:>9.2f}{win*100:>9.1f}{cum*100:>11.1f}{mdd*100:>9.1f}")


def print_monthly(title, variants):
    # variants: list of (label, month_ret)
    all_months = sorted({m for _, vr in variants for m in vr})
    print(f"\n=== {title}（每月收益%，累计见末行）===")
    print("  " + "月份".ljust(8) + "".join(lbl.rjust(13) for lbl, _ in variants))
    for m in all_months:
        print("  " + m.ljust(8) + "".join(f"{(vr.get(m,0)*100):>12.2f}%" for _, vr in variants))
    print("  " + "累计".ljust(8) + "".join(f"{(compound(vr)*100):>12.2f}%" for _, vr in variants))


if __name__ == "__main__":
    print("加载信号(策略3/基准/策略4)... 可能需数十秒")
    base = _load_top_first_vol_ma60()
    m3 = _load_top_first_vol_ma60_mode3()
    m4 = _load_top_first_vol_ma60_mode4()
    sig_base = {d: [r[0] for r in v] for d, v in base.items() if v}
    sig3 = {d: [r[0] for r in v] for d, v in m3.items() if v}
    sig4 = {d: [r[0] for r in v] for d, v in m4.items() if v}
    print(f"信号规模: 基准={sum(len(v) for v in sig_base.values())}只/{len(sig_base)}日, "
          f"策略3={sum(len(v) for v in sig3.values())}只/{len(sig3)}日, "
          f"策略4={sum(len(v) for v in sig4.values())}只/{len(sig4)}日")

    print("收集逐笔收益(读1D/5M)... 可能需数分钟")
    rb3, sk3 = collect_rows(sig3)
    rb_base, _ = collect_rows(sig_base)
    rb4, _ = collect_rows(sig4)
    print(f"策略3 有效日={len(rb3)} 跳过={sk3}")

    METHODS = ["avg", "first", "last", "random"]
    # ---- 策略3：5M 日内卖(r2) ----
    s3_5m = []
    s3_5m_monthly = []
    for m in METHODS:
        daily = daily_series_random_avg(rb3, "r2") if m == "random" else daily_series(rb3, m, "r2")
        mr, cum, mdd, win, md, n = monthly_cum(daily)
        lbl = {"avg":"等权全量","first":"每日一股-首(大市值)","last":"每日一股-末(小市值)","random":"每日一股-随机(50seed)"}[m]
        s3_5m.append((lbl, mr, cum, mdd, win, md, n))
        s3_5m_monthly.append((lbl, mr))
    # ---- 策略3：T+1 收盘卖(rc) ----
    s3_rc = []
    s3_rc_monthly = []
    for m in METHODS:
        daily = daily_series_random_avg(rb3, "rc") if m == "random" else daily_series(rb3, m, "rc")
        mr, cum, mdd, win, md, n = monthly_cum(daily)
        lbl = {"avg":"等权全量","first":"每日一股-首(大市值)","last":"每日一股-末(小市值)","random":"每日一股-随机(50seed)"}[m]
        s3_rc.append((lbl, mr, cum, mdd, win, md, n))
        s3_rc_monthly.append((lbl, mr))

    # ---- 基准 / 策略4 参考（仅 5M 日内卖 的 avg/first/last 摘要）----
    ref = []
    for name, rb in (("基准(首板MA60)", rb_base), ("策略4(原筛选3)", rb4)):
        for m in ("avg", "first", "last"):
            daily = daily_series(rb, m, "r2")
            mr, cum, mdd, win, md, n = monthly_cum(daily)
            lbl = f"{name}-{('等权' if m=='avg' else ('首/大市值' if m=='first' else '末/小市值'))}"
            ref.append((lbl, mr, cum, mdd, win, md, n))

    print_summary("策略3 · 5M日内卖", s3_5m)
    print_summary("策略3 · T+1收盘卖", s3_rc)
    print_summary("基准/策略4 参考 · 5M日内卖", ref)
    print_monthly("策略3 每月收益 · 5M日内卖", s3_5m_monthly)
    print_monthly("策略3 每月收益 · T+1收盘卖", s3_rc_monthly)
