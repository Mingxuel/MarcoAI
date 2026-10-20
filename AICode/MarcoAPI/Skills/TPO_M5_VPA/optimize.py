"""TPO_M5 两类优化验证（基于全量 504 样本）

(A) T-0 卖出优化：当前 -5% 止损以「前收」为基准，在「开盘跳空低开」时于开盘即触发，
    且当天随后收回 → 止损鞭鞘（如 20260930 万科A/滨江集团 两笔 -10%/-9%）。
    实测这两笔是开盘即低于止损线（跳空低开），且触发根成交量反而最大（开盘放量），
    故「量能过滤」无效；正确修法是把止损基准改为 min(前收, 开盘价)（跳空不单独止损，
    只在开盘价再跌 5% 才止损）。本脚本回测多种卖出变体对比。

(B) T-1 选股优化：候选池 = TOP/{t-1}（T-1 当日涨停股，已被实盘选股证明是其超集）。
    对池中每只算「决策 VPA(T-5..T-1)」与「T-1买→T-0卖 实际收益」，验证：
      - VPA 在宽候选池里能否区分盈亏（BULL vs BEAR 等）；
      - 实盘实际选中子集 vs 「按 VPA 排名选同数」的反事实，谁收益更高。

用法: python optimize.py
"""
import os
import sys
import statistics
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from AICode.MarcoAPI.Skills.TPO_M5_VPA.run_all import (
    load, prev_trading_date, classify, decision_vpa, t0_vpa,
    actual_return_5m, _limit_ratio, _limit_price, STOP_LOSS, CAT_LABEL,
)
from AICode.MarcoAPI.Skills.M5_DATA import m5_data as M

TOP_DIR = os.path.join(ROOT, "AIData", "TOP")
M5SEL_DIR = os.path.join(ROOT, "AIData", "TARGET", "TPO_M5")
VOL_MULT = 1.0  # 放量确认倍数（仅 openref_vol 用）


def t1_at_limit_up(code, t0):
    """T-1 收盘是否已是涨停 → 此时 T-1 尾盘买不进去，属不可成交样本。"""
    data = load(code)
    dd = M.trading_dates()
    if t0 not in dd or dd.index(t0) < 2:
        return False
    pd = dd[dd.index(t0) - 1]
    t2 = dd[dd.index(t0) - 2]
    pb = data.get(pd[:4] + "-" + pd[4:6] + "-" + pd[6:])
    p2b = data.get(t2[:4] + "-" + t2[4:6] + "-" + t2[6:])
    if not pb or not p2b:
        return False
    close_t1 = pb[-1].close
    pre_t1 = p2b[-1].close
    lim = _limit_price(pre_t1, _limit_ratio(code))
    return close_t1 >= lim - 1e-6


def _bars_t0(code, t0):
    data = load(code)
    dd = t0[:4] + "-" + t0[4:6] + "-" + t0[6:]
    return data.get(dd, [])


def _pre_close(code, t0):
    data = load(code)
    pd = prev_trading_date(t0)
    if pd is None:
        return None
    pb = data.get(pd[:4] + "-" + pd[4:6] + "-" + pd[6:], [])
    if not pb:
        return None
    return pb[-1].close


def sell_variant(code, t0, mode):
    """返回 (毛收益%, hit_limit, hit_stop, reason)。mode:
       baseline  : 前收基准止损（现有）
       openref   : 止损基准=min(前收,开盘)，量能盲
       openref_vol: openref + 破位根需放量(>=日均)确认
       nostop    : 无盘中止损，仅涨停捕获+14:55兜底
    """
    pre = _pre_close(code, t0)
    bars = _bars_t0(code, t0)
    if pre is None or not bars:
        return None
    open0 = bars[0].open
    limit_p = _limit_price(pre, _limit_ratio(code))
    ref = pre if mode == "baseline" else (min(pre, open0) if mode in ("openref", "openref_vol") else None)
    vols = [b.volume for b in bars[:47]]
    avgv = statistics.mean(vols) if vols else 0.0
    n = min(len(bars), 47)
    for i in range(n):
        b = bars[i]
        if b.high >= limit_p:
            return ((limit_p - pre) / pre * 100, True, False, "LIMIT")
        if mode != "nostop":
            if (b.close - ref) / ref < STOP_LOSS:
                if mode == "openref_vol" and b.volume < VOL_MULT * avgv:
                    continue
                return ((b.close - pre) / pre * 100, False, True, "STOP")
    last = bars[46] if len(bars) >= 47 else bars[-1]
    return ((last.close - pre) / pre * 100, False, False, "EOD")


def stat_line(rs):
    if not rs:
        return "  (无样本)"
    win = sum(1 for r in rs if r > 0)
    return (f"  n={len(rs):>4} 胜率={win/len(rs)*100:5.1f}% 均收益={statistics.mean(rs):6.2f}% "
            f"中位={statistics.median(rs):6.2f}% 最差={min(rs):6.2f}%")


def partA_sell():
    print("=" * 72)
    print("【A】T-0 卖出变体回测（全量 504 样本，T-1买→T-0卖）")
    print("=" * 72)
    dates = [f for f in os.listdir(M5SEL_DIR)]
    modes = ["baseline", "openref", "openref_vol", "nostop"]
    agg = {m: [] for m in modes}
    loss_detail = {m: [] for m in modes}
    excluded = 0
    for t0 in dates:
        for line in open(os.path.join(M5SEL_DIR, t0), encoding="utf-8", errors="ignore"):
            line = line.strip()
            if not line:
                continue
            code = line.split("|")[0].strip()
            if t1_at_limit_up(code, t0):   # T-1 已涨停 → 买不进去，剔除
                excluded += 1
                continue
            for m in modes:
                r = sell_variant(code, t0, m)
                if r is None:
                    continue
                ret, hl, hs, _ = r
                agg[m].append(ret)
                if ret <= 0:
                    loss_detail[m].append((t0, code, ret))
    print(f"（已剔除 T-1 涨停不可买样本 {excluded} 个；可执行样本 {len(agg['baseline'])} 个）")
    for m in modes:
        rs = agg[m]
        print(f"\n模式 {m}:")
        print(stat_line(rs))
        losses = loss_detail[m]
        print(f"  亏损数={len(losses)} 明细(前8): " +
              ", ".join(f"{t}/{c}{r:.1f}" for t, c, r in losses[:8]))
    # 重点看两笔鞭鞘在 openref 下是否消除
    print("\n== 两笔鞭鞘(20260930 000002.SZ / 002244.SZ) 各模式收益 ==")
    for code in ("000002.SZ", "002244.SZ"):
        row = []
        for m in modes:
            r = sell_variant(code, "20260930", m)
            row.append(f"{m}={r[0]:.2f}%" if r else f"{m}=NA")
        print(f"  {code}: " + "  ".join(row))


def partB_selection():
    print("\n" + "=" * 72)
    print("【B】T-1 选股：VPA 在宽候选池(TOP/{t-1})中的区分力")
    print("=" * 72)
    from AICode.MarcoAPI.Skills.M5_DATA import m5_data as M
    dates = M.list_target_dates()
    # 候选池按 VPA 类别分布（全候选池）
    pool_by_cat = defaultdict(list)      # dec_cat -> [ret]
    pool_by_cat_win = defaultdict(lambda: [0, 0])  # cat -> [win,total]
    actual_sel = []                      # 实盘选中且可成交的收益
    counter_vpa = []                     # 按 VPA 排名选同数 的收益
    counter_rand = []                    # 随机选同数（基线对照）
    total_cand = 0
    excluded_cand = 0
    import random
    random.seed(0)

    for t0 in dates:
        pd = prev_trading_date(t0)
        if pd is None or not os.path.exists(os.path.join(TOP_DIR, pd)):
            continue
        cand = [l.strip() for l in open(os.path.join(TOP_DIR, pd), encoding="utf-8", errors="ignore") if l.strip()]
        if not cand:
            continue
        sel = set(l.split("|")[0].strip() for l in open(os.path.join(M5SEL_DIR, t0), encoding="utf-8", errors="ignore") if l.strip())
        scored = []
        k_buyable = 0
        for code in cand:
            total_cand += 1
            if t1_at_limit_up(code, t0):   # T-1 已涨停 → 买不进去，剔除候选
                excluded_cand += 1
                continue
            dv = decision_vpa(code, t0)
            ar = actual_return_5m(code, t0)
            if ar is None:
                continue
            ret = ar[0]
            cat = dv["cat"] if dv else "NA"
            net = dv["net_pct"] if dv else 0.0
            pool_by_cat[cat].append(ret)
            pool_by_cat_win[cat][1] += 1
            if ret > 0:
                pool_by_cat_win[cat][0] += 1
            # 仅用决策时可知量: VPA类别 + 窗口净涨跌(net); 绝不用未来收益
            scored.append((cat, net, ret, code))
            if code in sel:
                actual_sel.append(ret)
                k_buyable += 1
        if not scored:
            continue
        # 反事实：按「决策时可用量」排序选 K=实际可成交选中数（无前视）
        K = k_buyable
        if K == 0:
            continue
        prio = {"BULL": 0, "SIDE": 1, "UP_NOD": 2, "DOWN_EXH": 3, "BEAR": 4, "NA": 5}
        scored.sort(key=lambda x: (prio.get(x[0], 9), -x[1]))
        topk = scored[:K]
        counter_vpa.extend([r for _, _, r, _ in topk])
        # 随机对照
        random.shuffle(scored)
        counter_rand.extend([r for _, _, r, _ in scored[:K]])
    print(f"（候选池共 {total_cand} 只，剔除 T-1 涨停不可买 {excluded_cand} 只（{(excluded_cand/total_cand*100):.1f}%））")

    print("\n候选池全样本（按决策 VPA 类别）T-1→T-0 收益:")
    for cat in ["BULL", "UP_NOD", "BEAR", "DOWN_EXH", "SIDE", "NA"]:
        rs = pool_by_cat.get(cat, [])
        w = pool_by_cat_win.get(cat, [0, 0])
        if not rs:
            continue
        print(f"  {CAT_LABEL.get(cat,cat):<20} n={len(rs):>4} 胜率={w[0]/w[1]*100:5.1f}% 均收益={statistics.mean(rs):6.2f}% 中位={statistics.median(rs):6.2f}%")
    print("\n  >> 实盘实际选中子集:")
    print(stat_line(actual_sel))
    print("  >> 反事实: 按 VPA 优先级选同数:")
    print(stat_line(counter_vpa))
    print("  >> 反事实: 随机选同数(对照):")
    print(stat_line(counter_rand))


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    partA_sell()
    partB_selection()
