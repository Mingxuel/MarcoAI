"""按「冲突解决方案」的确定性决策树，从 TPO_M5 候选宇宙中选股并重排，跑回测对比。

与 run_score_backtest.py（加权打分）不同：本脚本**不打分**，用
  - 一票否决（硬条件）
  - 及格线（gate）
  - 字典序排序键（逐级比较，不加权求和）
实现 T-1 重选，使每一档取舍可追溯、无分数笼统问题。

数据源：AIData/Strategy/TPO_M5/{卖出日}（TPO 硬过滤 + MA5 预测门槛后的候选宇宙）
产出 ：AIData/Strategy/TPO_DECISION/{卖出日}（通过决策树选出的 1 只，或空=不买）
对比 ：Backtest 对 TPO_DECISION 与 TPO_M5 各卖出方式做回测。

运行：cd e:/MarcoAI/AICode && python run_decision_backtest.py
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # e:/MarcoAI
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from AICode.MarcoAPI.Update.SZ2001D import GET_SZ200_1D_PREVIOUS  # noqa: E402
from AICode.MarcoAPI import Backtest  # noqa: E402

SRC_DIR = os.path.join(_ROOT, "AIData", "Strategy", "TPO_M5")
DST_DIR = os.path.join(_ROOT, "AIData", "Strategy", "TPO_DECISION")

UP_LONG = 1.0     # 上影/实体 >= 此值 视为"长上影"
UP_SHORT = 0.3    # 上影/实体 >= 此值 视为"短上影"
DN_SUPPORT = 0.3  # 下影/实体 >= 此值 视为"有下影支撑"


def _body(rec):
    return abs(rec.close - rec.open) or (max(rec.close, 1e-9) * 0.01)


def _up_ratio(rec):
    """上影长度 / 实体长度"""
    return (rec.high - max(rec.open, rec.close)) / _body(rec)


def _dn_ratio(rec):
    """下影长度 / 实体长度"""
    return (min(rec.open, rec.close) - rec.low) / _body(rec)


def _is_red(rec):
    return rec.is_red == 1


def _pred_high(rec1, rec2, rec3):
    """预测 T-0 最高价（解决 Daily.txt 冲突5：基准漂移）。
    默认 2*T-1高 - T-2高；仅当 T-1高 < T-2高（T-1 已回踩、高点下移）时改用 T-3&T-1。
    """
    if rec1.high < rec2.high and rec3 is not None:
        return rec1.high + (rec1.high - rec3.high)
    return 2 * rec1.high - rec2.high


def decide(rec1, rec2, rec3):
    """对一只候选做决策树判定。

    返回 (sort_key, reason) 表示通过且可排序；返回 (None, reason) 表示不买。
    sort_key = (-空间, 形态档, 均线档, 0/1未守住, 影线档, 0/1双长上影)
    全部按"越小越好"的升序比较，实现字典序（先比空间，再比形态…）。
    """
    reasons = []

    # ---- 基础派生量 ----
    pred = _pred_high(rec1, rec2, rec3)
    room = (pred - rec1.close) / rec1.close if rec1.close > 0 else 0.0   # 空间（冲突2/6 核心门槛）
    hu = rec1.high > rec2.high
    lu = rec1.low > rec2.low
    qi_sheng = hu and lu
    qi_jiang = (not hu) and (not lu)
    up1 = _up_ratio(rec1)
    up2 = _up_ratio(rec2)
    double_up = (up1 >= UP_LONG) and (up2 >= UP_LONG)          # 双长上影（冲突1）
    has_ls = _dn_ratio(rec1) >= DN_SUPPORT                     # 有下影支撑
    held = rec1.low >= rec2.low                                # 最低价守住（冲突2）
    no_support = (not has_ls) and (not held)                   # 无下影且破低

    # ---- 排序档位（按诊断实测方向修正；见 diagnose_signals.py）----
    # seq：阳转阴(1.25%) > 连阴(0.85%) > 连阳/阴转阳(0.45%) —— 与 TPO 的 T-1 缩量回踩本质一致
    red1, red2 = _is_red(rec1), _is_red(rec2)
    if (not red1) and red2:
        seq_tier = 0          # 阳转阴（洗盘回踩，最好买点）
    elif (not red1) and (not red2):
        seq_tier = 1          # 连阴
    else:
        seq_tier = 2          # 连阳 / 阴转阳

    above60 = (rec1.ma60 > 0) and (rec1.close > rec1.ma60)
    slope60 = rec1.ma60 - rec2.ma60
    if above60 and slope60 > 0:
        ma_tier = 0           # 价在 MA60 上 + 上坡
    elif above60:
        ma_tier = 1           # 价在上方但 MA60 下坡（最差）
    elif rec1.ma60 > 0:
        ma_tier = 2           # 价在 MA60 下方（压制，居中）
    else:
        ma_tier = 1           # MA60 数据缺失，中性

    # shadow：单长上影(1.89%) > 双长上影(1.32%) > 无上影(0.81%) > 短上影(-0.26%)
    if up1 >= UP_LONG and up2 >= UP_LONG:
        shadow_tier = 1       # 双长上影
    elif up1 >= UP_LONG:
        shadow_tier = 0       # 单长上影（T-1 长上影，最好）
    elif up1 < UP_SHORT:
        shadow_tier = 2       # 无上影
    else:
        shadow_tier = 3       # 短上影（最差）

    # ---- Step1 否决（仅保留无空间这种硬伤；长上影/连阴经数据验证非利空，不再否决）----
    if room <= 0:
        return None, "不买:无博弈空间(pred<=收盘)"

    # ---- Step2 字典序排序键（无打分，逐级比较）----
    # 注意：空间(room)只作"门槛+末位微调"，不作主导排序键——
    # 实测每天选 room 最大者会挑到最超买/小盘股，反而最差（见诊断）。
    sort_key = (
        seq_tier,              # 1) 阳转阴 > 连阴 > 连阳/阴转阳
        ma_tier,               # 2) MA60 态势（上坡>上方>下方）
        shadow_tier,           # 3) 长上影 > 双长 > 无 > 短上影
        -round(room, 6),       # 4) 空间仅作末位微调（需先过门槛）
        0 if held else 1,      # 5) 最低价守住（弱信号）
    )
    tag = ("阳转阴" if seq_tier == 0 else ("连阴" if seq_tier == 1 else ("连阳" if red1 else "阴转阳")))
    reasons.append(f"{tag} room={room*100:.1f}% pred={pred:.2f} "
                   f"{'齐升' if qi_sheng else ('齐降' if qi_jiang else '高低分列')} "
                   f"ma60={'上坡' if (above60 and slope60>0) else ('上方下坡' if above60 else '下方')} "
                   f"{'双长上影' if (up1>=UP_LONG and up2>=UP_LONG) else ('长上影' if up1>=UP_LONG else ('短上影' if up1>=UP_SHORT else '无上影'))} "
                   f"{'守低' if held else '破低'}")
    return sort_key, "; ".join(reasons)


def build_decision_strategy():
    os.makedirs(DST_DIR, exist_ok=True)
    dates = sorted(f for f in os.listdir(SRC_DIR) if f.isdigit())
    picked_days = 0
    skipped_days = 0
    total_candidates = 0
    reject_reasons = {}
    samples = []  # (date, code, name, key_tuple, reason)
    for d in dates:
        with open(os.path.join(SRC_DIR, d), "r", encoding="gbk", errors="ignore") as f:
            lines = [ln.rstrip("\n") for ln in f if ln.strip()]
        if not lines:
            open(os.path.join(DST_DIR, d), "w", encoding="utf-8").write("\n")
            skipped_days += 1
            continue
        feats = []  # (sort_key, line, reason, mcap)
        for ln in lines:
            cols = ln.split("|")
            if len(cols) < 11:
                continue
            code = cols[0]
            rec1 = GET_SZ200_1D_PREVIOUS(code, d, 1)
            rec2 = GET_SZ200_1D_PREVIOUS(code, d, 2)
            rec3 = GET_SZ200_1D_PREVIOUS(code, d, 3)
            if rec1 is None or rec2 is None:
                continue
            total_candidates += 1
            key, reason = decide(rec1, rec2, rec3)
            name = cols[1] if len(cols) > 1 else ""
            if key is None:
                reject_reasons[reason] = reject_reasons.get(reason, 0) + 1
                samples.append((d, code, name, None, reason))
                continue
            try:
                mcap = float(cols[2])
            except ValueError:
                mcap = 0.0
            feats.append((key, ln, reason, mcap))
            samples.append((d, code, name, key, reason))
        if not feats:
            open(os.path.join(DST_DIR, d), "w", encoding="utf-8").write("\n")
            skipped_days += 1
            continue
        # 市值约束：仅保留当日市值 ≥ 中位数 的候选（避免挑到小盘超买股，
        # 这是本宇宙最强因子——见 diagnose_cap.py）。再按排序键取最优。
        med = sorted(f[3] for f in feats)[len(feats) // 2]
        screened = [f for f in feats if f[3] >= med] or feats
        best = min(screened, key=lambda f: f[0])
        if best is None:
            open(os.path.join(DST_DIR, d), "w", encoding="utf-8").write("\n")
            skipped_days += 1
        else:
            with open(os.path.join(DST_DIR, d), "w", encoding="utf-8") as f:
                f.write(best[1] + "\n")
            picked_days += 1
    return picked_days, skipped_days, total_candidates, reject_reasons, samples


def monthly_and_total(strategy_name):
    res = Backtest.BACKTEST(strategy_name, sell_modes=["first", "5m"])
    text = res.get("first", "")
    p = os.path.join(_ROOT, "AIData", "Strategy", "RESULT", f"{strategy_name}.txt")
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
    import re
    _re_month = re.compile(r"^\s*(\d{6})\s*:\s*([-\d.]+)%")
    _re_total = re.compile(r"卖出方式:\s*(\w+).*?总收益率:\s*([-\d.]+)%", re.S)
    months = {}
    for line in text.split("\n"):
        mm = _re_month.search(line)
        if mm:
            months[mm.group(1)] = float(mm.group(2))
    totals = {}
    for m in re.finditer(r"卖出方式:\s*(\w+)\s*=+\s*.*?总收益率:\s*([-\d.]+)%", text, re.S):
        totals[m.group(1)] = float(m.group(2))
    return months, totals


def main():
    print("== 生成 TPO_DECISION 策略（确定性决策树，无打分）==")
    picked, skipped, total, rej, _ = build_decision_strategy()
    print(f"候选扫描: {total} 只 | 买入日: {picked} | 不买/跳过日: {skipped}\n")
    print("== 不买原因分布（决策树否决/及格未过）==")
    for r, c in sorted(rej.items(), key=lambda x: -x[1]):
        print(f"  {c:>4}  {r}")
    print()

    dm, dt = monthly_and_total("TPO_DECISION")
    bm, bt = monthly_and_total("TPO_M5")

    print("== 总收益率对比（first=取列表首只 / 5m=5分钟K线日内卖）==")
    print(f"  TPO_DECISION : first {dt.get('first','--')}% | 5m {dt.get('5m','--')}%")
    print(f"  TPO_M5(基线) : first {bt.get('first','--')}% | 5m {bt.get('5m','--')}%\n")

    print("== 月度收益对比（DECISION first vs M5 first）==")
    print(f"{'月份':<10}{'DECISION':>12}{'M5基线':>12}{'差值':>10}")
    for mo in sorted(set(dm) | set(bm)):
        a = dm.get(mo); b = bm.get(mo)
        def f(x):
            return f"{x:>10.2f}%" if x is not None else "       --"
        diff = (a - b) if (a is not None and b is not None) else None
        ds = f(a) if a is not None else "       --"
        print(f"{mo:<10}{ds:>12}{f(b):>12}{('' if diff is None else (f'{diff:>+9.2f}%')):>11}")


if __name__ == "__main__":
    main()
