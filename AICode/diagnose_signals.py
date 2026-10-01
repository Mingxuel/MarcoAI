"""信号有效性诊断：把 TPO_M5 全部候选按 Daily.txt 各理解维度分组，
比较其实际次日收益（与 Backtest 同一卖出规则），看哪些直觉真的有 edge。

不重排、不筛选，只做分组均值，回答"拼理解力"到底哪些维度能分离赢家/输家。
运行：cd e:/MarcoAI/AICode && python diagnose_signals.py
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from AICode.MarcoAPI.Update.SZ2001D import GET_SZ200_1D_PREVIOUS
from AICode.MarcoAPI import Backtest

SRC_DIR = os.path.join(_ROOT, "AIData", "Strategy", "TPO_M5")
UP_LONG = 1.0
UP_SHORT = 0.3
DN_SUPPORT = 0.3


def _body(r):
    return abs(r.close - r.open) or (max(r.close, 1e-9) * 0.01)


def _up(r):
    return (r.high - max(r.open, r.close)) / _body(r)


def _dn(r):
    return (min(r.open, r.close) - r.low) / _body(r)


def avg(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else float("nan")


def main():
    recs = []  # (ret, attrs)
    for d in sorted(f for f in os.listdir(SRC_DIR) if f.isdigit()):
        with open(os.path.join(SRC_DIR, d), "r", encoding="gbk", errors="ignore") as f:
            lines = [ln.rstrip("\n") for ln in f if ln.strip()]
        for ln in lines:
            cols = ln.split("|")
            if len(cols) < 11:
                continue
            code = cols[0]
            r1 = GET_SZ200_1D_PREVIOUS(code, d, 1)
            r2 = GET_SZ200_1D_PREVIOUS(code, d, 2)
            r3 = GET_SZ200_1D_PREVIOUS(code, d, 3)
            if r1 is None or r2 is None:
                continue
            ret = Backtest._stock_return(cols)
            if ret is None:
                continue
            pred = (r1.high + (r1.high - r3.high)) if (r3 and r1.high < r2.high) else (2 * r1.high - r2.high)
            room = (pred - r1.close) / r1.close if r1.close > 0 else 0
            hu, lu = r1.high > r2.high, r1.low > r2.low
            red1, red2 = r1.is_red == 1, r2.is_red == 1
            seq = "连阳/阴转阳" if red1 else ("阳转阴" if red2 else "连阴")
            hl = "齐升" if (hu and lu) else ("齐降" if (not hu and not lu) else "高低分列")
            up1 = _up(r1)
            shadow = "双长上影" if (_up(r1) >= UP_LONG and _up(r2) >= UP_LONG) else (
                "长上影" if up1 >= UP_LONG else ("短上影" if up1 >= UP_SHORT else "无上影"))
            above60 = r1.ma60 > 0 and r1.close > r1.ma60
            slope = r1.ma60 - r2.ma60
            ma60 = "上方上坡" if (above60 and slope > 0) else ("上方下坡" if above60 else "下方压制")
            held = r1.low >= r2.low
            recs.append((ret, dict(seq=seq, hl=hl, shadow=shadow, ma60=ma60,
                                  held="守低" if held else "破低",
                                  room="空间大(>3%)" if room > 0.03 else "空间小(<3%)")))
    print(f"候选样本: {len(recs)} 只 | 全样本均值次日收益: {avg([r for r, _ in recs])*100:.2f}%\n")

    dims = ["seq", "hl", "shadow", "ma60", "held", "room"]
    for dim in dims:
        print(f"== 按 [{dim}] 分组的平均次日收益 ==")
        buckets = {}
        for ret, a in recs:
            buckets.setdefault(a[dim], []).append(ret)
        for k in sorted(buckets, key=lambda x: -avg(buckets[x])):
            n = len(buckets[k])
            print(f"  {k:<14} n={n:>3}  均值 {avg(buckets[k])*100:>7.2f}%")
        print()


if __name__ == "__main__":
    main()
