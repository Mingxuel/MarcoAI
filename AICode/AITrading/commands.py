"""
业务命令封装（第二段 API）

将买入/卖出的完整业务规则封装为清晰命令，供 callbacks.py 的 tick 回调调用。
不直接操作 xtquant 细节，统一通过 qmt_api 与 config。
"""

import os
import time
import datetime
from types import SimpleNamespace

from AITrading import config as C
from AITrading import qmt_api as Q
from AICode.MarcoAPI.Update.Path import PATH_AIDATA_TARGET, PATH_AIDATA_TRADING_DATES
from AICode.MarcoAPI.Update.SZ2001D import GET_SZ200_1D_PREVIOUS, GET_SZ200_1D_ALL
from AICode.MarcoAPI.Update.StockCodes import GET_STOCK_INFO
from AICode.MarcoAPI.Update.TradingDates import TRADING_DATES, TRADING_DATE_AFTER
from AICode.MarcoAPI.Backtest import _limit_ratio, _limit_price


# ----------------------------------------------------------------------
# 买入池读取
# ----------------------------------------------------------------------
def latest_target_file():
    """AIData/TARGET/<STRATEGY_NAME> 下最新日期文件路径。"""
    d = PATH_AIDATA_TARGET(C.STRATEGY_NAME)
    if not os.path.isdir(d):
        C.log("buy", f"买入池目录不存在：{d}")
        return None
    dates = sorted(f for f in os.listdir(d) if f.isdigit())
    if not dates:
        C.log("buy", f"买入池为空：{d}")
        return None
    return os.path.join(d, dates[-1])


def read_target_pool(path):
    """读取买入池文件：代码|名称|市值 -> [(code, name, market_value)]"""
    out = []
    raw = open(path, "rb").read()
    text = raw.decode("gbk", errors="ignore")
    for line in text.splitlines():
        parts = line.strip().split("|")
        if len(parts) < 3:
            continue
        try:
            out.append((parts[0], parts[1], float(parts[2])))
        except ValueError:
            continue
    return out


# ----------------------------------------------------------------------
# TPO_M5 形态 + MA5 预测判定（与回测 GENERATE_STRATEGY_TPO 一致）
#   分两层：
#     pass_tpo_m5_precache —— 开盘前调用，只用「已固化数据」（T-4/T-3/T-2 + 市值 + 除 T-1 外条件）
#     pass_tpo_m5_live     —— 尾盘集合竞价调用，用 T-1 实时快照补判 T-1 条件（极快，纯内存）
#   这样把重型 I/O（全市场日线预热、读买入池、拉 T-4~T-2）从尾盘短窗口挪到开盘前。
# ----------------------------------------------------------------------
def pass_tpo_m5_precache(code, buy_date):
    """提前预筛：除 T-1 外的全部条件。返回 (ok, (rec2,rec3,rec4,info), mv_t2)。

    参数 buy_date 即「T-2（本地日历末日 / 买入池文件日期）」，已固化、必在离线文件中。
    取数：rec2=PREVIOUS(buy_date,0)=T-2，rec3=PREVIOUS(buy_date,1)=T-3，rec4=PREVIOUS(buy_date,2)=T-4。
    T-1 当天数据由尾盘 miniqmt 实时快照补充，不取自离线文件（离线文件无当日数据）。
    """
    rec2 = GET_SZ200_1D_PREVIOUS(code, buy_date, 0)  # T-2 候选池日
    rec3 = GET_SZ200_1D_PREVIOUS(code, buy_date, 1)  # T-3 首板日
    rec4 = GET_SZ200_1D_PREVIOUS(code, buy_date, 2)  # T-4（用于 MA5 预测）
    if rec2 is None or rec3 is None or rec4 is None:
        return False, None, 0.0
    # T-3 首板涨停 + 放量
    if rec3.is_top != 1 or rec3.lian_ban != 1 or rec3.is_volume_up != 1:
        return False, None, 0.0
    # T-2 上涨 + 放量 + 未涨停
    if rec2.is_up != 1 or rec2.is_volume_up != 1 or rec2.is_top != 0:
        return False, None, 0.0
    # 流通市值区间（用 T-2 close 粗估，尾盘以实时 T-1 close 复算；这里只做粗筛排除明显不符）
    info = GET_STOCK_INFO(code)
    if info is None or info[1] <= 0:
        return False, None, 0.0
    mv_t2 = float(info[1]) * rec2.close
    if mv_t2 < C.MARKET_MIN or mv_t2 > C.MARKET_MAX:
        return False, None, 0.0
    return True, (rec2, rec3, rec4, info), mv_t2


def pass_tpo_m5_live(code, buy_date, pre, rec2, rec3, rec4, info, live_t1):
    """尾盘快判：用 T-1 实时快照覆盖 close/volume，判定 T-1 条件 + 市值区间 + MA5 预测。

    参数 pre 为该股 T-1 前收；rec2/rec3/rec4 为已固化的 T-2/T-3/T-4；info 为流通股本信息；
    live_t1 为实时快照 {close, volume, pre_close}。返回 (ok, market_value)。
    """
    close1 = live_t1.get("close") or 0.0
    vol1 = live_t1.get("volume") or 0.0
    if close1 <= 0 or pre <= 0:
        return False, 0.0
    ratio1 = (close1 - pre) / pre
    is_vd1 = 1 if (rec2.volume > 0 and vol1 < rec2.volume) else 0
    ma5_1 = (close1 * 2 + rec2.close + rec3.close + rec4.close) / 5.0
    # T-1 收盘涨跌幅 <= MAX_RATIO 且缩量 且 close > MA5
    if ratio1 > C.MAX_RATIO:
        return False, 0.0
    if is_vd1 != 1:
        return False, 0.0
    if close1 <= ma5_1:
        return False, 0.0
    # 流通市值区间（以实时 T-1 close 复算）
    market_value = float(info[1]) * close1
    if market_value < C.MARKET_MIN or market_value > C.MARKET_MAX:
        return False, 0.0
    # MA5 预测：T-1.close >= 预测 T-0 MA5 = (T-1*2 + T-2 + T-3 + T-4)/5
    pred_ma5 = (close1 * 2 + rec2.close + rec3.close + rec4.close) / 5.0
    if close1 < pred_ma5:
        return False, 0.0
    return True, market_value


# 提前预筛结果缓存：买入池按市值倒序后的候选列表
#   元素 (code, name, rec2, rec3, rec4, info, mv_t2)，尾盘只对这些补 T-1 快判
_buy_candidates = None
_buy_prepped_date = None  # 已预筛的日期（买入池文件日期），防重复


def prepare_buy_candidates(force=False):
    """开盘前一次性准备：刷新日历 + 预热全市场日线 + 读买入池 + T-4/T-3/T-2 + 市值预筛。

    把原本挤在尾盘集合竞价短窗口里的重型 I/O（GET_SZ200_1D_ALL 全市场遍历、买入池读取、
    T-4~T-2 日线拉取、市值读取）全部提前到此处完成，结果按市值倒序缓存到 _buy_candidates。
    尾盘 decide_buy 只需对缓存候选补 T-1 实时快判，耗时从「秒级 I/O」降到「纯内存」。
    同一买入池文件只预筛一次（_buy_prepped_date 去重）。
    """
    global _buy_candidates, _buy_prepped_date
    ensure_trading_dates()
    GET_SZ200_1D_ALL()  # 预热离线日线缓存（最重 I/O，提前做）
    path = latest_target_file()
    if path is None:
        _buy_candidates = []
        return _buy_candidates
    pool_date = os.path.basename(path)
    if not force and pool_date == _buy_prepped_date and _buy_candidates is not None:
        return _buy_candidates  # 同日买入池已预筛，直接复用

    # 推算预筛基准 buy_date：
    #   实盘（force=False）——离线日历里【不含今天】，故不能用 today 当 buy_date
    #   （TRADING_DATE_PREVIOUS 在日历找不到 buy_date 会返回 None，导致 T-2/T-3/T-4 全取不到）。
    #   正确做法：buy_date 取本地日历最后一个已知交易日（=T-2，最近已收盘日），
    #   向前推 T-3(index=1)、T-4(index=2)；T-1 当天数据由尾盘 miniqmt 实时快照补充，不取自离线文件。
    #   force 离线验证——以买入池日期(pool_date=T-2) 推算 T-3/T-4，沿用原逻辑。
    if force:
        # 离线验证：买入池文件日期即 T-2，直接作为预筛基准（与实盘买_date 语义一致）
        buy_date = pool_date
        if buy_date is None:
            _buy_candidates = []
            return _buy_candidates
        ensure_date_in_calendar(buy_date)
    else:
        # 实盘：用本地日历末日（最近已收盘交易日 = T-2）作为预筛基准。
        # 离线日历不含今天，故不能用 today；T-1 当天数据由尾盘 miniqmt 实时补充。
        all_dates = TRADING_DATES()
        if not all_dates:
            C.log("buy", "本地交易日历为空，无法预筛，跳过。")
            _buy_candidates = []
            return _buy_candidates
        buy_date = all_dates[-1]

    pool = read_target_pool(path)
    cands = []
    for code, name, mv in pool:
        ok, payload, mv_t2 = pass_tpo_m5_precache(code, buy_date)
        if not ok:
            C.log("buy", f"[预筛] 剔除 {code} {name}（T-3/T-2/市值等前置条件不符）")
            continue
        rec2, rec3, rec4, info = payload
        cands.append((code, name, rec2, rec3, rec4, info, mv_t2))
    # 按 T-2 市值粗估倒序：尾盘命中即取第一只，大市值优先
    cands.sort(key=lambda x: x[6], reverse=True)
    _buy_candidates = cands
    _buy_prepped_date = pool_date
    C.log("buy", f"[预筛完成] 买入池 {pool_date} 候选数：{len(cands)}（共 {len(pool)} 只）")
    return _buy_candidates


# ----------------------------------------------------------------------
# 交易日历工具
# ----------------------------------------------------------------------
def ensure_trading_dates():
    """预热本地交易日历缓存（不联网、不依赖通达信，符合实盘仅用 miniqmt 的约束）。

    实盘完全依赖 miniqmt，禁止使用通达信 tq 接口做实时刷新。日历由离线更新管线
    （UPDATE_TRADING_DATES，盘后运行）写入 AIData/TRADING_DATES 文件，此处仅
    本地加载并缓存；文件不存在或读取失败仅告警，后续按本地日历/今日日期兜底。
    """
    try:
        from AICode.MarcoAPI.Update.TradingDates import TRADING_DATES
        TRADING_DATES()  # 触发本地文件读取与缓存，无通达信依赖
    except Exception as e:
        C.log("warn", f"加载本地交易日历失败：{e}（将使用今日日期兜底）")


def ensure_date_in_calendar(target):
    """若 target 不在日历中，按周一~周五向后补齐（用于盘后离线验证）。"""
    dates = TRADING_DATES()
    if target in dates or not target:
        return
    from datetime import datetime as _dt
    try:
        last = _dt.strptime(dates[-1], "%Y%m%d").date()
        tgt = _dt.strptime(target, "%Y%m%d").date()
    except Exception:
        return
    extra = []
    d = last + _dt.timedelta(days=1)
    while d <= tgt:
        if d.weekday() < 5:
            extra.append(d.strftime("%Y%m%d"))
        d += _dt.timedelta(days=1)
    if extra:
        dates.extend(extra)
        try:
            with open(PATH_AIDATA_TRADING_DATES(), "a") as f:
                f.write("\n" + "\n".join(extra) + "\n")
            C.log("info", f"日历已补齐未来交易日至 {target}：{extra}")
        except Exception:
            pass


# ----------------------------------------------------------------------
# 买入：决策 + 执行
# ----------------------------------------------------------------------
def decide_buy(force=False):
    """尾盘买入决策：对提前预筛的候选补 T-1 实时快判，返回 {'code','name','price'} 或 None。

    尾盘窗口（14:57-15:00）极短，故本函数不再做重型 I/O——只遍历 prepare_buy_candidates
    已缓存的候选，用 T-1 实时快照补判 T-1 条件（纯内存），再取实时价报价。若缓存为空
    （如未提前准备或离线验证），降级回退原全量逻辑，保证健壮性。
    """
    C.log("buy", f"开始买入判定 force={force}")

    # —— 交易日拦截：仅用 miniQMT 实时接口判断今日是否交易日（不依赖离线日历）——
    # miniQMT 不可用时直接抛异常，此处捕获后跳过当日买入（不兜底、不运行）。
    if not force:
        today = datetime.date.today().strftime("%Y%m%d")
        try:
            is_td = Q.is_trading_day(today)
        except Exception as e:
            C.log("buy", f"miniqmt 交易日判断不可用，跳过今日买入：{e}")
            return None
        if not is_td:
            C.log("buy", f"今日 {today} 非交易日（miniqmt 实时判定），跳过买入。")
            return None

    # —— 降级路径：缓存不可用（force 验证 / 未提前准备）时回退原全量逻辑 ——
    if force or _buy_candidates is None:
        return _decide_buy_full(force=force)

    if not _buy_candidates:
        C.log("buy", "无预筛候选，今日空仓。")
        return None

    # 取 T-1 前收：用于尾盘实时快照的 ratio 计算（rec2 已是 T-2，前收=上一交易日 close）
    # 对每只预筛候选取实时快照补判 T-1；命中即返回（已按市值倒序，第一只即最优）
    for code, name, rec2, rec3, rec4, info, mv_t2 in _buy_candidates:
        live_t1 = Q.get_live_snapshot(code)
        if live_t1 is None:
            C.log("buy", f"无法获取 {code} 实时 T-1 快照，跳过。")
            continue
        pre = live_t1.get("pre_close") or 0.0
        ok, market_value = pass_tpo_m5_live(code, None, pre, rec2, rec3, rec4, info, live_t1)
        if not ok:
            C.log("buy", f"剔除 {code} {name}（T-1 实时条件不符）")
            continue
        price = Q.get_realtime_price(code)
        if price is None:
            C.log("buy", f"无法获取 {code} 实时价，放弃。")
            continue
        C.log("buy", f"策略最优先股：{code} {name} 市值≈{market_value/1e8:.1f}亿 现价≈{price:.2f}")
        return {"code": code, "name": name, "price": price}

    C.log("buy", "预筛候选中无满足 T-1 实时条件的股票，今日空仓。")
    return None


def _decide_buy_full(force=False):
    """降级/离线全量判定：读买入池 + 全量 TPO_M5 判定（兼容未提前准备与 force 验证场景）。"""
    today = datetime.date.today().strftime("%Y%m%d")
    path = latest_target_file()
    if path is None:
        return None
    pool = read_target_pool(path)
    C.log("buy", f"买入池（{os.path.basename(path)}）候选数：{len(pool)}")

    if force:
        pool_date = os.path.basename(path)
        buy_date = pool_date  # 买入池日期即 T-2
        ensure_date_in_calendar(buy_date)
        C.log("buy", f"[force] 以买入池日期 {pool_date}(=T-2) 做离线判定")
    else:
        try:
            is_td = Q.is_trading_day(today)
        except Exception as e:
            C.log("buy", f"miniqmt 交易日判断不可用，跳过今日买入：{e}")
            return None
        if not is_td:
            C.log("buy", "今日非交易日（miniqmt 实时判定），跳过。")
            return None
        # 实盘：离线日历不含今天，buy_date 取本地日历末日（=T-2）
        all_dates = TRADING_DATES()
        if not all_dates:
            C.log("buy", "本地交易日历为空，跳过。")
            return None
        buy_date = all_dates[-1]
    if buy_date is None:
        C.log("buy", "无法推算 T-2 基准日，跳过。")
        return None

    for code, name, mv in sorted(pool, key=lambda x: x[2], reverse=True):
        live_t1 = Q.get_live_snapshot(code)
        ok, pre, rec2, rec3, rec4, info, mv_t2 = _full_check(code, buy_date, live_t1)
        if not ok:
            C.log("buy", f"剔除 {code} {name}（不满足 TPO_M5 形态/MA5 预测）")
            continue
        price = Q.get_realtime_price(code)
        if price is None:
            C.log("buy", f"无法获取 {code} 实时价，放弃。")
            continue
        C.log("buy", f"策略最优先股：{code} {name} 市值≈{mv_t2/1e8:.1f}亿 现价≈{price:.2f}")
        return {"code": code, "name": name, "price": price}

    C.log("buy", "无满足 TPO_M5 条件的股票，无策略最优先股，今日空仓。")
    return None


def _full_check(code, buy_date, live_t1):
    """全量判定（含 T-4/T-3/T-2 实时拉取），返回 (ok, pre, rec2, rec3, rec4, info, mv_t2)。
    buy_date 即 T-2（本地日历末日 / 买入池日期）。"""
    rec2 = GET_SZ200_1D_PREVIOUS(code, buy_date, 0)  # T-2
    rec3 = GET_SZ200_1D_PREVIOUS(code, buy_date, 1)  # T-3
    rec4 = GET_SZ200_1D_PREVIOUS(code, buy_date, 2)  # T-4
    if rec2 is None or rec3 is None or rec4 is None:
        return (False, 0.0, None, None, None, None, 0.0)
    if rec3.is_top != 1 or rec3.lian_ban != 1 or rec3.is_volume_up != 1:
        return (False, 0.0, None, None, None, None, 0.0)
    if rec2.is_up != 1 or rec2.is_volume_up != 1 or rec2.is_top != 0:
        return (False, 0.0, None, None, None, None, 0.0)
    info = GET_STOCK_INFO(code)
    if info is None or info[1] <= 0:
        return (False, 0.0, None, None, None, None, 0.0)
    mv_t2 = float(info[1]) * rec2.close
    if mv_t2 < C.MARKET_MIN or mv_t2 > C.MARKET_MAX:
        return (False, 0.0, None, None, None, None, 0.0)
    # T-1 实时快判
    if live_t1 is None:
        return (False, 0.0, rec2, rec3, rec4, info, mv_t2)
    pre = live_t1.get("pre_close") or 0.0
    ok, market_value = pass_tpo_m5_live(code, buy_date, pre, rec2, rec3, rec4, info, live_t1)
    return (ok, pre, rec2, rec3, rec4, info, market_value)


def _best_buy_quote(cash, vol, base_price, limit_px):
    """在 [base_price, limit_px] 区间内，找到「仍能买入 vol 手」的最高报价（单位：元）。

    尾盘集合竞价按「价格优先 + 时间优先」撮合，因此在不减少可买手数的前提下，
    应尽可能地用高价报价以确保大概率成交。手数随报价上升单调不增，
    用「以分为单位的整数二分」在 [基准价, 涨停价] 中定位仍能买满 vol 手的价格上界，
    避免浮点 round 导致的手数误差。
    """
    ratio = C.POSITION_RATIO

    def shares_at(cents):
        # cents 为「分」整数；返回按该价格可买的整百股手数
        return int(cash * ratio / ((cents / 100.0) * 100)) * 100

    base_c = int(round(base_price * 100))
    limit_c = int(round(limit_px * 100))
    # 防御：基准价本身已买不到 vol 手（理论不会发生）
    if shares_at(base_c) < vol:
        return round(base_price, 2)
    lo, hi = base_c, limit_c
    # 整数二分：找最大 cents ∈ [lo, hi] 使 shares_at(cents) >= vol
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if shares_at(mid) >= vol:
            lo = mid
        else:
            hi = mid - 1
    return lo / 100.0


def execute_buy(decision):
    """执行买入：计算股数（单股全仓），以「仍能买满手数的最高价」报价提交订单。"""
    code, name, price = decision["code"], decision["name"], decision["price"]
    try:
        xt, _ = Q.connect()
    except RuntimeError as e:
        C.log("buy", f"[模拟] {e}\n[模拟] 计划买入 {code} @ {price:.2f}（单股全仓）")
        return
    cash = Q.get_account_cash(xt)
    vol = int((cash * C.POSITION_RATIO) / (price * 100)) * 100
    if vol <= 0:
        C.log("buy", f"资金不足，无法买入 {code}")
        return
    # 报价硬上限 = 涨停价（集合竞价不可超涨跌停）
    limit_px = _limit_price(price, _limit_ratio(code))
    # 在「仍能买入 vol 手」前提下取最高报价，确保成交且不丢手数
    quote = _best_buy_quote(cash, vol, price, limit_px)
    oid = Q.submit_buy(xt, code, vol, quote)
    C.log("buy", f"已提交买入单：{code} 数量={vol} 报价={quote:.2f} "
                f"（仍能买{vol}手的最高价，涨停上限={limit_px:.2f}）订单号={oid}")
    # 打上「今日已买」标记：尾盘集合竞价区间内每个 tick 都会进来，避免重复下单
    global _buy_done_date
    _buy_done_date = datetime.date.today().strftime("%Y%m%d")


def cmd_buy(force=False):
    """顶层买入命令：先选出策略最优先股，有则按该股报价买入，无则跳过（空仓）。"""
    decision = decide_buy(force=force)   # 选出策略最优先股（或 None）
    if decision is None:
        C.log("buy", "无策略最优先股，跳过今日买入。")
        return
    execute_buy(decision)                 # 有可选股：按该股最优报价买入


# ----------------------------------------------------------------------
# 持仓状态机（处理部分卖出：以「每只股票」为粒度，而非「今天卖过」）
# ----------------------------------------------------------------------
_positions_state = {}  # code -> {"cost": 成本价, "target_vol": 目标卖出量, "ordered": 是否已挂单}


def sync_positions(xt_trader):
    """从券商同步真实持仓，更新状态机。部分成交后真实持仓减少，剩余量自动更新。"""
    if xt_trader is None:
        return
    positions = Q.get_positions(xt_trader)
    live = {p["code"]: p for p in positions}
    for code in list(_positions_state.keys()):
        if code not in live:
            _positions_state.pop(code, None)
    for code, p in live.items():
        if code not in _positions_state:
            _positions_state[code] = {"cost": p.get("cost", 0.0),
                                      "target_vol": p["volume"],
                                      "ordered": False}
        else:
            st = _positions_state[code]
            if p["volume"] != st["target_vol"]:  # 持仓变化（加仓/回补）→ 允许重新挂单
                st["target_vol"] = p["volume"]
                st["ordered"] = False


def _submit_if_pending(xt_trader, code, reason):
    """对已同步的持仓，若未挂单则按剩余量提交卖单并打印直观日志。返回是否提交。"""
    st = _positions_state.get(code)
    if not st:
        return False
    remaining = st["target_vol"]
    if remaining <= 0:
        return False
    if st["ordered"]:  # 已挂单，等成交回报（下个 tick 的 sync_positions 会更新剩余量）
        return False
    tick = Q.get_full_tick(code) or {}
    last = tick.get("lastPrice") or 0.0
    oid = Q.submit_sell(xt_trader, code, remaining, last)
    st["ordered"] = True
    C.log("sell", f"[{reason}触发] {code} 卖出数量={remaining} 价格={last:.2f} 订单号={oid}")
    return True


# ----------------------------------------------------------------------
# 卖出执行封装：只负责「下单 + 打印触发日志」，不含任何条件判断
#   （判断逻辑全部在 tick_logic.py：是否开盘、是否触止损/涨停、是否到尾盘）
# ----------------------------------------------------------------------
def stop_loss_order(xt_trader, code):
    """执行止损卖出：每 tick 先撤未成交挂单，再按「卖一价 - 0.01」重挂剩余量。

    止损单可能长时间卖不出去（价格挂在卖一附近但无人接），因此不依赖
    _submit_if_pending 的「已挂单就跳过」逻辑，而是每 tick 主动撤单重挂，
    确保报价始终贴着卖一价 - 0.01，提高成交概率。前提判断已在 tick_logic 完成。
    """
    # 1. 撤销该股未成交委托：不撤则旧单冻结持仓，无法按新报价重挂
    if xt_trader is not None:
        for o in Q.query_orders(xt_trader, code=code, cancelable_only=True):
            if Q.cancel_order(xt_trader, o["order_id"]):
                C.log("order", f"[止损撤单] {code} 订单号={o['order_id']} "
                               f"委托={o['volume']} 已成交={o['traded']}")
        st0 = _positions_state.get(code)
        if st0:
            st0["ordered"] = False

    # 2. 重新同步真实持仓：部分成交后剩余量在此更新
    sync_positions(xt_trader)
    st = _positions_state.get(code)
    if not st:
        C.log("sell", f"[止损完成] {code} 已全部卖出")
        return False
    remaining = st["target_vol"]
    if remaining <= 0:
        return False

    # 3. 按「卖一价 - 0.01」挂出剩余量
    tick = Q.get_full_tick(code) or {}
    ask1 = tick.get("ask1")
    if ask1 is None or ask1 <= 0:
        C.log("sell", f"{code} 取不到卖一价，止损本轮跳过。")
        return False
    price = round(ask1 - C.FORCE_CLOSE_P2_TICK, 2)
    oid = Q.submit_sell(xt_trader, code, remaining, price)
    st["ordered"] = True
    C.log("sell", f"[止损触发] {code} 卖出数量={remaining} 报价={price:.2f} 订单号={oid}")
    return True


def take_profit_order(xt_trader, code, reason):
    """执行止盈/涨停卖出下单，reason 为 '涨停' 或 '止盈'（前提判断已在 tick_logic 完成）。"""
    return _submit_if_pending(xt_trader, code, reason)


def close_liq_order(xt_trader, code):
    """执行收盘强平下单（前提判断已在 tick_logic 完成）。"""
    return _submit_if_pending(xt_trader, code, "收盘")


# ----------------------------------------------------------------------
# 收盘强平：三阶段阶梯报价（撤单 → 按阶段报价重挂剩余量，直到成交）
#   阶段一：卖一价        ，每 FORCE_CLOSE_RETRY_SEC 秒撤单重挂
#   阶段二：卖一价 - 0.01 ，最多 FORCE_CLOSE_P2_MAX 次，每 RETRY_SEC 秒一次
#   阶段三：买一价        ，每 tick 撤单重挂（至 14:57 集合竞价，之后不可撤单）
# ----------------------------------------------------------------------
_force_close_state = {}  # code -> {"order_id", "last_ts"（上次挂单时刻）, "p2_count"（阶段二已挂次数）}


def _fc_state(code):
    """取（或建）该股的强平状态，供节流与阶段二计数使用。"""
    return _force_close_state.setdefault(
        code, {"order_id": None, "last_ts": 0.0, "p2_count": 0})


def force_close_quote(code, phase):
    """按强平阶段计算报价：1→卖一价，2→卖一价-P2_TICK，3→买一价。取不到盘口返回 None。"""
    tick = Q.get_full_tick(code) or {}
    ask1, bid1 = tick.get("ask1"), tick.get("bid1")
    if phase == 1:
        return ask1
    if phase == 2:
        return None if ask1 is None else round(ask1 - C.FORCE_CLOSE_P2_TICK, 2)
    return bid1


def force_close_step(xt_trader, code, phase):
    """执行一轮强平撤挂：撤销该股未成交委托 → 同步真实持仓 → 按阶段报价重挂剩余量。

    返回是否成功挂出。已全部成交（持仓消失）则清理状态并返回 False。
    """
    fs = _fc_state(code)

    # 1. 撤销该股未成交委托：不撤则旧单冻结持仓，无法按剩余量重新报价
    if xt_trader is not None:
        for o in Q.query_orders(xt_trader, code=code, cancelable_only=True):
            if Q.cancel_order(xt_trader, o["order_id"]):
                C.log("order", f"[强平撤单] {code} 订单号={o['order_id']} "
                               f"委托={o['volume']} 已成交={o['traded']}")
        st0 = _positions_state.get(code)
        if st0:
            st0["ordered"] = False

    # 2. 重新同步真实持仓：部分成交后剩余量在此更新
    sync_positions(xt_trader)
    st = _positions_state.get(code)
    if not st:                                   # 持仓已清空 → 强平完成
        _force_close_state.pop(code, None)
        C.log("sell", f"[强平完成] {code} 已全部卖出")
        return False
    remaining = st["target_vol"]
    if remaining <= 0:
        _force_close_state.pop(code, None)
        return False

    # 3. 按当前阶段报价挂出剩余量
    price = force_close_quote(code, phase)
    if price is None or price <= 0:
        C.log("sell", f"{code} 取不到阶段{phase}报价（盘口缺失），本轮跳过。")
        return False
    oid = Q.submit_sell(xt_trader, code, remaining, price)
    st["ordered"] = True
    fs["order_id"] = oid
    fs["last_ts"] = time.time()
    if phase == 2:
        fs["p2_count"] += 1
    C.log("sell", f"[强平阶段{phase}] {code} 卖出数量={remaining} 报价={price:.2f} "
                  f"{'（阶段二第%d/%d次）' % (fs['p2_count'], C.FORCE_CLOSE_P2_MAX) if phase == 2 else ''}"
                  f"订单号={oid}")
    return True


# ----------------------------------------------------------------------
# 撤单封装：撤销未成交委托，释放被冻结的资金/持仓，保证后续能正常报价
#   未成交的挂单会冻结对应持仓（卖单）或资金（买单），不撤单则后续
#   强平/买入要么重复挂单，要么因可用量不足而无法报价。
# ----------------------------------------------------------------------
_cancel_done_date = None


def cancel_done_today():
    """判断：今日是否已执行过「收盘撤单」（每日仅一次，避免反复撤掉自己刚挂的单）。"""
    return _cancel_done_date == datetime.date.today().strftime("%Y%m%d")


def cancel_pending_orders(xt_trader, code=None):
    """撤销当日未成交（可撤）委托，返回撤销笔数。code 为 None 时撤全部。

    撤单后把对应股票的 ordered 标记复位，允许重新挂单报价。
    """
    if xt_trader is None:
        return 0
    orders = Q.query_orders(xt_trader, code=code, cancelable_only=True)
    if not orders:
        return 0
    n = 0
    for o in orders:
        if Q.cancel_order(xt_trader, o["order_id"]):
            n += 1
            C.log("order", f"[撤单] {o['code']} 订单号={o['order_id']} "
                           f"委托={o['volume']} 已成交={o['traded']}")
    if n:
        # 撤单成功 → 复位 ordered，使后续能对该股票重新报价卖出
        for c in {o["code"] for o in orders} & set(_positions_state.keys()):
            _positions_state[c]["ordered"] = False
        C.log("order", f"已撤销未成交委托 {n} 笔，释放冻结持仓/资金")
    return n


def reset_force_close():
    """清空强平状态（每日首次进入强平时调用，避免昨日计数/节流计时影响今日）。"""
    _force_close_state.clear()


# ----------------------------------------------------------------------
# 买入封装：尾盘集合竞价买入（含今日去重，直观可见「到尾盘开始集合竞价买入」）
# ----------------------------------------------------------------------
_buy_done_date = None


def buy_done_today():
    """判断：今日是否已买过（买入去重，供 tick 层在尾盘区间内判断能否再买）。"""
    return _buy_done_date == datetime.date.today().strftime("%Y%m%d")


def buy_at_close(xt_trader):
    """尾盘集合竞价买入：T-1 一次性决策，今日仅触发一次。"""
    if buy_done_today():
        return
    C.log("buy", "【尾盘集合竞价】买入窗口开启，开始选股买入")
    cmd_buy(force=False)


# ----------------------------------------------------------------------
# CLI 委托入口
# ----------------------------------------------------------------------
def cmd_sell():
    """顶层卖出命令：对全部持仓股按规则监控卖出（阻塞至收盘/清仓）。规则引擎见 commands。"""
    from AITrading.Structure import callbacks as CALL
    try:
        xt, _ = Q.connect()
    except RuntimeError as e:
        C.log("sell", f"[模拟] {e}\n[sell][模拟] 仅打印卖出计划，不真实报单。")
        xt = None
    if xt is None:
        CALL.run_sell_blocking(None)
        return
    CALL.run_sell_blocking(xt)
