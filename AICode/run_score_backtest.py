"""按权重（BuyScore）从 TPO_M5 候选宇宙中选股，跑回测并输出月度收益对比。

数据源：AIData/Strategy/TPO_M5/{卖出日}（已是 TPO 硬过滤 + MA5 预测门槛后的候选宇宙）
产出 ：AIData/Strategy/TPO_SCORE/{卖出日}（每只候选重算 BuyScore，选 Top1，含"不买"门槛）
对比 ：复用 Backtest.BACKTEST 对 TPO_SCORE 与 TPO_M5 各卖出方式做回测，输出每月收益。

运行：cd e:/MarcoAI/AICode && python run_score_backtest.py
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # e:/MarcoAI
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from AICode.MarcoAPI.Update.SZ2001D import GET_SZ200_1D_PREVIOUS  # noqa: E402
from AICode.MarcoAPI import Backtest  # noqa: E402

SRC_DIR = os.path.join(_ROOT, "AIData", "Strategy", "TPO_M5")
DST_DIR = os.path.join(_ROOT, "AIData", "Strategy", "TPO_SCORE")

# 权重（合计 100）
W = {"seq": 15, "hl": 20, "shadow": 15, "ma": 20, "room": 15, "amp": 8, "vol": 7}
GATE_SCORE = 55.0        # BuyScore 门槛（低于则不买）
GATE_ROOM = 0.0          # 预测最高价需 > T-1 收盘（否则无博弈空间，不买）


def _clamp(x, lo=0.0, hi=100.0):
    return max(lo, min(hi, x))


def buy_score(rec1, rec2, rec3):
    """按 Daily.txt 的 7 类查看条件计算 BuyScore(0~100) 与各分项。
    rec1=T-1(买入决策日), rec2=T-2, rec3=T-3。"""
    # --- 形态序列 f_seq (15) ---
    n_yang = (rec3.is_red, rec2.is_red, rec1.is_red).count(True)  # type: ignore
    if rec1.is_red:  # 阳
        f_seq = 100 if n_yang == 3 else (85 if n_yang == 2 else 65)
    else:  # 阴（阳转阴=40，连阴=10）
        f_seq = 40 if rec2.is_red else 10

    # --- T-1 高低齐升齐降 f_hl (20) ---
    hu = rec1.high > rec2.high
    lu = rec1.low > rec2.low
    if hu and lu:
        f_hl = 100      # 齐升
    elif hu and not lu:
        f_hl = 50       # 高升低降
    elif (not hu) and lu:
        f_hl = 65       # 高降低升（支撑）
    else:
        f_hl = 15       # 齐降

    # --- 影线 f_shadow (15) ---
    body1 = abs(rec1.close - rec1.open) or (max(rec1.close, 1e-9) * 0.01)
    up1 = (rec1.high - max(rec1.open, rec1.close)) / body1
    dn1 = (min(rec1.open, rec1.close) - rec1.low) / body1
    body2 = abs(rec2.close - rec2.open) or (max(rec2.close, 1e-9) * 0.01)
    up2 = (rec2.high - max(rec2.open, rec2.close)) / body2
    f_shadow = 100.0
    if up1 >= 1.0:
        f_shadow -= 35
    elif up1 >= 0.3:
        f_shadow -= 15
    if up1 >= 1.0 and up2 >= 1.0:   # 双长上影
        f_shadow -= 30
    if dn1 >= 0.3:                  # 下影支撑小幅加成
        f_shadow += 5
    f_shadow = _clamp(f_shadow)

    # --- 均线 f_ma (20) ---
    f_ma = 60.0
    f_ma += 15 if rec1.close > rec1.ma20 else -15
    f_ma += 15 if rec1.close > rec1.ma60 else -15
    slope60 = rec1.ma60 - rec2.ma60
    f_ma += 10 if slope60 > 0 else -10          # MA60 坡度
    gap5 = (rec1.close - rec1.ma5) / rec1.ma5 if rec1.ma5 > 0 else 0
    if gap5 < 0.01:
        f_ma -= 20                              # 收盘价贴 MA5 太近
    elif gap5 < 0.03:
        f_ma -= 8
    f_ma = _clamp(f_ma)

    # --- 空间 f_room (15) ---
    pred_high = 2 * rec1.high - rec2.high        # 线性外推 T-0 最高价
    room = (pred_high - rec1.close) / rec1.close if rec1.close > 0 else 0
    if room >= 0.03:
        f_room = 100.0
    elif room > 0:
        f_room = room / 0.03 * 100.0
    else:
        f_room = 0.0

    # --- 振幅 f_amp (8) ---
    pre = rec1.pre_close if rec1.pre_close > 0 else rec1.close
    amp = (rec1.high - rec1.low) / pre if pre > 0 else 0
    if amp >= 0.05:
        f_amp = 100.0
    elif amp >= 0.02:
        f_amp = 70.0
    else:
        f_amp = 30.0

    # --- 量能 f_vol (7)（相对 T-3 涨停放量，缩量后量能是否过弱） ---
    rv = rec1.volume / rec3.volume if (rec3.volume and rec3.volume > 0) else 1.0
    if 0.3 <= rv <= 1.0:
        f_vol = 100.0
    elif rv < 0.3:
        f_vol = 50.0
    else:
        f_vol = 90.0

    score = (W["seq"] * f_seq + W["hl"] * f_hl + W["shadow"] * f_shadow +
             W["ma"] * f_ma + W["room"] * f_room + W["amp"] * f_amp +
             W["vol"] * f_vol) / 100.0
    comps = {"seq": round(f_seq, 1), "hl": round(f_hl, 1), "shadow": round(f_shadow, 1),
             "ma": round(f_ma, 1), "room": round(f_room, 1), "amp": round(f_amp, 1),
             "vol": round(f_vol, 1), "pred_high": round(pred_high, 3),
             "room_pct": round(room * 100, 2)}
    return score, comps


def build_score_strategy(dst_dir, use_gate=True):
    os.makedirs(dst_dir, exist_ok=True)
    dates = sorted(f for f in os.listdir(SRC_DIR) if f.isdigit())
    picked_days = 0
    skipped_days = 0
    total_candidates = 0
    samples = []  # (date, code, name, score, comps)
    for d in dates:
        with open(os.path.join(SRC_DIR, d), "r", encoding="gbk", errors="ignore") as f:
            lines = [ln.rstrip("\n") for ln in f if ln.strip()]
        if not lines:
            open(os.path.join(dst_dir, d), "w", encoding="utf-8").write("\n")
            skipped_days += 1
            continue
        best = None  # (score, line)
        for ln in lines:
            cols = ln.split("|")
            if len(cols) < 11:
                continue
            code = cols[0]
            rec1 = GET_SZ200_1D_PREVIOUS(code, d, 1)
            rec2 = GET_SZ200_1D_PREVIOUS(code, d, 2)
            rec3 = GET_SZ200_1D_PREVIOUS(code, d, 3)
            if rec1 is None or rec2 is None or rec3 is None:
                continue
            total_candidates += 1
            score, comps = buy_score(rec1, rec2, rec3)
            samples.append((d, code, cols[1] if len(cols) > 1 else "", score, comps))
            if not use_gate or (score >= GATE_SCORE and comps["room_pct"] > GATE_ROOM * 100):
                if best is None or score > best[0]:
                    best = (score, ln)
        if best is None:
            open(os.path.join(dst_dir, d), "w", encoding="utf-8").write("\n")
            skipped_days += 1
        else:
            with open(os.path.join(dst_dir, d), "w", encoding="utf-8") as f:
                f.write(best[1] + "\n")
            picked_days += 1
    return picked_days, skipped_days, total_candidates, samples


DST_DIR_NOGATE = os.path.join(_ROOT, "AIData", "Strategy", "TPO_SCORE_ALL")


def monthly_block(strategy_name):
    """复用 Backtest 的回测，抽取每月收益文本块。"""
    res = Backtest.BACKTEST(strategy_name, sell_modes=["first"])
    # BACKTEST 已写文件；从返回文本里取 first 模式的每月收益
    text = res.get("first", "")
    out = []
    grab = False
    for line in text.split("\n"):
        if line.startswith("--- 每月收益"):
            grab = True
        elif line.startswith("--- ") and grab and not line.startswith("--- 每月收益"):
            break
        if grab:
            out.append(line)
    return "\n".join(out)


def monthly_and_total(strategy_name):
    res = Backtest.BACKTEST(strategy_name, sell_modes=["first"])
    text = res.get("first", "")
    p = os.path.join(_ROOT, "AIData", "Strategy", "RESULT", f"{strategy_name}.txt")
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
    import re
    _re_month = re.compile(r"^\s*(\d{6})\s*:\s*([-\d.]+)%")
    _re_total = re.compile(r"总收益率:\s*([-\d.]+)%")
    m = {}
    for line in text.split("\n"):
        mm = _re_month.search(line)
        if mm:
            m[mm.group(1)] = float(mm.group(2))
    tt = _re_total.search(text)
    return m, (float(tt.group(1)) if tt else None)


def main():
    print("== 生成 TPO_SCORE 策略（按 BuyScore 权重选股，含不买门槛）==")
    picked, skipped, total, _ = build_score_strategy(DST_DIR, use_gate=True)
    print(f"候选扫描: {total} 只 | 买入日: {picked} | 不买日(门槛未过): {skipped}\n")

    print("== 生成 TPO_SCORE_ALL 变体（只按权重重排序，不跳过任何日）==")
    picked2, skipped2, _, _ = build_score_strategy(DST_DIR_NOGATE, use_gate=False)
    print(f"买入日: {picked2} | 不买日: {skipped2}\n")

    sm, st = monthly_and_total("TPO_SCORE")
    sam, sat = monthly_and_total("TPO_SCORE_ALL")
    bm, bt = monthly_and_total("TPO_M5")

    print("== 总收益率对比 ==")
    print(f"  TPO_SCORE(加权+不买门槛): {st:.2f}%" if st is not None else "  TPO_SCORE: --")
    print(f"  TPO_SCORE_ALL(加权+全交易): {sat:.2f}%" if sat is not None else "  TPO_SCORE_ALL: --")
    print(f"  TPO_M5(基线,市值优先)    : {bt:.2f}%" if bt is not None else "  TPO_M5: --")

    print("\n== 月度收益对比 ==")
    print(f"{'月份':<10}{'SCORE+门槛':>13}{'SCORE全交易':>13}{'M5基线':>12}")
    for mo in sorted(set(sm) | set(sam) | set(bm)):
        a = sm.get(mo); b = sam.get(mo); c = bm.get(mo)
        def f(x):
            return f"{x:>11.2f}%" if x is not None else "        --"
        print(f"{mo:<10}{f(a):>13}{f(b):>13}{f(c):>12}")


if __name__ == "__main__":
    main()
