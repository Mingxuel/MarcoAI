"""
tick 回调框架（驱动 / 调度基础设施）

职责：
  · 提供 on_tick 的钩子，把每次 tick 派发给 tick_logic.handle_tick（具体买卖细节在 tick_logic.py）
  · 提供调度循环版本 on_schedule、阻塞卖出 run_sell_blocking、常驻 watch 模式
  · 维持「单票订阅」：一次只订阅一只票（当前持仓股），换票自动退订旧票

miniqmt 实战约束（本文件的核心设计依据）：
  · 订阅多只票时，回调会「分成好几组」返回，一次回调未必包含全部股票；
  · tick 偶发丢失，且回调报文字段可能不全。
  对策：只订阅一只票 + 回调不解析报文（只当心跳）+ 判断数据一律走 API 现取。

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
# 单票订阅（miniqmt 实战约束：一次只盯一只票）
#
# miniQMT 的两个坑：
#   1) 订阅多只票时，一次回调往往「分成好几组」返回，同一次回调未必包含全部股票；
#   2) tick 偶发丢失，且回调报文字段可能不全。
# 对策：始终只订阅一只票（当前持仓股，本策略单股全仓故最多一只），
#       回调只当「心跳」使用，不解析报文，数据一律走 API 现取，保证完整一致。
# ----------------------------------------------------------------------
_subscribed_code = None


def current_watch_code():
    """当前唯一需要盯的票：持仓中的第一只（本策略单股全仓，故最多一只）；无持仓返回 None。"""
    codes = list(CMD._positions_state.keys())
    return codes[0] if codes else None


def subscribe_single(xt_trader, code):
    """只订阅一只票：换票先退订旧的再订新的，同票不重复订阅；code 为 None 则只退订。

    订阅失败/未安装 xtquant 仅告警，不影响主循环（watch 另有每秒调度兜底）。
    """
    global _subscribed_code
    if code == _subscribed_code:
        return
    try:
        from xtquant import xtdata
    except Exception as e:
        C.log("watch", f"[订阅] 未加载 xtquant，跳过订阅：{e}")
        return
    if _subscribed_code:
        try:
            xtdata.unsubscribe_quote(_subscribed_code, period="tick")
            C.log("watch", f"[订阅] 已退订 {_subscribed_code}")
        except Exception as e:
            C.log("watch", f"[订阅] 退订 {_subscribed_code} 失败：{e}")
        _subscribed_code = None
    if code:
        if C.QMT_USERDATA_PATH:
            try:
                xtdata.connect(config_path=C.QMT_USERDATA_PATH)
            except Exception:
                pass
        try:
            xtdata.subscribe_quote(code, period="tick", callback=on_tick_datas)
            _subscribed_code = code
            C.log("watch", f"[订阅] 只订阅单只票 {code}（多票回调会分批返回且易丢 tick）")
        except Exception as e:
            C.log("watch", f"[订阅] 订阅 {code} 失败：{e}")


def on_tick_datas(datas):
    """xtquant subscribe_quote 的标准回调（签名 callback(datas)）——只用做心跳。

    不解析 datas：多票会分组返回、tick 会丢、报文字段可能不全。
    收到即按「当前唯一盯的票」用 API 现取完整行情，再交给 tick_logic。
    """
    on_tick(CMD.Q.current_trader(), datas)


# ----------------------------------------------------------------------
# tick 回调（框架：仅派发 + 现取数据，时机/条件判断在 tick_logic）
# ----------------------------------------------------------------------
def on_tick(xt_trader, tick):
    """tick 回调：丢弃回调报文，按当前盯的票用 API 现取完整行情后再派发。

    tick 入参仅用于兼容旧签名与定位代码（可能为空/缺字段，不可直接用于判断）；
    真实判断数据来自 CMD.Q.get_full_tick 的 API 现取结果，确保与订阅分组/丢 tick 无关。
    """
    code = current_watch_code()
    if code is None:
        return                                  # 无持仓（如已清仓）→ 本次回调无事可做
    snapshot = CMD.Q.get_full_tick(code) or {}  # API 现取完整快照（open/high/low/lastPrice/ask1/bid1）
    TL.handle_tick(xt_trader, snapshot)


# ----------------------------------------------------------------------
# 调度循环版本（watch 模式主循环每秒调用）
# ----------------------------------------------------------------------
def on_schedule():
    now = datetime.datetime.now().time()
    try:
        xt, _ = CMD.Q.connect()
    except RuntimeError:
        xt = None
    # 维持单票订阅：tick 会丢，每秒调度兜底；同时按最新持仓换订（清仓后退订）
    subscribe_single(xt, current_watch_code())
    # 卖出窗口内，逐持仓取快照交给 tick_logic（与 on_tick 同口径：API 现取，不用回调报文）
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
        subscribe_single(xt_trader, current_watch_code())   # 维持单票订阅（清仓后自动退订）
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
