"""
通用策略回测模块

====================================================
一、功能
====================================================
  对策略选股结果（MarcoAI/AIData/Strategy/{策略名}/ 下的每日选股文件）进行回测：
    - 自由选择策略（按策略名）
    - 自由选择卖出方式（first / last / avg）
    - 起始资金 10 万，复利滚动
    - 统计每月/季度/每年收益
    - 输出所选全部股票及卖出日信息

====================================================
二、卖出方式说明
====================================================
  first  每日列表取第一个股票，全仓当前资金
  last   每日列表取最后一个股票，全仓当前资金
  avg    每日取全部股票，资金平均分配，取平均收益率

====================================================
三、数据格式
====================================================
  策略数据: MarcoAI/AIData/Strategy/{策略名}/{卖出日}（每行一只股票，| 分隔）
    第0列 股票代码  第1列 股票名称  第2列 市值
    第3列 卖出日    第4列 开盘      第5列 最高
    第6列 最低      第7列 收盘      第8列 成交量
    第9列 成交额    第10列 前收     第11~27列 其他加工字段
  收益率 = (收盘 - 前收) / 前收   （T-1 买入 → T-0 卖出）

  输出: MarcoAI/AIData/STRATEGY/RESULT/{策略名}.txt
====================================================
"""

import os
import sys
from collections import defaultdict

_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _root not in sys.path:
    sys.path.insert(0, _root)
from AICode.MarcoAPI.Update.Path import PATH_AIDATA_STRATEGY, PATH_AIDATA_STRATEGY_RESULT, PATH_AIDATA_5M

INIT_CAPITAL = 100000.0  # 起始资金 10 万
SELL_MODES = ["first", "last", "avg", "5m"]  # 支持的卖出方式（5m = 基于 5 分钟 K 线的日内卖出）


def _read_lines(path):
    """兼容多种编码读取文件行（策略文件含中文股票名）"""
    raw = open(path, "rb").read()
    for enc in ("utf-8", "gbk", "gb2312", "latin-1"):
        try:
            return raw.decode(enc).splitlines()
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="ignore").splitlines()


def _load_strategy(strategy_name: str):
    """读取策略目录下全部每日选股文件，返回 {卖出日: [选股行(list[str])]}（按日期升序）"""
    strategy_dir = os.path.join(PATH_AIDATA_STRATEGY(), strategy_name)
    if not os.path.isdir(strategy_dir):
        print(f"BACKTEST: 策略目录不存在 {strategy_dir}")
        return {}
    daily: dict[str, list[list[str]]] = {}
    for file_name in sorted(os.listdir(strategy_dir)):
        if not file_name.isdigit():
            continue
        rows = []
        for line in _read_lines(os.path.join(strategy_dir, file_name)):
            line = line.strip()
            if not line:
                continue
            cols = line.split("|")
            if len(cols) >= 11:  # 至少需要代码/名称/市值/卖出日/开高低收量额/前收
                rows.append(cols)
        if rows:
            daily[file_name] = rows
    return daily


STOCK_SELL_STOP = -0.06  # 次日卖出止损线：低于此跌幅直接止损


def _limit_ratio(code: str) -> float:
    """按股票代码判断当日涨停幅度。创业/科创板 20%，主板 10%"""
    pure = code.split(".")[0]
    if pure.startswith(("300", "301", "302", "688", "689")):
        return 0.20
    return 0.10


def _limit_price(pre_close: float, ratio: float) -> float:
    """涨停价 = 前收×(1+涨幅)，按交易所规则两步四舍五入：

    1) 先四舍五入到 0.001（厘位）得中间价，例如 5.5445
    2) 再把中间价四舍五入到 0.01（分位），例如 5.5445 → 5.545 → 5.55

    不能一步四舍五入到 0.01：5.5445 一步到分是 5.54（第3位4舍去），
    但交易所先到厘成 5.545、再到分成 5.55，结果不同。
    """
    from decimal import Decimal, ROUND_HALF_UP
    mid = (Decimal(str(pre_close)) * Decimal(str(1 + ratio))) \
        .quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    return float(mid.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _stock_return(cols: list[str]) -> float | None:
    """按次日卖出规则计算单只股票收益率；数据无效返回 None。

    卖出规则（按优先级）：
      1. 开盘涨跌幅 < 止损线      -> 按开盘价卖出
      2. 最低价涨跌幅 < 止损线    -> 按止损线卖出
      3. 最高价触及涨停价          -> 按涨停价卖出
      4. 以上都不满足             -> 按收盘价卖出

    止损线优先取数据第 29 列（索引 28，由策略写入，如 TPO_M5 为 -5%），
    缺失时回退全局 STOCK_SELL_STOP（-6%）。
    """
    try:
        code = cols[0]
        open_p = float(cols[4])
        high = float(cols[5])
        low = float(cols[6])
        close = float(cols[7])
        pre_close = float(cols[10])
    except (ValueError, IndexError):
        return None
    if pre_close <= 0:
        return None

    # 本策略止损线（数据第 29 列，缺失则用全局默认）
    stop = STOCK_SELL_STOP
    if len(cols) > 28:
        try:
            v = float(cols[28])
            if v < 0:
                stop = v
        except ValueError:
            pass

    # 规则1：开盘涨跌幅 < 止损线 -> 按开盘价卖出
    open_ratio = (open_p - pre_close) / pre_close
    if open_ratio < stop:
        return open_ratio

    # 规则2：最低价 < 止损线 -> 按止损线卖出
    low_ratio = (low - pre_close) / pre_close
    if low_ratio < stop:
        return stop

    # 规则3：最高价触及涨停 -> 按涨停价卖出
    limit_p = _limit_price(pre_close, _limit_ratio(code))
    if high >= limit_p:
        return (limit_p - pre_close) / pre_close

    # 规则4：否则按收盘价卖出
    return (close - pre_close) / pre_close


# ----------------------------------------------------------------------
# 5 分钟 K 线日内卖出模式（sell_mode = "5m"）
#
# 规则（按当日 5min K 线时间升序，1-indexed 第 47 根 = 14:55）：
#   1. 任一 K 线 high 触及涨停价            -> 按涨停价卖出（盘中触及即卖）
#   2. 任一 K 线 close 相对 pre_close < 止损线(-5%) -> 按该根 close 卖出（盘中止损）
#   3. 前 47 根（至 14:55）均未触发         -> 按第 47 根（14:55）close 卖出
# 涨停优先于止损；第 48 根（15:00）不参与，避免尾盘集合竞价不可撤单。
# ----------------------------------------------------------------------
_5M_CACHE: dict[str, list[tuple] | None] = {}


def _get_5m_bars(code: str) -> list[tuple] | None:
    """读取并缓存单只股票的全部 5M K 线，返回按时间升序的
    [(time_str, open, high, low, close, volume, amount), ...]；无文件返回 None。

    文件: AIData/5M/{code}，每行 time|open|high|low|close|volume|amount
    """
    if code in _5M_CACHE:
        return _5M_CACHE[code]
    path = os.path.join(PATH_AIDATA_5M(), code)
    if not os.path.isfile(path):
        _5M_CACHE[code] = None
        return None
    raw = open(path, "rb").read()
    text: str | None = None
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        _5M_CACHE[code] = None
        return None
    bars: list[tuple] = []
    for line in text.splitlines():
        p = line.strip().split("|")
        if len(p) < 7:
            continue
        try:
            bars.append((p[0], float(p[1]), float(p[2]), float(p[3]), float(p[4]), float(p[5]), float(p[6])))
        except ValueError:
            continue
    bars.sort(key=lambda x: x[0])  # 按时间（字符串 YYYY-MM-DD HH:MM:SS）升序
    _5M_CACHE[code] = bars
    return bars


def _sell_price_5m(cols: list[str]) -> float | None:
    """基于 5 分钟 K 线的 T-0 日内实际卖出价；无当日 5M 数据返回 None。

    规则（按当日 5min K 线时间升序，1-indexed 第 47 根 = 14:55）：
      1. 任一 K 线 high 触及涨停价            -> 涨停价
      2. 任一 K 线 close 相对 pre_close < 止损线 -> 该根 close
      3. 前 47 根均未触发                -> 第 47 根（14:55）close
    涨停优先于止损；第 48 根（15:00）不参与，避免尾盘集合竞价不可撤单。
    """
    try:
        code = cols[0]
        sell_date = cols[3]          # T-0 卖出日 YYYYMMDD
        pre_close = float(cols[10])
    except (ValueError, IndexError):
        return None
    if pre_close <= 0:
        return None
    bars = _get_5m_bars(code)
    if not bars:
        return None
    date_prefix = f"{sell_date[:4]}-{sell_date[4:6]}-{sell_date[6:8]}"
    day_bars = [b for b in bars if b[0].startswith(date_prefix)]
    if not day_bars:
        return None

    limit_p = _limit_price(pre_close, _limit_ratio(code))
    stop = STOCK_SELL_STOP
    if len(cols) > 28:
        try:
            v = float(cols[28])
            if v < 0:
                stop = v
        except ValueError:
            pass

    # 遍历前 47 根（1-indexed）；不足 47 根则遍历全部
    n = min(len(day_bars), 47)
    for i in range(n):
        _t, _o, h, _l, c, _v, _a = day_bars[i]
        if h >= limit_p:
            return limit_p
        if (c - pre_close) / pre_close < stop:
            return c

    # 兜底：第 47 根（14:55）收盘卖；若当日不足 47 根则取最后一根
    last = day_bars[46] if len(day_bars) >= 47 else day_bars[-1]
    return last[4]


def _stock_return_5m(cols: list[str]) -> float | None:
    """基于 5 分钟 K 线的 T-0 日内卖出收益率；无当日 5M 数据返回 None。

    详见模块顶部「5 分钟 K 线日内卖出模式」说明。
    """
    sp = _sell_price_5m(cols)
    if sp is None:
        return None
    try:
        pre_close = float(cols[10])
    except (ValueError, IndexError):
        return None
    if pre_close <= 0:
        return None
    return (sp - pre_close) / pre_close


def _daily_return(rows: list[list[str]], mode: str) -> float:
    """计算某卖出日组合的收益率"""
    if mode == "first":
        ret = _stock_return(rows[0])
        return ret if ret is not None else 0.0
    if mode == "last":
        ret = _stock_return(rows[-1])
        return ret if ret is not None else 0.0
    if mode == "avg":
        # 平均收益率（资金平均分配给当日所有选股）
        returns = [r for r in (_stock_return(row) for row in rows) if r is not None]
        if not returns:
            return 0.0
        return sum(returns) / len(returns)
    if mode == "5m":
        # 基于 5 分钟 K 线的日内卖出（资金平均分配给当日所有选股）
        returns = [r for r in (_stock_return_5m(row) for row in rows) if r is not None]
        if not returns:
            return 0.0
        return sum(returns) / len(returns)
    return 0.0


def _backtest(daily: dict[str, list[list[str]]], mode: str):
    """按卖出方式回测，返回 (交易记录, 每日资金序列)"""
    capital = INIT_CAPITAL
    records = []  # (卖出日, 所选股票代码列表, 当日收益率, 当日资金)
    for date in sorted(daily):
        rows = daily[date]
        if not rows:
            continue
        day_ret = _daily_return(rows, mode)
        capital *= (1.0 + day_ret)
        # 记录所选股票（first/last 取1只，avg 取全部）
        if mode == "first":
            selected = [rows[0]]
        elif mode == "last":
            selected = [rows[-1]]
        else:
            selected = rows
        records.append((date, selected, day_ret, capital))
    return records


def _group_by_period(records, fmt):
    """按时间段（月/季/年）聚合收益率（区间内复利）"""
    period_mul = defaultdict(lambda: 1.0)
    period_count = defaultdict(int)
    for date, _, day_ret, _ in records:
        period = fmt(date)
        period_mul[period] = period_mul[period] * (1 + day_ret)  # 累积 (1+r)
        period_count[period] += 1
    period_ret = {p: m - 1.0 for p, m in period_mul.items()}  # 区间复利收益率
    return period_ret, period_count


def _fmt_month(date: str) -> str:
    return date[:6]  # YYYYMM


def _fmt_quarter(date: str) -> str:
    month = int(date[4:6])
    quarter = (month - 1) // 3 + 1
    return f"{date[:4]}Q{quarter}"


def _fmt_year(date: str) -> str:
    return date[:4]


def _format_return(value: float) -> str:
    return f"{value * 100:.2f}%"


def BACKTEST(strategy_name: str, sell_modes: list[str] | None = None) -> dict[str, str]:
    """对指定策略进行回测，输出结果文件并返回 {卖出方式: 结果文本}。

    参数:
        strategy_name: 策略名（对应 MarcoAI/AIData/Strategy/{策略名}/ 目录）
        sell_modes:    卖出方式列表，默认三种都算（first/last/avg）
    """
    if sell_modes is None:
        sell_modes = SELL_MODES
    daily = _load_strategy(strategy_name)
    if not daily:
        print(f"BACKTEST: 策略 {strategy_name} 无数据")
        return {}

    os.makedirs(PATH_AIDATA_STRATEGY_RESULT(), exist_ok=True)
    result_file = os.path.join(PATH_AIDATA_STRATEGY_RESULT(), f"{strategy_name}.txt")

    lines: list[str] = []
    lines.append(f"策略: {strategy_name}")
    lines.append(f"起始资金: {INIT_CAPITAL:.0f} 元")
    lines.append(f"数据范围: {sorted(daily)[0]} ~ {sorted(daily)[-1]}")
    lines.append("")

    result_text: dict[str, str] = {}
    for mode in sell_modes:
        records = _backtest(daily, mode)
        if not records:
            continue
        final_capital = records[-1][3]
        total_ret = final_capital / INIT_CAPITAL - 1.0

        block = [f"================ 卖出方式: {mode} ================"]
        block.append(f"总收益率: {_format_return(total_ret)}")
        block.append(f"最终资金: {final_capital:.2f} 元")
        block.append("")

        # 每年收益
        year_ret, _ = _group_by_period(records, _fmt_year)
        block.append("--- 每年收益 ---")
        for y in sorted(year_ret):
            block.append(f"  {y}: {_format_return(year_ret[y])}")
        block.append("")

        # 每季度收益
        quarter_ret, _ = _group_by_period(records, _fmt_quarter)
        block.append("--- 每季度收益 ---")
        for q in sorted(quarter_ret):
            block.append(f"  {q}: {_format_return(quarter_ret[q])}")
        block.append("")

        # 每月收益
        month_ret, month_cnt = _group_by_period(records, _fmt_month)
        block.append("--- 每月收益 ---")
        for m in sorted(month_ret):
            block.append(f"  {m}: {_format_return(month_ret[m])} (交易{month_cnt[m]}日)")
        block.append("")

        # 所选全部股票 + 卖出日信息
        block.append("--- 选股明细（所选股票 | 卖出日信息）---")
        for date, selected, day_ret, capital in records:
            stock_names = []
            for cols in selected:
                code = cols[0]
                name = cols[1] if len(cols) > 1 else ""
                close = cols[7]
                pre_close = cols[10]
                stock_names.append(f"{code}({name}) 收:{close} 前收:{pre_close}")
            block.append(f"卖出日 {date}: 收益率 {_format_return(day_ret)}, 资金 {capital:.2f}")
            for s in stock_names:
                block.append(f"    {s}")

        text = "\n".join(block)
        lines.append(text)
        lines.append("")
        result_text[mode] = text

    with open(result_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"BACKTEST: 策略 {strategy_name} 结果已写入 {result_file}")
    return result_text


if __name__ == "__main__":
    BACKTEST("TPO_3")
