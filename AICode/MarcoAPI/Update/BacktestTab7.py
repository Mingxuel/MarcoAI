"""TAB7 动量回踩策略 —— 独立回测脚本（不污染任何其它代码）。

设计:
  标的池: TAB7(首板涨停放量连阳股) 近 WINDOW 个交易日内出现过信号的票, 每只在其信号日后
          WINDOW 天内择机入场, 过期放弃。
  入场:   候选票某日 d 满足 (趋势MA_a>MA_b) 且 (收盘>=支撑MA) 且 (缩量收阳 或 放量站上支撑MA) -> d+1 开盘买入。
  仓位:   最多分 2 仓。第一止盈 +TP1 触及卖 50%(仓1), 余 50%(仓2) 转跟踪止盈。
  出场(仓2, 多日持股, 优先级):
          1) 硬止损: 盘中最低 <= 买入价*(1-SL)
          2) 跟踪止盈: 自最高点回撤 >= TRAIL
          3) 均线破位: 收盘 < 支撑MA
          4) 死叉强离场: 出场MA_a < 出场MA_b
          5) 量价背离: 创新高但缩量(量比<DV) 或 长上影(上影/振幅>SH)
          6) 时间止损: 持仓满 MAX_HOLD 日收盘离场
  策略变体: 通过 trend_a/trend_b(趋势背景), support(入场支撑与破位线), exit_a/exit_b(死叉对) 组合,
            MA 不拘泥 MA5, 含 MA20/MA30 等中长线回踩。

用法: 项目根目录 `python -m AICode.MarcoAPI.Update.BacktestTab7`
"""

import os
import sys
from collections import Counter, defaultdict

_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _root not in sys.path:
    sys.path.insert(0, _root)

from AICode.MarcoAPI.Update.SZ2001D import GET_SZ200_1D_AFTER, GET_SZ200_1D_ALL
from AICode.MarcoAPI.Update.Path import PATH_AIDATA_TOP_FIRST_VOL_SUN

# ---- 通用参数(策略未指定时使用的默认值) ----
WINDOW = 10          # 候选窗口: 信号日后 WINDOW 天内择机入场
MAX_HOLD_G = 10      # 默认最大持股天数(时间止损)
SL = 0.05            # 硬止损 -5%
TP1_G = 0.08         # 默认第一止盈目标 +8% (卖50%=仓1)
TRAIL_G = 0.05       # 默认跟踪止盈: 自高点回撤 -5% (仓2)
DV = 0.6             # 背离: 缩量新高量比阈值
SH = 0.5             # 背离: 长上影阈值(上影/振幅)

def _s(name, desc, ta, tb, sup, ea, eb, tp1=8, trail=5, max_hold=10):
    return {"name": name, "desc": desc, "trend_a": ta, "trend_b": tb,
            "support": sup, "exit_a": ea, "exit_b": eb,
            "tp1": tp1 / 100.0, "trail": trail / 100.0, "max_hold": max_hold}

# ---- 策略变体(各自独立, 仅改 MA 组合 / 止盈参数) ----
STRATEGIES = [
    # 标准止盈: 第一目标 +8%, 余仓跟踪 -5%, 持股 10 天
    _s("SUN_MA5",       "短线回踩: 趋势 MA5>MA10, 回踩 MA5, 破 MA5/MA5<MA10 离场", 5, 10, 5, 5, 10),
    _s("SUN_MA20",      "中线回踩: 趋势 MA20>MA60, 回踩 MA20, 破 MA20/MA20<MA60 离场", 20, 60, 20, 20, 60),
    _s("SUN_MA30",      "长线回踩: 趋势 MA30>MA60, 回踩 MA30, 破 MA30/MA30<MA60 离场", 30, 60, 30, 30, 60),
    _s("SUN_MA20x5",    "混合: 短线多头(MA5>MA10)下深回踩 MA20, 破 MA20/MA20<MA60 离场", 5, 10, 20, 20, 60),
    # 大止盈: 第一目标 +15%, 余仓跟踪 -8%(让利润奔跑), 持股放宽到 15 天
    _s("SUN_MA5_BIG",    "[大止盈] 同 MA5, TP1+15%/跟踪-8%/持股15天", 5, 10, 5, 5, 10, 15, 8, 15),
    _s("SUN_MA20_BIG",   "[大止盈] 同 MA20, TP1+15%/跟踪-8%/持股15天", 20, 60, 20, 20, 60, 15, 8, 15),
    _s("SUN_MA30_BIG",   "[大止盈] 同 MA30, TP1+15%/跟踪-8%/持股15天", 30, 60, 30, 30, 60, 15, 8, 15),
    _s("SUN_MA20x5_BIG", "[大止盈] 同 MA20x5, TP1+15%/跟踪-8%/持股15天", 5, 10, 20, 20, 60, 15, 8, 15),
    # 宽尾仓: 仍 +8% 锁 50%, 但余仓跟踪放宽到 -8% / 持股 15 天(只让赢家多跑)
    _s("SUN_MA5_RUN",    "[宽尾仓] 同 MA5, 锁8%后余仓跟踪-8%/持股15天", 5, 10, 5, 5, 10, 8, 8, 15),
    _s("SUN_MA20_RUN",   "[宽尾仓] 同 MA20, 锁8%后余仓跟踪-8%/持股15天", 20, 60, 20, 20, 60, 8, 8, 15),
    _s("SUN_MA20x5_RUN", "[宽尾仓] 同 MA20x5, 锁8%后余仓跟踪-8%/持股15天", 5, 10, 20, 20, 60, 8, 8, 15),
]


def _ma(r, n):
    return getattr(r, "ma%d" % n)


def _divergence(h, prev_vol, new_high):
    if new_high and prev_vol > 0 and (h.volume / prev_vol) < DV:
        return True
    rng = h.high - h.low
    if rng > 1e-9 and (h.high - max(h.open, h.close)) / rng > SH:
        return True
    return False


def _entry_trigger(r, p):
    ma_ta = _ma(r, p["trend_a"])
    ma_tb = _ma(r, p["trend_b"])
    ma_s = _ma(r, p["support"])
    if ma_ta <= 0 or ma_tb <= 0 or ma_s <= 0:
        return False
    if not (ma_ta > ma_tb):
        return False
    if r.close < ma_s:
        return False
    if r.is_volume_down == 1 and r.is_red == 1:
        return True
    if r.is_volume_up == 1 and r.close > ma_s:
        return True
    return False


def _simulate_trade(code, buy_date, buy_price, p):
    ma_s = p["support"]
    ma_ea = p["exit_a"]
    ma_eb = p["exit_b"]
    TP1 = p.get("tp1", TP1_G)
    TRAIL = p.get("trail", TRAIL_G)
    MAXH = p.get("max_hold", MAX_HOLD_G)
    peak = buy_price
    tp_hit = False
    remaining = 1.0
    exit_price = None
    reason = None
    holding = []
    for m in range(MAXH):
        h = GET_SZ200_1D_AFTER(code, buy_date, m)
        if h is None:
            break
        holding.append(h)
        peak_before = peak
        peak = max(peak, h.high)

        if h.low <= buy_price * (1 - SL):          # 1) 硬止损(盘中)
            exit_price = buy_price * (1 - SL)
            reason = "hard_stop"
            break

        if (not tp_hit) and h.high >= buy_price * (1 + TP1):  # 2) 第一止盈(仓1卖50%)
            tp_hit = True
            remaining = 0.5

        prev_vol = holding[m - 1].volume if m > 0 else h.volume
        new_high = h.high > peak_before
        diverge = _divergence(h, prev_vol, new_high)
        s_now = _ma(h, ma_s)
        ea_now = _ma(h, ma_ea)
        eb_now = _ma(h, ma_eb)

        if tp_hit:                                  # 仓2 跟踪/均线离场
            if (peak - h.close) / peak >= TRAIL:
                reason, exit_price = "trailing", h.close
                break
            if s_now > 0 and h.close < s_now:
                reason, exit_price = "ma_break", h.close
                break
            if eb_now > 0 and ea_now < eb_now:
                reason, exit_price = "death_cross", h.close
                break
            if diverge:
                reason, exit_price = "divergence", h.close
                break
        else:                                       # 未触TP1: 全部按均线/背离离场
            if s_now > 0 and h.close < s_now:
                reason, exit_price = "ma_break", h.close
                break
            if eb_now > 0 and ea_now < eb_now:
                reason, exit_price = "death_cross", h.close
                break
            if diverge:
                reason, exit_price = "divergence", h.close
                break

        if m == MAXH - 1 and exit_price is None:
            reason, exit_price = "time_stop", h.close

    if exit_price is None:
        if holding:
            reason, exit_price = (reason or "eod"), holding[-1].close
        else:
            return None

    if tp_hit:
        ret = 0.5 * TP1 + remaining * ((exit_price - buy_price) / buy_price)
    else:
        ret = (exit_price - buy_price) / buy_price
    return ret, len(holding), reason, buy_date[:6]


def backtest_strategy(p):
    base = PATH_AIDATA_TOP_FIRST_VOL_SUN()
    dates = sorted(d for d in os.listdir(base) if d.isdigit())
    trades = []
    skipped = 0
    for t2 in dates:
        with open(os.path.join(base, t2), "r", encoding="utf-8") as f:
            codes = [l.strip() for l in f if l.strip()]
        for code in codes:
            entered = False
            for k in range(1, WINDOW + 1):
                d = GET_SZ200_1D_AFTER(code, t2, k)
                if d is None:
                    break
                if _entry_trigger(d, p):
                    buy = GET_SZ200_1D_AFTER(code, d.date, 1)
                    if buy is None or buy.open <= 0:
                        break
                    res = _simulate_trade(code, buy.date, buy.open, p)
                    if res is not None:
                        trades.append(res)
                    entered = True
                    break
            if not entered:
                skipped += 1
    return trades, skipped


def report(p, trades, skipped):
    n = len(trades)
    print("=" * 64)
    print("策略 %s  | %s" % (p["name"], p["desc"]))
    if n == 0:
        print("  无成交(数据不足或参数过严). skipped=", skipped)
        return
    rets = [t[0] for t in trades]
    days = [t[1] for t in trades]
    reasons = Counter(t[2] for t in trades)
    wins = sum(1 for r in rets if r > 0)
    avg = sum(rets) / n
    med = sorted(rets)[n // 2]
    capital = 1.0
    for r in rets:
        capital *= (1 + r)
    print("  成交 %d 笔 | 未触发入场 %d | 胜率 %.1f%%" % (n, skipped, wins / n * 100))
    print("  平均每笔 %.2f%% | 中位 %.2f%% | 平均持股 %.1f 天(最短%d 最长%d)"
          % (avg * 100, med * 100, sum(days) / n, min(days), max(days)))
    print("  等权复利(粗略,忽略并发) %.2f%%" % ((capital - 1) * 100))
    print("  离场原因: " + ", ".join("%s %d(%.0f%%)" % (k, v, v / n * 100) for k, v in reasons.most_common()))

    # 每月收益(按买入月分组, 统计该月开仓的每笔平均收益与胜率)
    mret = defaultdict(list)
    for r, _d, _rs, bm in trades:
        mret[bm].append(r)
    print("  --- 每月收益(买入月) ---")
    print("  月份      笔数   月均收益   胜率")
    for m in sorted(mret):
        rs = mret[m]
        w = sum(1 for x in rs if x > 0)
        print("  %s   %4d   %+6.2f%%   %.0f%%" % (m, len(rs), sum(rs) / len(rs) * 100, w / len(rs) * 100))
    print("=" * 64)


def run_all():
    GET_SZ200_1D_ALL()  # 预热全量缓存
    for p in STRATEGIES:
        trades, skipped = backtest_strategy(p)
        report(p, trades, skipped)


if __name__ == "__main__":
    run_all()
