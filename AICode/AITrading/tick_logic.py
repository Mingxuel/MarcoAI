"""
on_tick 的细节实现（只编排 handle_tick，不含任何判断函数）

本文件只做一件事：在每次 tick 时，按「前提 → 判断 → 有/无 → 执行/跳过」的层次编排买卖动作。
  · 前提判断 / 触发条件判断 全部在 conditions.py（in_trading_session / hit_stop_loss / is_limit_up ...）
  · 下单执行 全部在 commands.py（stop_loss_order / take_profit_order / close_liq_order / execute_buy）

每个阶段块都严格遵循同一模板，只靠本文件即可读懂整个策略：

    if <前提：是否处于该阶段>:
        <判断：筛出满足条件的股票>
        if <无>:
            pass                     # 无目标 → 跳过
        else:
            for <每只目标股>:
                <执行：下单>          # 有目标 → 逐只执行

要改买卖节奏或触发条件，去 conditions.py；要改下单执行，去 commands.py。
"""

from AITrading import config as C
from AITrading import conditions as CON
from AITrading import commands as CMD


def _sell_by_tick(xt_trader, tick):
    """tick 模式卖出（旧逻辑）：止损用「最新价 vs 成本」，涨停用「最高价 vs 涨停价」。

    两个判断独立执行：先逐只止损（撤单重挂至成交），再逐只涨停卖出。
    """
    hits = [c for c in list(CMD._positions_state.keys())
            if CON.hit_stop_loss(c, tick)]
    if not hits:
        pass                                                # 无持仓触发止损 → 跳过
    else:
        for code in hits:
            CMD.stop_loss_order(xt_trader, code)            # 有 → 逐只止损（撤单重挂）

    hits = [c for c in list(CMD._positions_state.keys())
            if CON.is_limit_up(c, tick)]
    if not hits:
        pass                                                # 无持仓涨停 → 跳过
    else:
        for code in hits:
            CMD.take_profit_order(xt_trader, code, "涨停")   # 有 → 逐只卖出


def _sell_by_5m(xt_trader, tick):
    """5 分钟卖出模式：涨停走 tick 实时判定，止损走 5min K 线收盘价判定。

    判定分工（由 miniQMT 实战特性决定，勿改回全部由 K 线判定）：
      · 涨停 —— 用本轮 tick 的 high 对涨停价（CON.is_limit_up）。tick 是最高频数据源，
                封板瞬间即可捕捉；若也改用 5min K 线，最多会延迟一整根（5 分钟）才卖出。
      · 止损 —— 用当日 5min K 线的收盘价（CON.hit_stop_loss_5m），与回测
                Backtest._sell_price_5m 的止损分支一致，避免瞬时插针把仓位震出去。
    涨停优先于止损（与回测同根内「先判涨停」的优先级一致）。
    5min 数据取不到（行情未就绪 / 接口异常）时回退「最新价止损」，避免漏掉大幅下跌。
    """
    for code in list(CMD._positions_state.keys()):
        # 1. 涨停优先：tick 环境实时判定
        if CON.is_limit_up(code, tick):
            CMD.take_profit_order(xt_trader, code, "涨停")
            continue
        # 2. 止损：5 分钟 K 线收盘价判定
        bars = CON.today_5m_bars(code)
        if bars:
            if CON.hit_stop_loss_5m(code, bars):
                CMD.stop_loss_order(xt_trader, code)
            continue
        # 3. 5min 数据不可用 → 回退最新价止损
        C.log("sell", f"[5m回退] {code} 取不到当日 5 分钟 K 线，本轮回退最新价止损判定")
        if CON.hit_stop_loss(code, tick):
            CMD.stop_loss_order(xt_trader, code)


def handle_tick(xt_trader, tick):
    """每次 tick 按交易阶段执行：盘中卖出（5min / tick 模式）→ 收盘强平 → 尾盘买入。

    三个阶段结构一致：先判断「前提」（是否处于该阶段），
    再筛出「满足触发条件的股票」，有则逐只执行下单，无则跳过。
    盘中卖出的触发条件由 config.SELL_MODE 决定，详见 _sell_by_5m / _sell_by_tick。
    """
    tick = tick or {}

    # —— 阶段一·盘中卖出：同步真实持仓 → 按卖出模式判定 → 逐只执行 ——
    # 前提：处于盘中交易区间 [09:30,14:55)
    # 卖出模式（config.SELL_MODE，可在 config.json 热切换）：
    #   "5m"   —— 5 分钟 K 线卖出：与回测 Backtest._sell_price_5m 一致，逐根 5min K 线判
    #            「high 触涨停 → 涨停卖 / close 跌破前收止损线 → 止损卖」（同根内涨停优先）；
    #            以「前收」而非成本价为基准，用 K 线收盘价而非瞬时最新价，避免插针误杀。
    #   "tick" —— 最新价卖出（旧逻辑）：最新价跌破成本×止损线 → 止损；最高价触涨停 → 涨停卖。
    # 执行：止损每 tick 撤单重挂（卖一价-0.01）直到成交；涨停按最新价挂单。
    if CON.in_trading_session():
        CMD.sync_positions(xt_trader)                       # 同步真实持仓（处理部分成交）
        if C.SELL_MODE == "5m":
            _sell_by_5m(xt_trader, tick)
        else:
            _sell_by_tick(xt_trader, tick)

    # —— 阶段三·临近收盘：三阶段阶梯强平（14:55-14:57 可撤重挂，14:57 后不可撤）——
    # 前提：已到达收盘强平时间点（>=14:55）
    # 撤单：先撤掉止损/止盈遗留挂单（每日一次），释放被冻结的持仓
    # 判断：处于强平第几小阶段 → 还有哪些持仓未卖出 → 该股本 tick 是否该撤挂
    #   3.1  卖一价        ，每 15 秒撤单重挂
    #   3.2  卖一价 - 0.01 ，最多 2 次
    #   3.3  买一价        ，每 tick 撤挂，直到 14:57 集合竞价
    if CON.is_close_approach():
        if not CMD.cancel_done_today():                     # 每日仅第一次
            CMD.cancel_pending_orders(xt_trader)            # 撤掉止损/止盈遗留的未成交挂单
            CMD.reset_force_close()                         # 清空昨日强平计数/节流计时
        CMD.sync_positions(xt_trader)                       # 撤单后重新同步真实持仓
        left = list(CMD._positions_state.keys())
        if not left:
            pass                                            # 已空仓 → 跳过
        else:
            phase = CON.force_close_phase()                 # 判断：当前强平小阶段（3.1/3.2/3.3，None=已进集合竞价）
            for code in left:
                if not CON.force_close_due(code, phase):    # 判断：节流未到 / 次数用尽 / 已成交
                    continue                                # → 本 tick 不动
                CMD.force_close_step(xt_trader, code, phase)  # 有 → 撤单并按该小阶段报价重挂剩余量

    # —— 阶段四·尾盘：集合竞价买入 ——
    # 前提：处于尾盘集合竞价区间 [14:57,15:00)，且今日尚未买过
    # 判断：选出「策略最优先股」；有可选股 → 按该股报价买入；无 → 跳过（空仓）
    if CON.in_tail_session():
        if CMD.buy_done_today():
            pass                                            # 今日已买过 → 跳过（避免重复下单）
        else:
            CMD.cancel_pending_orders(xt_trader)            # 撤单：释放冻结资金，保证买入能正常报价
            decision = CMD.decide_buy()                     # 判断：选出策略最优先股
            if decision is None:
                pass                                        # 无可选股 → 跳过（今日空仓）
            else:
                CMD.execute_buy(decision)                   # 有 → 按该股最优报价买入
