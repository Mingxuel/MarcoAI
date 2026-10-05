"""临时策略回测(独立, 不污染任何其它代码/数据)。

池: TAB6 首板涨停放量股(TOP_FIRST_VOL)。
信号(在 T-2 信号日起 5 日内任一日 d 出现):
  - 长下影线: 下影线/区间 >= LONG_LOWER_RATIO 且 下影线/收盘 >= MIN_LOWER_PCT
  - 下影线刺穿 MA5 或 MA10: 当日最低 < MA5 或 < MA10
  - 小实体: |收盘-开盘|/开盘 <= BODY_RATIO (2%)
  - 短上影/无上影: 上影线/区间 <= SHORT_UPPER_RATIO
交易:
  - 信号日 d 收盘买入, 次日(d+1)收盘卖出(隔夜 1 日仓)
  - 每日最多 1 只; 同日多只符合条件者取流通市值最高者
输出: 胜率 + 每月收益(按买入月分组的平均每笔收益与胜率)。

用法: python -m AICode.MarcoAPI.Update.BacktestTab6_LowerShadow
"""

import os
import sys
from collections import Counter, defaultdict

_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _root not in sys.path:
    sys.path.insert(0, _root)

from AICode.MarcoAPI.Update.SZ2001D import GET_SZ200_1D_AFTER, GET_SZ200_1D_ALL
from AICode.MarcoAPI.Update.StockCodes import GET_STOCK_INFO
from AICode.MarcoAPI.Update.Path import PATH_AIDATA_TOP_FIRST_VOL

# ---- 参数 ----
WINDOW = 5              # 从 T-2 起 5 日内
START_OFFSET = 0        # 0=含 T-2 当日; 若想只看其后, 改 1
LONG_LOWER_RATIO = 0.5  # 下影线占区间比例下限
MIN_LOWER_PCT = 0.01    # 下影线绝对值下限(占收盘价), 过滤无效小针
BODY_RATIO = 0.02       # 实体占开盘价上限(2%)
SHORT_UPPER_RATIO = 0.15  # 上影线占区间比例上限


def _signal(d):
    hi, lo, o, c = d.high, d.low, d.open, d.close
    rng = hi - lo
    if rng <= 0 or o <= 0 or c <= 0:
        return False
    lower_sh = min(o, c) - lo
    upper_sh = hi - max(o, c)
    body = abs(c - o)
    if lower_sh / rng < LONG_LOWER_RATIO:
        return False
    if lower_sh / c < MIN_LOWER_PCT:
        return False
    if not (lo < d.ma5 or lo < d.ma10):          # 下影刺穿 MA5 或 MA10
        return False
    if body / o > BODY_RATIO:                    # 实体在 2% 内
        return False
    if upper_sh / rng > SHORT_UPPER_RATIO:       # 短上影/无上影
        return False
    return True


def _cap(code, price):
    info = GET_STOCK_INFO(code)
    if info is None or len(info) < 2 or info[1] <= 0:
        return 0.0
    return float(info[1]) * price


def main():
    GET_SZ200_1D_ALL()
    base = PATH_AIDATA_TOP_FIRST_VOL()
    dates = sorted(d for d in os.listdir(base) if d.isdigit())
    # buy_date -> 候选(保留市值最高): {date: (code, ret, cap)}
    picks = {}
    scanned = 0
    for t2 in dates:
        with open(os.path.join(base, t2), "r", encoding="utf-8") as f:
            codes = [l.strip() for l in f if l.strip()]
        for code in codes:
            for k in range(START_OFFSET, START_OFFSET + WINDOW):
                d = GET_SZ200_1D_AFTER(code, t2, k)
                if d is None:
                    break
                scanned += 1
                if not _signal(d):
                    continue
                nxt = GET_SZ200_1D_AFTER(code, d.date, 1)
                if nxt is None or nxt.close <= 0 or d.close <= 0:
                    break
                ret = (nxt.close - d.close) / d.close
                cap = _cap(code, d.close)
                cur = picks.get(d.date)
                if cur is None or cap > cur[2]:
                    picks[d.date] = (code, ret, cap)
                break  # 该 code 在窗口内取首个信号日即可

    trades = list(picks.values())
    n = len(trades)
    print("=" * 60)
    print("TAB6 长下影临时策略 (T-2 起5日, 收盘买/次日收盘卖, 每日1只取市值最高)")
    print("  扫描 %d 候选日次 | 实际成交 %d 日(每日≤1只)" % (scanned, n))
    if n == 0:
        print("  无成交。")
        return
    rets = [t[1] for t in trades]
    wins = sum(1 for r in rets if r > 0)
    avg = sum(rets) / n
    win_rets = [r for r in rets if r > 0]
    lose_rets = [r for r in rets if r <= 0]
    avg_win = sum(win_rets) / len(win_rets) if win_rets else 0
    avg_lose = sum(lose_rets) / len(lose_rets) if lose_rets else 0
    print("  胜率 %.1f%% | 平均每笔 %.2f%% | 平均盈 %.2f%% / 平均亏 %.2f%%"
          % (wins / n * 100, avg * 100, avg_win * 100, avg_lose * 100))
    print("  盈亏比(均盈/均亏) %.2f" % (avg_win / -avg_lose if avg_lose < 0 else 0))

    mret = defaultdict(list)  # 月 -> [(买入日, 收益)]
    for date, (code, ret, cap) in picks.items():
        mret[date[:6]].append((date, ret))
    print("  --- 每月收益(买入月, 满仓滚动复利) ---")
    print("  月份      笔数   整月收益   胜率")
    for m in sorted(mret):
        items = sorted(mret[m])
        rs = [r for _, r in items]
        eq = 1.0
        for r in rs:
            eq *= (1 + r)
        w = sum(1 for x in rs if x > 0)
        print("  %s   %4d   %+6.2f%%   %.0f%%" % (m, len(rs), (eq - 1) * 100, w / len(rs) * 100))
    print("=" * 60)


if __name__ == "__main__":
    main()
