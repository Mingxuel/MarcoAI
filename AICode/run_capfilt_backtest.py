"""大盘优先 + 形态过滤（实盘友好版）。

思路（来自 diagnose_signals / diagnose_composite 的实证）：
  - 市值排序是主导信号（TPO_M5 基线 282% >> 任何纯形态重排 132%）；
  - 但部分形态维度有"明确负 edge"，应作为否决项剔除，而不是用来重排序；
  - 否决后在大盘优先队列里顺延到下一只"干净"的候选（保留大盘信号）。

否决条件（对应 diagnose_signals 中显著为负/最低的桶）：
  V1 无空间        room <= 0          (空间小<3% 均值 -0.06%，但 0 空间最极端)
  V2 短上影        0.3<=up1<1.0        (短上影桶均值 -0.26%，全样本最差)
  V3 MA60上方下坡   above60 and slope<0 (上方下坡桶均值 0.27%，MA60 三档最差)

产出：AIData/Strategy/TPO_CAPFILT/{卖出日}（每行一只，按大盘顺延后的选择）
对比：Backtest 对 TPO_CAPFILT 与 TPO_M5 各卖出方式回测。

运行：cd e:/MarcoAI/AICode && python run_capfilt_backtest.py
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from AICode.MarcoAPI.Update.SZ2001D import GET_SZ200_1D_PREVIOUS  # noqa: E402
from AICode.MarcoAPI import Backtest  # noqa: E402

SRC_DIR = os.path.join(_ROOT, "AIData", "Strategy", "TPO_M5")
DST_DIR = os.path.join(_ROOT, "AIData", "Strategy", "TPO_CAPFILT")

UP_SHORT = 0.3   # 短上影下界


def _body(r):
    return abs(r.close - r.open) or (max(r.close, 1e-9) * 0.01)


def _up(r):
    return (r.high - max(r.open, r.close)) / _body(r)


def _feat(r1, r2, r3):
    pred = (r1.high + (r1.high - r3.high)) if (r3 and r1.high < r2.high) else (2 * r1.high - r2.high)
    room = (pred - r1.close) / r1.close if r1.close > 0 else -9
    up1 = _up(r1)
    above60 = (r1.ma60 > 0) and (r1.close > r1.ma60)
    slope = r1.ma60 - r2.ma60
    return dict(pred=pred, room=room, up1=up1, above60=above60, slope=slope)


def veto(f):
    """返回 (是否否决, 原因)。"""
    if f["room"] <= 0:
        return True, "无空间"
    if UP_SHORT <= f["up1"] < 1.0:
        return True, "短上影"
    if f["above60"] and f["slope"] < 0:
        return True, "MA60上方下坡"
    return False, ""


def build(dst_dir):
    os.makedirs(dst_dir, exist_ok=True)
    dates = sorted(f for f in os.listdir(SRC_DIR) if f.isdigit())
    picked, skipped, total = 0, 0, 0
    for d in dates:
        with open(os.path.join(SRC_DIR, d), "r", encoding="gbk", errors="ignore") as fh:
            lines = [ln.rstrip("\n") for ln in fh if ln.strip()]
        rows = [ln.split("|") for ln in lines if len(ln.split("|")) >= 11]
        if not rows:
            open(os.path.join(dst_dir, d), "w", encoding="utf-8").write("\n")
            skipped += 1
            continue
        chosen = None
        reason = ""
        for c in rows:  # 已按大盘顺序（首只=市值最大），顺延
            r1 = GET_SZ200_1D_PREVIOUS(c[0], d, 1)
            r2 = GET_SZ200_1D_PREVIOUS(c[0], d, 2)
            r3 = GET_SZ200_1D_PREVIOUS(c[0], d, 3)
            if r1 is None or r2 is None:
                continue
            total += 1
            f = _feat(r1, r2, r3)
            v, rsn = veto(f)
            if not v:
                chosen = c
                break
            reason = rsn
        if chosen is None:
            open(os.path.join(dst_dir, d), "w", encoding="utf-8").write("\n")
            skipped += 1
        else:
            with open(os.path.join(dst_dir, d), "w", encoding="utf-8") as fh:
                fh.write("|".join(chosen) + "\n")
            picked += 1
    return picked, skipped, total


def monthly_and_total(strategy_name):
    res = Backtest.BACKTEST(strategy_name, sell_modes=["first", "5m"])
    text = res.get("first", "")
    p = os.path.join(_ROOT, "AIData", "Strategy", "RESULT", f"{strategy_name}.txt")
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8", errors="ignore") as fh:
            text = fh.read()
    import re
    _re_month = re.compile(r"^\s*(\d{6})\s*:\s*([-\d.]+)%")
    _re_total = re.compile(r"总收益率:\s*([-\d.]+)%")
    m = {}
    for line in text.split("\n"):
        mm = _re_month.search(line)
        if mm:
            m[mm.group(1)] = float(mm.group(2))
    tt = _re_total.search(text)
    # 5m 总收益另取
    tm = None
    mt = re.compile(r"总收益率:\s*([-\d.]+)%")
    for line in res.get("5m", "").split("\n"):
        if mt.search(line):
            tm = float(mt.search(line).group(1))
            break
    return m, (float(tt.group(1)) if tt else None), tm


def main():
    print("== 生成 TPO_CAPFILT 策略（大盘优先 + 形态否决过滤）==")
    picked, skipped, total = build(DST_DIR)
    print(f"候选扫描: {total} 只 | 买入日: {picked} | 跳过日(全否决): {skipped}\n")

    cm, ct, c5 = monthly_and_total("TPO_CAPFILT")
    bm, bt, b5 = monthly_and_total("TPO_M5")

    print("== 总收益率对比（first=收盘卖 / 5m=日内卖）==")
    print(f"  TPO_CAPFILT(大盘+否决) : first {ct:.2f}% | 5m {c5:.2f}%" if ct is not None else "  TPO_CAPFILT: --")
    print(f"  TPO_M5(基线,大盘优先)  : first {bt:.2f}% | 5m {b5:.2f}%" if bt is not None else "  TPO_M5: --")

    print("\n== 月度收益对比（CAPFILT first vs M5 first）==")
    print(f"{'月份':<10}{'CAPFILT':>12}{'M5基线':>12}{'差值':>10}")
    for mo in sorted(set(cm) | set(bm)):
        a = cm.get(mo); b = bm.get(mo)
        def f(x):
            return f"{x:>10.2f}%" if x is not None else "       --"
        diff = (f"{a-b:+8.2f}%") if (a is not None and b is not None) else "    --"
        print(f"{mo:<10}{f(a):>12}{f(b):>12}{diff:>10}")


if __name__ == "__main__":
    main()
