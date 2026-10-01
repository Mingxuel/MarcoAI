"""根因诊断：市值效应 + 各主排序键的独立贡献。
对比同一 TPO_M5 池内：
  - 基线 big-cap-first（文件首只=市值最大）
  - 仅按空间(room)选
  - 仅按市值倒序的 last（最小市值）
  - 全样本按市值分位的收益
运行：cd e:/MarcoAI/AICode && python diagnose_cap.py
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


def _body(r):
    return abs(r.close - r.open) or (max(r.close, 1e-9) * 0.01)


def _up(r):
    return (r.high - max(r.open, r.close)) / _body(r)


def _day_pick(rows, mode):
    """rows: 当日候选 cols 列表。返回所选 cols（或 None）。"""
    if not rows:
        return None
    if mode == "first":
        return rows[0]
    if mode == "last":
        return rows[-1]
    if mode == "space":
        best, bk = None, None
        for c in rows:
            r1 = GET_SZ200_1D_PREVIOUS(c[0], c[3], 1)
            r2 = GET_SZ200_1D_PREVIOUS(c[0], c[3], 2)
            r3 = GET_SZ200_1D_PREVIOUS(c[0], c[3], 3)
            if r1 is None or r2 is None:
                continue
            pred = (r1.high + (r1.high - r3.high)) if (r3 and r1.high < r2.high) else (2 * r1.high - r2.high)
            room = (pred - r1.close) / r1.close if r1.close > 0 else -9
            if bk is None or room > bk:
                bk, best = room, c
        return best
    return None


def _capital_compound(picks):
    cap = 100000.0
    for cols in picks:
        if cols is None:
            continue
        sp = Backtest._sell_price_1d(cols)
        try:
            pre = float(cols[10])
        except (ValueError, IndexError):
            continue
        if sp is None or pre <= 0:
            continue
        cap *= (1 + Backtest._trade_net_return(pre, sp, cap))
    return cap / 100000.0 - 1.0


def main():
    per_day = {}  # date -> rows
    for d in sorted(f for f in os.listdir(SRC_DIR) if f.isdigit()):
        with open(os.path.join(SRC_DIR, d), "r", encoding="gbk", errors="ignore") as f:
            lines = [ln.rstrip("\n") for ln in f if ln.strip()]
        rows = [ln.split("|") for ln in lines if len(ln.split("|")) >= 11]
        per_day[d] = rows

    # 全样本市值分位收益
    all_mc, all_ret = [], []
    for d, rows in per_day.items():
        for c in rows:
            r1 = GET_SZ200_1D_PREVIOUS(c[0], c[3], 1)
            if r1 is None:
                continue
            ret = Backtest._stock_return(c)
            if ret is None:
                continue
            try:
                mc = float(c[2])
            except ValueError:
                continue
            all_mc.append(mc)
            all_ret.append(ret)
    order = sorted(range(len(all_mc)), key=lambda i: all_mc[i])
    n = len(order)
    print(f"候选 {n} 只，按市值升序分 4 档的平均次日收益：")
    for q in range(4):
        seg = [all_ret[i] for i in order[q * n // 4: (q + 1) * n // 4]]
        lo = all_mc[order[q * n // 4]] / 1e8
        hi = all_mc[order[min((q + 1) * n // 4, n) - 1]] / 1e8
        print(f"  档{q+1} 市值 {lo:6.0f}~{hi:6.0f}亿  n={len(seg):>3}  均值 {sum(seg)/len(seg)*100:>6.2f}%")
    print()

    for mode in ["first", "last", "space"]:
        picks = [ _day_pick(per_day[d], mode) for d in sorted(per_day) ]
        traded = [p for p in picks if p]
        tot = _capital_compound(picks)
        print(f"模式 {mode:<6}: 交易 {len(traded)} 日, 总收益 {tot*100:.2f}%")


if __name__ == "__main__":
    main()
