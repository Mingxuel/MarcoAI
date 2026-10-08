"""临时统计: TAB6(首板涨停放量股, 信号日=t2=T-2) 每月在 T-1(=t2+1) 或 T-0(=t2+2) 出现涨停的次数。
只读 TOP_FIRST_VOL 与 1D, 不写任何数据。
用法: python -m AICode.MarcoAPI.Update.StatTab6_Follow
"""

import os
import sys
from collections import defaultdict

_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _root not in sys.path:
    sys.path.insert(0, _root)

from AICode.MarcoAPI.Update.SZ2001D import GET_SZ200_1D_AFTER, GET_SZ200_1D_ALL
from AICode.MarcoAPI.Update.Path import PATH_AIDATA_TOP_FIRST_VOL


def main():
    GET_SZ200_1D_ALL()
    base = PATH_AIDATA_TOP_FIRST_VOL()
    dates = sorted(d for d in os.listdir(base) if d.isdigit())
    tot = defaultdict(int)    # 信号月 TAB6 条目数
    c1 = defaultdict(int)     # T-1(=t2+1) 涨停次数
    c0 = defaultdict(int)     # T-0(=t2+2) 涨停次数
    ce = defaultdict(int)     # T-1 或 T-0 任一涨停的条目数
    for t2 in dates:
        with open(os.path.join(base, t2), "r", encoding="utf-8") as f:
            codes = [l.strip() for l in f if l.strip()]
        for code in codes:
            m = t2[:6]
            tot[m] += 1
            t1 = GET_SZ200_1D_AFTER(code, t2, 1)
            t0 = GET_SZ200_1D_AFTER(code, t2, 2)
            a = t1 is not None and t1.is_top == 1
            b = t0 is not None and t0.is_top == 1
            c1[m] += a
            c0[m] += b
            ce[m] += (a or b)

    print("=" * 70)
    print("TAB6 每月 T-1(=t2+1) / T-0(=t2+2) 涨停统计")
    print("  月份    TAB6条目  T-1涨停  T-0涨停  任一涨停  占比")
    for m in sorted(tot):
        print("  %s   %5d   %5d   %5d   %5d   %5.1f%%"
              % (m, tot[m], c1[m], c0[m], ce[m], ce[m] / tot[m] * 100 if tot[m] else 0))
    print("  合计   %5d   %5d   %5d   %5d   %5.1f%%"
          % (sum(tot.values()), sum(c1.values()), sum(c0.values()), sum(ce.values()),
             sum(ce.values()) / sum(tot.values()) * 100 if tot else 0))
    print("=" * 70)


if __name__ == "__main__":
    main()
