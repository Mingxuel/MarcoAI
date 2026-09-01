"""
交易触发条件判断（独立文件）

集中存放所有「前提判断」与「触发条件判断」：
  · 前提判断：当前处于哪个交易阶段（是否已开盘 / 是否到尾盘 / 是否临近收盘）
  · 触发条件判断：某持仓是否满足卖出信号（止损 / 涨停 / 止盈）

设计约定：
  · 这些函数只做判断、返回 bool，绝不调用下单逻辑（下单在 commands.py）。
  · tick 推送的行情快照为 dict，至少含 low/high/lastPrice 字段（见 qmt_api.get_full_tick）。
  · 前提判断基于当前时间；触发条件判断基于「某只股票 code + 当前 tick 快照」。
  · tick_logic.py 在 handle_tick 中调用本模块，按「前提 → 触发条件 → 执行」编排买卖动作。
"""

import datetime
import time

from AITrading import config as C
from AITrading import commands as CMD
from AITrading import qmt_api as Q
from AICode.MarcoAPI.Backtest import _limit_ratio, _limit_price


def _parse_time(s):
    """把 'HH:MM:SS' 字符串解析为 datetime.time，供时间比较使用。"""
    h, m, sec = (int(x) for x in s.split(":"))
    return datetime.time(h, m, sec)


def _now():
    """返回当前时间（本地时区），所有「前提判断」都以此为基准。"""
    return datetime.datetime.now().time()


# ----------------------------------------------------------------------
# 前提判断：当前处于哪个交易阶段（均以「时间区间」表达，而非单点阈值）
#   区间形式可避免「14:57 之后永远为 True」这类边界模糊问题。
# ----------------------------------------------------------------------
def in_trading_session():
    """前提判断：当前是否处于「盘中交易区间」。

    区间：[SELL_STOP_TIME, SELL_CLOSE_TIME) 即 [09:30, 14:55)。
    开盘后进入可交易时段，止损监控、涨停/止盈监控都以此为前提；
    到达 SELL_CLOSE_TIME(14:55) 即切出本区间、进入收盘强平阶段。
    """
    start = _parse_time(C.SELL_STOP_TIME)
    end = _parse_time(C.SELL_CLOSE_TIME)
    now = _now()
    return start <= now < end


def in_tail_session():
    """前提判断：当前是否处于「尾盘集合竞价区间」。

    区间：[BUY_TIME, 15:00:00) 即 [14:57, 15:00)。
    此时触发尾盘买入，对应 T-1 选股后在收盘集合竞价阶段挂单；
    用上界 15:00 收口，避免 15:00 之后仍误判为尾盘。
    """
    start = _parse_time(C.BUY_TIME)
    end = _parse_time("15:00:00")
    now = _now()
    return start <= now < end


def is_close_approach():
    """前提判断：当前是否已到达「收盘强平时间点」。

    单点触发：now >= SELL_CLOSE_TIME（默认 14:55）。
    与 in_trading_session 的上界衔接——盘中区间一结束即进入强平，
    此时若持仓仍未触发涨停/止损，则不再等待，直接市价清仓，避免隔夜风险。
    """
    return _now() >= _parse_time(C.SELL_CLOSE_TIME)


# ----------------------------------------------------------------------
# 触发条件判断：持仓是否满足某卖出信号
#   参数 code：股票代码（用于取前收、算涨停价）
#   参数 tick：当前行情快照 dict，含 low/high/lastPrice
#   返回：是否满足该卖出信号（bool）
# ----------------------------------------------------------------------
def hit_stop_loss(code, tick):
    """触发条件：该持仓是否已触发止损。

    逻辑：当前最新价相对持仓成本价的跌幅达到 config.STOP_LOSS（默认 -5%）即止损。
    用「最新价」判断——最新价跌破止损线就立刻卖掉，不等最低价反弹。
    成本价来自 commands 的持仓状态机（sync_positions 同步的真实持仓成本）。
    取不到成本价或最新价时返回 False（保守，不误杀）。
    """
    st = CMD._positions_state.get(code)
    last = tick.get("lastPrice")
    if not st or st["cost"] <= 0 or last is None:
        return False
    return (last - st["cost"]) / st["cost"] < C.STOP_LOSS


def is_limit_up(code, tick):
    """触发条件：该持仓是否涨停（止盈即涨停，不再设独立止盈线）。

    逻辑：当天最高价 >= 涨停价即视为涨停。涨停价由前收 × 涨跌幅限制算出
    （_limit_price(pre_close, _limit_ratio(code))，主板 10% / 创业板 20%）。
    涨停意味着当日盈利已锁定在最高位，按涨停价卖出。
    """
    pre_close = Q.get_pre_close(code)
    high = tick.get("high")
    if pre_close is None or high is None:
        return False
    limit_px = _limit_price(pre_close, _limit_ratio(code))
    return high >= limit_px


# ----------------------------------------------------------------------
# 收盘强平：阶段判断（当前处于三阶段中的第几阶段）与执行时机判断（节流/次数）
# ----------------------------------------------------------------------
def _secs_since(t):
    """当前时刻相对 t（datetime.time）已过去的秒数，当天内计算。"""
    today = datetime.date.today()
    return (datetime.datetime.combine(today, _now())
            - datetime.datetime.combine(today, t)).total_seconds()


def force_close_phase():
    """判断当前处于收盘强平第几阶段（1/2/3）；未到强平时间或已进集合竞价返回 None。

    强平窗口 = [SELL_CLOSE_TIME, BUY_TIME) = [14:55, 14:57)：
      阶段一 前 P1_SEC 秒         → 卖一价，每 RETRY_SEC 撤挂
      阶段二 接着 P2_SEC 秒       → 卖一价-P2_TICK，最多 P2_MAX 次
      阶段三 直到 BUY_TIME        → 买一价，每 tick 撤挂
    14:57 进入集合竞价后交易所不接受撤单，故返回 None 停止撤挂操作。
    """
    start = _parse_time(C.SELL_CLOSE_TIME)
    end = _parse_time(C.BUY_TIME)
    now = _now()
    if now < start or now >= end:
        return None
    secs = _secs_since(start)
    if secs < C.FORCE_CLOSE_P1_SEC:
        return 1
    if secs < C.FORCE_CLOSE_P1_SEC + C.FORCE_CLOSE_P2_SEC:
        return 2
    return 3


def force_close_due(code, phase):
    """判断该股本 tick 是否该执行强平撤挂。

    · 阶段一/二：距上次挂单 >= FORCE_CLOSE_RETRY_SEC 秒才重挂（阶段二另有次数上限）
    · 阶段三    ：每 tick 都撤挂买一价，直到集合竞价
    · 已清仓 / 已过集合竞价（phase 为 None）→ 不再操作
    """
    if phase is None:
        return False
    st = CMD._positions_state.get(code)
    if not st or st["target_vol"] <= 0:
        return False                        # 已清仓，无需再操作
    if phase == 3:
        return True                         # 每 tick 撤挂
    fs = CMD._force_close_state.get(code)
    if phase == 2 and fs and fs["p2_count"] >= C.FORCE_CLOSE_P2_MAX:
        return False                        # 阶段二次数用尽，等进入阶段三
    if fs and fs["last_ts"]:
        return (time.time() - fs["last_ts"]) >= C.FORCE_CLOSE_RETRY_SEC
    return True                             # 从未挂过 → 立即挂首单
