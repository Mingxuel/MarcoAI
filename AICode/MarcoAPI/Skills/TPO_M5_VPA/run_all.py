"""TPO_M5_VPA 全量验证（跑全 181 个 T-3 涨停日文件）

时间轴（已用数据验证：选定股 100% 落在文件当日涨停池 TOP{D}；杭电例子钉死）：
    文件日期 D = 涨停日(T-3) = 选股池日(T-2)（同日，D 当天触涨停）
    T-1      = D+1（买入日：尾盘买入）
    T-0      = D+2（卖出日）

口径
----
- 决策 VPA（选股，T-2 收盘前可知）：窗口以 T-2 结尾的 5 个交易日 (T-6..T-2)，仅用 T-2 收盘前
  已可知的量价（无未来数据；T-0 当日数据不参与选股）。
- 买入：T-1（D+2）收盘价。
- 实际收益（outcome）：复刻 config 的 TPO_M5 实盘卖出逻辑（与 Backtest._sell_price_5m 一致）：
  以 T-1 收盘为买入价，T-0 当日 5M K 线逐根判定——触及涨停→涨停价卖；收盘相对前收<止损(-5%)→
  该根收盘卖；否则第 47 根(14:55)收盘卖。收益=(卖价-前收)/前收（毛收益，未扣费）。
- 买入日封板(涨停)：T-1 收盘涨停，现实买不进，单独标注，不计入可执行收益。
- T-0 VPA：仅用 T-0 当日 5M K 线算盘中量价结构，用于 (B) 卖出优化。

输出
----
- AIData/VPA_ALL_RESULT.csv      ：逐 (D, code) 明细
- 控制台 + AIData/VPA_ALL_SUMMARY.txt ：按 verdict 分组的胜率/收益统计
"""
import os
import sys
import csv
import statistics
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from AICode.MarcoAPI.Skills.M5_DATA import m5_data as M
from AICode.MarcoAPI.Skills.TPO_M5_VPA import vpa

STOP_LOSS = -0.05  # 与 AITrading/config.py STOP_LOSS 一致

_BAR_CACHE = {}


def load(code):
    if code not in _BAR_CACHE:
        _BAR_CACHE[code] = M.load_5m(code)
    return _BAR_CACHE[code]


def _limit_ratio(code):
    pure = code.split(".")[0]
    if pure.startswith(("300", "301", "302", "688", "689")):
        return 0.20
    return 0.10


def _limit_price(pre_close, ratio):
    mid = (Decimal(str(pre_close)) * Decimal(str(1 + ratio))) \
        .quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    return float(mid.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def map_days(D):
    """时间轴（由用户例子钉死：杭电 file=0903, T-1=0904）：
       文件日 D = 涨停日(T-3) = 选股池日(T-2)（同日，数据确认 D 当天触涨停）
       买入日 T-1 = D+1（下一交易日尾盘）
       卖出日 T-0 = D+2
    返回 (T3, T2, T1, T0) = (D, D, D+1, D+2)；不足返回 None。"""
    alld = M.trading_dates()
    if D not in alld:
        return None
    i = alld.index(D)
    if i + 2 >= len(alld):
        return None
    return alld[i], alld[i], alld[i + 1], alld[i + 2]


def classify(net_pct, up_share):
    if net_pct > 0.5 and up_share >= 0.55:
        return "BULL"
    if net_pct > 0.5 and up_share < 0.45:
        return "UP_NOD"
    if net_pct < -0.5 and up_share < 0.45:
        return "BEAR"
    if net_pct < -0.5 and up_share >= 0.55:
        return "DOWN_EXH"
    return "SIDE"


def decision_vpa(code, t2):
    """选股信号：用 T-2（选股池日）收盘前可知量价，窗口 T-6..T-2（以 T-2 结尾）。"""
    dates = M.date_window(t2, 5, clamp=True)
    pts = vpa.build_zigzag(code, dates)
    v = vpa.volume_stats(code, dates)
    net = net_pct = slope = 0.0
    if len(pts) >= 2:
        p0, pN = pts[0], pts[-1]
        net = pN["price"] - p0["price"]
        net_pct = net / p0["price"] * 100 if p0["price"] else 0.0
        dx = pN["x"] - p0["x"]
        slope = (net / (dx / 5.0)) if dx else 0.0
    cat = classify(net_pct, v["up_vol_share"])
    slopes = [p.get("slope_per_bar", 0.0) for p in pts[1:]]
    trend = ""
    if len(slopes) >= 3:
        if slopes[0] < 0 and slopes[-1] > slopes[0]:
            trend = "REV_UP"
        elif slopes[0] > 0 and slopes[-1] < slopes[0]:
            trend = "REV_DN"
    return {
        "net_pct": net_pct, "up_share": v["up_vol_share"], "slope": slope,
        "cat": cat, "trend": trend, "n_bars": v["n"],
    }


def sell_day_vpa(code, t0):
    """仅用 T-0 当日 5M K 线算盘中量价结构（用于 T-0 卖出优化）。"""
    data = load(code)
    dd = t0[:4] + "-" + t0[4:6] + "-" + t0[6:]
    bars = data.get(dd, [])
    if not bars:
        return None
    up = [b for b in bars if b.close >= b.open]
    down = [b for b in bars if b.close < b.open]
    upv = sum(b.volume for b in up)
    tot = upv + sum(b.volume for b in down)
    share = upv / tot if tot else 0.0
    chg = (bars[-1].close - bars[0].close) / bars[0].close * 100 if bars[0].close else 0.0
    cat = classify(chg, share)
    lo = min(b.low for b in bars)
    hi = max(b.high for b in bars)
    return {
        "chg": chg, "up_share": share, "cat": cat, "n": len(bars),
        "lo_pct": (lo - bars[0].close) / bars[0].close * 100 if bars[0].close else 0.0,
        "hi_pct": (hi - bars[0].close) / bars[0].close * 100 if bars[0].close else 0.0,
    }


def actual_return_5m(code, t1, t0):
    """复刻实盘 T-0 卖出：买价=T-1(D+2)收盘，T-0(D+3)5M 逐根判定卖价。
    返回 dict{ret,hit_limit,hit_stop,sell,sell_idx,sell_time,reason,buy} 或 None。"""
    data = load(code)
    t1dd = t1[:4] + "-" + t1[4:6] + "-" + t1[6:]
    pb = data.get(t1dd, [])
    if not pb:
        return None
    pre_close = pb[-1].close           # T-1 收盘 = 买入价
    if pre_close <= 0:
        return None
    dd = t0[:4] + "-" + t0[4:6] + "-" + t0[6:]
    bars = data.get(dd, [])
    if not bars:
        return None
    limit_p = _limit_price(pre_close, _limit_ratio(code))
    n = min(len(bars), 47)
    hit_limit = hit_stop = False
    sell = sell_idx = sell_time = reason = None
    for i in range(n):
        b = bars[i]
        if b.high >= limit_p:
            sell = limit_p
            hit_limit = True
            sell_idx = i
            sell_time = b.time
            reason = "涨停"
            break
        if (b.close - pre_close) / pre_close < STOP_LOSS:
            sell = b.close
            hit_stop = True
            sell_idx = i
            sell_time = b.time
            reason = "止损"
            break
    if sell is None:
        last = bars[46] if len(bars) >= 47 else bars[-1]
        sell = last.close
        sell_idx = 46 if len(bars) >= 47 else len(bars) - 1
        sell_time = last.time
        reason = "收盘"
    ret = (sell - pre_close) / pre_close * 100
    return {"ret": ret, "hit_limit": hit_limit, "hit_stop": hit_stop,
            "sell": sell, "sell_idx": sell_idx, "sell_time": sell_time,
            "reason": reason, "buy": pre_close}


def buy_day_limit_up(code, t1):
    """T-1（D+2）收盘是否封板（涨停）。用该股票正确涨跌幅 + 当日真实昨收。"""
    data = load(code)
    t1dd = t1[:4] + "-" + t1[4:6] + "-" + t1[6:]
    pb = data.get(t1dd, [])
    if not pb:
        return None
    pre = pb[0].pre_close
    if pre <= 0:
        return None
    limit_p = _limit_price(pre, _limit_ratio(code))
    return pb[-1].close >= limit_p - 0.005


CAT_LABEL = {
    "BULL": "量价齐升(需求主导)",
    "UP_NOD": "价升量缩(无需求)",
    "BEAR": "价跌量增(供应主导)",
    "DOWN_EXH": "价跌量缩(供应枯竭)",
    "SIDE": "横盘(供需均衡)",
}


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    all_dates = M.list_target_dates()
    print(f"T-3 涨停日文件数: {len(all_dates)}")

    rows = []
    dec_groups = defaultdict(list)
    t0_groups = defaultdict(list)
    dec_trend_groups = defaultdict(list)
    cross = defaultdict(int)
    exec_dec_groups = defaultdict(list)
    miss = 0
    n_limit = 0
    n_total_pairs = 0

    for D in all_dates:
        m = map_days(D)
        if m is None:
            continue
        t3, t2, t1, t0 = m
        for code, name, mv in M.target_stocks(D):
            dv = decision_vpa(code, t2)
            tv = sell_day_vpa(code, t0)
            ar = actual_return_5m(code, t1, t0)
            lim = buy_day_limit_up(code, t1)
            if ar is None:
                miss += 1
                continue
            n_total_pairs += 1
            if lim:
                n_limit += 1
            ret, hit_limit, hit_stop = ar["ret"], ar["hit_limit"], ar["hit_stop"]
            dcat = dv["cat"] if dv else "NA"
            tcat = tv["cat"] if tv else "NA"
            dec_groups[dcat].append(ret)
            t0_groups[tcat].append(ret)
            if dv and dv["trend"]:
                dec_trend_groups[dv["trend"]].append(ret)
            if not lim:
                exec_dec_groups[dcat].append(ret)
            sign = "WIN" if ret > 0 else "LOSS"
            cross[(dcat, sign)] += 1
            rows.append({
                "D_T3": D, "t2_sel": t2, "t1_buy": t1, "t0_sell": t0,
                "code": code, "name": name, "mv": mv,
                "dec_cat": dcat,
                "dec_net_pct": f"{dv['net_pct']:.2f}" if dv else "",
                "dec_up_share": f"{dv['up_share']*100:.1f}" if dv else "",
                "dec_slope": f"{dv['slope']:.4f}" if dv else "",
                "dec_trend": dv["trend"] if dv else "",
                "buy_limit": int(bool(lim)),
                "t0_cat": tcat,
                "t0_chg": f"{tv['chg']:.2f}" if tv else "",
                "t0_up_share": f"{tv['up_share']*100:.1f}" if tv else "",
                "buy": f"{ar['buy']:.2f}",
                "sell_time": ar["sell_time"] or "",
                "sell": f"{ar['sell']:.2f}",
                "reason": ar["reason"] or "",
                "ret": f"{ret:.2f}", "hit_limit": int(hit_limit),
                "hit_stop": int(hit_stop),
            })

    out_csv = os.path.join(ROOT, "AIData", "VPA_ALL_RESULT.csv")
    fields = ["D_T3", "t2_sel", "t1_buy", "t0_sell", "code", "name", "mv", "dec_cat",
              "dec_net_pct", "dec_up_share", "dec_slope", "dec_trend", "buy_limit",
              "t0_cat", "t0_chg", "t0_up_share", "buy", "sell_time", "sell",
              "reason", "ret", "hit_limit", "hit_stop"]
    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    lines = []
    lines.append("=" * 70)
    lines.append(f"TPO_M5_VPA 全量验证  T-3文件数={len(all_dates)}  样本(股·日)={len(rows)}  缺数据={miss}")
    lines.append("  时间轴: D=涨停日=选股池日, T-1=D+1买入, T-0=D+2卖出")
    lines.append("=" * 70)

    def stat_block(title, groups):
        lines.append("")
        lines.append(f"【{title}】按 verdict 分组的 T-1→T-0 实际毛收益")
        lines.append(f"  {'verdict':<22}{'n':>5}{'胜率%':>8}{'均收益%':>9}{'中位%':>8}{'最佳%':>8}{'最差%':>8}")
        for cat in ["BULL", "UP_NOD", "BEAR", "DOWN_EXH", "SIDE", "NA"]:
            rs = groups.get(cat, [])
            if not rs:
                continue
            win = sum(1 for r in rs if r > 0)
            avg = statistics.mean(rs)
            med = statistics.median(rs)
            lines.append(f"  {CAT_LABEL.get(cat,cat):<20}{len(rs):>5}{win/len(rs)*100:>7.1f}{avg:>9.2f}{med:>8.2f}{max(rs):>8.2f}{min(rs):>8.2f}")

    stat_block("决策 VPA（T-2 选股信号）", dec_groups)
    stat_block("T-0 当日 VPA（T-0 卖出信号）", t0_groups)
    stat_block("决策末段斜率转折", dec_trend_groups)
    lines.append("")
    lines.append(f"【执行现实】T-1(D+2)收盘封板(买不进) = {n_limit}/{n_total_pairs} "
                 f"({n_limit/n_total_pairs*100:.1f}%)  |  可成交(未封板) = {n_total_pairs-n_limit}")
    stat_block("可成交子集 决策 VPA（剔除封板后）", exec_dec_groups)

    lines.append("")
    lines.append(f"【决策 verdict × 盈亏 交叉表】")
    lines.append(f"  {'verdict':<22}{'WIN':>7}{'LOSS':>7}{'胜率%':>8}")
    for cat in ["BULL", "UP_NOD", "BEAR", "DOWN_EXH", "SIDE"]:
        wn = cross.get((cat, "WIN"), 0)
        ls = cross.get((cat, "LOSS"), 0)
        tot = wn + ls
        if not tot:
            continue
        lines.append(f"  {CAT_LABEL.get(cat,cat):<20}{wn:>7}{ls:>7}{wn/tot*100:>7.1f}")

    allret = [float(r["ret"]) for r in rows]
    lines.append("")
    lines.append(f"【总体】样本={len(allret)}  总胜率={sum(1 for r in allret if r>0)/len(allret)*100:.1f}%  "
                 f"均收益={statistics.mean(allret):.2f}%  中位={statistics.median(allret):.2f}%")

    summary = "\n".join(lines)
    print(summary)
    out_txt = os.path.join(ROOT, "AIData", "VPA_ALL_SUMMARY.txt")
    with open(out_txt, "w", encoding="utf-8") as f:
        f.write(summary)
    print(f"\n明细 -> {out_csv}")
    print(f"汇总 -> {out_txt}")


if __name__ == "__main__":
    main()
