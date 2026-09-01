"""
tick 回调框架（驱动 / 调度基础设施）

职责：
  · 提供 on_tick 的钩子，把每次 tick 派发给 tick_logic.handle_tick（具体买卖细节在 tick_logic.py）
  · 提供调度循环版本 on_schedule、阻塞卖出 run_sell_blocking、常驻 watch 模式

本文件不含任何买卖判断逻辑；所有「是否开盘 / 是否触止损 / 是否到尾盘」等条件判断都在
tick_logic.py 中。要改买卖节奏或触发条件，去 AITrading/tick_logic.py；要改下单执行，去 AITrading/commands.py。
"""

import datetime

from AITrading import config as C
from AITrading import commands as CMD
from AITrading import tick_logic as TL


def _parse_time(s):
    h, m, sec = (int(x) for x in s.split(":"))
    return datetime.time(h, m, sec)


def _in_window(now, start, end):
    return _parse_time(start) <= now <= _parse_time(end)


# ----------------------------------------------------------------------
# tick 回调（框架：仅派发，时机/条件判断在 tick_logic）
# ----------------------------------------------------------------------
def on_tick(xt_trader, tick):
    """标准 tick 回调：每次 tick 交给 tick_logic 处理各阶段买卖。"""
    TL.handle_tick(xt_trader, tick)


# ----------------------------------------------------------------------
# 调度循环版本（watch 模式主循环每秒调用）
# ----------------------------------------------------------------------
def on_schedule():
    now = datetime.datetime.now().time()
    try:
        xt, _ = CMD.Q.connect()
    except RuntimeError:
        xt = None
    # 卖出窗口内，逐持仓取快照交给 tick_logic（与 on_tick 同口径）
    if _in_window(now, C.SELL_STOP_TIME, C.SELL_CLOSE_TIME):
        for code in list(CMD._positions_state.keys()):
            TL.handle_tick(xt, CMD.Q.get_full_tick(code) or {})
    if _in_window(now, C.BUY_TIME, "15:00:00"):
        TL.handle_tick(xt, {})


def run_sell_blocking(xt_trader):
    """CLI 一次性卖出：阻塞监控到收盘或清仓（底层走 tick_logic 同一套细节）。"""
    import time
    C.log("sell", "进入卖出监控（阻塞至收盘或清仓）...")
    end = _parse_time(C.SELL_CLOSE_TIME)
    while datetime.datetime.now().time() <= end:
        for code in list(CMD._positions_state.keys()):
            TL.handle_tick(xt_trader, CMD.Q.get_full_tick(code) or {})
        if not CMD._positions_state:
            C.log("sell", "持仓已清空，退出卖出监控。")
            return
        time.sleep(3)
    C.log("sell", "已过收盘时间，退出卖出监控。")


def watch():
    """常驻 watch 模式：按时间窗口自动触发买卖。Ctrl+C 退出。"""
    try:
        CMD.Q.connect()
    except RuntimeError as e:
        C.log("watch", f"[模拟] 无法连接 QMT：{e}；仍以调度模式运行（命令走模拟分支）")
    C.log("watch", "已进入 watch 模式（按时间窗口触发买卖）。Ctrl+C 退出。")
    import time
    try:
        while True:
            on_schedule()
            time.sleep(1)
    except KeyboardInterrupt:
        C.log("watch", "已退出 watch 模式。")
