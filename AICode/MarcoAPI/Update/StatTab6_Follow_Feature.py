"""临时统计: TAB6 中 T-1(=t2+1) 涨停 vs T-0(=t2+2) 涨停 的两类票, 在信号日 t2 及之前的特征差异。
分组(互斥):
  T1      : t2+1 涨停(不论 t2+2)
  T0_ONLY : t2+1 未涨停 但 t2+2 涨停(延迟板)
  BOTH    : t2+1 与 t2+2 都涨停
  NONE    : 两日都未涨停(基线)
特征在 t2 信号日(及 t2-1=T-3)测量。只读, 不写。
用法: python -m AICode.MarcoAPI.Update.StatTab6_Follow_Feature
"""

import os
import sys
from collections import defaultdict

_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _root not in sys.path:
    sys.path.insert(0, _root)

from AICode.MarcoAPI.Update.SZ2001D import GET_SZ200_1D_AFTER, GET_SZ200_1D_PREVIOUS, GET_SZ200_1D_ALL
from AICode.MarcoAPI.Update.StockCodes import GET_STOCK_INFO
from AICode.MarcoAPI.Update.Path import PATH_AIDATA_TOP_FIRST_VOL


def _feat(code, t2):
    d = GET_SZ200_1D_AFTER(code, t2, 0)        # t2 信号日
    prev = GET_SZ200_1D_PREVIOUS(code, t2, 1)  # t2-1 = T-3(首板涨停日)
    if d is None:
        return None
    rng = d.high - d.low
    f = {}
    f["ratio_t2"] = d.ratio
    f["ma5dev"] = (d.close / d.ma5 - 1) if d.ma5 > 0 else None
    f["ma20dev"] = (d.close / d.ma20 - 1) if d.ma20 > 0 else None
    f["upsh"] = (d.high - max(d.open, d.close)) / rng if rng > 0 else None
    f["losh"] = (min(d.open, d.close) - d.low) / rng if rng > 0 else None
    f["volr"] = (d.volume / prev.volume) if (prev is not None and prev.volume > 0) else None
    info = GET_STOCK_INFO(code)
    f["cap"] = (float(info[1]) * d.close / 1e8) if (info is not None and len(info) > 1 and info[1] > 0) else None
    f["ratio_t3"] = prev.ratio if prev is not None else None
    t1 = GET_SZ200_1D_AFTER(code, t2, 1)
    f["gap_t1"] = (t1.open / d.close - 1) if (t1 is not None and d.close > 0) else None
    return f


def main():
    GET_SZ200_1D_ALL()
    base = PATH_AIDATA_TOP_FIRST_VOL()
    dates = sorted(d for d in os.listdir(base) if d.isdigit())
    sums = defaultdict(lambda: defaultdict(float))
    cnts = defaultdict(lambda: defaultdict(int))
    groups_n = defaultdict(int)

    KEYS = ["ratio_t2", "ma5dev", "ma20dev", "upsh", "losh", "volr", "cap", "ratio_t3", "gap_t1"]
    for t2 in dates:
        with open(os.path.join(base, t2), "r", encoding="utf-8") as fh:
            codes = [l.strip() for l in fh if l.strip()]
        for code in codes:
            t1 = GET_SZ200_1D_AFTER(code, t2, 1)
            t0 = GET_SZ200_1D_AFTER(code, t2, 2)
            a = t1 is not None and t1.is_top == 1
            b = t0 is not None and t0.is_top == 1
            if a and b:
                g = "BOTH"
            elif a:
                g = "T1"
            elif b:
                g = "T0_ONLY"
            else:
                g = "NONE"
            groups_n[g] += 1
            if g == "NONE":
                continue  # 基线不进特征对比(量太大)
            f = _feat(code, t2)
            if f is None:
                continue
            for k in KEYS:
                v = f[k]
                if v is not None:
                    sums[g][k] += v
                    cnts[g][k] += 1

    print("=" * 78)
    print("TAB6: T-1涨停 vs 延迟T-0涨停 — 信号日(t2)特征均值对比")
    print("  (NONE 基线共 %d 条, 已排除; 仅对比封板两组)" % groups_n["NONE"])
    print("  分组      n    t2涨幅% 收/MA5% 收/MA20% 上影/区间 下影/区间 量比  市值(亿) T-3涨幅% T+1跳空%")
    order = ["T1", "T0_ONLY", "BOTH"]
    for g in order:
        n = groups_n[g]
        line = "  %-7s %4d" % (g, n)
        vals = {
            "ratio_t2": sums[g]["ratio_t2"] / cnts[g]["ratio_t2"] if cnts[g]["ratio_t2"] else 0,
            "ma5dev": sums[g]["ma5dev"] / cnts[g]["ma5dev"] * 100 if cnts[g]["ma5dev"] else 0,
            "ma20dev": sums[g]["ma20dev"] / cnts[g]["ma20dev"] * 100 if cnts[g]["ma20dev"] else 0,
            "upsh": sums[g]["upsh"] / cnts[g]["upsh"] * 100 if cnts[g]["upsh"] else 0,
            "losh": sums[g]["losh"] / cnts[g]["losh"] * 100 if cnts[g]["losh"] else 0,
            "volr": sums[g]["volr"] / cnts[g]["volr"] if cnts[g]["volr"] else 0,
            "cap": sums[g]["cap"] / cnts[g]["cap"] if cnts[g]["cap"] else 0,
            "ratio_t3": sums[g]["ratio_t3"] / cnts[g]["ratio_t3"] if cnts[g]["ratio_t3"] else 0,
            "gap_t1": sums[g]["gap_t1"] / cnts[g]["gap_t1"] * 100 if cnts[g]["gap_t1"] else 0,
        }
        line += "  %6.2f  %6.2f  %7.2f  %7.2f  %7.2f  %5.2f  %7.1f  %7.2f  %7.2f" % (
            vals["ratio_t2"], vals["ma5dev"], vals["ma20dev"], vals["upsh"], vals["losh"],
            vals["volr"], vals["cap"], vals["ratio_t3"], vals["gap_t1"])
        print(line)
    print("=" * 78)
    print("  说明: 收/MA=收盘相对均线的偏离%; 上影/下影=占当日振幅比例%; 量比=信号日量/前一日量;")
    print("        T+1跳空=次日(T-1)开盘相对信号日收盘的跳空%; T-3涨幅=首板涨停日涨幅。")


if __name__ == "__main__":
    main()
