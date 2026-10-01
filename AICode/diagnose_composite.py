"""组合策略诊断：把"空间"降为门槛，形态/MA/影线作为排序，并叠加市值约束，
看用户的 candlestick 理解能否在市值溢价之上再增效。
运行：cd e:/MarcoAI/AICode && python diagnose_composite.py
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


def _body(r):
    return abs(r.close - r.open) or (max(r.close, 1e-9) * 0.01)


def _up(r):
    return (r.high - max(r.open, r.close)) / _body(r)


def _feat(cols):
    """返回 (rec1,rec2,rec3, pred, room, seq_tier, ma_tier, shadow_tier, mcap) 或 None。"""
    r1 = GET_SZ200_1D_PREVIOUS(cols[0], cols[3], 1)
    r2 = GET_SZ200_1D_PREVIOUS(cols[0], cols[3], 2)
    r3 = GET_SZ200_1D_PREVIOUS(cols[0], cols[3], 3)
    if r1 is None or r2 is None:
        return None
    pred = (r1.high + (r1.high - r3.high)) if (r3 and r1.high < r2.high) else (2 * r1.high - r2.high)
    room = (pred - r1.close) / r1.close if r1.close > 0 else -9
    red1, red2 = r1.is_red == 1, r2.is_red == 1
    seq_tier = 0 if ((not red1) and red2) else (1 if (not red1 and not red2) else 2)
    above60 = (r1.ma60 > 0) and (r1.close > r1.ma60)
    slope = r1.ma60 - r2.ma60
    ma_tier = 0 if (above60 and slope > 0) else (1 if above60 else (2 if r1.ma60 > 0 else 1))
    up1, up2 = _up(r1), _up(r2)
    shadow_tier = 1 if (up1 >= UP_LONG and up2 >= UP_LONG) else (0 if up1 >= UP_LONG else (2 if up1 < UP_SHORT else 3))
    try:
        mcap = float(cols[2])
    except ValueError:
        mcap = 0.0
    return (r1, r2, r3, pred, room, seq_tier, ma_tier, shadow_tier, mcap)


def _pick(rows, mode):
    feats = [f for f in (_feat(c) for c in rows) if f]
    if not feats:
        return None
    if mode == "first":
        return rows[0]
    if mode == "candle":  # 门槛 room>0，排序 形态>MA>影线（空间仅末位微调）
        cand = [f for f in feats if f[4] > 0]
        if not cand:
            return None
        cand.sort(key=lambda f: (f[5], f[6], f[7], -f[4]))
        return rows[feats.index(cand[0])]
    if mode == "candle_capmed":  # 先按当日市值中位数过滤，再 candle
        med = sorted(f[8] for f in feats)[len(feats) // 2]
        cand = [f for f in feats if f[4] > 0 and f[8] >= med]
        if not cand:
            return None
        cand.sort(key=lambda f: (f[5], f[6], f[7], -f[4]))
        return rows[feats.index(cand[0])]
    if mode.startswith("top"):  # topN 市值，再 candle
        n = int(mode[3:])
        top = sorted(feats, key=lambda f: -f[8])[:n]
        cand = [f for f in top if f[4] > 0]
        if not cand:
            return None
        cand.sort(key=lambda f: (f[5], f[6], f[7], -f[4]))
        return rows[feats.index(cand[0])]
    return None


def _compound(picks):
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
    per_day = {}
    for d in sorted(f for f in os.listdir(SRC_DIR) if f.isdigit()):
        with open(os.path.join(SRC_DIR, d), "r", encoding="gbk", errors="ignore") as f:
            lines = [ln.rstrip("\n") for ln in f if ln.strip()]
        per_day[d] = [ln.split("|") for ln in lines if len(ln.split("|")) >= 11]

    # 基线
    base = _compound([_pick(per_day[d], "first") for d in sorted(per_day)])
    print(f"基线 big-cap-first : {base*100:.2f}%\n")
    for mode in ["candle", "candle_capmed", "top2", "top3", "top5"]:
        picks = [_pick(per_day[d], mode) for d in sorted(per_day)]
        traded = [p for p in picks if p]
        print(f"模式 {mode:<14}: 交易 {len(traded)} 日, 总收益 {_compound(picks)*100:.2f}%")


if __name__ == "__main__":
    main()
