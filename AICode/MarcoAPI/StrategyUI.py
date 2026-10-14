"""
策略回测 + 实盘目标股综合看板生成器

功能:
    生成一个自包含的交互式 HTML 面板（AICode/MarcoAPI/UI/StrategyDashboard.html）：
        TAB1 策略回测
           - 自由选择策略
           - 三种卖出方式（first/last/avg）逐日资金曲线对比（Chart.js 折线图）
           - 每月 / 季度 / 每年收益
        TAB2 实盘候选池
           - 候选股票池按日期倒序显示（默认最新日期，T-2 日收盘后确定，下个交易日可买入）
           - 点击候选股展示日线 K 线图（LightweightCharts，MA5/10/20/60 + 成交量）
    双击 HTML 即可在浏览器中交互，无需服务器。

数据来源:
    MarcoAI/AIData/Strategy/{策略名}/  每日选股文件（回测）
    MarcoAI/AIData/TARGET/{策略名}/{日期}   T-2 日候选股票池（实盘，每行 代码|名称|市值）
    MarcoAI/AIData/1D_ORIGIN/{代码}    原始日线（K 线，MA 由前端计算）
"""

import json
import os
import re
import sys
import webbrowser
import datetime as _dt
from typing import Any

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, os.path.dirname(_root))
from AICode.MarcoAPI.Backtest import (
    _load_strategy, INIT_CAPITAL, _stock_return, _limit_ratio, _limit_price, STOCK_SELL_STOP,
    _stock_return_5m, _sell_price_5m, _sell_price_1d, _trade_net_return,
)
from AICode.MarcoAPI.Update.Path import (
    PATH_AIDATA_STRATEGY, PATH_AIDATA_TARGET, PATH_AIDATA_1D_ORIGIN, PATH_AIDATA, PATH_AIDATA_TOP,
    PATH_AIDATA_TOP_FIRST, PATH_AIDATA_TOP_FIRST_VOL, PATH_AIDATA_TOP_FIRST_VOL_SUN, PATH_AIDATA_5M,
    PATH_AIDATA_INDEX_ORIGIN,
)
from AICode.MarcoAPI.Update.Update1D import UPDATE_ALL
from AICode.MarcoAPI.Update.SZ2001D import GET_SZ200_1D_PREVIOUS, UPDATE_1D_ORIGIN, UPDATE_1D
from AICode.MarcoAPI.Update.SZ200Index import UPDATE_INDEX_CODES, UPDATE_INDEX_1D_ORIGIN, UPDATE_INDEX_1D, INDEX_CODES, GET_INDEX_NAME
from AICode.MarcoAPI.Update.SZ200Strategy import BUILD_SENTIMENT_KLINE
from AICode.MarcoAPI.Update.StockCodes import GET_STOCK_INFO, UPDATE_STOCK_CODES
from AICode.MarcoAPI.Update.TradingDates import UPDATE_TRADING_DATES
from AICode.MarcoAPI.Update.SZ200Top import UPDATE_TOP, UPDATE_TOP_FIRST, UPDATE_TOP_FIRST_VOL, UPDATE_TOP_FIRST_VOL_SUN
from AICode.MarcoAPI.Update.SZ200Strategy import (
    UPDATE_STRATEGY_TPO_3, UPDATE_STRATEGY_TPO_TOP, UPDATE_STRATEGY_TPO_M5,
)
from AICode.MarcoAPI.Update.SZ200Target import (
    UPDATE_TARGET_TPO_3, UPDATE_TARGET_TPO_TOP, UPDATE_TARGET_TPO_M5,
)
from AICode.MarcoAPI.Update.SZ2005M import UPDATE_5M_ORIGIN

# K 线内嵌【全部历史】日线（1D_ORIGIN 有多少就嵌多少，不再截断到 120 根）

# 同花顺板块 XML：模板与拷贝目标目录（实盘机）
THS_TEMPLATE_FILE = PATH_AIDATA() + "/THS/blockstockV3.xml"
# 目标目录为同花顺安装路径（外部软件），可用环境变量 THS_TARGET_DIR 覆盖
THS_TARGET_DIR = os.environ.get("THS_TARGET_DIR", r"C:\同花顺远航版\bin\users\狗蛋儿家的金")
THS_BLOCK_NAME = "blockstockV3.xml"

# 板块占位符
PLACEHOLDER_TPO3  = "===TPO3==="
PLACEHOLDER_TPO31 = "===TPO31==="
PLACEHOLDER_TOP   = "===TOP==="   # 当天（最新交易日）涨停股
PLACEHOLDER_HIS    = "===HIS==="   # 最近 5 日首板涨停放量股（TAB: 首板涨停放量股），剔除首板日后其它日又涨停的股


def _read_text(path):
    raw = open(path, "rb").read()
    for enc in ("utf-8", "gbk", "gb2312", "latin-1"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="ignore")


def _to_float(v: str) -> float:
    try:
        return float(v)
    except (ValueError, TypeError):
        return 0.0


def _load_strategy_detail(strategies: list[str]) -> dict[str, dict[str, list[dict[str, object]]]]:
    """加载各策略每天的选股详情，返回 {策略: {日期: [{code,name,market,open,high,low,close,pre,vol,amount,chg}]}}"""
    out: dict[str, dict[str, list[dict[str, object]]]] = {}
    for name in strategies:
        daily = _load_strategy(name)
        detail: dict[str, list[dict[str, object]]] = {}
        for date in sorted(daily):
            rows = []
            for r in daily[date]:
                if len(r) < 11:
                    continue
                close = _to_float(r[7])
                pre = _to_float(r[10])
                sp_1d = _sell_price_1d(r)            # 日线实际卖出价
                sp_5m = _sell_price_5m(r)            # 5 分钟 K 线日内卖出价
                net_1d = _trade_net_return(pre, sp_1d, INIT_CAPITAL) if (sp_1d is not None and pre > 0) else None
                net_5m = _trade_net_return(pre, sp_5m, INIT_CAPITAL) if (sp_5m is not None and pre > 0) else None
                item = {
                    "code": r[0],
                    "name": r[1] if len(r) > 1 else "",
                    "market": r[2] if len(r) > 2 else "",
                    "open": _to_float(r[4]),
                    "high": _to_float(r[5]),
                    "low": _to_float(r[6]),
                    "close": close,
                    "pre": pre,
                    "vol": _to_float(r[8]),
                    "amount": _to_float(r[9]),
                    "chg": round((close - pre) / pre * 100, 2) if pre else 0.0,
                    "sell_chg": round(net_1d * 100, 2) if net_1d is not None else 0.0,
                    "sell_chg_5m": round(net_5m * 100, 2) if net_5m is not None
                    else (round(net_1d * 100, 2) if net_1d is not None else 0.0),
                }
                rows.append(item)
            detail[date] = rows
        out[name] = detail
    return out


def _touched_limit(cols: list[str]) -> bool:
    """当日是否「摸到涨停」：最高价 >= 涨停价（前收 × 涨跌幅限制，主板10%/创业板20%）。

    与回测 Backtest._sell_price_1d / _sell_price_5m 的涨停卖规则同源（high >= limit_p），
    盘中触板但未封板（is_top==0）同样算摸到，因为回测此时已按涨停价卖出。
    数据无效（缺列/前收<=0）返回 False。
    """
    try:
        code = cols[0]
        high = float(cols[5])
        pre_close = float(cols[10])
    except (ValueError, IndexError, TypeError):
        return False
    if pre_close <= 0:
        return False
    return high >= _limit_price(pre_close, _limit_ratio(code))


def _build_strategy_payload(strategy_name: str, sell_mode: str = "5m") -> dict[str, object]:
    """构建单个策略的回测数据（first：每日买入第一只股票即市值最大；
    sell_mode="5m" 用 5 分钟 K 线日内卖出，sell_mode="day" 用日线 O/H/L/C 卖出。

    返回:
        name: 策略名
        dates: 卖出日列表（升序）
        capital: 资金曲线（first，复利）
        total: 总收益率
        final: 最终资金
        month/quarter/year: 每月/季度/年收益（first）
        month_trades: 每月交易次数（当日有票即 1 笔；无交易的月份不含该键）
        month_tops: 每月「摸到涨停」个数（当日最高价触及涨停价即算，不要求收盘封板）
        kline: 资金 K 线 [{time,open,high,low,close,volume,pre_close}]，
               每根蜡烛为当日资金 OHLC（由 O/C/H/L 涨跌幅 × 前收资金复利算出），时间 YYYY-MM-DD
        dist: {open,high,low,close} 四组每日涨跌幅序列（相对前收）
    """
    daily = _load_strategy(strategy_name)
    dates = sorted(daily)

    # 资金曲线 + 区间收益（复利，first：每日买入第一只，即市值最大）
    capital = INIT_CAPITAL
    capitals = []
    rets = []        # 每日收益（对应 dates 顺序）
    month = {}
    quarter = {}
    year = {}
    month_trades = {}  # 每月交易次数（当日有票即算 1 笔，策略每日最多买 1 只）
    month_tops = {}    # 每月「抓到涨停」个数（当日买入股在 T-0 涨停，即数据第 12 列 is_top==1）
    kline = []      # 资金 K 线：每根蜡烛为当日资金 OHLC（由涨跌幅×前收资金复利算出）
    dist = {"open": [], "high": [], "low": [], "close": []}
    prev_capital = INIT_CAPITAL  # 前收资金（首日 = 起始资金）
    for date in dates:
        rows = daily[date]
        if not rows:
            # 无票日期：资金不动，K线/涨跌幅留空占位
            capitals.append(round(capital, 2))
            rets.append(0.0)
            kline.append(None)
            for k in dist:
                dist[k].append(None)
            continue
        first = rows[0]  # 每日买入第一只（first 模式）
        # T-0 卖出方式：5m = 5 分钟 K 线日内卖出；day = 日线 O/H/L/C
        if sell_mode == "5m":
            sell_price = _sell_price_5m(first)
            if sell_price is None:  # 缺 5M 数据则回退日线
                sell_price = _sell_price_1d(first)
        else:
            sell_price = _sell_price_1d(first)
        try:
            pre = float(first[10])
        except (ValueError, IndexError):
            pre = 0.0
        # 净收益：万1免5 佣金（买卖双边）+ 千0.5 印花税（卖出），满仓 10 万
        net_ret = _trade_net_return(pre, sell_price, capital) if (sell_price is not None and pre > 0) else 0.0
        capital *= (1.0 + net_ret)
        capitals.append(round(capital, 2))
        rets.append(net_ret)

        # 区间复利收益
        ym = date[:6]
        month[ym] = month.get(ym, 1.0) * (1 + net_ret)
        month_trades[ym] = month_trades.get(ym, 0) + 1
        # 摸到涨停：当日【最高价触及涨停价】即算（与回测「涨停卖」规则一致：high >= 涨停价），
        # 不要求收盘封板（is_top==1 只是封板，会漏掉盘中触板又打开的票）
        month_tops[ym] = month_tops.get(ym, 0) + (1 if _touched_limit(first) else 0)
        qm = _quarter_of(date)
        quarter[qm] = quarter.get(qm, 1.0) * (1 + net_ret)
        y = date[:4]
        year[y] = year.get(y, 1.0) * (1 + net_ret)

        # 资金 K 线：开盘按开盘价、收盘按实际卖出价（与 _stock_return 一致）换算成资金
        try:
            t = date[:4] + '-' + date[4:6] + '-' + date[6:8]
            open_p = float(first[4])
            high = float(first[5])
            low = float(first[6])
            close = float(first[7])
            pre = float(first[10])
            volume = float(first[8])
            if pre > 0 and sell_price is not None:
                k_open = prev_capital * (1 + (open_p - pre) / pre)
                k_high = prev_capital * (1 + (high - pre) / pre)
                k_low = prev_capital * (1 + (low - pre) / pre)
                k_close = prev_capital * (1 + net_ret)  # 收盘资金按净收益（含手续费）
                kline.append({
                    "time": t, "open": round(k_open, 2), "high": round(k_high, 2),
                    "low": round(k_low, 2), "close": round(k_close, 2),
                    "volume": volume, "pre_close": round(prev_capital, 2),
                })
                prev_capital = k_close  # 复利：当日收盘资金作为次日前收资金
                # O/C/H/L 涨跌幅（相对前收）
                dist["open"].append((open_p - pre) / pre)
                dist["high"].append((high - pre) / pre)
                dist["low"].append((low - pre) / pre)
                dist["close"].append((close - pre) / pre)
            else:
                kline.append(None)
                for k in dist:
                    dist[k].append(None)
        except (ValueError, IndexError):
            kline.append(None)
            for k in dist:
                dist[k].append(None)

    month = {k: round(v - 1, 6) for k, v in month.items()}
    quarter = {k: round(v - 1, 6) for k, v in quarter.items()}
    year = {k: round(v - 1, 6) for k, v in year.items()}

    return {
        "name": strategy_name,
        "dates": dates,
        "capitals": capitals,
        "rets": rets,
        "total": round(capital / INIT_CAPITAL - 1.0, 6),
        "final": round(capital, 2),
        "month": month,
        "month_trades": month_trades,
        "month_tops": month_tops,
        "quarter": quarter,
        "year": year,
        "kline": kline,
        "dist": dist,
    }


def _sell_price(cols: list[str]) -> float | None:
    """按实际卖出规则计算卖出价（与 Backtest._stock_return 一致的优先级）：
      1. 开盘涨跌幅 < -6%        -> 按开盘价卖出
      2. 最低价涨跌幅 < -6%      -> 按 -6% 止损卖出
      3. 最高价触及涨停价        -> 按涨停价卖出
      4. 以上都不满足            -> 按收盘价卖出
    返回卖出价；数据无效返回 None。
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
    # 规则1：开盘 < -6% -> 开盘价
    if (open_p - pre_close) / pre_close < STOCK_SELL_STOP:
        return open_p
    # 规则2：最低 < -6% -> -6% 止损价
    if (low - pre_close) / pre_close < STOCK_SELL_STOP:
        return pre_close * (1 + STOCK_SELL_STOP)
    # 规则3：最高触涨停 -> 涨停价
    limit_p = _limit_price(pre_close, _limit_ratio(code))
    if high >= limit_p:
        return limit_p
    # 规则4：收盘价
    return close


def _quarter_of(date: str) -> str:
    q = (int(date[4:6]) - 1) // 3 + 1
    return f"{date[:4]}Q{q}"


def _list_strategies() -> list[str]:
    base = PATH_AIDATA_STRATEGY()
    if not os.path.isdir(base):
        return []
    # 排除 RESULT 与 _rotate_dir 产生的 .old_ 备份目录（否则会被当成策略列进下拉框）
    names = [d for d in os.listdir(base)
             if os.path.isdir(os.path.join(base, d)) and d != "RESULT" and ".old_" not in d]
    # 已下线的策略目录不再出现在看板（数据/管线保留，便于回滚）：TPO_M5_MID、TPO_M5_SMALL
    _excluded = ("TPO_M5_MID", "TPO_M5_SMALL")
    names = [n for n in names if n not in _excluded]
    # TPO_M5 系列（大市值档）优先排前，其余按字母序
    _m5 = ("TPO_M5",)
    ordered = [n for n in _m5 if n in names]
    rest = sorted(n for n in names if n not in _m5)
    return ordered + rest


def _load_candidates(strategy_name: str) -> dict[str, list[list[str]]]:
    """读取策略候选池 {日期: [[code, name, market], ...]}（日期倒序，默认最新）"""
    base = PATH_AIDATA_TARGET(strategy_name)
    if not os.path.isdir(base):
        return {}
    candidates = {}
    for f in sorted(os.listdir(base)):      # 排序：os.listdir 顺序不稳定，排序保证结果可复现
        if not f.isdigit():
            continue
        rows = []
        for line in _read_text(os.path.join(base, f)).splitlines():
            line = line.strip()
            if not line:
                continue
            cols = line.split("|")
            code = cols[0]
            name = cols[1] if len(cols) > 1 else ""
            market_value = cols[2] if len(cols) > 2 else ""
            rows.append([code, name, market_value])
        # 即使目录为空（无候选股）也保留日期，方便查看当日是否有票
        candidates[f] = rows
    # 倒序（默认显示最新）
    return dict(sorted(candidates.items(), key=lambda x: x[0], reverse=True))


def _stock_close_map(code: str) -> dict[str, float]:
    """读取个股 1D_ORIGIN，构建 {YYYYMMDD: close} 映射"""
    path = os.path.join(PATH_AIDATA_1D_ORIGIN(), code)
    if not os.path.exists(path):
        return {}
    closes = {}
    for line in _read_text(path).splitlines():
        parts = line.split("|")
        if len(parts) >= 5 and parts[0].isdigit():
            try:
                closes[parts[0]] = float(parts[4])  # r[4] 是 close
            except ValueError:
                continue
    return closes


def _load_top() -> dict[str, list[list[str]]]:
    """读取涨停列表 {日期: [[code, name, market_value], ...]}。

    按市值（流通股本×当日收盘价）倒序排列；日期倒序（默认最新）。
    """
    base = PATH_AIDATA_TOP()
    if not os.path.isdir(base):
        return {}
    top = {}
    close_cache: dict[str, dict[str, float]] = {}
    for date in sorted(os.listdir(base)):
        if not date.isdigit():
            continue
        path = os.path.join(base, date)
        codes = [line.strip() for line in _read_text(path).splitlines() if line.strip()]
        rows = []
        for code in codes:
            norm = code if "." in code else (f"{code}.SH" if code.startswith("6") else f"{code}.SZ")
            info = GET_STOCK_INFO(norm)
            if info is None or info[1] <= 0:
                continue
            closes = close_cache.get(norm)
            if closes is None:
                closes = _stock_close_map(norm)
                close_cache[norm] = closes
            close = closes.get(date)
            if close is None or close <= 0:
                continue
            name = info[0]
            market_value = float(info[1]) * close
            rows.append([norm, name, f"{market_value:.2f}"])
        # 按市值倒序
        rows.sort(key=lambda r: float(r[2]), reverse=True)
        top[date] = rows
    # 日期倒序（默认最新）
    return dict(sorted(top.items(), key=lambda x: x[0], reverse=True))


def _load_top_first() -> dict[str, list[list[str]]]:
    """读取首板涨停列表 {日期: [[code, name, market_value], ...]}（来自 AIData/TOP_FIRST）。

    格式与 _load_top 完全一致（仅数据源改为 TOP_FIRST），按流通市值倒序、日期倒序。
    """
    base = PATH_AIDATA_TOP_FIRST()
    if not os.path.isdir(base):
        return {}
    top_first: dict[str, list[list[str]]] = {}
    close_cache: dict[str, dict[str, float]] = {}
    for date in sorted(os.listdir(base)):
        if not date.isdigit():
            continue
        path = os.path.join(base, date)
        codes = [line.strip() for line in _read_text(path).splitlines() if line.strip()]
        rows = []
        for code in codes:
            norm = code if "." in code else (f"{code}.SH" if code.startswith("6") else f"{code}.SZ")
            info = GET_STOCK_INFO(norm)
            if info is None or info[1] <= 0:
                continue
            closes = close_cache.get(norm)
            if closes is None:
                closes = _stock_close_map(norm)
                close_cache[norm] = closes
            close = closes.get(date)
            if close is None or close <= 0:
                continue
            name = info[0]
            market_value = float(info[1]) * close
            rows.append([norm, name, f"{market_value:.2f}"])
        rows.sort(key=lambda r: float(r[2]), reverse=True)
        top_first[date] = rows
    return dict(sorted(top_first.items(), key=lambda x: x[0], reverse=True))


def _load_top_first_vol() -> dict[str, list[list[str]]]:
    """读取首板涨停放量股 {日期: [[code, name, market_value], ...]}（来自 AIData/TOP_FIRST_VOL）。

    与 _load_top/_load_top_first 格式一致（按流通市值倒序、日期倒序），但**不做市值筛选**：
    市值仅用于展示与排序；缺少流通股本或收盘价的个股仍保留（市值记 0），
    因为本 TAB 的定义就是忽略市值条件。
    """
    base = PATH_AIDATA_TOP_FIRST_VOL()
    if not os.path.isdir(base):
        return {}
    out: dict[str, list[list[str]]] = {}
    close_cache: dict[str, dict[str, float]] = {}
    for date in sorted(os.listdir(base)):
        if not date.isdigit():
            continue
        path = os.path.join(base, date)
        codes = [line.strip() for line in _read_text(path).splitlines() if line.strip()]
        rows = []
        for code in codes:
            norm = code if "." in code else (f"{code}.SH" if code.startswith("6") else f"{code}.SZ")
            info = GET_STOCK_INFO(norm)
            name = info[0] if info else norm
            market_value = 0.0
            if info is not None and info[1] > 0:
                closes = close_cache.get(norm)
                if closes is None:
                    closes = _stock_close_map(norm)
                    close_cache[norm] = closes
                close = closes.get(date)
                if close is not None and close > 0:
                    market_value = float(info[1]) * close
            rows.append([norm, name, f"{market_value:.2f}"])
        rows.sort(key=lambda r: float(r[2]), reverse=True)
        out[date] = rows
    return dict(sorted(out.items(), key=lambda x: x[0], reverse=True))


def _load_top_first_vol_sun() -> dict[str, list[list[str]]]:
    """读取首板涨停放量连阳股 {日期: [[code, name, market_value], ...]}（来自 AIData/TOP_FIRST_VOL_SUN）。

    与 _load_top_first_vol 同口径（不做市值筛选，市值仅用于展示/排序），只是多了 T-1 收>开 + T-1 创新高
    两个过滤条件。格式、排序与 _load_top_first_vol 完全一致。
    """
    base = PATH_AIDATA_TOP_FIRST_VOL_SUN()
    if not os.path.isdir(base):
        return {}
    out: dict[str, list[list[str]]] = {}
    close_cache: dict[str, dict[str, float]] = {}
    for date in sorted(os.listdir(base)):
        if not date.isdigit():
            continue
        path = os.path.join(base, date)
        codes = [line.strip() for line in _read_text(path).splitlines() if line.strip()]
        rows = []
        for code in codes:
            norm = code if "." in code else (f"{code}.SH" if code.startswith("6") else f"{code}.SZ")
            info = GET_STOCK_INFO(norm)
            name = info[0] if info else norm
            market_value = 0.0
            if info is not None and info[1] > 0:
                closes = close_cache.get(norm)
                if closes is None:
                    closes = _stock_close_map(norm)
                    close_cache[norm] = closes
                close = closes.get(date)
                if close is not None and close > 0:
                    market_value = float(info[1]) * close
            rows.append([norm, name, f"{market_value:.2f}"])
        rows.sort(key=lambda r: float(r[2]), reverse=True)
        out[date] = rows
    return dict(sorted(out.items(), key=lambda x: x[0], reverse=True))


def _load_kline(codes: set[str], names: dict[str, str] | None = None, max_days: int | None = None,
                origin_dir: str | None = None) -> dict[str, dict[str, Any]]:
    """读取候选股的【全部历史】原始日线（默认 1D_ORIGIN；指数传 INDEX_ORIGIN）。

    仅传原始 OHLCV，所有指标（MA/MACD/KDJ/BOLL/VWAP）与月线聚合
    均由前端 JS 动态计算，便于配置切换。names 提供 code->股票名称。
    max_days>0 时仅保留最近 N 条（用于涨停股等数据量大、且只需近期走势的场景，减小 payload）。
    origin_dir 指定原始日线目录（默认 PATH_AIDATA_1D_ORIGIN；指数传 PATH_AIDATA_INDEX_ORIGIN）。
    """
    names = names or {}
    kline = {}
    origin_dir = origin_dir or PATH_AIDATA_1D_ORIGIN()
    # 按代码排序遍历：codes 是 set，直接遍历顺序不稳定，会导致两次生成的
    # payload（在线/离线）字节不一致（内容相同但键顺序不同），排序保证可复现
    for code in sorted(codes):
        path = os.path.join(origin_dir, code)
        if not os.path.exists(path):
            continue
        lines = _read_text(path).splitlines()
        rows = [l.split("|") for l in lines if l.strip() and len(l.split("|")) >= 6]
        if max_days and max_days > 0 and len(rows) > max_days:
            rows = rows[-max_days:]
        ohlcv = []
        prev_close = None
        for r in rows:
            # r[0] 是 YYYYMMDD（如 20260105），LightweightCharts 要求 YYYY-MM-DD
            t = r[0][:4] + '-' + r[0][4:6] + '-' + r[0][6:8]
            close = float(r[4])
            ohlcv.append({
                "time": t, "open": float(r[1]), "high": float(r[2]),
                "low": float(r[3]), "close": close, "volume": float(r[5]),
                "pre_close": prev_close if prev_close is not None else float(r[1]),
            })
            prev_close = close
        kline[code] = {"ohlcv": ohlcv, "name": names.get(code, code)}
    return kline


def _read_5m_window(code: str, anchor_date: str, days_before: int = 5, days_span: int = 8) -> list[list]:
    """读取单只股票 5 分钟 K 线，截取其「重要日期(T)前 5 个交易日」起、最多 8 个交易日的窗口。

    返回紧凑数组 [unix_seconds, open, high, low, close, volume]（unix 秒，前端直接作为 time 使用），
    避免把全部 5M 历史塞进 HTML。
    """
    path = os.path.join(PATH_AIDATA_5M(), code)
    if not os.path.isfile(path):
        return []
    try:
        if len(anchor_date or "") == 8 and str(anchor_date).isdigit():
            a = _dt.datetime.strptime(anchor_date, "%Y%m%d").date()
        else:
            a = _dt.datetime.strptime(anchor_date, "%Y-%m-%d").date()
    except Exception:
        a = None
    raw: list[tuple] = []
    for line in _read_text(path).splitlines():
        p = line.split("|")
        if len(p) < 6:
            continue
        ts = p[0].strip()
        if not ts:
            continue
        try:
            dt = _dt.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
            vals = [float(p[1]), float(p[2]), float(p[3]), float(p[4]), float(p[5])]
        except (ValueError, TypeError):
            continue
        raw.append((dt, vals))
    if not raw:
        return []
    udays = sorted({d.date() for d, _ in raw})
    idx = None
    for i, d in enumerate(udays):
        if a is not None and d >= a:
            idx = i
            break
    if idx is None:
        idx = len(udays) - 1
    start = max(0, idx - days_before)
    end = min(len(udays), start + days_span)
    keep = set(udays[start:end])
    bars: list[list] = []
    for dt, vals in raw:
        if dt.date() in keep:
            bars.append([int(dt.timestamp()), round(vals[0], 2), round(vals[1], 2),
                         round(vals[2], 2), round(vals[3], 2), round(vals[4], 0)])
    return bars


def _read_5m_windows(code: str, anchors: list[str], days_before: int = 5, days_span: int = 8,
                     days_after: int | None = None) -> dict[str, list]:
    """一次读取某股 5M 文件，为多个锚定日期各切一个窗口，返回 {锚定日: bars}。

    默认窗口口径与 `_read_5m_window` 一致（锚定日前 5 个交易日起、最多 8 个交易日）。

    days_after 给定时启用「居中」：让锚定日尽量落在窗口中间（前面 days_span-1-days_after 天、
    后面 days_after 天）。若锚定日之后的数据不足（如最新日期没有未来数据），自动向前补足，
    保证窗口总长度不变、仍能看满上下文。

    只解析一次文件：涨停/首板要按出现日期批量生成窗口，若逐日调用原函数会产生上万次
    重复读盘，明显拖慢一条龙更新。
    """
    path = os.path.join(PATH_AIDATA_5M(), code)
    if not os.path.isfile(path):
        return {}
    raw: list[tuple] = []
    for line in _read_text(path).splitlines():
        p = line.split("|")
        if len(p) < 6:
            continue
        ts = p[0].strip()
        if not ts:
            continue
        try:
            dt = _dt.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
            vals = [float(p[1]), float(p[2]), float(p[3]), float(p[4]), float(p[5])]
        except (ValueError, TypeError):
            continue
        raw.append((dt, vals))
    if not raw:
        return {}
    by_day: dict = {}
    for dt, vals in raw:
        by_day.setdefault(dt.date(), []).append((dt, vals))
    udays = sorted(by_day.keys())
    out: dict[str, list] = {}
    for anchor in anchors:
        try:
            if len(str(anchor or "")) == 8 and str(anchor).isdigit():
                a = _dt.datetime.strptime(str(anchor), "%Y%m%d").date()
            else:
                a = _dt.datetime.strptime(str(anchor), "%Y-%m-%d").date()
        except Exception:
            continue
        idx = None
        for i, d in enumerate(udays):
            if d >= a:
                idx = i
                break
        if idx is None:
            idx = len(udays) - 1
        if days_after is not None:
            # 居中：锚定日后保留 days_after 天；后面不够（如最新日期）就自动向前补足
            after = max(0, min(days_after, len(udays) - 1 - idx))
            before = max(0, days_span - 1 - after)
        else:
            before = days_before
        start = max(0, idx - before)
        end = min(len(udays), start + days_span)
        bars: list[list] = []
        for day in udays[start:end]:
            for dt, vals in by_day.get(day, []):
                bars.append([int(dt.timestamp()), round(vals[0], 2), round(vals[1], 2),
                             round(vals[2], 2), round(vals[3], 2), round(vals[4], 0)])
        if bars:
            out[str(anchor)] = bars
    return out


def _build_five_min(strategies: list[str]) -> dict[str, dict]:
    """离线内嵌用：为「策略选股详情」出现的个股生成【按日期精确命中】的 5 分钟窗口，控制 HTML 体积、加快加载。

    返回 five_min[code] = { 窗口键: bars }：
      - "YYYY-MM-DD"：该股票在策略选股中出现的具体日期(T-0)窗口，离线点击即精确命中、包含当天 5 分钟；
      - "__default__"：该股出现的最晚日期窗口，作为兜底（部分同时出现在候选池/涨停股面板的回退）。
    涨停股 / 首板面板此前不内嵌 5 分钟（离线右侧图显示提示）。现由 `_extend_five_min_top` 为其个股补 `__default__`
    最新窗口，使其离线也能看 5 分钟图（无 5M 文件的个股仍走离线提示）。
    窗口长度固定 T-3 起 8 个交易日（首日为 T-3 首板涨停日），与日线图对齐；在线模式经 /api/5m 取数不受此限。
    """
    detail_dates: dict[str, set[str]] = {}
    detail = _load_strategy_detail(strategies)
    for _d in detail.values():
        for _date_key, _rows in _d.items():
            for _it in _rows:
                c = str(_it.get("code") or "")
                if c:
                    detail_dates.setdefault(c, set()).add(_date_key)
    five_min: dict[str, dict] = {}
    for code, dates in detail_dates.items():
        out: dict[str, list] = {}
        latest = max(dates)   # 兜底锚：该股最晚出现日
        out["__default__"] = _read_5m_window(code, latest, days_before=3)
        for dt in dates:
            dash = f"{dt[:4]}-{dt[4:6]}-{dt[6:8]}"   # 与前端 ymdDash 一致，便于离线精确命中
            out[dash] = _read_5m_window(code, dt, days_before=3)
        out = {k: v for k, v in out.items() if v}
        if out:
            five_min[code] = out
    return five_min


def _collect_code_dates(tab: dict) -> dict[str, set[str]]:
    """把涨停/首板数据 {日期YYYYMMDD: [[code, name, market], ...]} 整理成 {股票代码: {日期集合}}，
    用于按其各自出现的日期精确生成 5 分钟窗口。"""
    m: dict[str, set[str]] = {}
    for date_key, rows in (tab or {}).items():
        for r in rows or []:
            code = str(r[0]) if r else ""
            if code:
                m.setdefault(code, set()).add(str(date_key))
    return m


def _extend_five_min_top(code_dates: dict[str, set[str]], five_min: dict[str, dict]) -> None:
    """为涨停股 / 首板个股生成【按出现日期精确命中】的 5 分钟窗口（与策略选股口径一致）。

    为该股在涨停/首板中出现的每一个日期各切一个窗口（含当天的 5 分钟），因此点击历史某日
    会命中当日的 5 分钟区间，范围正确。__default__ 仍保留最晚日期窗口作兜底。

    注意：早期版本只补 __default__（最新窗口），导致点击历史日期时命不中、回退显示最新区间
    ——这正是「涨停/首板 5 分钟显示范围错误」的原因；此处已修正为按日期精确生成。
    """
    for code, dates in sorted(code_dates.items()):
        if not dates:
            continue
        anchors = sorted(dates)
        # 居中窗口：涨停/首板当天尽量落在区间中间（后 4 个交易日、前 3 个交易日）；
        # 当天之后数据不足时（如最新日期）自动向前补足，窗口长度仍为 8 个交易日。
        windows = _read_5m_windows(code, anchors, days_span=8, days_after=4)
        if not windows:
            continue
        out: dict[str, list] = {}
        for dt in anchors:
            dash = f"{dt[:4]}-{dt[4:6]}-{dt[6:8]}"   # 与前端 ymdDash 一致，便于离线精确命中
            if windows.get(dt):
                out[dash] = windows[dt]
        if windows.get(anchors[-1]):
            out.setdefault("__default__", windows[anchors[-1]])
        if not out:
            continue
        existing = five_min.get(code)
        if existing:
            merged = dict(existing)
            for k, v in out.items():
                merged.setdefault(k, v)      # 策略选股已生成的窗口优先保留
            five_min[code] = merged
        else:
            five_min[code] = out


# 左侧快捷命令侧边栏：命令按钮依赖本地服务 / marcoai:// 自定义协议，
# 离线单文件拷到别的机器后这些按钮无意义，故离线看板不再输出（show_sidebar=False）。
_SIDEBAR_HTML = """<!-- ============ 左侧快捷命令侧边栏 ============ -->
<div class="sidebar">
  <div class="brand">MarcoAI 控制台<small>策略回测 &amp; 实盘看板</small></div>
  <div class="section">数据更新</div>
  <div class="cmds" id="cmd-list"></div>
  <div class="section">单项数据更新</div>
  <div class="cmds" id="cmd-steps"></div>
  <div class="cmd-output">
    <div class="label">命令输出</div>
    <pre id="cmd-output"></pre>
  </div>
</div>
"""


def OFFLINE_DASHBOARD_PATH() -> str:
    """离线看板 HTML 的绝对路径。"""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "UI", "StrategyDashboardOffline.html")


def _source_data_mtime() -> float:
    """扫描源数据目录(AIData)下所有文件的最新修改时间。

    用于判断离线看板是否已过期：只有源数据真的变动过才需要重建。
    （重建要扫描全部个股的 5M 数据并写出数百 MB，耗时数分钟，应避免不必要的触发。）
    """
    latest = 0.0
    root = PATH_AIDATA()
    if not os.path.isdir(root):
        return latest
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            try:
                m = os.path.getmtime(os.path.join(dirpath, fn))
            except OSError:
                continue
            if m > latest:
                latest = m
    return latest


def OFFLINE_DASHBOARD_STATUS() -> tuple[bool, str]:
    """返回 (是否最新, 说明文字)。

    菜单「离线看板」据此判断能否直接打开：看板已是最新时无需重建，打开即为秒开。
    源数据在上次生成之后被修改过，则需要重新生成。
    """
    html = OFFLINE_DASHBOARD_PATH()
    meta = html + ".meta.json"
    if not os.path.isfile(html):
        return False, "尚未生成离线看板"
    if not os.path.isfile(meta):
        return False, "看板元信息缺失（将重新生成）"
    try:
        with open(meta, "r", encoding="utf-8") as f:
            saved = json.load(f)
        saved_m = float(saved.get("src_mtime", 0))
        gen = saved.get("generated", "未知时间")
    except Exception:
        return False, "看板元信息损坏（将重新生成）"
    cur = _source_data_mtime()
    if cur > saved_m + 1.0:
        return False, f"源数据已更新，需重新生成（看板生成于 {gen}）"
    return True, f"已是最新，直接打开（生成于 {gen}）"


def _write_offline_data(here: str, data: dict) -> None:
    """离线零内嵌：把看板数据写到 UI/data/ 伴随文件（HTML 不内嵌任何数据）。

    - index.js：骨架（strategies/backtest/candidates/top/top_first/strategy_detail/sentiment）
                + 空的 kline/fiveMin + 加载基路径 _stockBase；
    - stock/<code>.js：每只股票的日线(kline) 与 5 分钟(fiveMin) 窗口。
    HTML 经 <script src="data/index.js"> 同步加载骨架，点击个股时再按需注入 data/stock/<code>.js。
    """
    data_dir = os.path.join(here, "UI", "data")
    stock_dir = os.path.join(data_dir, "stock")
    os.makedirs(stock_dir, exist_ok=True)
    # 不清空旧文件：存在的会被直接覆盖；个别已下线个股的残留文件也不会被 index.js 引用，
    # 且避免每次构建都批量删除两千多个文件（触发批量删除保护、也拖慢一条龙）。
    # 首屏（策略回测）只需的最小骨架；其余 TAB 的数据拆成独立文件，首次进入该 TAB 才加载，
    # 避免开页时被这些看不见的面板拖慢（index.js 由 1.42MB 降到约 0.25MB）
    index_data = {
        "strategies": data.get("strategies", []),
        "backtest": data.get("backtest", {}),
        "sentiment": data.get("sentiment", {}),
        "top": {}, "top_first": {}, "top_first_vol": {}, "top_first_vol_sun": {}, "candidates": {}, "strategy_detail": {},   # 占位，进对应 TAB 后填充
        "kline": {},
        "fiveMin": {},
        "index_kline": data.get("index_kline", {}),
        "_stockBase": "data/stock/",
        "_stockChunks": 64,
    }
    with open(os.path.join(data_dir, "index.js"), "w", encoding="utf-8") as f:
        f.write("window.__IDX = " + json.dumps(index_data, ensure_ascii=False) + ";\n")

    # 按 TAB 拆分的数据文件：加载后把占位填充进 window.__IDX
    for fname, key in (("top.js", "top"), ("top_first.js", "top_first"),
                       ("top_first_vol.js", "top_first_vol"),
                       ("top_first_vol_sun.js", "top_first_vol_sun"),
                       ("candidates.js", "candidates"), ("detail.js", "strategy_detail")):
        with open(os.path.join(data_dir, fname), "w", encoding="utf-8") as f:
            f.write("Object.assign(window.__IDX, "
                    + json.dumps({key: data.get(key, {})}, ensure_ascii=False) + ");\n")
    kline = data.get("kline", {}) or {}
    five_min = data.get("fiveMin", {}) or {}
    all_codes = sorted(set(kline.keys()) | set(five_min.keys()))
    # 个股数据分块落盘：按 code 稳定哈希分成 _stockChunks 块（每块约 36 只、~6MB）。
    # 避免 Windows 下逐个创建 2300+ 小文件的巨大开销（生成快 ~36 倍），同时保留点击按需加载：
    # 点一只股票只加载其所在块，同块后续点击直接命中内存、零请求。
    STOCK_CHUNKS = 64
    # 清理上一代「每只一个文件」的残留（仅过渡期一次；之后目录里只有 chunk_*.js，本步为空操作）
    for fn in os.listdir(stock_dir):
        if not fn.startswith("chunk_"):
            try:
                os.remove(os.path.join(stock_dir, fn))
            except OSError:
                pass
    chunks = {i: [] for i in range(STOCK_CHUNKS)}
    for code in all_codes:
        h = 0
        for ch in code:
            h = (h * 31 + ord(ch)) & 0xFFFFFFFF
        chunks[h % STOCK_CHUNKS].append(code)
    for ci, codes in chunks.items():
        if not codes:
            continue
        sf = os.path.join(stock_dir, "chunk_%d.js" % ci)
        with open(sf, "w", encoding="utf-8") as f:
            f.write("window.__STK = window.__STK || {};\n")
            for code in codes:
                obj = {"kline": kline.get(code), "fiveMin": five_min.get(code, {})}
                f.write("window.__STK[%s] = %s;\n" % (json.dumps(code), json.dumps(obj, ensure_ascii=False)))
    print(f"STRATEGY_UI: 离线数据已写出 {len(all_codes)} 只个股(分 {STOCK_CHUNKS} 块)到 {stock_dir}")


def _render_html(data: dict[str, Any], show_sidebar: bool = True, external: bool = False) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    strategies_json = json.dumps(data.get("strategies", []), ensure_ascii=False)
    sidebar_html = _SIDEBAR_HTML if show_sidebar else ""
    html = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<script>window.__P={{t0:performance.now(),loads:[]}};</script>
<meta charset="utf-8">
<meta http-equiv="Cache-Control" content="no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>策略回测 & 实盘目标股看板</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='14' fill='%230f172a'/%3E%3Crect width='64' height='64' rx='14' fill='url(%23g)'/%3E%3Cdefs%3E%3ClinearGradient id='g' x1='0' y1='0' x2='64' y2='64'%3E%3Cstop offset='0' stop-color='%232b6cb0'/%3E%3Cstop offset='1' stop-color='%231d4ed8'/%3E%3C/linearGradient%3E%3C/defs%3E%3Cpath d='M16 44 L26 34 L34 40 L48 24' stroke='white' stroke-width='4' fill='none' stroke-linecap='round' stroke-linejoin='round'/%3E%3Cpath d='M48 24 L42 24 M48 24 L48 30' stroke='white' stroke-width='4' fill='none' stroke-linecap='round'/%3E%3Crect x='30' y='28' width='5' height='12' rx='1.5' fill='%23f59e0b'/%3E%3C/svg%3E">
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<!-- TradingView Lightweight Charts -->
<script src="https://unpkg.com/lightweight-charts@5.0.8/dist/lightweight-charts.standalone.production.js"></script>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
html, body {{ height: 100%; }}
/* ---- 朋克深色主题 ---- */
body {{ font-family: 'Microsoft YaHei', sans-serif; background: #000000; color: #e6e9f0; display: flex; overflow: hidden; }}
/* ---- 左侧快捷命令侧边栏 ---- */
.sidebar {{ width: 420px; min-width: 420px; background: #000000; border-right: 1px solid #252c3f; display: flex; flex-direction: column; height: 100vh; }}
.sidebar .brand {{ padding: 18px 16px; font-size: 15px; font-weight: 700; color: #e6e9f0; border-bottom: 1px solid #252c3f; letter-spacing: .5px; text-shadow: 0 0 8px rgba(207,212,220,.4); }}
.sidebar .brand small {{ display: block; font-size: 11px; color: #8a93a8; font-weight: 400; margin-top: 3px; }}
.sidebar .section {{ padding: 14px 16px 6px; font-size: 11px; color: #8a93a8; text-transform: uppercase; letter-spacing: 1px; }}
.sidebar .cmds {{ padding: 4px 12px 12px; overflow-y: auto; }}
.sidebar .cmd {{ display: flex; align-items: center; gap: 8px; width: 100%; text-align: left; background: #000000; color: #e6e9f0; border: 1px solid #2a3249; border-radius: 6px; padding: 9px 11px; margin-bottom: 7px; font-size: 13px; cursor: pointer; transition: background .15s, border-color .15s, box-shadow .15s; }}
.sidebar .cmd:hover {{ background: #1b2036; border-color: #cfd4dc; box-shadow: 0 0 8px rgba(207,212,220,.25); }}
.sidebar .cmd:active {{ transform: translateY(1px); }}
.sidebar .cmd .dot {{ width: 8px; height: 8px; border-radius: 50%; background: #cfd4dc; flex-shrink: 0; box-shadow: 0 0 6px rgba(207,212,220,.8); }}
.sidebar .cmd.danger .dot {{ background: #ffffff; box-shadow: 0 0 6px rgba(255,255,255,.8); }}
.sidebar .cmd.running {{ opacity: .6; pointer-events: none; }}
.sidebar .cmd.running .spinner {{ display: inline-block; width: 12px; height: 12px; border: 2px solid #8a93a8; border-top-color: transparent; border-radius: 50%; animation: spin .8s linear infinite; flex-shrink: 0; }}
@keyframes spin {{ to {{ transform: rotate(360deg); }} }}
.sidebar .cmd .spinner {{ display: none; }}
.sidebar .cmd-output {{ padding: 12px 14px 16px; border-top: 1px solid #252c3f; overflow: hidden; display: flex; flex-direction: column; min-height: 320px; flex: 1 1 0; }}
.sidebar .cmd-output .label {{ font-size: 11px; color: #8a93a8; margin-bottom: 6px; }}
.sidebar .cmd-output pre {{ flex: 1; font-size: 11px; line-height: 1.5; color: #b6bdcb; white-space: pre-wrap; word-break: break-all; overflow-y: auto; max-height: 44vh; font-family: Consolas, monospace; }}
.sidebar .cmds {{ overflow-y: auto; max-height: 30vh; }}
.main {{ flex: 1; padding: 20px; overflow-y: auto; display: flex; flex-direction: column; min-height: 0; }}
.main > h1, .main > .tabs {{ flex: 0 0 auto; }}
h1 {{ font-size: 22px; margin-bottom: 16px; color: #e6e9f0; }}
.toolbar {{ display: flex; gap: 16px; align-items: center; margin-bottom: 14px; flex-wrap: wrap; }}
.toolbar label {{ font-size: 13px; color: #8a93a8; }}
select {{ background: #000000; color: #e6e9f0; border: 1px solid #2a3249; padding: 8px 10px; border-radius: 6px; font-size: 14px; }}
/* TAB */
.tabs {{ display: flex; gap: 4px; margin-bottom: 16px; border-bottom: 1px solid #252c3f; }}
.tab {{ padding: 10px 22px; cursor: pointer; font-size: 14px; color: #8a93a8; border: 1px solid transparent; border-bottom: none; border-radius: 8px 8px 0 0; transition: color .15s; }}
.tab:hover {{ color: #cfd4dc; }}
.tab.active {{ color: #fff; background: #000000; border-color: #252c3f; box-shadow: inset 0 -2px 0 #cfd4dc; }}
.tab-panel {{ display: none; }}
.tab-panel.active {{ display: block; }}
/* 策略选股详情 TAB：内部填满 main 剩余高度，消除底部空白 */
#panel-detail.active {{ display: flex; flex-direction: column; height: calc(100vh - 140px); min-height: 0; overflow: hidden; }}
#panel-detail.active > .toolbar {{ flex: 0 0 auto; }}
#panel-detail.active > .card {{ flex: 1 1 0; min-height: 0; display: flex; flex-direction: column; margin-bottom: 0; }}
.card {{ padding: 18px; margin-bottom: 18px; background: #000000; }}
.card h2 {{ font-size: 15px; color: #8a93a8; margin-bottom: 12px; font-weight: 500; }}
.grid {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 18px; }}
@media (max-width: 900px) {{ .grid {{ grid-template-columns: 1fr; }} }}
.ret-table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
.ret-table th, .ret-table td {{ padding: 4px 8px; text-align: right; border-bottom: 1px solid #232a36; }}
.ret-table th:first-child, .ret-table td:first-child {{ text-align: left; }}
/* 月/季/年收益三列表：字号 月<季<年 递进 */
/* 整体宽度取卡片的一半（对应下方 .dist-grid 四个分布图中「2 个表」的宽度） */
.bt-ret3 {{ width: 50%; table-layout: fixed; border-collapse: collapse; border-spacing: 0; }}
.bt-ret3 th, .bt-ret3 td {{ padding: 6px 10px; text-align: center; vertical-align: middle; }}
/* 列宽：月份占主体，季/年等宽。必须同时作用于 th 与 td，否则表头与数据列对不齐 */
.bt-ret3 th:nth-child(1), .bt-ret3 td:nth-child(1) {{ width: 66%; }}
.bt-ret3 th:nth-child(2), .bt-ret3 td:nth-child(2) {{ width: 17%; }}
.bt-ret3 th:nth-child(3), .bt-ret3 td:nth-child(3) {{ width: 17%; }}
.bt-ret3 td.bt-td-month {{ font-size: 11px; color: #b8c0cc; }}
.bt-ret3 td.bt-td-quarter {{ font-size: 13px; }}
.bt-ret3 td.bt-td-year {{ font-size: 15px; font-weight: 600; }}
/* 月/季/年收益：月为「月份+当月收益+累计条」一行；季/年只显示数值（无条） */
.bt-ret3 .bt-td-month {{ font-size: 11px; color: #b8c0cc; }}
/* 表头(th.bt-th-month)与数据行(td.bt-td-month)共用同一套子列布局：
   必须让 flex 同时作用于两者，否则表头里的 span 是 inline 元素，width 会被忽略、完全不对齐 */
.bt-ret3 .bt-th-month .bt-cell-inline,
.bt-ret3 .bt-td-month .bt-cell-inline {{ display: flex; align-items: center; gap: 8px; }}
.bt-ret3 .bt-mon {{ font-size: 10px; color: #7a7f8a; width: 26px; flex-shrink: 0; text-align: left; letter-spacing: 1px; }}
.bt-ret3 .bt-cnt {{ font-size: 10px; color: #8a93a8; width: 38px; flex-shrink: 0; text-align: right; }}
/* 抓到涨停个数：放在「次数」右侧，只显示数字（列宽收窄），用暖色区分 */
.bt-ret3 .bt-tops {{ font-size: 10px; color: #ffffff; width: 30px; flex-shrink: 0; text-align: right; }}
/* 表头：弱化、居中，与数据行区分 */
.bt-ret3 thead th {{ font-size: 11px; font-weight: 600; color: #8a93a8; text-align: center;
  padding: 4px 10px 8px; letter-spacing: .5px; border-bottom: 1px solid #252c3f !important; }}
/* 表头中对应「累计条」的占位（与数据行的 .bt-cumtrack 同为 flex:1，保证列宽一致） */
.bt-ret3 .bt-th-cum {{ flex: 1 1 0; text-align: center; min-width: 40px; }}
/* 收益列给固定宽度：否则表头「收益」与数据「-61.37%」内容宽度不同，会让后面几列错位 */
.bt-ret3 .bt-val {{ font-weight: 500; width: 60px; flex-shrink: 0; }}
.bt-ret3 .bt-cumtrack {{ position: relative; flex: 1 1 0; height: 12px; background: #161a24; border-radius: 2px; overflow: hidden; min-width: 40px; }}
.bt-ret3 .bt-cum {{ position: absolute; left: 0; top: 0; bottom: 0; border-radius: 2px; opacity: .85; }}
.bt-ret3 .bt-cum.zero, .bt-ret3 .bt-cum.empty {{ background: transparent; }}
.bt-ret3 .bt-cumval {{ font-size: 10px; width: 46px; flex-shrink: 0; text-align: right; }}
.bt-ret3 td {{ vertical-align: middle; }}
.bt-ret3 .bt-plain {{ text-align: left; vertical-align: middle; padding-left: 16px; }}
.bt-ret3 .bt-big {{ font-weight: 700; padding: 8px 14px; border-radius: 6px; display: inline-block; letter-spacing: .5px; }}
.bt-ret3 .bt-big.bt-q {{ font-size: 18px; color: #cfd4dc; text-shadow: 0 0 6px rgba(207,212,220,.45); }}
.bt-ret3 .bt-big.bt-y {{ font-size: 26px; color: #ffffff; text-shadow: 0 0 8px rgba(255,255,255,.55); }}
.bt-ret3 .bt-big.pos {{ color: #ffffff; text-shadow: 0 0 8px rgba(255,255,255,.55); }}
.bt-ret3 .bt-big.neg {{ color: #cfd4dc; text-shadow: 0 0 8px rgba(207,212,220,.55); }}
.bt-ret3 td[rowspan] {{ background: transparent; border-bottom: none !important; border-top: none !important; }}
.bt-ret3 td, .bt-ret3 th {{ border: none !important; border-bottom: none !important; border-top: none !important; background-color: transparent !important; }}
/* 收益统计条 */
.bt-stats {{ display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 12px; }}
.bt-stat {{ background: #000000; border: 1px solid #232b3d; border-radius: 6px; padding: 8px 14px; text-align: center; min-width: 92px; }}
.bt-stat .k {{ display: block; font-size: 10px; color: #7a8398; letter-spacing: .5px; margin-bottom: 3px; }}
.bt-stat .v {{ display: block; font-size: 16px; font-weight: 700; color: #e6e9f0; }}
.bt-stat .v.pos {{ color: #ffffff; text-shadow: 0 0 8px rgba(255,255,255,.5); }}
.bt-stat .v.neg {{ color: #cfd4dc; text-shadow: 0 0 8px rgba(207,212,220,.5); }}
.bt-stat .v.gold {{ color: #ffffff; text-shadow: 0 0 8px rgba(255,255,255,.5); }}
.dist-grid {{ display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 12px; }}
/* 标题居中显眼，颜色说明放边缘 */
.dist-grid .dist-head {{ position: relative; display: flex; align-items: center; justify-content: center; margin-bottom: 6px; }}
.dist-grid .dist-head h3 {{ margin: 0; font-size: 14px; font-weight: 700; color: #fff; letter-spacing: .5px; text-shadow: 0 0 8px rgba(207,212,220,.35); }}
.dist-grid .dist-legend {{ position: absolute; right: 0; font-size: 9px; color: #7a8398; display: inline-flex; align-items: center; gap: 4px; }}
.dist-grid .dist-legend .lg {{ display: inline-block; width: 8px; height: 8px; border-radius: 2px; }}
.dist-grid .dist-legend .lg-all {{ background: #cfd4dc; }}
.dist-grid .dist-legend .lg-last {{ background: #ffffff; }}
.dist-grid .dist-box {{ background: #000000; border: 1px solid #242b3d; border-radius: 6px; padding: 8px; aspect-ratio: 1 / 1; min-height: 140px; display: flex; flex-direction: column; }}
.dist-grid .dist-canvas {{ flex: 1 1 0; position: relative; min-height: 0; }}
.dist-grid canvas {{ width: 100% !important; height: 100% !important; display: block; }}
@media (max-width: 1200px) {{ .dist-grid {{ grid-template-columns: 1fr 1fr; }} }}
@media (max-width: 700px) {{ .dist-grid {{ grid-template-columns: 1fr; }} }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
th, td {{ padding: 6px 8px; text-align: left; border-bottom: 1px solid #262c38; }}
th {{ color: #9aa0a6; font-weight: 500; }}
.pos {{ color: #d62828; }} .neg {{ color: #0077b6; }} .limit-up {{ color: #f5c518; }}
.chart-wrap {{ position: relative; height: 320px; }}
#panel-detail table {{ font-size: 12px; }}
#panel-detail td {{ white-space: nowrap; }}
#panel-detail tbody tr:hover {{ background: #000000; }}
table.detail-table tbody tr.row-selected {{ background: #2a2f3a; border-left: 3px solid #e8eaed; }}
table.detail-table tbody tr.row-selected:hover {{ background: #343c4a; }}
table.detail-table tbody tr.row-selected td {{ color: #e8eaed; font-weight: 600; }}
table.detail-table tbody tr.row-selected td.pos {{ color: #ffffff; }}
table.detail-table tbody tr.row-selected td.neg {{ color: #5aa9e6; }} table.detail-table tbody tr.row-selected td.limit-up {{ color: #f5c518; }}
#detail-groups {{ flex: 1 1 0; min-height: 0; }}
.detail-date-head {{ background: #000000; color: #e8eaed; font-size: 12px; font-weight: 600; padding: 6px 10px; margin: 8px 0 4px; border-radius: 5px; border-left: 3px solid #e8eaed; }}
.detail-date-head:first-child {{ margin-top: 0; }}
table.detail-table {{ width: auto; max-width: 100%; border-collapse: collapse; margin-bottom: 4px; table-layout: fixed; }}
table.detail-table th, table.detail-table td {{ padding: 5px 6px; text-align: right; border-bottom: 1px solid #232a36; overflow: hidden; text-overflow: ellipsis; }}
table.detail-table th:first-child, table.detail-table td:first-child {{ text-align: center; }}
table.detail-table thead th {{ position: sticky; top: 0; background: #141821; color: #9aa0a6; font-weight: 600; z-index: 1; }}
table.detail-table tbody tr:hover {{ background: #000000; }}
/* 固定列宽 */
/* 列宽：# / 代码 / 名称 / 涨跌幅% / 实际卖出% / 市值 / 最高时% / 最低时% */
table.detail-table th:nth-child(1) {{ width: 30px; }}
table.detail-table th:nth-child(2) {{ width: 80px; }}
table.detail-table th:nth-child(3) {{ width: 92px; }}
table.detail-table th:nth-child(4) {{ width: 66px; }}
table.detail-table th:nth-child(5) {{ width: 78px; }}
table.detail-table th:nth-child(6) {{ width: 74px; }}
table.detail-table th:nth-child(7) {{ width: 74px; }}
table.detail-table th:nth-child(8) {{ width: 80px; }}
/* 策略选股：左侧选股表格 + 右侧 K 线（参照实盘候选池）。去掉原 max-width 以便表格铺开 */
#panel-detail .card {{ padding: 12px 16px 8px; }}
/* 左侧数据 1/3、右侧 K 线 2/3；minmax(0,1fr) 允许列收缩，避免宽表格把网格撑破 */
.detail-layout {{ display: grid; grid-template-columns: auto 1fr; gap: 14px; align-items: stretch; }}
/* 策略选股整页不出现最外框滚动条：面板按视口高度铺满，仅左侧列表在面板内独立滚动（表头 sticky 随容器固定） */
#panel-detail.active > .detail-layout {{ flex: 1 1 0; min-height: 0; }}
#panel-detail.active > .detail-layout > div:first-child {{ height: 100%; min-height: 0; overflow-y: auto; }}
@media (max-width: 1100px) {{ .detail-layout {{ grid-template-columns: 1fr; }} #panel-detail.active {{ height: auto; overflow: visible; }} #panel-detail.active > .detail-layout > div:first-child {{ height: auto; min-height: 0; overflow-y: visible; }} }}
/* 选股表格行可点击 */
table.detail-table tbody tr {{ cursor: pointer; }}
#panel-backtest.active {{ display: flex; flex-direction: column; }}
#panel-backtest .capital-card {{ order: 99; }}
.mode-badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; margin-right: 6px; }}
.b-first {{ background: #3a4150; color: #e8eaed; }}
.b-last {{ background: #2b303c; color: #c9cdd4; }}
.b-avg {{ background: #1f2530; color: #9aa0a6; }}
.legend {{ display: flex; gap: 16px; margin-bottom: 8px; flex-wrap: wrap; }}
/* 情绪曲线下方「单均线」小图与周期按钮选中态 */
.sent-ma-head {{ margin: 12px 0 6px; font-size: 13px; color: #9aa0a6; }}
#sent-ma-kline {{ height: 720px; }}
.sent-ma-btn.active {{ background: #1b2036; border-color: #cfd4dc; box-shadow: 0 0 8px rgba(207,212,220,.25); }}
/* 候选池 */
.cand-layout {{ display: grid; grid-template-columns: 220px 280px 1fr; gap: 14px; }}
@media (max-width: 1000px) {{ .cand-layout {{ grid-template-columns: 1fr; }} }}
.date-list, .stock-list {{ max-height: 62vh; overflow-y: auto; }}
/* 候选池 / 涨停股：三列等高，K 线填满右侧列，与左右列表顶端对齐（顶到最上面） */
#panel-candidate.active, #panel-top.active, #panel-top_first.active, #panel-top_first_vol.active, #panel-top_first_vol_sun.active {{ display: flex; flex-direction: column; height: calc(100vh - 140px); min-height: 0; overflow: hidden; }}
#panel-candidate.active > .card, #panel-top.active > .card, #panel-top_first.active > .card, #panel-top_first_vol.active > .card, #panel-top_first_vol_sun.active > .card {{ flex: 1 1 0; min-height: 0; display: flex; flex-direction: column; margin-bottom: 0; }}
#panel-candidate.active .cand-layout, #panel-top.active .cand-layout, #panel-top_first.active .cand-layout, #panel-top_first_vol.active .cand-layout, #panel-top_first_vol_sun.active .cand-layout {{ flex: 1 1 0; min-height: 0; align-items: stretch; }}
#panel-candidate.active .cand-layout > div, #panel-top.active .cand-layout > div, #panel-top_first.active .cand-layout > div, #panel-top_first_vol.active .cand-layout > div, #panel-top_first_vol_sun.active .cand-layout > div {{ display: flex; flex-direction: column; min-height: 0; }}
#panel-candidate .date-list, #panel-candidate .stock-list, #panel-top .date-list, #panel-top .stock-list, #panel-top_first .date-list, #panel-top_first .stock-list, #panel-top_first_vol .date-list, #panel-top_first_vol .stock-list, #panel-top_first_vol_sun .date-list, #panel-top_first_vol_sun .stock-list {{ flex: 1 1 0; min-height: 0; max-height: none; }}
.date-item, .stock-item {{ padding: 7px 10px; cursor: pointer; border-radius: 6px; font-size: 13px; margin-bottom: 2px; }}
.date-item:hover, .stock-item:hover {{ background: #1f2530; }}
.date-item.active, .stock-item.active {{ background: #3a4150; color: #ffffff; }}
.stock-count {{ color: #9aa0a6; font-size: 12px; margin-left: 6px; }}
.stock-market {{ color: #6b7280; font-size: 11px; margin-left: 4px; }}
#kline, #top-kline, #top_first-kline, #top_first_vol-kline, #top_first_vol_sun-kline, #detail-kline {{ width: auto; flex: 1 1 0; min-height: 0; display: flex; flex-direction: column; }}
/* 日线(左) 与 5 分钟(右) 左右并排：日线:5分钟 = 1:2（整列高度） */
.kline-split {{ flex: 1 1 0; min-height: 0; display: flex; flex-direction: row; gap: 12px; }}
.kline-5m-col {{ flex: 2 1 0; min-height: 0; display: flex; flex-direction: column; }}
#kline-main {{ flex: 3 1 0; min-height: 0; }}
/* K线容器兜底纯黑，防止图表背景异常时透出底色 */
#bt-kline-main, #kline-main, #top-kline-main, #top_first-kline-main, #top_first_vol-kline-main, #top_first_vol_sun-kline-main, #detail-kline-main {{ background: #000000; }}
/* 策略选股右侧 K 线容器（与实盘候选池同规格，填满列高） */
#detail-kline {{ width: auto; flex: 1 1 0; min-height: 0; display: flex; flex-direction: column; }}
#detail-kline-main {{ flex: 3 1 0; min-height: 0; }}
#panel-detail.active .detail-layout > div {{ display: flex; flex-direction: column; min-height: 0; }}
#panel-detail.active .detail-layout > div:first-child > .card {{ flex: 1 1 0; min-height: 0; }}
/* 重要日期高亮框：覆盖层需父容器定位基准 */
#kline-main, #top-kline-main, #top_first-kline-main, #top_first_vol-kline-main, #top_first_vol_sun-kline-main, #detail-kline-main {{ position: relative; flex: 3 1 0; min-height: 0; }}
/* 5 分钟 K 线容器：置于右侧栏，占 2 份（日线占 1 份，故日线:5分钟 = 1:2） */
#kline-5m, #top-kline-5m, #top_first-kline-5m, #top_first_vol-kline-5m, #top_first_vol_sun-kline-5m, #detail-kline-5m {{ width: 100%; flex: 1 1 0; min-height: 0; display: flex; flex-direction: column; }}
#kline-5m-main, #top-kline-5m-main, #top_first-kline-5m-main, #top_first_vol-kline-5m-main, #top_first_vol_sun-kline-5m-main, #detail-kline-5m-main {{ position: relative; flex: 3 1 0; min-height: 0; background: #000000; }}
.kline-subhead {{ font-size: 13px; color: #9aa0a6; margin: 0 0 6px; }}
.kline-hlbox {{ position: absolute; pointer-events: none; z-index: 5;
  border: 1px solid #ffffff; border-radius: 2px;
  background: rgba(255, 255, 255, .10); box-shadow: 0 0 10px rgba(255, 255, 255, .5); }}
.kline-ind {{ flex: 1 1 0; min-height: 0; margin-top: 4px; }}
.chart-title {{ font-size: 13px; color: #c9cdd4; margin-bottom: 8px; min-height: 18px; }}
.kline-info {{ font-size: 12px; color: #9aa0a6; margin-bottom: 6px; min-height: 16px; font-family: Consolas, monospace; }}
.kline-info .up {{ color: #d62828; }}
.kline-info .down {{ color: #0077b6; }}
.kline-info .limit-up {{ color: #f5c518; }}
/* K 线左上角 MA 数值浮层 */
.ma-overlay {{ position: absolute; top: 6px; left: 10px; z-index: 20; font: 12px/1.7 Consolas, monospace; background: rgba(0,0,0,0.55); padding: 3px 9px; border-radius: 4px; pointer-events: none; white-space: nowrap; }}
.ma-overlay b {{ font-weight: 700; }}
.chg-big {{ font-size: 20px; font-weight: 700; margin-right: 10px; }}
.chg-big.up {{ color: #d62828; }}
.chg-big.down {{ color: #0077b6; }}
.chg-big.limit-up {{ color: #f5c518; }}
.empty-hint {{ color: #6b7280; font-size: 13px; padding: 20px; text-align: center; }}
/* K 线工具栏 */
.kline-toolbar {{ display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 8px; }}
.kline-toolbar select, .kline-toolbar input[type="color"] {{
  background: #000000; color: #e4e6eb; border: 1px solid #2a3140; border-radius: 6px; padding: 5px 8px; font-size: 12px; height: 28px;
}}
.kline-toolbar select:focus {{ outline: none; border-color: #cfd4dc; }}
.kline-toolbar button {{
  background: #000000; color: #e4e6eb; border: 1px solid #2a3140; border-radius: 6px; padding: 5px 10px; font-size: 12px; cursor: pointer; height: 28px;
}}
.kline-toolbar button:hover {{ background: #252b38; border-color: #3a4556; }}
.kline-chk {{ display: inline-flex; align-items: center; gap: 4px; font-size: 12px; color: #c9cdd4; cursor: pointer; }}
.kline-chk input {{ accent-color: #cfd4dc; }}
.kline-ma-config {{ display: none; padding: 8px; margin-bottom: 8px; }}
/* MA 复选框行：默认显示（不隐藏），左对齐一排，勾选=显示对应均线 */
.kline-ma-row {{ display: flex; flex-wrap: wrap; align-items: center; gap: 12px; padding: 5px 8px; margin-bottom: 8px; background: #11141a; border: 1px solid #20262f; border-radius: 6px; }}
.kline-ma-row .ma-row-tip {{ color: #9aa0a6; font-size: 12px; font-weight: 600; margin-right: 2px; }}
.ma-chk {{ display: inline-flex; align-items: center; gap: 4px; font-size: 12px; color: #c8ccd4; cursor: pointer; user-select: none; white-space: nowrap; }}
.ma-chk input {{ cursor: pointer; margin: 0; }}
.ma-row {{ display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }}
/* 选股条件说明块（首板/首板涨停放量/首板涨停放量连阳 三个 TAB 标题下展示） */
.sel-cond {{ display: block; margin: 6px 0 12px; padding: 8px 10px; background: #11141a; border: 1px solid #20262f; border-left: 3px solid #38bdf8; border-radius: 4px; font-size: 12.5px; line-height: 1.6; color: #9aa0a6; }}
.sel-cond b {{ color: #cfd4dc; font-weight: 600; }}
.ma-row span {{ color: #9aa0a6; font-size: 12px; width: 24px; }}
.ma-row input[type="number"] {{ width: 60px; background: #000000; color: #e4e6eb; border: 1px solid #2a3140; border-radius: 5px; padding: 4px 6px; font-size: 12px; }}
.ma-row input[type="color"] {{ width: 32px; height: 24px; padding: 0; border: 1px solid #2a3140; border-radius: 5px; background: none; cursor: pointer; }}
.ma-row .ma-del {{ width: 24px; height: 24px; background: #000000; color: #e8eaed; border: 1px solid #2a3140; border-radius: 5px; cursor: pointer; font-size: 14px; line-height: 1; }}
.ma-row .ma-del:hover {{ background: #2a2f3a; border-color: #e8eaed; }}
/* 指标栏管理 */
.kline-bars {{ display: none; padding: 8px; margin-bottom: 8px; }}
.bar-row {{ display: flex; align-items: center; gap: 6px; margin-bottom: 6px; flex-wrap: wrap; }}
.bar-row .bar-label {{ color: #9aa0a6; font-size: 12px; width: 26px; }}
.bar-row select {{ background: #000000; color: #e4e6eb; border: 1px solid #2a3140; border-radius: 5px; padding: 4px 6px; font-size: 12px; }}
.bar-row .bar-volma {{ color: #9aa0a6; font-size: 11px; }}
.bar-row .bar-volma-input {{ width: 70px; background: #000000; color: #e4e6eb; border: 1px solid #2a3140; border-radius: 5px; padding: 4px 6px; font-size: 12px; }}
.bar-row .bar-del {{ width: 24px; height: 24px; background: #000000; color: #e8eaed; border: 1px solid #2a3140; border-radius: 5px; cursor: pointer; font-size: 14px; line-height: 1; }}
.bar-row .bar-del:hover {{ background: #2a2f3a; border-color: #e8eaed; }}
/* 涨跌颜色配置 */
.kline-color-config {{ display: none; padding: 8px; margin-bottom: 8px; }}
</style>
</head>
<body>
<div id="__errbox" onclick="this.style.display='none'" style="position:fixed;left:0;right:0;bottom:0;z-index:99999;background:#854d0e;color:#fff;font:12px/1.5 Menlo,Consolas,monospace;padding:8px 12px;white-space:pre-wrap;border-top:2px solid #f59e0b;max-height:40vh;overflow:auto;cursor:pointer">⏳ 看板脚本已启动，正在加载数据…（若一直停在此行说明脚本中途出错；点击本行可关闭）</div>
<script>
(function(){{
  function box(){{ return document.getElementById('__errbox'); }}
  function raw(m){{ var d=box(); if(d) d.textContent += m + '\\n'; }}
  function fail(m){{ var d=box(); if(!d) return; d.style.background='#7f1d1d'; d.style.borderTopColor='#ef4444'; d.textContent = m + '\\n' + d.textContent; }}
  window.__errboxMark = function(t){{ raw('[trace] ' + t); }};
  window.__errboxDone = function(){{
    var d=box(); if(!d) return;
    d.style.background='#14532d'; d.style.borderTopColor='#22c55e';
    d.textContent = '✅ 看板脚本执行完成（点击可关闭）';
    setTimeout(function(){{ if(d) d.style.display='none'; }}, 3500);
  }};
  window.addEventListener('error', function(e){{
    var loc = (e.filename||'') + ':' + (e.lineno||0) + ':' + (e.colno||0);
    var st = (e.error && e.error.stack) ? ('\\n' + e.error.stack) : '';
    fail('==== JS ERROR ====\\n' + (e.message || e.error) + '\\n  @ ' + loc + st);
  }}, true);
  window.addEventListener('unhandledrejection', function(e){{
    fail('==== JS REJECT ====\\n' + ((e.reason && (e.reason.stack || e.reason.message)) || e.reason));
  }});
}})();
</script>
{sidebar_html}
<!-- ============ 主内容区 ============ -->
<div class="main">
<h1>📊 策略回测 & 实盘目标股看板</h1>
<div class="tabs">
  <div class="tab active" data-tab="backtest" onclick="switchTab('backtest')">1 策略回测</div>
  <div class="tab" data-tab="candidate" onclick="switchTab('candidate')">2 实盘候选池</div>
  <div class="tab" data-tab="detail" onclick="switchTab('detail')">3 策略选股</div>
  <div class="tab" data-tab="top_first" onclick="switchTab('top_first')">4 首板涨停股</div>
  <div class="tab" data-tab="top_first_vol" onclick="switchTab('top_first_vol')">5 首板涨停放量股</div>
  <div class="tab" data-tab="index" onclick="switchTab('index')">6 指数K线</div>
</div>

<div id="panel-backtest" class="tab-panel active">
  <div class="toolbar">
    <div><label>策略：</label>
      <select id="strategy-select"></select>
    </div>
    <div><label>T-0 卖出：</label>
      <select id="sell-mode">
        <option value="5m">5分钟日内</option>
        <option value="day">日线收盘</option>
      </select>
    </div>
    <div class="legend" id="legend" style="margin-bottom:0"></div>
  </div>
  <div class="card capital-card">
    <h2>资金 K 线（每日资金 OHLC：起始 10 万复利，由每日买入股票的 O/C/H/L 涨跌幅计算）</h2>
    <div class="kline-toolbar">
      <button id="bt-bar-btn" type="button">指标栏</button>
      <label class="kline-chk"><input type="checkbox" id="bt-boll"> BOLL</label>
      <label class="kline-chk"><input type="checkbox" id="bt-vwap"> VWAP</label>
      <button id="bt-ma-btn" type="button">MA 配置</button>
      <button id="bt-ma-add" type="button" style="display:none">+</button>
      <button id="bt-color-btn" type="button">涨跌颜色</button>
    </div>
    <div class="kline-bars" id="bt-bars"></div>
    <div class="kline-ma-config" id="bt-ma-config"></div>
    <div class="kline-ma-row" id="bt-kline-ma-row"></div>
    <div class="kline-color-config" id="bt-color-config"></div>
    <div id="bt-kline"><div id="bt-kline-main"><div class="empty-hint">暂无资金 K 线数据</div></div></div>
  </div>
  <div class="card">
    <div class="toolbar">
      <div><label>年份：</label>
        <select id="bt-year-select"></select>
      </div>
      <div id="bt-year-info" style="font-size:12px;color:#9aa0a6;"></div>
    </div>
    <div id="bt-stats" class="bt-stats"></div>
    <table class="ret-table bt-ret3">
      <thead>
        <tr>
          <!-- 月份列的表头用与数据行相同的 bt-cell-inline + 同名子列 class，
               宽度与下方数据逐列严格对齐（月/次数/涨停/收益/累计条/累计） -->
          <th class="bt-th-month">
            <div class="bt-cell-inline">
              <span class="bt-mon">月份</span>
              <span class="bt-cnt">次数</span>
              <span class="bt-tops">涨停</span>
              <span class="bt-val">收益</span>
              <span class="bt-th-cum">年内累计走势</span>
              <span class="bt-cumval">累计</span>
            </div>
          </th>
          <th class="bt-th-quarter">季度</th>
          <th class="bt-th-year">年度</th>
        </tr>
      </thead>
      <tbody id="bt-month"></tbody>
    </table>
  </div>
  <div class="card">
    <h2>每日涨跌幅正态分布（1% 一个单位；蓝=全部，红=最近20日）</h2>
    <div class="dist-grid">
      <div class="dist-box"><div class="dist-head"><h3>Open</h3><div class="dist-legend"><span class="lg lg-all"></span>全部<span class="lg lg-last"></span>最近20日</div></div><div class="dist-canvas"><canvas id="dist-open"></canvas></div></div>
      <div class="dist-box"><div class="dist-head"><h3>High</h3><div class="dist-legend"><span class="lg lg-all"></span>全部<span class="lg lg-last"></span>最近20日</div></div><div class="dist-canvas"><canvas id="dist-high"></canvas></div></div>
      <div class="dist-box"><div class="dist-head"><h3>Low</h3><div class="dist-legend"><span class="lg lg-all"></span>全部<span class="lg lg-last"></span>最近20日</div></div><div class="dist-canvas"><canvas id="dist-low"></canvas></div></div>
      <div class="dist-box"><div class="dist-head"><h3>Close</h3><div class="dist-legend"><span class="lg lg-all"></span>全部<span class="lg lg-last"></span>最近20日</div></div><div class="dist-canvas"><canvas id="dist-close"></canvas></div></div>
    </div>
  </div>
</div>

<div id="panel-candidate" class="tab-panel">
  <div class="toolbar">
    <div><label>策略：</label>
      <select id="strategy-select-2"></select>
    </div>
  </div>
  <div class="card">
    <h2>实盘候选股票池（T-2 日收盘后确定，下个交易日可买入；日期倒序，默认最新）</h2>
    <div class="cand-layout">
      <div style="padding:10px">
        <div style="font-size:13px;color:#9aa0a6;margin-bottom:8px">候选池日期</div>
        <div class="date-list" id="date-list"></div>
      </div>
      <div style="padding:10px">
        <div style="font-size:13px;color:#9aa0a6;margin-bottom:8px">候选股票</div>
        <div class="stock-list" id="stock-list"></div>
      </div>
      <div style="padding:10px">
        <div class="chart-title" id="kline-title"></div>
        <div class="kline-info" id="kline-info"></div>
        <div class="kline-toolbar">
          <select id="kline-period" title="周期">
            <option value="day">日线</option>
            <option value="month">月线</option>
          </select>
          <button id="kline-bar-btn" type="button">指标栏</button>
          <label class="kline-chk"><input type="checkbox" id="kline-boll"> BOLL</label>
          <label class="kline-chk"><input type="checkbox" id="kline-vwap"> VWAP</label>
          <button id="kline-ma-btn" type="button">MA 配置</button>
          <button id="kline-ma-add" type="button" style="display:none">+</button>
          <button id="kline-color-btn" type="button">涨跌颜色</button>
        </div>
        <div class="kline-bars" id="kline-bars"></div>
        <div class="kline-ma-config" id="kline-ma-config"></div>
        <div class="kline-ma-row" id="kline-ma-row"></div>
        <div class="kline-color-config" id="kline-color-config"></div>
        <div class="kline-split">
          <div id="kline">
            <div id="kline-main"><div class="empty-hint">请选择候选池日期与个股</div></div>
          </div>
          <div class="kline-5m-col">
            <div class="kline-subhead">5 分钟 K 线（自 T-5 日起，约 20 个交易日）· 含 MA</div>
            <div id="kline-5m"><div id="kline-5m-main"><div class="empty-hint">请选择个股查看 5 分钟 K 线</div></div></div>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>

<div id="panel-detail" class="tab-panel">
  <div class="toolbar">
    <div><label>策略：</label>
      <select id="detail-strategy"></select>
    </div>
    <div><label>月份：</label>
      <select id="detail-date"></select>
    </div>
    <div id="detail-count" style="font-size:12px;color:#9aa0a6;"></div>
  </div>
  <div class="detail-layout">
    <div style="padding:10px">
      <div id="detail-groups" class="card"></div>
    </div>
    <div style="padding:10px">
      <div class="chart-title" id="detail-kline-title"></div>
      <div class="kline-info" id="detail-kline-info"></div>
      <div class="kline-toolbar">
        <select id="detail-kline-period" title="周期">
          <option value="day">日线</option>
          <option value="month">月线</option>
        </select>
        <button id="detail-kline-bar-btn" type="button">指标栏</button>
        <label class="kline-chk"><input type="checkbox" id="detail-kline-boll"> BOLL</label>
        <label class="kline-chk"><input type="checkbox" id="detail-kline-vwap"> VWAP</label>
        <button id="detail-kline-ma-btn" type="button">MA 配置</button>
        <button id="detail-kline-ma-add" type="button" style="display:none">+</button>
        <button id="detail-kline-color-btn" type="button">涨跌颜色</button>
      </div>
      <div class="kline-bars" id="detail-kline-bars"></div>
      <div class="kline-ma-config" id="detail-kline-ma-config"></div>
      <div class="kline-ma-row" id="detail-kline-ma-row"></div>
      <div class="kline-color-config" id="detail-kline-color-config"></div>
      <div class="kline-split">
        <div id="detail-kline">
          <div id="detail-kline-main"><div class="empty-hint">请点击左侧任意一行查看 K 线</div></div>
        </div>
        <div class="kline-5m-col">
          <div class="kline-subhead">5 分钟 K 线（自 T-5 日起，约 20 个交易日）· 含 MA</div>
          <div id="detail-kline-5m"><div id="detail-kline-5m-main"><div class="empty-hint">请点击左侧任意一行查看 5 分钟 K 线</div></div></div>
        </div>
      </div>
    </div>
  </div>
</div>

<div id="panel-top" class="tab-panel">
  <div class="card">
    <h2>涨停股列表（按流通市值倒序；日期倒序，默认最新）</h2>
    <div class="cand-layout">
      <div style="padding:10px">
        <div style="font-size:13px;color:#9aa0a6;margin-bottom:8px">涨停日期</div>
        <div class="date-list" id="top-date-list"></div>
      </div>
      <div style="padding:10px">
        <div style="font-size:13px;color:#9aa0a6;margin-bottom:8px">涨停股票（市值倒序）</div>
        <div class="stock-list" id="top-stock-list"></div>
      </div>
      <div style="padding:10px">
        <div class="chart-title" id="top-kline-title"></div>
        <div class="kline-info" id="top-kline-info"></div>
        <div class="kline-toolbar">
          <select id="top-kline-period" title="周期">
            <option value="day">日线</option>
            <option value="month">月线</option>
          </select>
          <button id="top-bar-btn" type="button">指标栏</button>
          <label class="kline-chk"><input type="checkbox" id="top-boll"> BOLL</label>
          <label class="kline-chk"><input type="checkbox" id="top-vwap"> VWAP</label>
          <button id="top-ma-btn" type="button">MA 配置</button>
          <button id="top-ma-add" type="button" style="display:none">+</button>
          <button id="top-color-btn" type="button">涨跌颜色</button>
        </div>
        <div class="kline-bars" id="top-bars"></div>
        <div class="kline-ma-config" id="top-ma-config"></div>
        <div class="kline-ma-row" id="top-kline-ma-row"></div>
        <div class="kline-color-config" id="top-color-config"></div>
        <div class="kline-split">
          <div id="top-kline">
            <div id="top-kline-main"><div class="empty-hint">请选择涨停日期与个股</div></div>
          </div>
          <div class="kline-5m-col">
            <div class="kline-subhead">5 分钟 K 线（自 T-5 日起，约 20 个交易日）· 含 MA</div>
            <div id="top-kline-5m"><div id="top-kline-5m-main"><div class="empty-hint">请选择个股查看 5 分钟 K 线</div></div></div>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>

<div id="panel-top_first" class="tab-panel">
  <div class="card">
    <h2>首板涨停股列表（按流通市值倒序；日期倒序，默认最新）</h2>
    <div class="sel-cond"><b>选股条件：</b>当日涨停，且前一日未涨停（剔除连板）；当日日线放量（is_volume_up=1）。口径与同花顺板块 ===TOP=== 一致。</div>
    <div class="cand-layout">
      <div style="padding:10px">
        <div style="font-size:13px;color:#9aa0a6;margin-bottom:8px">首板日期</div>
        <div class="date-list" id="top_first-date-list"></div>
      </div>
      <div style="padding:10px">
        <div style="font-size:13px;color:#9aa0a6;margin-bottom:8px">首板涨停股票（市值倒序）</div>
        <div class="stock-list" id="top_first-stock-list"></div>
      </div>
      <div style="padding:10px">
        <div class="chart-title" id="top_first-kline-title"></div>
        <div class="kline-info" id="top_first-kline-info"></div>
        <div class="kline-toolbar">
          <select id="top_first-kline-period" title="周期">
            <option value="day">日线</option>
            <option value="month">月线</option>
          </select>
          <button id="top_first-bar-btn" type="button">指标栏</button>
          <label class="kline-chk"><input type="checkbox" id="top_first-boll"> BOLL</label>
          <label class="kline-chk"><input type="checkbox" id="top_first-vwap"> VWAP</label>
          <button id="top_first-ma-btn" type="button">MA 配置</button>
          <button id="top_first-ma-add" type="button" style="display:none">+</button>
          <button id="top_first-color-btn" type="button">涨跌颜色</button>
        </div>
        <div class="kline-bars" id="top_first-bars"></div>
        <div class="kline-ma-config" id="top_first-ma-config"></div>
        <div class="kline-ma-row" id="top_first-kline-ma-row"></div>
        <div class="kline-color-config" id="top_first-color-config"></div>
        <div class="kline-split">
          <div id="top_first-kline">
            <div id="top_first-kline-main"><div class="empty-hint">请选择首板日期与个股</div></div>
          </div>
          <div class="kline-5m-col">
            <div class="kline-subhead">5 分钟 K 线（自 T-5 日起，约 20 个交易日）· 含 MA</div>
            <div id="top_first-kline-5m"><div id="top_first-kline-5m-main"><div class="empty-hint">请选择个股查看 5 分钟 K 线</div></div></div>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>

<div id="panel-top_first_vol" class="tab-panel">
  <div class="card">
    <h2>首板涨停放量股列表（按流通市值倒序；日期倒序，默认最新）</h2>
    <div class="sel-cond"><b>选股条件：</b>T-3（前一日）涨停 + 首板（lian_ban=1）+ 放量；T-2（当日）上涨（is_up=1）+ 放量 + 未涨停（is_top=0）。即「首板涨停后的次日放量上涨但未涨停」，不限市值。</div>
    <div class="cand-layout">
      <div style="padding:10px">
        <div style="font-size:13px;color:#9aa0a6;margin-bottom:8px">放量日（T-2）</div>
        <div class="date-list" id="top_first_vol-date-list"></div>
      </div>
      <div style="padding:10px">
        <div style="font-size:13px;color:#9aa0a6;margin-bottom:8px">首板涨停放量股票（市值倒序）</div>
        <div class="stock-list" id="top_first_vol-stock-list"></div>
      </div>
      <div style="padding:10px">
        <div class="chart-title" id="top_first_vol-kline-title"></div>
        <div class="kline-info" id="top_first_vol-kline-info"></div>
        <div class="kline-toolbar">
          <select id="top_first_vol-kline-period" title="周期">
            <option value="day">日线</option>
            <option value="month">月线</option>
          </select>
          <button id="top_first_vol-bar-btn" type="button">指标栏</button>
          <label class="kline-chk"><input type="checkbox" id="top_first_vol-boll"> BOLL</label>
          <label class="kline-chk"><input type="checkbox" id="top_first_vol-vwap"> VWAP</label>
          <button id="top_first_vol-ma-btn" type="button">MA 配置</button>
          <button id="top_first_vol-ma-add" type="button" style="display:none">+</button>
          <button id="top_first_vol-color-btn" type="button">涨跌颜色</button>
        </div>
        <div class="kline-bars" id="top_first_vol-bars"></div>
        <div class="kline-ma-config" id="top_first_vol-ma-config"></div>
        <div class="kline-ma-row" id="top_first_vol-kline-ma-row"></div>
        <div class="kline-color-config" id="top_first_vol-color-config"></div>
        <div class="kline-split">
          <div id="top_first_vol-kline">
            <div id="top_first_vol-kline-main"><div class="empty-hint">请选择放量日期与个股</div></div>
          </div>
          <div class="kline-5m-col">
            <div class="kline-subhead">5 分钟 K 线（放量日居中）· 含 MA</div>
            <div id="top_first_vol-kline-5m"><div id="top_first_vol-kline-5m-main"><div class="empty-hint">请选择个股查看 5 分钟 K 线</div></div></div>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>

<div id="panel-top_first_vol_sun" class="tab-panel">
  <div class="card">
    <h2>首板涨停放量连阳股列表（按流通市值倒序；日期倒序，默认最新）</h2>
    <div class="sel-cond"><b>选股条件：</b>在「首板涨停放量股」基础上，再加 T-1（次日）两条件：① 收&gt;开（阳线 is_red=1）；② 最高价创阶段新高（&gt; 之前 20 个交易日最高价）。</div>
    <div class="cand-layout">
      <div style="padding:10px">
        <div style="font-size:13px;color:#9aa0a6;margin-bottom:8px">放量日（T-2）</div>
        <div class="date-list" id="top_first_vol_sun-date-list"></div>
      </div>
      <div style="padding:10px">
        <div style="font-size:13px;color:#9aa0a6;margin-bottom:8px">首板涨停放量连阳股票（市值倒序）</div>
        <div class="stock-list" id="top_first_vol_sun-stock-list"></div>
      </div>
      <div style="padding:10px">
        <div class="chart-title" id="top_first_vol_sun-kline-title"></div>
        <div class="kline-info" id="top_first_vol_sun-kline-info"></div>
        <div class="kline-toolbar">
          <select id="top_first_vol_sun-kline-period" title="周期">
            <option value="day">日线</option>
            <option value="month">月线</option>
          </select>
          <button id="top_first_vol_sun-bar-btn" type="button">指标栏</button>
          <label class="kline-chk"><input type="checkbox" id="top_first_vol_sun-boll"> BOLL</label>
          <label class="kline-chk"><input type="checkbox" id="top_first_vol_sun-vwap"> VWAP</label>
          <button id="top_first_vol_sun-ma-btn" type="button">MA 配置</button>
          <button id="top_first_vol_sun-ma-add" type="button" style="display:none">+</button>
          <button id="top_first_vol_sun-color-btn" type="button">涨跌颜色</button>
        </div>
        <div class="kline-bars" id="top_first_vol_sun-bars"></div>
        <div class="kline-ma-config" id="top_first_vol_sun-ma-config"></div>
        <div class="kline-ma-row" id="top_first_vol_sun-kline-ma-row"></div>
        <div class="kline-color-config" id="top_first_vol_sun-color-config"></div>
        <div class="kline-split">
          <div id="top_first_vol_sun-kline">
            <div id="top_first_vol_sun-kline-main"><div class="empty-hint">请选择放量日期与个股</div></div>
          </div>
          <div class="kline-5m-col">
            <div class="kline-subhead">5 分钟 K 线（放量日居中）· 含 MA</div>
            <div id="top_first_vol_sun-kline-5m"><div id="top_first_vol_sun-kline-5m-main"><div class="empty-hint">请选择个股查看 5 分钟 K 线</div></div></div>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>

<div id="panel-index" class="tab-panel">
  <div class="card">
    <h2>指数 1D K 线（数据起始与 1D 一致）</h2>
    <div class="toolbar">
      <div><label>指数：</label><select id="index-select" onchange="onIndexSelect()"></select></div>
      <div id="index-kline-ma-row" class="ma-row"></div>
    </div>
    <div class="chart-title" id="index-kline-title"></div>
    <div id="index-kline-main" style="height:600px"><div class="empty-hint">请选择指数</div></div>
  </div>
</div>

__EXTERNAL_DATA_SCRIPT__
<script>
const DATA = __DATA_DECL__;
/* 指数 K 线数据：离线由骨架 index.js 内嵌（DATA.index_kline）；在线由本 payload 内嵌 */
window.__INDEX_KLINE = window.__INDEX_KLINE || (typeof DATA !== 'undefined' && DATA.index_kline) || {{}};
if (window.__P) window.__P.tScript = performance.now();
/* 访问方式判定：必须在脚本开头声明。加载器(ensureStock)与初始化流程（loadCandidates 等）
   都早于该常量原本所在位置执行，若留在原处会因 const 的暂时性死区(TDZ)直接抛错并中断初始化。 */
const IS_FILE_PROTOCOL = (location.protocol === 'file:');
let current = {{ strategy: null, candStrategy: null, date: null, code: null, topDate: null, topCode: null,
                topFirstDate: null, topFirstCode: null,
                topFirstVolDate: null, topFirstVolCode: null,
                topFirstVolSunDate: null, topFirstVolSunCode: null,
                detailDate: null, detailCode: null, sellMode: "5m" }};

/* 离线零内嵌：数据外置到 data/ 伴随文件（file:// 下仅 <script src> 兄弟文件可加载，fetch 被禁）
   提速策略：面板渲染出股票列表时后台预取该列表数据，点击时命中缓存，消除逐次点击的 I/O 等待。 */
/* 个股数据已分块落盘（chunk_{{i}}.js），按 code 稳定哈希定位所在块；同块只加载一次 */
function _stockChunkOf(code) {{
  const N = (DATA && DATA._stockChunks) || 64;
  let h = 0;
  for (let i = 0; i < code.length; i++) h = (h * 31 + code.charCodeAt(i)) >>> 0;
  return h % N;
}}
const _loadedChunks = {{}};
function _loadScript(src) {{
  return new Promise(function (resolve, reject) {{
    const s = document.createElement('script');
    s.src = src;
    s.onload = function () {{ resolve(); }};
    s.onerror = function () {{ reject(new Error('load fail: ' + src)); }};
    document.head.appendChild(s);
  }});
}}
async function _doLoadStock(code) {{
  const base = (DATA && DATA._stockBase) || 'data/stock/';
  const chunk = _stockChunkOf(code);
  const _t0 = performance.now();
  if (!_loadedChunks[chunk]) {{
    try {{ await _loadScript(base + 'chunk_' + chunk + '.js'); }} catch (e) {{ console.warn(e); }}
    _loadedChunks[chunk] = true;
  }}
  if (window.__P) window.__P.loads.push(+(performance.now() - _t0).toFixed(1));
  const st = (window.__STK && window.__STK[code]);
  if (st) {{
    DATA.kline = DATA.kline || {{}};
    DATA.fiveMin = DATA.fiveMin || {{}};
    DATA.kline[code] = (st.kline != null) ? st.kline : null;
    DATA.fiveMin[code] = st.fiveMin || {{}};
  }}
}}
/* 用 Promise 缓存：预取与点击共用同一次加载，不会重复请求 */
const _stockPromises = {{}};
function ensureStock(code) {{
  if (!code || !IS_FILE_PROTOCOL) return Promise.resolve();   // 在线模式数据已内嵌，无需本地按需加载
  if (!_stockPromises[code]) _stockPromises[code] = _doLoadStock(code);
  return _stockPromises[code];
}}
/* 后台预取列表：不阻塞渲染，用户点击时通常已命中缓存（限并发，避免瞬间大量请求反而卡顿） */
const _prefetchQueue = [];
let _prefetchActive = 0;
const _PREFETCH_MAX = 6;
function _pumpPrefetch() {{
  while (_prefetchActive < _PREFETCH_MAX && _prefetchQueue.length) {{
    const c = _prefetchQueue.shift();
    if (_stockPromises[c]) continue;
    _prefetchActive++;
    ensureStock(c).catch(function () {{}}).then(function () {{
      _prefetchActive--;
      _pumpPrefetch();
    }});
  }}
}}
function prefetchStocks(codes, limit) {{
  /* 批量预取已关闭：file:// 下并发加载数百个小文件会显著拖慢开页，并刷出大量加载失败日志。
     当前策略 = 按需单次加载：点一只股票才读它那一个文件。
     若日后要恢复批量预取，取消下面三行注释即可（面板级预取已限定只预取当前激活 TAB）。 */
  return;
  // if (!IS_FILE_PROTOCOL) return;
  // (codes || []).slice(0, limit || 200).forEach(function (c) {{ if (c && !_stockPromises[c]) _prefetchQueue.push(c); }});
  // _pumpPrefetch();
}}
/* 面板级预取：只预取「当前激活 TAB」的列表。
   开页时四个面板都会渲染，若不限定，会瞬间发起 600+ 个文件请求把页面拖慢。 */
function prefetchPanelCodes(panel, codes, limit) {{
  if (!IS_FILE_PROTOCOL) return;
  const el = document.getElementById('panel-' + panel);
  if (el && !el.classList.contains('active')) return;
  prefetchStocks(codes, limit);
}}
/* 切到某个 TAB 时，补预取该面板当前列表，保证后续点击命中缓存 */
function prefetchActivePanel(name) {{
  if (name === 'top') {{
    prefetchPanelCodes('top', (DATA.top[current.topDate] || []).map(function (s) {{ return s[0]; }}));
  }} else if (name === 'top_first') {{
    prefetchPanelCodes('top_first', (DATA.top_first[current.topFirstDate] || []).map(function (s) {{ return s[0]; }}));
  }} else if (name === 'top_first_vol') {{
    prefetchPanelCodes('top_first_vol', (DATA.top_first_vol[current.topFirstVolDate] || []).map(function (s) {{ return s[0]; }}));
  }} else if (name === 'candidate') {{
    const cs = DATA.candidates[current.candStrategy] || {{}};
    prefetchPanelCodes('candidate', (cs[current.date] || []).map(function (s) {{ return s[0]; }}));
  }} else if (name === 'detail') {{
    prefetchPanelCodes('detail', (window._detailRows || []).map(function (r) {{ return r.code; }}));
  }}
}}

/* ---- 按 TAB 懒加载数据 + 懒初始化 ----
   开页只加载 index.js 的骨架与首屏(策略回测)数据；候选池/涨停/首板/策略选股的数据各自独立成文件，
   首次点击进入该 TAB 时才加载并初始化，避免开页时被这些看不见的面板拖慢。 */
const _panelDataPromises = {{}};
function ensurePanelData(tab) {{
  if (!IS_FILE_PROTOCOL) return Promise.resolve();   // 在线模式数据已全量内嵌
  if (_panelDataPromises[tab]) return _panelDataPromises[tab];
  const map = {{ top: 'top.js', top_first: 'top_first.js', top_first_vol: 'top_first_vol.js',
                top_first_vol_sun: 'top_first_vol_sun.js',
                candidate: 'candidates.js', detail: 'detail.js' }};
  const f = map[tab];
  if (!f) return Promise.resolve();
  _panelDataPromises[tab] = _loadScript('data/' + f).catch(function (e) {{ console.warn(e); }});
  return _panelDataPromises[tab];
}}
const _tabInited = {{}};
async function ensureTab(name) {{
  if (_tabInited[name]) return;
  _tabInited[name] = true;
  if (name === 'top') {{ await ensurePanelData('top'); loadTop(); }}
  else if (name === 'top_first') {{ await ensurePanelData('top_first'); loadTopFirst(); }}
  else if (name === 'top_first_vol') {{ await ensurePanelData('top_first_vol'); loadTopFirstVol(); }}
  else if (name === 'top_first_vol_sun') {{ await ensurePanelData('top_first_vol_sun'); loadTopFirstVolSun(); }}
  else if (name === 'candidate') {{ await ensurePanelData('candidate'); loadCandidates(); }}
  else if (name === 'detail') {{ await ensurePanelData('detail'); initDetailTab(); }}
  else if (name === 'index') {{ initIndexTab(); }}
}}
/* ---- 指数 K 线 TAB（独立渲染，不依赖个股 K 线状态）---- */
const _indexMa = [
  {{p:5,c:'#e6e9f0'}},{{p:10,c:'#4dd0e1'}},{{p:20,c:'#ffb74d'}},
  {{p:30,c:'#ba68c8'}},{{p:60,c:'#81c784'}},{{p:120,c:'#ff8a65'}},
];
let _indexChart = null;
function _destroyIndexChart() {{
  if (_indexChart) {{ try {{ _indexChart.remove(); }} catch(e) {{}} _indexChart = null; }}
}}
function initIndexTab() {{
  const sel = document.getElementById('index-select');
  if (!sel) return;
  if (sel.options.length === 0) {{
    const ik = window.__INDEX_KLINE || {{}};
    Object.keys(ik).forEach(code => {{
      const opt = document.createElement('option');
      opt.value = code;
      opt.textContent = ((ik[code] && ik[code].name) ? ik[code].name + '  ' : '') + code;
      sel.appendChild(opt);
    }});
    _fillIndexMaRow();
  }}
  onIndexSelect();
}}
function onIndexSelect() {{
  const sel = document.getElementById('index-select');
  if (!sel || !sel.value) return;
  renderIndexKline(sel.value);
}}
function _fillIndexMaRow() {{
  const box = document.getElementById('index-kline-ma-row');
  if (!box) return;
  box.innerHTML = '';
  const tip = document.createElement('span');
  tip.className = 'ma-row-tip'; tip.textContent = 'MA';
  box.appendChild(tip);
  _indexMa.forEach(ma => {{
    const lab = document.createElement('label');
    lab.className = 'ma-chk';
    const cb = document.createElement('input');
    cb.type = 'checkbox'; cb.checked = (ma.visible !== false); cb.style.accentColor = ma.c;
    cb.onchange = () => {{ ma.visible = cb.checked; const s = document.getElementById('index-select'); if (s && s.value) renderIndexKline(s.value); }};
    lab.appendChild(cb);
    const txt = document.createElement('span');
    txt.textContent = ma.p; txt.style.color = ma.c;
    lab.appendChild(txt);
    box.appendChild(lab);
  }});
}}
function renderIndexKline(code) {{
  const ik = window.__INDEX_KLINE || {{}};
  const k = ik[code];
  const box = document.getElementById('index-kline-main');
  if (!box) return;
  if (!k || !k.ohlcv || k.ohlcv.length === 0) {{
    _destroyIndexChart();
    box.innerHTML = '<div class="empty-hint">暂无指数 K 线数据（请先运行指数数据更新）</div>';
    return;
  }}
  box.innerHTML = '<div id="index-kline-main-inner" style="height:600px"></div>';
  const mainEl = document.getElementById('index-kline-main-inner');
  _destroyIndexChart();
  _indexChart = LightweightCharts.createChart(mainEl, {{
    layout: {{ background: {{ type: LightweightCharts.ColorType.Solid, color: '#000000' }}, textColor: '#d1d4dc' }},
    grid: {{ vertLines: {{ color: '#161616' }}, horzLines: {{ color: '#161616' }} }},
    rightPriceScale: {{ borderColor: '#2b2b43' }},
    timeScale: {{ borderColor: '#2b2b43' }},
    crosshair: {{ mode: LightweightCharts.CrosshairMode.Normal }},
    height: mainEl.offsetHeight || 600,
  }});
  const data = k.ohlcv.map(d => ({{ time: d.time, open: d.open, high: d.high, low: d.low, close: d.close }}));
  const candle = _indexChart.addSeries(LightweightCharts.CandlestickSeries, {{
    upColor: '#d62828', downColor: '#0077b6', borderUpColor: '#d62828', borderDownColor: '#0077b6',
    wickUpColor: '#d62828', wickDownColor: '#0077b6',
  }});
  candle.setData(data);
  _indexMa.forEach(ma => {{
    if (ma.p <= 0 || ma.visible === false) return;
    _indexChart.addSeries(LightweightCharts.LineSeries, {{ color: ma.c, lineWidth: 1, priceLineVisible: false, lastValueVisible: false }}).setData(calcMA(data, ma.p));
  }});
  const title = document.getElementById('index-kline-title');
  if (title) {{
    const last = k.ohlcv[k.ohlcv.length - 1];
    const prev = last.pre_close || last.open;
    const pct = prev > 0 ? (last.close - prev) / prev * 100 : 0;
    title.innerHTML = '<span style="font-size:14px;font-weight:600;color:#e4e6eb">' + ((k.name ? k.name + '  ' : '') + code) + '  日线（共 ' + k.ohlcv.length + ' 根）</span> <span class="chg-big ' + (pct >= 0 ? 'up' : 'down') + '">' + (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%</span>';
  }}
  _indexChart.timeScale().fitContent();
}}
async function switchTab(name) {{
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === name));
  document.getElementById('panel-backtest').classList.toggle('active', name === 'backtest');
  document.getElementById('panel-candidate').classList.toggle('active', name === 'candidate');
  document.getElementById('panel-detail').classList.toggle('active', name === 'detail');
  document.getElementById('panel-top').classList.toggle('active', name === 'top');
  document.getElementById('panel-top_first').classList.toggle('active', name === 'top_first');
  document.getElementById('panel-top_first_vol').classList.toggle('active', name === 'top_first_vol');
  document.getElementById('panel-top_first_vol_sun').classList.toggle('active', name === 'top_first_vol_sun');
  document.getElementById('panel-index').classList.toggle('active', name === 'index');
  // 首次进入该 TAB：先取数据并初始化（此时容器已可见，图表能按实际高度渲染）
  await ensureTab(name);
  // TAB 激活时重绘 K 线（容器可见后再渲染）
  if (name === 'candidate') {{
    klineTarget = 'candidate';
    if (current.code) requestAnimationFrame(() => selectStock(current.code));
  }}
  if (name === 'top') {{
    klineTarget = 'top';
    if (current.topCode) requestAnimationFrame(() => selectTopStock(current.topCode));
  }}
  if (name === 'top_first') {{
    klineTarget = 'top_first';
    if (current.topFirstCode) requestAnimationFrame(() => selectTopFirstStock(current.topFirstCode));
  }}
  if (name === 'top_first_vol') {{
    klineTarget = 'top_first_vol';
    if (current.topFirstVolCode) requestAnimationFrame(() => selectTopFirstVolStock(current.topFirstVolCode));
  }} else if (name === 'top_first_vol_sun') {{
    klineTarget = 'top_first_vol_sun';
    if (current.topFirstVolSunCode) requestAnimationFrame(() => selectTopFirstVolSunStock(current.topFirstVolSunCode));
  }}
  if (name === 'detail') {{
    klineTarget = 'detail';
    if (current.detailCode) requestAnimationFrame(() => selectDetailStock(current.detailCode));
  }}
  prefetchActivePanel(name);   // 切到本 TAB 后补预取其列表，后续点击命中缓存
}}

// 策略下拉（回测）
const strategySelect = document.getElementById('strategy-select');
DATA.strategies.forEach(s => {{
  const opt = document.createElement('option'); opt.value = s; opt.textContent = s; strategySelect.appendChild(opt);
}});
strategySelect.value = DATA.strategies[0];
// 策略下拉（候选池）
const strategySelect2 = document.getElementById('strategy-select-2');
DATA.strategies.forEach(s => {{
  const opt = document.createElement('option'); opt.value = s; opt.textContent = s; strategySelect2.appendChild(opt);
}});
strategySelect2.value = DATA.strategies[0];

// T-0 卖出方式选择器：day = 日线收盘；5m = 5 分钟 K 线日内卖出（默认 5m）
const sellModeSelect = document.getElementById('sell-mode');
sellModeSelect.value = current.sellMode;
sellModeSelect.addEventListener('change', () => {{
  current.sellMode = sellModeSelect.value;
  updateCharts();
  loadDetail();
}});
function backtestPayload() {{
  const p = DATA.backtest[current.strategy];
  if (!p) return null;
  return p[current.sellMode] || p;
}}

function fmtPct(v) {{ return (v * 100).toFixed(2) + '%'; }}
function pctClass(v) {{ return v >= 0 ? 'pos' : 'neg'; }}
function fmtYi(v) {{ const n = parseFloat(v); return isNaN(n) ? '' : (n / 1e8).toFixed(2) + '亿'; }}

/* ------- 回测 ------- */
function loadStrategy() {{
  current.strategy = strategySelect.value;
  updateCharts();
}}

function updateCharts() {{
  const st = backtestPayload();
  if (!st) return;
  const legend = document.getElementById('legend');
  const smLabel = current.sellMode === '5m' ? '5分钟卖出' : '日线卖出';
  legend.innerHTML =
    `<span class="mode-badge b-first">first</span>` +
    `<span class="mode-badge b-avg">${{smLabel}}</span>` +
    ` 总收益: <b class="${{pctClass(st.total)}}">${{fmtPct(st.total)}}</b>` +
    ` 最终资金: ${{st.final.toFixed(2)}}` +
    ` 交易天数: ${{st.dates.length}}`;
  renderBacktestKline(st);
  renderPeriodTables(st);
  renderBtStats(st);
  renderDistCharts(st);
}}

/* 资金 K 线：复用 klineState（指标栏/MA/BOLL/VWAP/颜色）渲染每日资金 OHLC */
function renderBacktestKline(st) {{
  const box = document.getElementById('bt-kline');
  box.innerHTML = '<div id="bt-kline-main"></div>';
  if (window.btKlineChart) {{ try {{ window.btKlineChart.remove(); }} catch(e) {{}} window.btKlineChart = null; }}
  const data = (st.kline || []).filter(Boolean);
  if (!data.length) {{
    box.innerHTML = '<div id="bt-kline-main"><div class="empty-hint">无资金 K 线数据</div></div>';
    return;
  }}
  const mainEl = document.getElementById('bt-kline-main');
  const chart = LightweightCharts.createChart(mainEl, {{
    layout: {{ background: {{ type: LightweightCharts.ColorType.Solid, color: '#000000' }}, textColor: '#d1d4dc' }},
    grid: {{ vertLines: {{ color: '#161616' }}, horzLines: {{ color: '#161616' }} }},
    rightPriceScale: {{ borderColor: '#2b2b43' }},
    timeScale: {{ borderColor: '#2b2b43' }},
    crosshair: {{ mode: LightweightCharts.CrosshairMode.Normal }},
    height: mainEl.offsetHeight || 600,
  }});
  // 主图：资金 K 线
  const c = btKlineState.colors;
  const candle = chart.addSeries(LightweightCharts.CandlestickSeries, {{
    upColor: '#d62828', downColor: '#0077b6', borderUpColor: '#d62828', borderDownColor: '#0077b6',
    wickUpColor: '#d62828', wickDownColor: '#0077b6',
  }});
  candle.setData(data.map(d => ({{ time: d.time, open: d.open, high: d.high, low: d.low, close: d.close }})));
  // 主图：MA
  btKlineState.ma.forEach(ma => {{
    if (ma.p <= 0 || ma.visible === false) return;
    chart.addSeries(LightweightCharts.LineSeries, {{ color: ma.c, lineWidth: 1, priceLineVisible: false, lastValueVisible: false }}).setData(calcMA(data, ma.p));
  }});
  injectMaOverlay(mainEl, btKlineState.ma, data, d => d.close);
  // 主图：BOLL
  if (btKlineState.showBOLL) {{
    const boll = calcBOLL(data);
    chart.addSeries(LightweightCharts.LineSeries, {{ color: '#9aa0a6', lineWidth: 1, priceLineVisible: false, lastValueVisible: false }}).setData(boll.up);
    chart.addSeries(LightweightCharts.LineSeries, {{ color: '#9aa0a6', lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dotted, priceLineVisible: false, lastValueVisible: false }}).setData(boll.mid);
    chart.addSeries(LightweightCharts.LineSeries, {{ color: '#9aa0a6', lineWidth: 1, priceLineVisible: false, lastValueVisible: false }}).setData(boll.low);
  }}
  // 主图：VWAP
  if (btKlineState.showVWAP) {{
    chart.addSeries(LightweightCharts.LineSeries, {{ color: '#c0c4cc', lineWidth: 2, priceLineVisible: true, lastValueVisible: true }}).setData(calcVWAP(data));
  }}
  // 指标栏：复用 renderIndicatorBar（v5 addPane 分栏，对齐/十字线自动）
  btKlineState.bars.forEach(bar => {{
    const pane = chart.addPane();
    renderIndicatorBar(pane, bar, data, new Map());
  }});
  chart.timeScale().fitContent();
  window.btKlineChart = chart;
  renderMaRow();  // 刷新 MA 复选框行（含资金 K 线面板）
}}

/* ---- 回测资金 K 线：指标栏/MA/颜色配置面板（独立 btKlineState） ---- */
function renderBtMaConfig() {{
  const cfg = document.getElementById('bt-ma-config');
  if (cfg.style.display === 'none') return;
  cfg.innerHTML = '';
  btKlineState.ma.forEach((ma, i) => {{
    const row = document.createElement('div');
    row.className = 'ma-row';
    row.innerHTML = '<span>MA</span><input type="number" class="ma-p" value="' + ma.p + '" min="1" max="250" title="周期">' +
      '<input type="color" class="ma-c" value="' + ma.c + '" title="颜色">' +
      '<button type="button" class="ma-del">×</button>';
    row.querySelector('.ma-p').onchange = e => {{ ma.p = +e.target.value || 5; rerenderBtKline(); }};
    row.querySelector('.ma-c').oninput = e => {{ ma.c = e.target.value; rerenderBtKline(); }};
    row.querySelector('.ma-del').onclick = () => {{ btKlineState.ma.splice(i, 1); renderBtMaConfig(); rerenderBtKline(); }};
    cfg.appendChild(row);
  }});
}}
function renderBtBarConfig() {{
  const box = document.getElementById('bt-bars');
  box.innerHTML = '';
  btKlineState.bars.forEach((bar, i) => {{
    const row = document.createElement('div');
    row.className = 'bar-row';
    row.innerHTML = '<span class="bar-label">栏' + (i + 1) + '</span>' +
      '<select class="bar-type">' +
      '<option value="volume"' + (bar.type === 'volume' ? ' selected' : '') + '>成交量</option>' +
      '<option value="macd"' + (bar.type === 'macd' ? ' selected' : '') + '>MACD</option>' +
      '<option value="kdj"' + (bar.type === 'kdj' ? ' selected' : '') + '>KDJ</option>' +
      '</select>' +
      '<span class="bar-volma" title="成交量均线，逗号分隔">VOL MA:</span>' +
      '<input type="text" class="bar-volma-input" value="' + (bar.volMA || []).join(',') + '" placeholder="5,10">' +
      '<button type="button" class="bar-del">×</button>';
    row.querySelector('.bar-type').onchange = e => {{ bar.type = e.target.value; renderBtBarConfig(); rerenderBtKline(); }};
    row.querySelector('.bar-volma-input').onchange = e => {{
      const arr = e.target.value.split(',').map(x => parseInt(x, 10)).filter(x => !isNaN(x) && x > 0);
      bar.volMA = arr.length ? arr.slice(0, 3) : [5, 10];
      rerenderBtKline();
    }};
    row.querySelector('.bar-del').onclick = () => {{ btKlineState.bars.splice(i, 1); renderBtBarConfig(); rerenderBtKline(); }};
    if (bar.type !== 'volume') {{
      row.querySelector('.bar-volma').style.display = 'none';
      row.querySelector('.bar-volma-input').style.display = 'none';
    }}
    box.appendChild(row);
  }});
  const add = document.createElement('button');
  add.type = 'button';
  add.textContent = '+ 添加指标栏';
  add.style.cssText = 'width:100%;margin-top:4px;background:#1c2029;color:#e4e6eb;border:1px solid #2a3140;border-radius:6px;padding:5px;font-size:12px;cursor:pointer;';
  add.onclick = () => {{
    if (btKlineState.bars.length >= MAX_BARS) return;
    const types = ['volume', 'macd', 'kdj'].filter(t => !btKlineState.bars.some(b => b.type === t));
    btKlineState.bars.push({{ type: types[0] || 'macd', volMA: [5, 10] }});
    renderBtBarConfig(); rerenderBtKline();
  }};
  if (btKlineState.bars.length < MAX_BARS) box.appendChild(add);
}}
function renderBtColorConfig() {{
  const box = document.getElementById('bt-color-config');
  box.innerHTML = '';
  const defs = [['up', '涨', klineState.colors.up], ['down', '跌', klineState.colors.down], ['limitUp', '涨停', klineState.colors.limitUp]];
  defs.forEach(([key, label, val]) => {{
    const row = document.createElement('div');
    row.className = 'ma-row';
    row.innerHTML = '<span>' + label + '</span><input type="color" value="' + val + '" title="' + label + '">';
    row.querySelector('input').oninput = e => {{ klineState.colors[key] = e.target.value; renderBtColorConfig(); rerenderBtKline(); }};
    box.appendChild(row);
  }});
}}
function rerenderBtKline() {{
  const st = backtestPayload();
  if (st) requestAnimationFrame(() => renderBacktestKline(st));
}}

/* 情绪曲线：T-3 首板涨停股在 T-1 / T-0 / T-0+1 三个时点的收盘均涨幅复利曲线。
   改为线条展示（不再画蜡烛）；均线/BOLL/VWAP/指标栏仍基于 T-0 的 O/H/L/C 资金 K 线。 */
const SENT_LINE_COLORS = ['#cfd4dc', '#9aa0a6', '#e8eaed', '#8a93a8'];
function renderSentimentKline() {{
  const box = document.getElementById('sent-kline');
  box.innerHTML = '<div id="sent-kline-main"></div>';
  if (window.sentKlineChart) {{ try {{ window.sentKlineChart.remove(); }} catch(e) {{}} window.sentKlineChart = null; }}
  const sent = DATA.sentiment || {{}};
  const lines = (sent.lines || []).filter(l => l && l.data && l.data.length);
  const data = (sent.kline || []).filter(Boolean);
  const legendEl = document.getElementById('sent-legend');
  if (!lines.length && !data.length) {{
    box.innerHTML = '<div id="sent-kline-main"><div class="empty-hint">无情绪曲线数据</div></div>';
    if (legendEl) legendEl.innerHTML = '';
    return;
  }}
  const mainEl = document.getElementById('sent-kline-main');
  const chart = LightweightCharts.createChart(mainEl, {{
    layout: {{ background: {{ type: LightweightCharts.ColorType.Solid, color: '#000000' }}, textColor: '#d1d4dc' }},
    grid: {{ vertLines: {{ color: '#161616' }}, horzLines: {{ color: '#161616' }} }},
    rightPriceScale: {{ borderColor: '#2b2b43' }},
    timeScale: {{ borderColor: '#2b2b43' }},
    crosshair: {{ mode: LightweightCharts.CrosshairMode.Normal }},
    height: mainEl.offsetHeight || 600,
  }});
  // 三条曲线：T-1 / T-0 / T-0+1
  lines.forEach((ln, i) => {{
    chart.addSeries(LightweightCharts.LineSeries, {{
      color: SENT_LINE_COLORS[i % SENT_LINE_COLORS.length],
      lineWidth: 2, title: ln.name,
      priceLineVisible: false, lastValueVisible: true,
    }}).setData(ln.data);
  }});
  if (legendEl) {{
    legendEl.innerHTML = lines.map((ln, i) =>
      '<span><i style="display:inline-block;width:12px;height:3px;vertical-align:middle;' +
      'margin-right:5px;background:' + SENT_LINE_COLORS[i % SENT_LINE_COLORS.length] + '"></i>' +
      ln.name + '</span>').join('');
  }}
  // 主图不叠加均线（均线单独放到下方 renderSentimentMa 的图里）
  if (sentKlineState.showBOLL) {{
    const boll = calcBOLL(data);
    chart.addSeries(LightweightCharts.LineSeries, {{ color: '#9aa0a6', lineWidth: 1, priceLineVisible: false, lastValueVisible: false }}).setData(boll.up);
    chart.addSeries(LightweightCharts.LineSeries, {{ color: '#9aa0a6', lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dotted, priceLineVisible: false, lastValueVisible: false }}).setData(boll.mid);
    chart.addSeries(LightweightCharts.LineSeries, {{ color: '#9aa0a6', lineWidth: 1, priceLineVisible: false, lastValueVisible: false }}).setData(boll.low);
  }}
  if (sentKlineState.showVWAP) {{
    chart.addSeries(LightweightCharts.LineSeries, {{ color: '#c0c4cc', lineWidth: 2, priceLineVisible: true, lastValueVisible: true }}).setData(calcVWAP(data));
  }}
  sentKlineState.bars.forEach(bar => {{
    const pane = chart.addPane();
    renderIndicatorBar(pane, bar, data, new Map());
  }});
  chart.timeScale().fitContent();
  window.sentKlineChart = chart;
  renderSentimentMa();                       // 下方均线小图随主图一起刷新
}}

/* 情绪曲线均线：单独画在下方 —— 三条情绪曲线各算一条均线（同一周期，颜色与主图一致），
   周期由上方 5/10/20 按钮切换，同一时刻只显示一个周期的均线。 */
const sentMaState = {{ period: 5 }};
function renderSentimentMa() {{
  const box = document.getElementById('sent-ma-kline');
  box.innerHTML = '<div id="sent-ma-kline-main"></div>';
  if (window.sentMaChart) {{ try {{ window.sentMaChart.remove(); }} catch(e) {{}} window.sentMaChart = null; }}
  const titleEl = document.getElementById('sent-ma-title');
  const legendEl = document.getElementById('sent-ma-legend');
  const p = sentMaState.period;
  if (titleEl) titleEl.textContent = 'MA' + p;
  const lines = ((DATA.sentiment || {{}}).lines || []).filter(l => l && l.data && l.data.length);
  if (!lines.length) {{
    box.innerHTML = '<div id="sent-ma-kline-main"><div class="empty-hint">暂无均线数据</div></div>';
    if (legendEl) legendEl.innerHTML = '';
    return;
  }}
  const mainEl = document.getElementById('sent-ma-kline-main');
  const chart = LightweightCharts.createChart(mainEl, {{
    layout: {{ background: {{ type: LightweightCharts.ColorType.Solid, color: '#000000' }}, textColor: '#d1d4dc' }},
    grid: {{ vertLines: {{ color: '#161616' }}, horzLines: {{ color: '#161616' }} }},
    rightPriceScale: {{ borderColor: '#2b2b43' }},
    timeScale: {{ borderColor: '#2b2b43' }},
    crosshair: {{ mode: LightweightCharts.CrosshairMode.Normal }},
    height: mainEl.offsetHeight || 720,
  }});
  // 三条情绪曲线各自的均线：value 转成 calcMA 需要的 close 字段
  lines.forEach((ln, i) => {{
    const asClose = ln.data.map(d => ({{ time: d.time, close: d.value }}));
    chart.addSeries(LightweightCharts.LineSeries, {{
      color: SENT_LINE_COLORS[i % SENT_LINE_COLORS.length],
      lineWidth: 2, title: ln.name + ' MA' + p,
      priceLineVisible: false, lastValueVisible: true,
    }}).setData(calcMA(asClose, p));
  }});
  if (legendEl) {{
    legendEl.innerHTML = lines.map((ln, i) =>
      '<span><i style="display:inline-block;width:12px;height:3px;vertical-align:middle;' +
      'margin-right:5px;background:' + SENT_LINE_COLORS[i % SENT_LINE_COLORS.length] + '"></i>' +
      ln.name + ' MA' + p + '</span>').join('');
  }}
  chart.timeScale().fitContent();
  window.sentMaChart = chart;
}}
function renderSentColorConfig() {{
  const box = document.getElementById('sent-color-config');
  box.innerHTML = '';
  const defs = [['up', '涨', klineState.colors.up], ['down', '跌', klineState.colors.down], ['limitUp', '涨停', klineState.colors.limitUp]];
  defs.forEach(([key, label, val]) => {{
    const row = document.createElement('div');
    row.className = 'ma-row';
    row.innerHTML = '<span>' + label + '</span><input type="color" value="' + val + '" title="' + label + '">';
    row.querySelector('input').oninput = e => {{ klineState.colors[key] = e.target.value; renderSentColorConfig(); rerenderSentKline(); }};
    box.appendChild(row);
  }});
}}
function rerenderSentKline() {{
  requestAnimationFrame(() => renderSentimentKline());
}}

/* 综合收益：每日(柱状图) + 每月(表) + 每年(标题)，按年份切换 */
let btYear = null;
function populateYearSelect(st) {{
  const sel = document.getElementById('bt-year-select');
  const years = Object.keys(st.year || {{}}).sort().reverse();
  sel.innerHTML = years.map(y => `<option value="${{y}}">${{y}}</option>`).join('');
  if (years.length && (!btYear || !years.includes(btYear))) btYear = years[0];
  sel.value = btYear || '';
}}
function renderBtYearView(st) {{
  const year = btYear || Object.keys(st.year || {{}})[0];
  const sel = document.getElementById('bt-year-select');
  if (year) sel.value = year;
  const info = document.getElementById('bt-year-info');
  const yearRet = year ? st.year[year] : null;
  info.innerHTML = year
    ? `${{year}} 年收益: <b class="${{pctClass(yearRet)}}">${{fmtPct(yearRet)}}</b> · 总收益: <b class="${{pctClass(st.total)}}">${{fmtPct(st.total)}}</b> · 最终资金: ${{st.final.toFixed(2)}}`
    : '';
  // 月/季/年三列表：12 行对应 12 个月；季(rowspan=3)、年(rowspan=12) 垂直合并
  // 月：月份 + 当月收益率 + 累计收益条（1月~该月累计），三者一行，无基准线
  // 季/年：只显示收益数值（不显示条），用颜色/加粗突出
  const tbody = document.getElementById('bt-month');
  const yearRetVal = year ? st.year[year] : null;
  const quarterNum = m => Math.floor((m - 1) / 3) + 1;  // 1~3->Q1 ...
  // 逐月累计收益（复利）：cum[m] = 年初到 m 月的累计
  const cumRets = [];
  let cum = 1.0;
  for (let m = 1; m <= 12; m++) {{
    const mm = String(m).padStart(2, '0');
    const mr = st.month ? st.month[year + mm] : null;
    if (mr !== undefined && mr !== null && mr !== 0) cum *= (1 + mr);
    cumRets.push(cum - 1.0);
  }}
  // 累计条宽度：累计收益相对年内最大累计绝对值归一化（从左侧起点向右）
  const cumMax = Math.max(1e-9, ...cumRets.map(Math.abs));
  const cumBar = val => {{
    if (val === undefined || val === null) return '<div class="bt-cum empty"></div>';
    if (val === 0) return '<div class="bt-cum zero"></div>';
    const w = Math.min(100, Math.abs(val) / cumMax * 100);
    const c = val > 0 ? '#ffffff' : '#cfd4dc';
    return `<div class="bt-cum" style="width:${{w.toFixed(1)}}%;background:${{c}}"></div>`;
  }};
  // 当月交易次数（无交易的月份不显示）
  const cntHtml = cnt => (cnt === undefined || cnt === null) ? '' : `<span class="bt-cnt">${{cnt}}次</span>`;
  // 当月摸到涨停个数（最高价触及涨停价即算，不要求封板）；放在次数右侧只显示数字，0 也显示
  const topHtml = tp => (tp === undefined || tp === null) ? '' : `<span class="bt-tops" title="摸到涨停个数">${{tp}}</span>`;
  const monthRow = (m, mr, cnt, tp) => {{
    if (mr === undefined || mr === null) {{
      // 空白月：只显示月份，不显示条/累计盈亏
      return `<div class="bt-cell-inline"><span class="bt-mon">${{m}}月</span>${{cntHtml(cnt)}}${{topHtml(tp)}}</div>`;
    }}
    const v = fmtPct(mr);
    const cumVal = cumRets[m - 1];
    const cumStr = (cumVal !== undefined && cumVal !== null) ? fmtPct(cumVal) : '';
    return `<div class="bt-cell-inline">` +
      `<span class="bt-mon">${{m}}月</span>` +
      cntHtml(cnt) +
      topHtml(tp) +
      `<span class="bt-val ${{pctClass(mr)}}">${{v}}</span>` +
      `<span class="bt-cumtrack">${{cumBar(cumVal)}}</span>` +
      `<span class="bt-cumval ${{pctClass(cumVal)}}">${{cumStr}}</span>` +
      `</div>`;
  }};
  const plainCell = (val, cls) => {{
    const v = (val !== undefined && val !== null) ? fmtPct(val) : '';
    return `<span class="bt-val bt-big ${{cls}} ${{v ? pctClass(val) : ''}}">${{v}}</span>`;
  }};
  let html = '';
  for (let m = 1; m <= 12; m++) {{
    const mm = String(m).padStart(2, '0');
    const monthRet = st.month ? st.month[year + mm] : null;  // 无数据的月份显示空行
    const monthCnt = st.month_trades ? st.month_trades[year + mm] : null;  // 当月交易次数
    const monthTop = st.month_tops ? st.month_tops[year + mm] : null;      // 当月抓到涨停个数
    const qNum = quarterNum(m);
    const quarterRet = st.quarter ? st.quarter[year + 'Q' + qNum] : null;
    let qCell = '';
    if ((m % 3) === 1) {{
      qCell = `<td rowspan="3" class="bt-td-quarter bt-plain">${{plainCell(quarterRet, 'bt-q')}}</td>`;
    }} else {{
      qCell = '<td></td>';
    }}
    let yCell = '';
    if (m === 1) {{
      yCell = `<td rowspan="12" class="bt-td-year bt-plain">${{plainCell(yearRetVal, 'bt-y')}}</td>`;
    }} else {{
      yCell = '<td></td>';
    }}
    html += `<tr>
      <td class="bt-td-month">${{monthRow(m, monthRet, monthCnt, monthTop)}}</td>
      ${{qCell}}
      ${{yCell}}
    </tr>`;
  }}
  tbody.innerHTML = html || '<tr><td colspan="3" style="text-align:center;color:#6b7280">无数据</td></tr>';
}}
function renderPeriodTables(st) {{
  populateYearSelect(st);
  renderBtYearView(st);
}}

/* 全周期统计：最大连赢/连亏天数、最大回撤、最大盈利、胜率 */
function renderBtStats(st) {{
  const box = document.getElementById('bt-stats');
  if (!box) return;
  const rets = (st.rets || []).filter(v => v !== null && v !== undefined);
  let win = 0, loss = 0, maxWin = 0, maxLoss = 0, curW = 0, curL = 0;
  rets.forEach(r => {{
    if (r > 0) {{ win++; curW++; curL = 0; maxWin = Math.max(maxWin, curW); }}
    else if (r < 0) {{ loss++; curL++; curW = 0; maxLoss = Math.max(maxLoss, curL); }}
    else {{ curW = 0; curL = 0; }}
  }});
  // 最大回撤 / 最大盈利：基于资金曲线（回撤=峰值回落，盈利=谷值上冲，互为反向）
  const caps = (st.capitals || []).filter(v => v !== null && v !== undefined);
  let peak = 0, maxDrawdown = 0, trough = Infinity, maxGain = 0;
  caps.forEach(c => {{
    if (c > peak) peak = c;
    if (peak > 0) maxDrawdown = Math.max(maxDrawdown, (peak - c) / peak);
    if (c < trough) trough = c;
    if (trough > 0 && isFinite(trough)) maxGain = Math.max(maxGain, (c - trough) / trough);
  }});
  const totalDays = win + loss;
  const winRate = totalDays ? win / totalDays : 0;
  const stat = (k, v, cls) => `<div class="bt-stat"><span class="k">${{k}}</span><span class="v ${{cls}}">${{v}}</span></div>`;
  box.innerHTML =
    stat('最大连赢天数', maxWin + ' 天', 'pos') +
    stat('最大连亏天数', maxLoss + ' 天', 'neg') +
    stat('最大回撤', fmtPct(-maxDrawdown), 'neg') +
    stat('最大盈利', fmtPct(maxGain), 'pos') +
    stat('胜率', (winRate * 100).toFixed(1) + '%', 'gold') +
    stat('交易天数', totalDays, '');
}}

/* 正态分布：按 1% 为单位分桶。r 为小数涨跌幅，返回 labels, all, lastArr 三个数组 */
function buildDist(distArr) {{
  const vals = (distArr || []).filter(v => v !== null && v !== undefined);
  const last = vals.slice(-20);
  // 一次遍历统计频率，避免对每个桶全量 filter 导致的 O(n^2)
  const allMap = new Map(), lastMap = new Map();
  vals.forEach(v => {{ const k = Math.round(v * 100); allMap.set(k, (allMap.get(k) || 0) + 1); }});
  last.forEach(v => {{ const k = Math.round(v * 100); lastMap.set(k, (lastMap.get(k) || 0) + 1); }});
  // 固定横坐标范围 -10% ~ 10%（共 21 个整数百分比桶），超出范围的数据不显示
  const keys = [];
  for (let k = -10; k <= 10; k++) keys.push(k);
  return {{
    labels: keys.map(k => k + '%'),
    all: keys.map(k => allMap.get(k) || 0),
    lastArr: keys.map(k => lastMap.get(k) || 0),
  }};
}}

function renderDistChart(id, distArr) {{
  const el = document.getElementById(id);
  const key = 'dist_' + id;
  if (window[key]) {{ window[key].destroy(); window[key] = null; }}
  const {{ labels, all, lastArr }} = buildDist(distArr);
  window[key] = new Chart(el, {{
    type: 'line',
    data: {{ labels, datasets: [
      {{ label: '全部', data: all, borderColor: '#cfd4dc', backgroundColor: 'rgba(207,212,220,0.3)', fill: true, tension: 0.25, pointRadius: 0, borderWidth: 2 }},
      {{ label: '最近20日', data: lastArr, borderColor: '#ffffff', backgroundColor: 'rgba(255,255,255,0.25)', fill: true, tension: 0.25, pointRadius: 0, borderWidth: 2 }},
    ] }},
    options: {{ responsive: true, maintainAspectRatio: false, resizeDelay: 100, interaction: {{ mode: 'index', intersect: false }},
      plugins: {{ legend: {{ display: false }} }},
      scales: {{ x: {{ ticks: {{ color: '#9aa0a6', maxRotation: 0, autoSkip: true, maxTicksLimit: 11 }}, grid: {{ color: '#232a36' }} }},
                y: {{ ticks: {{ color: '#9aa0a6', precision: 0 }}, beginAtZero: true }} }} }}
  }});
}}

function renderDistCharts(st) {{
  const dist = st.dist || {{}};
  renderDistChart('dist-open', dist.open);
  renderDistChart('dist-high', dist.high);
  renderDistChart('dist-low', dist.low);
  renderDistChart('dist-close', dist.close);
}}

/* ------- 实盘候选池 ------- */
function loadCandidates() {{
  current.candStrategy = strategySelect2.value;
  // JS 的 Object.keys 对数字键会升序，这里手动倒序
  const dates = Object.keys(DATA.candidates[current.candStrategy] || {{}}).sort().reverse();
  const list = document.getElementById('date-list');
  list.innerHTML = '';
  if (dates.length === 0) {{ list.innerHTML = '<div class="empty-hint">无候选池</div>'; return; }}
  dates.forEach(d => {{
    const n = DATA.candidates[current.candStrategy][d].length;
    const el = document.createElement('div');
    el.className = 'date-item';
    el.innerHTML = d + '<span class="stock-count">' + n + '只</span>';
    el.onclick = () => {{ selectDate(d); }};
    list.appendChild(el);
  }});
  selectDate(dates[0]);  // 默认最新
}}

function selectDate(date) {{
  current.date = date;
  klineHighlight.candidate = ymdDash(date);   // 候选池日期（T-2 选股日）在 K 线上高亮
  document.querySelectorAll('.date-item').forEach(el => {{
    el.classList.toggle('active', el.textContent.startsWith(date));
  }});
  const stocks = DATA.candidates[current.candStrategy][date] || [];
  const list = document.getElementById('stock-list');
  list.innerHTML = '';
  if (stocks.length === 0) {{ list.innerHTML = '<div class="empty-hint">该日无候选股</div>'; return; }}
  stocks.forEach(s => {{
    const el = document.createElement('div');
    el.className = 'stock-item';
    el.innerHTML = s[0] + ' ' + s[1] + (s[2] ? '<span class="stock-market">' + fmtYi(s[2]) + '</span>' : '');
    el.onclick = () => {{ selectStock(s[0]); }};
    list.appendChild(el);
  }});
  prefetchPanelCodes('candidate', stocks.map(function (s) {{ return s[0]; }}));
  selectStock(stocks[0][0]);
}}

/* ------- 涨停股 ------- */
function loadTop() {{
  const dates = Object.keys(DATA.top || {{}}).sort().reverse();
  const list = document.getElementById('top-date-list');
  list.innerHTML = '';
  if (dates.length === 0) {{ list.innerHTML = '<div class="empty-hint">无涨停数据</div>'; return; }}
  dates.forEach(d => {{
    const n = (DATA.top[d] || []).length;
    const el = document.createElement('div');
    el.className = 'date-item';
    el.innerHTML = d + '<span class="stock-count">' + n + '只</span>';
    el.onclick = () => {{ selectTopDate(d); }};
    list.appendChild(el);
  }});
  selectTopDate(dates[0]);  // 默认最新
}}
function selectTopDate(date) {{
  current.topDate = date;
  klineHighlight.top = ymdDash(date);         // 涨停日在 K 线上高亮
  document.querySelectorAll('#top-date-list .date-item').forEach(el => {{
    el.classList.toggle('active', el.textContent.startsWith(date));
  }});
  const stocks = DATA.top[date] || [];
  const list = document.getElementById('top-stock-list');
  list.innerHTML = '';
  if (stocks.length === 0) {{ list.innerHTML = '<div class="empty-hint">该日无涨停股</div>'; return; }}
  stocks.forEach(s => {{
    const el = document.createElement('div');
    el.className = 'stock-item';
    el.innerHTML = s[0] + ' ' + s[1] + (s[2] ? '<span class="stock-market">' + fmtYi(s[2]) + '</span>' : '');
    el.onclick = () => {{ selectTopStock(s[0]); }};
    list.appendChild(el);
  }});
  prefetchPanelCodes('top', stocks.map(function (s) {{ return s[0]; }}));
  selectTopStock(stocks[0][0]);
}}
function selectTopStock(code) {{
  klineTarget = 'top';
  current.topCode = code;
  current.code = code;
  document.querySelectorAll('#top-stock-list .stock-item').forEach(el => {{
    el.classList.toggle('active', el.textContent.startsWith(code));
  }});
  selectStock(code);
}}

/* ------- 首板涨停股 ------- */
function loadTopFirst() {{
  const dates = Object.keys(DATA.top_first || {{}}).sort().reverse();
  const list = document.getElementById('top_first-date-list');
  list.innerHTML = '';
  if (dates.length === 0) {{ list.innerHTML = '<div class="empty-hint">无首板数据</div>'; return; }}
  dates.forEach(d => {{
    const n = (DATA.top_first[d] || []).length;
    const el = document.createElement('div');
    el.className = 'date-item';
    el.innerHTML = d + '<span class="stock-count">' + n + '只</span>';
    el.onclick = () => {{ selectTopFirstDate(d); }};
    list.appendChild(el);
  }});
  selectTopFirstDate(dates[0]);  // 默认最新
}}
function selectTopFirstDate(date) {{
  current.topFirstDate = date;
  klineHighlight.top_first = ymdDash(date);   // 首板日在 K 线上高亮
  document.querySelectorAll('#top_first-date-list .date-item').forEach(el => {{
    el.classList.toggle('active', el.textContent.startsWith(date));
  }});
  const stocks = DATA.top_first[date] || [];
  const list = document.getElementById('top_first-stock-list');
  list.innerHTML = '';
  if (stocks.length === 0) {{ list.innerHTML = '<div class="empty-hint">该日无首板涨停股</div>'; return; }}
  stocks.forEach(s => {{
    const el = document.createElement('div');
    el.className = 'stock-item';
    el.innerHTML = s[0] + ' ' + s[1] + (s[2] ? '<span class="stock-market">' + fmtYi(s[2]) + '</span>' : '');
    el.onclick = () => {{ selectTopFirstStock(s[0]); }};
    list.appendChild(el);
  }});
  prefetchPanelCodes('top_first', stocks.map(function (s) {{ return s[0]; }}));
  selectTopFirstStock(stocks[0][0]);
}}
function selectTopFirstStock(code) {{
  klineTarget = 'top_first';
  current.topFirstCode = code;
  current.code = code;
  document.querySelectorAll('#top_first-stock-list .stock-item').forEach(el => {{
    el.classList.toggle('active', el.textContent.startsWith(code));
  }});
  selectStock(code);
}}

/* ------- 首板涨停放量股（T-3 首板涨停放量 + T-2 上涨放量未涨停，不限市值）------- */
function loadTopFirstVol() {{
  const dates = Object.keys(DATA.top_first_vol || {{}}).sort().reverse();
  const list = document.getElementById('top_first_vol-date-list');
  list.innerHTML = '';
  if (dates.length === 0) {{ list.innerHTML = '<div class="empty-hint">无首板涨停放量数据</div>'; return; }}
  dates.forEach(d => {{
    const n = (DATA.top_first_vol[d] || []).length;
    const el = document.createElement('div');
    el.className = 'date-item';
    el.innerHTML = d + '<span class="stock-count">' + n + '只</span>';
    el.onclick = () => {{ selectTopFirstVolDate(d); }};
    list.appendChild(el);
  }});
  selectTopFirstVolDate(dates[0]);  // 默认最新
}}
function selectTopFirstVolDate(date) {{
  current.topFirstVolDate = date;
  klineHighlight.top_first_vol = ymdDash(date);   // 放量日(T-2)在 K 线上高亮
  document.querySelectorAll('#top_first_vol-date-list .date-item').forEach(el => {{
    el.classList.toggle('active', el.textContent.startsWith(date));
  }});
  const stocks = DATA.top_first_vol[date] || [];
  const list = document.getElementById('top_first_vol-stock-list');
  list.innerHTML = '';
  if (stocks.length === 0) {{ list.innerHTML = '<div class="empty-hint">该日无首板涨停放量股</div>'; return; }}
  stocks.forEach(s => {{
    const el = document.createElement('div');
    el.className = 'stock-item';
    el.innerHTML = s[0] + ' ' + s[1] + (s[2] ? '<span class="stock-market">' + fmtYi(s[2]) + '</span>' : '');
    el.onclick = () => {{ selectTopFirstVolStock(s[0]); }};
    list.appendChild(el);
  }});
  prefetchPanelCodes('top_first_vol', stocks.map(function (s) {{ return s[0]; }}));
  selectTopFirstVolStock(stocks[0][0]);
}}
function selectTopFirstVolStock(code) {{
  klineTarget = 'top_first_vol';
  current.topFirstVolCode = code;
  current.code = code;
  document.querySelectorAll('#top_first_vol-stock-list .stock-item').forEach(el => {{
    el.classList.toggle('active', el.textContent.startsWith(code));
  }});
  selectStock(code);
}}

/* ------- 首板涨停放量连阳股（TOP_FIRST_VOL + T-1 收>开 + T-1 创新高）------- */
function loadTopFirstVolSun() {{
  const dates = Object.keys(DATA.top_first_vol_sun || {{}}).sort().reverse();
  const list = document.getElementById('top_first_vol_sun-date-list');
  list.innerHTML = '';
  if (dates.length === 0) {{ list.innerHTML = '<div class="empty-hint">无首板涨停放量连阳数据</div>'; return; }}
  dates.forEach(d => {{
    const n = (DATA.top_first_vol_sun[d] || []).length;
    const el = document.createElement('div');
    el.className = 'date-item';
    el.innerHTML = d + '<span class="stock-count">' + n + '只</span>';
    el.onclick = () => {{ selectTopFirstVolSunDate(d); }};
    list.appendChild(el);
  }});
  selectTopFirstVolSunDate(dates[0]);  // 默认最新
}}
function selectTopFirstVolSunDate(date) {{
  current.topFirstVolSunDate = date;
  klineHighlight.top_first_vol_sun = ymdDash(date);   // 放量日(T-2)在 K 线上高亮
  document.querySelectorAll('#top_first_vol_sun-date-list .date-item').forEach(el => {{
    el.classList.toggle('active', el.textContent.startsWith(date));
  }});
  const stocks = DATA.top_first_vol_sun[date] || [];
  const list = document.getElementById('top_first_vol_sun-stock-list');
  list.innerHTML = '';
  if (stocks.length === 0) {{ list.innerHTML = '<div class="empty-hint">该日无首板涨停放量连阳股</div>'; return; }}
  stocks.forEach(s => {{
    const el = document.createElement('div');
    el.className = 'stock-item';
    el.innerHTML = s[0] + ' ' + s[1] + (s[2] ? '<span class="stock-market">' + fmtYi(s[2]) + '</span>' : '');
    el.onclick = () => {{ selectTopFirstVolSunStock(s[0]); }};
    list.appendChild(el);
  }});
  prefetchPanelCodes('top_first_vol_sun', stocks.map(function (s) {{ return s[0]; }}));
  selectTopFirstVolSunStock(stocks[0][0]);
}}
function selectTopFirstVolSunStock(code) {{
  klineTarget = 'top_first_vol_sun';
  current.topFirstVolSunCode = code;
  current.code = code;
  document.querySelectorAll('#top_first_vol_sun-stock-list .stock-item').forEach(el => {{
    el.classList.toggle('active', el.textContent.startsWith(code));
  }});
  selectStock(code);
}}

/* ==================== K 线增强（分栏指标/MA配置/BOLL/VWAP/月线） ==================== */
/* klineState：周期(day/month)、副图指标(volume/macd/kdj)、MA列表、BOLL/VWAP开关 */
const klineState = {{
  period: 'day',
  bars: [{{ type: 'volume', volMA: [5, 10] }}],   // 指标栏列表，最多 MAX_BARS 个
  // 默认 MA：5/10/20/30/60/120，全部默认显示（visible）。visible=false 时不在图上绘制。
  ma: [{{ p: 5, c: '#f5c518', visible: true }}, {{ p: 10, c: '#4ade80', visible: true }},
       {{ p: 20, c: '#38bdf8', visible: true }}, {{ p: 30, c: '#fb923c', visible: true }},
       {{ p: 60, c: '#c084fc', visible: true }}, {{ p: 120, c: '#f472b6', visible: true }}],
  showBOLL: false,
  showVWAP: false,
  colors: {{ up: '#d62828', down: '#0077b6', limitUp: '#f5c518' }},  // 涨/跌/涨停颜色（涨深红、跌深蓝，涨停保留金）
}};
const MAX_BARS = 3;

/* 资金 K 线独立状态：默认不显示成交量指标栏；颜色与候选池共享 */
const btKlineState = {{
  bars: [],                                   // 资金曲线默认无成交量/指标栏
  ma: klineState.ma.map(m => ({{ p: m.p, c: m.c, visible: m.visible !== false }})),  // 独立副本，避免与主图共享对象
  showBOLL: false,
  showVWAP: false,
  colors: klineState.colors,                  // 共享涨跌颜色
}};

const sentKlineState = {{
  bars: [],
  showBOLL: false,
  showVWAP: false,
  colors: klineState.colors,                  // 共享涨跌颜色
}};

/* ---- 周期数据：日线原样，月线聚合 ---- */
function monthKey(time) {{ return time.slice(0, 7); }}  // "2026-01"
function aggregateMonthly(daily) {{
  const map = new Map();
  daily.forEach(d => {{
    const mk = monthKey(d.time);
    const g = map.get(mk);
    if (!g) {{
      map.set(mk, {{ time: d.time.slice(0, 7) + '-01', open: d.open, high: d.high, low: d.low, close: d.close, volume: d.volume }});
    }} else {{
      g.high = Math.max(g.high, d.high);
      g.low = Math.min(g.low, d.low);
      g.close = d.close;
      g.volume += d.volume;
    }}
  }});
  return Array.from(map.values()).sort((a, b) => a.time < b.time ? -1 : 1);
}}
function getSeriesData(k) {{
  return klineState.period === 'month' ? aggregateMonthly(k.ohlcv) : k.ohlcv;
}}

/* ---- 指标计算 ---- */
function calcMA(data, period) {{
  const out = [];
  let sum = 0;
  for (let i = 0; i < data.length; i++) {{
    sum += data[i].close;
    if (i >= period) sum -= data[i - period].close;
    if (i >= period - 1) out.push({{ time: data[i].time, value: +(sum / period).toFixed(3) }});
  }}
  return out;
}}
/* 在 K 线容器左上角叠加全部 MA 数值浮层（取最新一根的均线值）。
   maList: [{{p, c, visible}}], getClose: 从数据项取收盘价。 */
function injectMaOverlay(mainEl, maList, data, getClose) {{
  if (!mainEl || !data || data.length === 0) return;
  mainEl.style.position = 'relative';
  let html = '';
  maList.forEach(ma => {{
    const p = ma.p;
    if (p <= 0 || ma.visible === false || data.length < p) return;
    let sum = 0;
    for (let i = data.length - p; i < data.length; i++) sum += getClose(data[i]);
    const v = sum / p;
    html += '<span style="color:' + ma.c + ';margin-right:12px;">MA' + p + ' <b>' + v.toFixed(2) + '</b></span>';
  }});
  if (!html) return;
  const div = document.createElement('div');
  div.className = 'ma-overlay';
  div.innerHTML = html;
  mainEl.appendChild(div);
}}
function emaArr(values, period) {{
  const k = 2 / (period + 1);
  const out = [];
  let prev = null;
  for (let i = 0; i < values.length; i++) {{
    prev = i === 0 ? values[i] : values[i] * k + prev * (1 - k);
    out.push(prev);
  }}
  return out;
}}
function calcMACD(data) {{
  const closes = data.map(d => d.close);
  const ema12 = emaArr(closes, 12), ema26 = emaArr(closes, 26);
  const dif = closes.map((_, i) => ema12[i] - ema26[i]);
  const dea = emaArr(dif, 9);
  const bars = data.map((d, i) => ({{
    time: d.time, value: (dif[i] - dea[i]) * 2, color: (dif[i] - dea[i]) >= 0 ? '#e8eaed55' : '#9aa0a655',
  }}));
  const difLine = data.map((d, i) => ({{ time: d.time, value: +dif[i].toFixed(3) }}));
  const deaLine = data.map((d, i) => ({{ time: d.time, value: +dea[i].toFixed(3) }}));
  return {{ bars, dif: difLine, dea: deaLine }};
}}
function calcKDJ(data, n = 9, m1 = 3, m2 = 3) {{
  const out = [];
  let rsv = [], k = 50, d = 50;
  for (let i = 0; i < data.length; i++) {{
    if (i >= n - 1) {{
      let hh = -Infinity, ll = Infinity;
      for (let j = i - n + 1; j <= i; j++) {{ hh = Math.max(hh, data[j].high); ll = Math.min(ll, data[j].low); }}
      rsv[i] = (hh === ll) ? 50 : (data[i].close - ll) / (hh - ll) * 100;
    }} else {{
      rsv[i] = 50;
    }}
    k = (m1 - 1) / m1 * k + (1 / m1) * rsv[i];
    d = (m2 - 1) / m2 * d + (1 / m2) * k;
    out.push({{ time: data[i].time, K: k, D: d, J: 3 * k - 2 * d }});
  }}
  return out;
}}
function calcBOLL(data, period = 20, mult = 2) {{
  const up = [], mid = [], low = [];
  for (let i = 0; i < data.length; i++) {{
    if (i >= period - 1) {{
      let s = 0;
      for (let j = i - period + 1; j <= i; j++) s += data[j].close;
      const ma = s / period;
      let v = 0;
      for (let j = i - period + 1; j <= i; j++) v += (data[j].close - ma) * (data[j].close - ma);
      const sd = Math.sqrt(v / period);
      const t = data[i].time;
      up.push({{ time: t, value: +(ma + mult * sd).toFixed(3) }});
      mid.push({{ time: t, value: +ma.toFixed(3) }});
      low.push({{ time: t, value: +(ma - mult * sd).toFixed(3) }});
    }}
  }}
  return {{ up, mid, low }};
}}
function calcVWAP(data) {{
  const out = [];
  let cumPV = 0, cumV = 0;
  for (let i = 0; i < data.length; i++) {{
    const tp = (data[i].high + data[i].low + data[i].close) / 3;
    cumPV += tp * data[i].volume;
    cumV += data[i].volume;
    out.push({{ time: data[i].time, value: +(cumPV / (cumV || 1)).toFixed(3) }});
  }}
  return out;
}}
/* 涨停幅度：创业/科创板20%，主板10% */
function limitRatio(code) {{
  const pure = code.split('.')[0];
  if (pure && (pure.startsWith('300') || pure.startsWith('301') || pure.startsWith('302') ||
               pure.startsWith('688') || pure.startsWith('689'))) return 0.20;
  return 0.10;
}}
/* 涨停价 = 前收×(1+涨幅)，四舍五入到分 */
function limitPrice(preClose, ratio) {{
  return Math.round(preClose * (1 + ratio) * 100) / 100;
}}
/* 标记每根K线是否涨停（收盘触及涨停价），返回 time -> isLimit 映射 */
function markLimitUp(data, code) {{
  const ratio = limitRatio(code);
  const map = new Map();
  for (let i = 1; i < data.length; i++) {{
    const pre = data[i - 1].close;
    if (pre > 0 && data[i].close >= limitPrice(pre, ratio)) map.set(data[i].time, true);
  }}
  return map;
}}
/* 单条记录是否「收盘涨停」（用于涨跌幅数字着色，与 K 线涨停金色一致） */
function isLimitUp(row) {{
  if (!row || !row.pre || !row.close) return false;
  return row.close >= limitPrice(row.pre, limitRatio(row.code));
}}
/* 成交量均线（VOL MA），对成交量序列求均值 */
function calcVolMA(data, period) {{
  const out = [];
  let sum = 0;
  for (let i = 0; i < data.length; i++) {{
    sum += data[i].volume;
    if (i >= period) sum -= data[i - period].volume;
    if (i >= period - 1) out.push({{ time: data[i].time, value: +(sum / period).toFixed(1) }});
  }}
  return out;
}}

/* 默认可见范围：总宽 日线2个月 / 月线24个月（≈2年），并以「重要日期」（选股日/涨停日/卖出日）为正中心；
   未选中个股（或无重要日期）时退化为以最后一根为正中心（即最近2个月） */
function setDefaultRange(chart, data) {{
  if (!data || !data.length) return;
  const last = data[data.length - 1].time;
  const half = klineState.period === 'month' ? 12 : 1;   // 半窗：日线1月、月线12月
  let center = last;
  const hl = klineHighlight[klineTarget];
  if (hl) {{
    const cand = data.find(x => x.time === hl) || data.find(x => x.time.slice(0, 7) === String(hl).slice(0, 7));
    if (cand) center = cand.time;
  }}
  const from = shiftMonth(center, -half);
  const to = shiftMonth(center, half);
  try {{ chart.timeScale().setVisibleRange({{ from: from, to: to }}); }}
  catch (e) {{ try {{ chart.timeScale().fitContent(); }} catch (e2) {{}} }}
}}
function shiftMonth(dateStr, delta) {{
  const d = new Date(dateStr);
  d.setMonth(d.getMonth() + delta);
  const y = d.getFullYear(), m = String(d.getMonth() + 1).padStart(2, '0'), day = String(d.getDate()).padStart(2, '0');
  return y + '-' + m + '-' + day;
}}
/* 5 分钟 K 线的 MA：直接对紧凑数组 [ts,o,h,l,c,v] 的收盘价求均值 */
function calcMA5m(bars, period) {{
  const out = [];
  let sum = 0;
  for (let i = 0; i < bars.length; i++) {{
    sum += bars[i][4];
    if (i >= period) sum -= bars[i - period][4];
    if (i >= period - 1) out.push({{ time: bars[i][0], value: +(sum / period).toFixed(3) }});
  }}
  return out;
}}
/* 获取某股的 5 分钟窗口数据：file:// 离线模式用内嵌的 DATA.fiveMin；http 服务模式向 /api/5m 按实际锚定日精确取数 */
function get5m(code, anchor, cb) {{
  if (IS_FILE_PROTOCOL) {{
    const fm = DATA.fiveMin && DATA.fiveMin[code];
    if (!fm) {{ cb(null); return; }}
    cb(fm[anchor] || fm.__default__ || null);   // 离线按选中日精确取；无命中则回退最晚日窗口
    return;
  }}
  fetch('/api/5m?code=' + encodeURIComponent(code) + '&anchor=' + encodeURIComponent(anchor || ''))
    .then(r => r.json()).then(d => cb(d && d.ok ? d.bars : null))
    .catch(() => cb(null));
}}
/* 渲染 5 分钟 K 线（日线下方，约半高）：蜡烛 + MA（共享 klineState.ma）+ 成交量分栏 */
let _chart5m = null;
function destroyKline5m() {{
  if (_chart5m) {{ try {{ _chart5m.remove(); }} catch (e) {{}} _chart5m = null; }}
}}
function renderKline5m(code, anchor) {{
  const box = document.getElementById(klineEl('kline-5m'));
  if (!box) return;
  box.innerHTML = '<div id="' + klineEl('kline-5m-main') + '"></div>';
  destroyKline5m();
  get5m(code, anchor, (bars) => {{
    const mainEl = document.getElementById(klineEl('kline-5m-main'));
    if (!bars || !bars.length) {{
      mainEl.innerHTML = '<div class="empty-hint">暂无 5 分钟数据（请确认已更新 5M 数据；离线模式可运行本地服务查看）</div>';
      return;
    }}
    const chart = LightweightCharts.createChart(mainEl, {{
      layout: {{ background: {{ type: LightweightCharts.ColorType.Solid, color: '#000000' }}, textColor: '#d1d4dc' }},
      grid: {{ vertLines: {{ color: '#161616' }}, horzLines: {{ color: '#161616' }} }},
      rightPriceScale: {{ borderColor: '#2b2b43' }},
      timeScale: {{ borderColor: '#2b2b43', timeVisible: true, secondsVisible: false }},
      crosshair: {{ mode: LightweightCharts.CrosshairMode.Normal }},
      height: mainEl.offsetHeight || 300,
    }});
    _chart5m = chart;
    const c = klineState.colors;
    const candle = chart.addSeries(LightweightCharts.CandlestickSeries, {{
      upColor: '#d62828', downColor: '#0077b6', borderUpColor: '#d62828', borderDownColor: '#0077b6',
      wickUpColor: '#d62828', wickDownColor: '#0077b6',
    }});
    candle.setData(bars.map(b => ({{ time: b[0], open: b[1], high: b[2], low: b[3], close: b[4] }})));
    klineState.ma.forEach(ma => {{
      if (ma.p <= 0 || ma.visible === false) return;
      chart.addSeries(LightweightCharts.LineSeries, {{ color: ma.c, lineWidth: 1, priceLineVisible: false, lastValueVisible: false }})
        .setData(calcMA5m(bars, ma.p));
    }});
    injectMaOverlay(mainEl, klineState.ma, bars, b => b[4]);
    const pane = chart.addPane();
    const vol = pane.addSeries(LightweightCharts.HistogramSeries, {{ priceFormat: {{ type: 'volume' }} }});
    vol.setData(bars.map(b => ({{ time: b[0], value: b[5], color: b[4] >= b[1] ? c.up + '66' : c.down + '66' }})));
    chart.timeScale().fitContent();
  }});
}}
/* ---- K 线渲染（LightweightCharts v5 原生分栏：主图 + 最多3个指标栏，自动对齐与十字线贯穿） ---- */
let _chart = null;
/* K 线渲染目标：'candidate'（实盘候选池）、'top'（涨停股）、'detail'（策略选股）。
   共用一套渲染函数，按目标给 DOM id 加不同前缀，从而访问各自面板的元素。 */
let klineTarget = 'candidate';
const KLINE_PREFIX = {{ candidate: '', top: 'top-', detail: 'detail-', top_first: 'top_first-', top_first_vol: 'top_first_vol-', top_first_vol_sun: 'top_first_vol_sun-' }};
/* 各面板的「重要日期」（YYYY-MM-DD），在 K 线上用标记高亮：
     candidate = 候选池日期（T-2 选股日）；top = 涨停日；detail = 该行卖出日（T-0） */
const KLINE_HL_LABEL = {{ candidate: '选股日', top: '涨停日', detail: '卖出日', top_first: '首板日', top_first_vol: '放量日', top_first_vol_sun: '放量日' }};
const klineHighlight = {{ candidate: '', top: '', detail: '', top_first: '', top_first_vol: '', top_first_vol_sun: '' }};
function klineEl(id) {{
  const p = KLINE_PREFIX[klineTarget] || '';
  return (p && id.indexOf(p) !== 0) ? p + id : id;
}}
function destroyKline() {{
  if (_chart) {{ try {{ _chart.remove(); }} catch(e) {{}} _chart = null; }}
}}
/* 主图悬浮时在标题栏下方显示当天数据 */
function showDayInfo(chart, candleSeries, data, limitMap) {{
  chart.subscribeCrosshairMove(param => {{
    const info = document.getElementById(klineEl('kline-info'));
    if (!param.time) {{ if (info && info.dataset.base) info.textContent = info.dataset.base; return; }}
    // 始终从完整 data（内嵌含 pre_close）查找，避免 seriesData 不含 pre_close 导致涨跌幅用 open
    let d = null;
    for (let i = 0; i < data.length; i++) {{ if (data[i].time === param.time) {{ d = data[i]; break; }} }}
    if (!d) d = param.seriesData ? param.seriesData.get(candleSeries) : null;
    if (!d) return;
    const base = info.dataset.base || '';
    const pc = d.pre_close || d.open;
    const chg = pc > 0 ? ((d.close - pc) / pc * 100).toFixed(2) : '0.00';
    const cls = (limitMap && limitMap.has(d.time)) ? 'limit-up' : (d.close >= pc ? 'up' : 'down');
    info.innerHTML = base + ' <span class="' + cls + '">' + d.time + '</span>' +
      ' 开 ' + d.open + ' 高 ' + d.high + ' 低 ' + d.low + ' 收 ' + d.close +
      ' 涨跌 <span class="' + cls + '">' + chg + '%</span>' +
      ' 量 ' + d.volume;
  }});
}}
/* 渲染单个指标栏（v5 addPane 分栏，pane 为独立窗格） */
function renderIndicatorBar(pane, bar, data, limitMap) {{
  if (bar.type === 'volume') {{
    const vol = pane.addSeries(LightweightCharts.HistogramSeries, {{ priceFormat: {{ type: 'volume' }} }});
    vol.setData(data.map(d => ({{
      time: d.time, value: d.volume,
      color: limitMap.has(d.time) ? klineState.colors.limitUp + 'aa' : (d.close >= d.open ? klineState.colors.up + '66' : klineState.colors.down + '66'),
    }})));
    // 成交量均线（可配置）
    (bar.volMA || []).forEach((p, i) => {{
      if (p <= 0) return;
      pane.addSeries(LightweightCharts.LineSeries, {{ color: i === 0 ? '#e8eaed' : '#c0c4cc', lineWidth: 1, priceLineVisible: false, lastValueVisible: false }})
        .setData(calcVolMA(data, p));
    }});
  }} else if (bar.type === 'macd') {{
    const macd = calcMACD(data);
    const b = pane.addSeries(LightweightCharts.HistogramSeries, {{}});
    b.setData(macd.bars.map(x => ({{
      time: x.time, value: x.value,
      color: x.value >= 0 ? klineState.colors.up + '55' : klineState.colors.down + '55',
    }})));
    pane.addSeries(LightweightCharts.LineSeries, {{ color: '#e8eaed', lineWidth: 1, priceLineVisible: false, lastValueVisible: false }}).setData(macd.dif);
    pane.addSeries(LightweightCharts.LineSeries, {{ color: '#9aa0a6', lineWidth: 1, priceLineVisible: false, lastValueVisible: false }}).setData(macd.dea);
  }} else if (bar.type === 'kdj') {{
    const kdj = calcKDJ(data);
    pane.addSeries(LightweightCharts.LineSeries, {{ color: '#cfd4dc', lineWidth: 1, priceLineVisible: false, lastValueVisible: false }}).setData(kdj.map(x => ({{ time: x.time, value: +x.K.toFixed(2) }})));
    pane.addSeries(LightweightCharts.LineSeries, {{ color: '#e8eaed', lineWidth: 1, priceLineVisible: false, lastValueVisible: false }}).setData(kdj.map(x => ({{ time: x.time, value: +x.D.toFixed(2) }})));
    pane.addSeries(LightweightCharts.LineSeries, {{ color: '#8a93a8', lineWidth: 1, priceLineVisible: false, lastValueVisible: false }}).setData(kdj.map(x => ({{ time: x.time, value: +x.J.toFixed(2) }})));
  }}
}}
/* YYYYMMDD -> YYYY-MM-DD（K 线时间轴格式） */
function ymdDash(d) {{ return String(d || '').length === 8 ? d.slice(0, 4) + '-' + d.slice(4, 6) + '-' + d.slice(6, 8) : (d || ''); }}

/* 重要日期高亮：v5 已移除 series.setMarkers（仅 markers 原语 createSeriesMarkers 才有），
   故改用 HTML 覆盖层自绘「高亮框」：坐标换算用 timeToCoordinate / priceToCoordinate，
   并随缩放、平移、窗口变化重绘。全程 try/catch：高亮失败绝不影响主图渲染。 */
let hlResizeHandler = null;
function applyKlineHighlight(candleSeries, data) {{
  const host = document.getElementById(klineEl('kline-main'));
  const old = document.getElementById(klineEl('kline-hlbox'));
  if (old) {{ try {{ old.remove(); }} catch (e) {{}} }}
  if (hlResizeHandler) {{ try {{ window.removeEventListener('resize', hlResizeHandler); }} catch (e) {{}} hlResizeHandler = null; }}
  const raw = klineHighlight[klineTarget] || '';
  if (!raw || !_chart || !host) return;
  // 月线周期下时间是 YYYY-MM-01，需把日期归到所属月份
  const t = (klineState.period === 'month') ? raw.slice(0, 7) + '-01' : raw;
  const d = data.find(x => x.time === t);
  if (!d) return;

  const box = document.createElement('div');
  box.id = klineEl('kline-hlbox');
  box.className = 'kline-hlbox';
  host.appendChild(box);

  const place = () => {{
    try {{
      const ts = _chart.timeScale();
      const x = ts.timeToCoordinate(t);
      const yTop = candleSeries.priceToCoordinate(d.high);
      const yBot = candleSeries.priceToCoordinate(d.low);
      if (x === null || x === undefined || yTop === null || yTop === undefined
          || yBot === null || yBot === undefined) {{ box.style.display = 'none'; return; }}
      // 更细更长的竖框：宽 ~10px，上下各外扩 26px，便于一眼定位到该根 K 线
      const padX = 3, padY = 26, w = 4;
      box.style.display = 'block';
      box.style.left = (x - w / 2 - padX) + 'px';
      box.style.width = (w + padX * 2) + 'px';
      box.style.top = (Math.min(yTop, yBot) - padY) + 'px';
      box.style.height = (Math.abs(yBot - yTop) + padY * 2) + 'px';
    }} catch (e) {{ box.style.display = 'none'; }}
  }};
  place();
  requestAnimationFrame(place);              // 等布局稳定后再校准一次
  try {{ _chart.timeScale().subscribeVisibleTimeRangeChange(place); }} catch (e) {{}}
  hlResizeHandler = place;
  window.addEventListener('resize', place);
}}
function renderKline(k) {{
  const data = getSeriesData(k);
  const box = document.getElementById(klineEl('kline'));
  box.innerHTML = '<div id="' + klineEl('kline-main') + '"></div>';
  destroyKline();

  const mainEl = document.getElementById(klineEl('kline-main'));
  _chart = LightweightCharts.createChart(mainEl, {{
    layout: {{ background: {{ type: LightweightCharts.ColorType.Solid, color: '#000000' }}, textColor: '#d1d4dc' }},
    grid: {{ vertLines: {{ color: '#161616' }}, horzLines: {{ color: '#161616' }} }},
    rightPriceScale: {{ borderColor: '#2b2b43' }},
    timeScale: {{ borderColor: '#2b2b43' }},
    crosshair: {{ mode: LightweightCharts.CrosshairMode.Normal }},
    height: mainEl.offsetHeight || 600,
  }});

  // 涨停标记（黄色显示）
  const limitMap = markLimitUp(data, current.code);

  // 主图：K线（涨停日黄色）
  const c = klineState.colors;
  const candle = _chart.addSeries(LightweightCharts.CandlestickSeries, {{
    upColor: '#d62828', downColor: '#0077b6', borderUpColor: '#d62828', borderDownColor: '#0077b6',
    wickUpColor: '#d62828', wickDownColor: '#0077b6',
  }});
  candle.setData(data.map(d => {{
    const o = {{ time: d.time, open: d.open, high: d.high, low: d.low, close: d.close }};
    if (limitMap.has(d.time)) o.color = c.limitUp;
    return o;
  }}));
  // 高亮该面板的「重要日期」：出错也不影响主图与均线的渲染
  try {{ applyKlineHighlight(candle, data); }} catch (e) {{}}
  // 主图：MA（可配置周期与颜色）
  klineState.ma.forEach(ma => {{
    if (ma.p <= 0 || ma.visible === false) return;
    _chart.addSeries(LightweightCharts.LineSeries, {{ color: ma.c, lineWidth: 1, priceLineVisible: false, lastValueVisible: false }}).setData(calcMA(data, ma.p));
  }});
  // 主图：BOLL
  if (klineState.showBOLL) {{
    const boll = calcBOLL(data);
    _chart.addSeries(LightweightCharts.LineSeries, {{ color: '#9aa0a6', lineWidth: 1, priceLineVisible: false, lastValueVisible: false }}).setData(boll.up);
    _chart.addSeries(LightweightCharts.LineSeries, {{ color: '#9aa0a6', lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dotted, priceLineVisible: false, lastValueVisible: false }}).setData(boll.mid);
    _chart.addSeries(LightweightCharts.LineSeries, {{ color: '#9aa0a6', lineWidth: 1, priceLineVisible: false, lastValueVisible: false }}).setData(boll.low);
  }}
  // 主图：VWAP
  if (klineState.showVWAP) {{
    _chart.addSeries(LightweightCharts.LineSeries, {{ color: '#c0c4cc', lineWidth: 2, priceLineVisible: true, lastValueVisible: true }}).setData(calcVWAP(data));
  }}
  // 左上角 MA 数值浮层（最新一根）
  injectMaOverlay(mainEl, klineState.ma, data, d => d.close);

  // 各指标栏：v5 原生分栏（addPane），价格刻度/时间轴/十字线自动对齐
  klineState.bars.forEach(bar => {{
    const pane = _chart.addPane();
    renderIndicatorBar(pane, bar, data, limitMap);
  }});

  _chart.timeScale().fitContent();
  setDefaultRange(_chart, data);
  showDayInfo(_chart, candle, data, limitMap);
  renderMaRow();  // 刷新当前面板（及所有面板）的 MA 复选框行
}}

/* 标题栏 HTML：涨跌幅放最前（大字号红绿色），后跟名称/代码/周期 */
function klineTitleHtml(k, code) {{
  let chg = '';
  if (k && k.ohlcv.length) {{
    const last = k.ohlcv[k.ohlcv.length - 1];
    const prev = last.pre_close || last.open;
    const pct = prev > 0 ? (last.close - prev) / prev * 100 : 0;
    const isLimit = last.close >= limitPrice(prev, limitRatio(code));
    const cls = isLimit ? 'limit-up' : (pct >= 0 ? 'up' : 'down');
    chg = '<span class="chg-big ' + cls + '">' + (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%</span>';
  }}
  const name = (k && k.name ? k.name + '  ' : '');
  const per = klineState.period === 'month' ? '月线' : '日线';
  const n = k ? k.ohlcv.length : 0;
  return '<span style="font-size:14px;font-weight:600;color:#e4e6eb">' + name + code + '  ' + per + '（共 ' + n + ' 根）</span> ' + chg;
}}
async function selectStock(code) {{
  await ensureStock(code);
  current.code = code;
  document.querySelectorAll('.stock-item').forEach(el => {{
    el.classList.toggle('active', el.textContent.startsWith(code));
  }});
  const k = DATA.kline[code];
  const title = document.getElementById(klineEl('kline-title'));
  title.innerHTML = klineTitleHtml(k, code);
  const info = document.getElementById(klineEl('kline-info'));
  const base = (k && k.name ? k.name + '  ' : '') + code + '  ' + (klineState.period === 'month' ? '月线' : '日线');
  info.dataset.base = base;
  info.textContent = base;
  if (!k || k.ohlcv.length === 0) {{
    destroyKline();
    document.getElementById(klineEl('kline')).innerHTML = '<div id="' + klineEl('kline-main') + '"><div class="empty-hint">暂无 K 线数据</div></div>';
    destroyKline5m();
    document.getElementById(klineEl('kline-5m')).innerHTML = '<div id="' + klineEl('kline-5m-main') + '"><div class="empty-hint">请选择个股查看 5 分钟 K 线</div></div>';
    return;
  }}
  requestAnimationFrame(() => {{ renderKline(k); renderKline5m(code, klineHighlight[klineTarget]); }});
}}

/* ---- MA 复选框行（默认显示，左对齐一排，勾选=显示对应均线）---- */
/* 主图面板（candidate/top/top_first/top_first_vol/top_first_vol_sun/detail）共享 klineState.ma；
   资金 K 线面板（bt）使用独立 btKlineState.ma。两者均默认显示 MA5/10/20/30/60/120。 */
const _MA_ROW_PREFIXES = ['', 'top-', 'top_first-', 'top_first_vol-', 'top_first_vol_sun-', 'detail-'];
function renderMaRow() {{
  _MA_ROW_PREFIXES.forEach(prefix => {{
    _fillMaRow(prefix + 'kline-ma-row', klineState.ma, rerenderKline);
  }});
  _fillMaRow('bt-kline-ma-row', btKlineState.ma, rerenderBtKline);
}}
function _fillMaRow(id, maList, rerender) {{
  const box = document.getElementById(id);
  if (!box) return;
  box.innerHTML = '';
  const tip = document.createElement('span');
  tip.className = 'ma-row-tip';
  tip.textContent = 'MA';
  box.appendChild(tip);
  maList.forEach((ma, i) => {{
    const lab = document.createElement('label');
    lab.className = 'ma-chk';
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = ma.visible !== false;
    cb.style.accentColor = ma.c;
    cb.onchange = () => {{ ma.visible = cb.checked; rerender(); }};
    lab.appendChild(cb);
    const txt = document.createElement('span');
    txt.textContent = ma.p;
    txt.style.color = ma.c;
    lab.appendChild(txt);
    box.appendChild(lab);
  }});
}}
/* ---- MA 配置面板 ---- */
function renderMaConfig() {{
  const cfg = document.getElementById(klineEl('kline-ma-config'));
  if (cfg.style.display === 'none') return;
  cfg.innerHTML = '';
  klineState.ma.forEach((ma, i) => {{
    const row = document.createElement('div');
    row.className = 'ma-row';
    row.innerHTML = '<span>MA</span><input type="number" class="ma-p" value="' + ma.p + '" min="1" max="250" title="周期">' +
      '<input type="color" class="ma-c" value="' + ma.c + '" title="颜色">' +
      '<button type="button" class="ma-del">×</button>';
    row.querySelector('.ma-p').onchange = e => {{ ma.p = +e.target.value || 5; rerenderKline(); }};
    row.querySelector('.ma-c').oninput = e => {{ ma.c = e.target.value; rerenderKline(); }};
    row.querySelector('.ma-del').onclick = () => {{ klineState.ma.splice(i, 1); renderMaConfig(); rerenderKline(); }};
    cfg.appendChild(row);
  }});
}}
function rerenderKline() {{
  if (current.code && DATA.kline[current.code]) {{
    const code = current.code;
    const anchor = klineHighlight[klineTarget];
    requestAnimationFrame(() => {{ renderKline(DATA.kline[code]); renderKline5m(code, anchor); }});
  }}
}}
/* ---- 指标栏管理面板 ---- */
function renderBarConfig() {{
  const box = document.getElementById(klineEl('kline-bars'));
  box.innerHTML = '';
  klineState.bars.forEach((bar, i) => {{
    const row = document.createElement('div');
    row.className = 'bar-row';
    row.innerHTML = '<span class="bar-label">栏' + (i + 1) + '</span>' +
      '<select class="bar-type">' +
      '<option value="volume"' + (bar.type === 'volume' ? ' selected' : '') + '>成交量</option>' +
      '<option value="macd"' + (bar.type === 'macd' ? ' selected' : '') + '>MACD</option>' +
      '<option value="kdj"' + (bar.type === 'kdj' ? ' selected' : '') + '>KDJ</option>' +
      '</select>' +
      '<span class="bar-volma" title="成交量均线，逗号分隔">VOL MA:</span>' +
      '<input type="text" class="bar-volma-input" value="' + (bar.volMA || []).join(',') + '" placeholder="5,10">' +
      '<button type="button" class="bar-del">×</button>';
    row.querySelector('.bar-type').onchange = e => {{ bar.type = e.target.value; renderBarConfig(); rerenderKline(); }};
    row.querySelector('.bar-volma-input').onchange = e => {{
      const arr = e.target.value.split(',').map(x => parseInt(x, 10)).filter(x => !isNaN(x) && x > 0);
      bar.volMA = arr.length ? arr.slice(0, 3) : [5, 10];
      rerenderKline();
    }};
    row.querySelector('.bar-del').onclick = () => {{
      klineState.bars.splice(i, 1);
      renderBarConfig(); rerenderKline();
    }};
    // 非成交量栏隐藏 VOL MA 配置
    if (bar.type !== 'volume') {{
      row.querySelector('.bar-volma').style.display = 'none';
      row.querySelector('.bar-volma-input').style.display = 'none';
    }}
    box.appendChild(row);
  }});
  const add = document.createElement('button');
  add.type = 'button';
  add.textContent = '+ 添加指标栏';
  add.style.cssText = 'width:100%;margin-top:4px;background:#1c2029;color:#e4e6eb;border:1px solid #2a3140;border-radius:6px;padding:5px;font-size:12px;cursor:pointer;';
  add.onclick = () => {{
    if (klineState.bars.length >= MAX_BARS) return;
    const types = ['volume', 'macd', 'kdj'].filter(t => !klineState.bars.some(b => b.type === t));
    klineState.bars.push({{ type: types[0] || 'macd', volMA: [5, 10] }});
    renderBarConfig(); rerenderKline();
  }};
  if (klineState.bars.length < MAX_BARS) box.appendChild(add);
}}
/* ---- 涨跌/涨停颜色配置面板 ---- */
function renderColorConfig() {{
  const box = document.getElementById(klineEl('kline-color-config'));
  box.innerHTML = '';
  const defs = [['up', '涨', klineState.colors.up], ['down', '跌', klineState.colors.down], ['limitUp', '涨停', klineState.colors.limitUp]];
  defs.forEach(([key, label, val]) => {{
    const row = document.createElement('div');
    row.className = 'ma-row';
    row.innerHTML = '<span>' + label + '</span><input type="color" value="' + val + '" title="' + label + '">';
    row.querySelector('input').oninput = e => {{ klineState.colors[key] = e.target.value; renderColorConfig(); rerenderKline(); }};
    box.appendChild(row);
  }});
}}
function initKlineControls() {{
  document.getElementById('kline-period').onchange = e => {{
    klineState.period = e.target.value;
    const k = current.code && DATA.kline[current.code];
    document.getElementById('kline-title').innerHTML = klineTitleHtml(k, current.code || '');
    rerenderKline();
  }};
  const barsPanel = document.getElementById('kline-bars');
  const barBtn = document.getElementById('kline-bar-btn');
  function toggleBarsPanel(forceShow) {{
    const show = (forceShow !== undefined) ? forceShow : (barsPanel.style.display === 'none' || barsPanel.style.display === '');
    barsPanel.style.display = show ? 'block' : 'none';
    if (show) renderBarConfig();
  }}
  barBtn.onclick = () => toggleBarsPanel();
  document.getElementById('kline-boll').onchange = e => {{ klineState.showBOLL = e.target.checked; rerenderKline(); }};
  document.getElementById('kline-vwap').onchange = e => {{ klineState.showVWAP = e.target.checked; rerenderKline(); }};
  const maBtn = document.getElementById('kline-ma-btn');
  const cfg = document.getElementById('kline-ma-config');
  maBtn.onclick = () => {{
    const show = (cfg.style.display === 'none' || cfg.style.display === '');
    cfg.style.display = show ? 'block' : 'none';
    if (show) renderMaConfig();
  }};
  const addBtn = document.getElementById('kline-ma-add');
  addBtn.onclick = () => {{
    klineState.ma.push({{ p: 5, c: '#aab0bc', visible: true }});
    renderMaConfig(); rerenderKline();
  }};
  addBtn.style.display = 'inline-block';
  // 涨跌颜色面板开关
  const colorBtn = document.getElementById('kline-color-btn');
  const colorCfg = document.getElementById(klineEl('kline-color-config'));
  colorBtn.onclick = () => {{
    const show = (colorCfg.style.display === 'none' || colorCfg.style.display === '');
    colorCfg.style.display = show ? 'block' : 'none';
    if (show) renderColorConfig();
  }};
  renderBarConfig();
}}
/* 回测资金 K 线的指标栏/MA/颜色控制（共享 klineState，独立 DOM） */
function initBtKlineControls() {{
  const barsPanel = document.getElementById('bt-bars');
  const barBtn = document.getElementById('bt-bar-btn');
  barBtn.onclick = () => {{
    const show = (barsPanel.style.display === 'none' || barsPanel.style.display === '');
    barsPanel.style.display = show ? 'block' : 'none';
    if (show) renderBtBarConfig();
  }};
  document.getElementById('bt-boll').onchange = e => {{ btKlineState.showBOLL = e.target.checked; rerenderBtKline(); }};
  document.getElementById('bt-vwap').onchange = e => {{ btKlineState.showVWAP = e.target.checked; rerenderBtKline(); }};
  const cfg = document.getElementById('bt-ma-config');
  document.getElementById('bt-ma-btn').onclick = () => {{
    const show = (cfg.style.display === 'none' || cfg.style.display === '');
    cfg.style.display = show ? 'block' : 'none';
    if (show) renderBtMaConfig();
  }};
  const addBtn = document.getElementById('bt-ma-add');
  addBtn.onclick = () => {{
    btKlineState.ma.push({{ p: 5, c: '#aab0bc', visible: true }});
    renderBtMaConfig(); rerenderBtKline();
  }};
  addBtn.style.display = 'inline-block';
  const colorCfg = document.getElementById('bt-color-config');
  document.getElementById('bt-color-btn').onclick = () => {{
    const show = (colorCfg.style.display === 'none' || colorCfg.style.display === '');
    colorCfg.style.display = show ? 'block' : 'none';
    if (show) renderBtColorConfig();
  }};
  renderBtBarConfig();

}}
/* 涨停 TAB 的 K 线控制：复用共享 klineState，DOM 用 top- 前缀 */
function initTopKlineControls() {{
  document.getElementById('top-kline-period').onchange = e => {{
    klineState.period = e.target.value;
    if (current.topCode && DATA.kline[current.topCode]) {{
      document.getElementById(klineEl('kline-title')).innerHTML = klineTitleHtml(DATA.kline[current.topCode], current.topCode);
      rerenderKline();
    }}
  }};
  document.getElementById('top-boll').onchange = e => {{ klineState.showBOLL = e.target.checked; rerenderKline(); }};
  document.getElementById('top-vwap').onchange = e => {{ klineState.showVWAP = e.target.checked; rerenderKline(); }};
  document.getElementById('top-ma-btn').onclick = () => {{
    const cfg = document.getElementById('top-ma-config');
    const show = (cfg.style.display === 'none' || cfg.style.display === '');
    cfg.style.display = show ? 'block' : 'none';
    if (show) renderMaConfig();
  }};
  document.getElementById('top-ma-add').onclick = () => {{
    klineState.ma.push({{ p: 5, c: '#aab0bc', visible: true }});
    renderMaConfig(); rerenderKline();
  }};
  document.getElementById('top-ma-add').style.display = 'inline-block';
  document.getElementById('top-bar-btn').onclick = () => {{
    const barsPanel = document.getElementById('top-bars');
    const show = (barsPanel.style.display === 'none' || barsPanel.style.display === '');
    barsPanel.style.display = show ? 'block' : 'none';
    if (show) renderBarConfig();
  }};
  document.getElementById('top-color-btn').onclick = () => {{
    const cfg = document.getElementById('top-color-config');
    const show = (cfg.style.display === 'none' || cfg.style.display === '');
    cfg.style.display = show ? 'block' : 'none';
    if (show) renderColorConfig();
  }};
}}
/* 首板涨停 TAB 的 K 线控制：复用共享 klineState，DOM 用 top_first- 前缀 */
function initTopFirstKlineControls() {{
  document.getElementById('top_first-kline-period').onchange = e => {{
    klineState.period = e.target.value;
    if (current.topFirstCode && DATA.kline[current.topFirstCode]) {{
      document.getElementById(klineEl('kline-title')).innerHTML = klineTitleHtml(DATA.kline[current.topFirstCode], current.topFirstCode);
      rerenderKline();
    }}
  }};
  document.getElementById('top_first-boll').onchange = e => {{ klineState.showBOLL = e.target.checked; rerenderKline(); }};
  document.getElementById('top_first-vwap').onchange = e => {{ klineState.showVWAP = e.target.checked; rerenderKline(); }};
  document.getElementById('top_first-ma-btn').onclick = () => {{
    const cfg = document.getElementById('top_first-ma-config');
    const show = (cfg.style.display === 'none' || cfg.style.display === '');
    cfg.style.display = show ? 'block' : 'none';
    renderMaConfig(); rerenderKline();
  }};
  document.getElementById('top_first-ma-add').style.display = 'inline-block';
  document.getElementById('top_first-bar-btn').onclick = () => {{
    const barsPanel = document.getElementById('top_first-bars');
    const show = (barsPanel.style.display === 'none' || barsPanel.style.display === '');
    barsPanel.style.display = show ? 'block' : 'none';
    if (show) renderBarConfig();
  }};
  document.getElementById('top_first-color-btn').onclick = () => {{
    const cfg = document.getElementById('top_first-color-config');
    const show = (cfg.style.display === 'none' || cfg.style.display === '');
    cfg.style.display = show ? 'block' : 'none';
    if (show) renderColorConfig();
  }}
}}
/* 首板涨停放量股 TAB 的 K 线控制：复用共享 klineState，DOM 用 top_first_vol- 前缀 */
function initTopFirstVolKlineControls() {{
  document.getElementById('top_first_vol-kline-period').onchange = e => {{
    klineState.period = e.target.value;
    if (current.topFirstVolCode && DATA.kline[current.topFirstVolCode]) {{
      document.getElementById(klineEl('kline-title')).innerHTML = klineTitleHtml(DATA.kline[current.topFirstVolCode], current.topFirstVolCode);
      rerenderKline();
    }}
  }};
  document.getElementById('top_first_vol-boll').onchange = e => {{ klineState.showBOLL = e.target.checked; rerenderKline(); }};
  document.getElementById('top_first_vol-vwap').onchange = e => {{ klineState.showVWAP = e.target.checked; rerenderKline(); }};
  document.getElementById('top_first_vol-ma-btn').onclick = () => {{
    const cfg = document.getElementById('top_first_vol-ma-config');
    const show = (cfg.style.display === 'none' || cfg.style.display === '');
    cfg.style.display = show ? 'block' : 'none';
    renderMaConfig(); rerenderKline();
  }};
  document.getElementById('top_first_vol-ma-add').style.display = 'inline-block';
  document.getElementById('top_first_vol-bar-btn').onclick = () => {{
    const barsPanel = document.getElementById('top_first_vol-bars');
    const show = (barsPanel.style.display === 'none' || barsPanel.style.display === '');
    barsPanel.style.display = show ? 'block' : 'none';
    if (show) renderBarConfig();
  }};
  document.getElementById('top_first_vol-color-btn').onclick = () => {{
    const cfg = document.getElementById('top_first_vol-color-config');
    const show = (cfg.style.display === 'none' || cfg.style.display === '');
    cfg.style.display = show ? 'block' : 'none';
    if (show) renderColorConfig();
  }}
}}
/* 首板涨停放量连阳股 TAB 的 K 线控制：复用共享 klineState，DOM 用 top_first_vol_sun- 前缀 */
function initTopFirstVolSunKlineControls() {{
  document.getElementById('top_first_vol_sun-kline-period').onchange = e => {{
    klineState.period = e.target.value;
    if (current.topFirstVolSunCode && DATA.kline[current.topFirstVolSunCode]) {{
      document.getElementById(klineEl('kline-title')).innerHTML = klineTitleHtml(DATA.kline[current.topFirstVolSunCode], current.topFirstVolSunCode);
      rerenderKline();
    }}
  }};
  document.getElementById('top_first_vol_sun-boll').onchange = e => {{ klineState.showBOLL = e.target.checked; rerenderKline(); }};
  document.getElementById('top_first_vol_sun-vwap').onchange = e => {{ klineState.showVWAP = e.target.checked; rerenderKline(); }};
  document.getElementById('top_first_vol_sun-ma-btn').onclick = () => {{
    const cfg = document.getElementById('top_first_vol_sun-ma-config');
    const show = (cfg.style.display === 'none' || cfg.style.display === '');
    cfg.style.display = show ? 'block' : 'none';
    renderMaConfig(); rerenderKline();
  }};
  document.getElementById('top_first_vol_sun-ma-add').style.display = 'inline-block';
  document.getElementById('top_first_vol_sun-bar-btn').onclick = () => {{
    const barsPanel = document.getElementById('top_first_vol_sun-bars');
    const show = (barsPanel.style.display === 'none' || barsPanel.style.display === '');
    barsPanel.style.display = show ? 'block' : 'none';
    if (show) renderBarConfig();
  }};
  document.getElementById('top_first_vol_sun-color-btn').onclick = () => {{
    const cfg = document.getElementById('top_first_vol_sun-color-config');
    const show = (cfg.style.display === 'none' || cfg.style.display === '');
    cfg.style.display = show ? 'block' : 'none';
    if (show) renderColorConfig();
  }}
}}
window.__errboxMark && window.__errboxMark('init: kline controls');
initKlineControls();
initBtKlineControls();
initTopKlineControls();
initTopFirstKlineControls();
initTopFirstVolKlineControls();
initTopFirstVolSunKlineControls();
renderMaRow();  // 初始渲染所有面板的 MA 复选框行（默认 5/10/20/30/60/120 全勾选）
window.__errboxMark && window.__errboxMark('init: loadStrategy');
if (window.__P) window.__P.tPre = performance.now();
loadStrategy();    // klineState 就绪后再加载回测（避免 TDZ），渲染资金 K 线
if (window.__P) window.__P.tPost = performance.now();
/* 候选池 / 涨停股 / 首板 / 策略选股 不再在开页时初始化：
   它们的数据已按 TAB 拆到独立文件，首次点击进入该 TAB 时才加载并渲染（见 switchTab → ensureTab），
   这样开页只处理首屏回测，避免被隐藏面板拖慢。 */
window.__errboxMark && window.__errboxMark('init: DONE');
window.__errboxDone && window.__errboxDone();
if (window.__P) window.__P.tDone = performance.now();
/* 耗时埋点面板：仅在地址栏带 ?perf 时显示（如 file:///.../StrategyDashboardOffline.html?perf=1），
   用于定位「到底是解析/渲染慢，还是读 data/ 下的个股文件慢」。平时完全不显示、不影响使用。 */
function _perfBadge() {{
  const P = window.__P; if (!P) return;
  let el = document.getElementById('__perfBadge');
  if (!el) {{
    el = document.createElement('div'); el.id = '__perfBadge';
    el.style.cssText = 'position:fixed;right:8px;bottom:8px;z-index:99999;background:rgba(17,24,39,.94);'
      + 'color:#e5e7eb;font:12px/1.6 Consolas,monospace;padding:8px 10px;border:1px solid #374151;'
      + 'border-radius:6px;max-width:380px;white-space:pre-wrap';
    document.body.appendChild(el);
  }}
  const d = (a, b) => (a != null && b != null) ? (b - a).toFixed(1) + 'ms' : '-';
  const L = P.loads || [];
  const avg = L.length ? (L.reduce((s, x) => s + x, 0) / L.length).toFixed(1) : '-';
  el.textContent =
    '⏱ 开页: HTML+库+index ' + d(P.t0, P.tScript)
    + ' | 控件 ' + d(P.tScript, P.tPre)
    + ' | 首屏回测 ' + d(P.tPre, P.tPost)
    + ' | 收尾 ' + d(P.tPost, P.tDone)
    + ' | 总计 ' + d(P.t0, P.tDone)
    + '\\n个股文件加载: 次数 ' + L.length + ' 均值 ' + avg + 'ms'
    + (L.length ? ' 最近[' + L.slice(-6).join(', ') + ']ms' : '');
}}
if (location.search.indexOf('perf') >= 0) {{ _perfBadge(); setInterval(_perfBadge, 1000); }}

/* ------- 策略选股详情 TAB ------- */
function fmtNum(v) {{
  if (v >= 1e8) return (v / 1e8).toFixed(2) + '亿';
  if (v >= 1e4) return (v / 1e4).toFixed(2) + '万';
  return v.toFixed(2);
}}
function loadDetail() {{
  const s = document.getElementById('detail-strategy').value;
  const m = document.getElementById('detail-date').value;  // YYYYMM
  const detail = DATA.strategy_detail[s] || {{}};
  // 收集该月所有日期（降序），同一天的多只股票框在一起
  const dates = Object.keys(detail).filter(d => d.startsWith(m)).sort().reverse();
  let total = 0;
  const allRows = [];                     // 本月全部选中项（代码+日期），用于保持/回落选中
  const box = document.getElementById('detail-groups');
  box.innerHTML = '';
  dates.forEach(date => {{
    const rows = detail[date];
    if (!rows || rows.length === 0) return;
    // 日期区块标题（显示为 YYYY-MM-DD）
    const head = document.createElement('div');
    head.className = 'detail-date-head';
    head.textContent = date.slice(0, 4) + '-' + date.slice(4, 6) + '-' + date.slice(6, 8) + '（' + rows.length + ' 只）';
    box.appendChild(head);
    // 该日股票表格
    const table = document.createElement('table');
    table.className = 'detail-table';
    table.innerHTML = '<thead><tr><th>#</th><th>代码</th><th>名称</th><th>涨跌幅%</th><th>实际卖出%(' + (current.sellMode === '5m' ? '5m' : '日线') + ')</th><th>最高时%</th><th>最低时%</th><th>市值(亿)</th></tr></thead>';
    const tbody = document.createElement('tbody');
    rows.forEach((row, i) => {{
      total++;
      const cls = isLimitUp(row) ? 'limit-up' : pctClass(row.chg);  // 涨停金；涨红跌蓝
      const sellVal = current.sellMode === '5m' ? (row.sell_chg_5m ?? row.sell_chg) : row.sell_chg;
      const scls = pctClass(sellVal || 0);  // 实际卖出涨跌颜色（红涨蓝跌）
      const tr = document.createElement('tr');
      tr.dataset.code = row.code;                   // 供点击后定位与高亮
      tr.onclick = () => selectDetailStock(row.code, date);
      if (row.code === current.detailCode) tr.className = 'row-selected';  // 当前选中股高亮
      allRows.push({{ code: row.code, date: date }});
      // 最高/最低时的涨跌幅（相对前收）：(high-pre)/pre、(low-pre)/pre
      const pre = row.pre || 0;
      const highPct = pre > 0 ? (row.high - pre) / pre * 100 : 0;
      const lowPct = pre > 0 ? (row.low - pre) / pre * 100 : 0;
      const hcls = pctClass(highPct);   // 涨红跌蓝
      const lcls = pctClass(lowPct);
      tr.innerHTML = '<td>' + (i + 1) + '</td>' +
        '<td>' + row.code + '</td><td>' + row.name + '</td>' +
        '<td class="' + cls + '">' + row.chg.toFixed(2) + '</td>' +
        '<td class="' + scls + '">' + (sellVal || 0).toFixed(2) + '</td>' +
        '<td class="' + hcls + '">' + highPct.toFixed(2) + '</td>' +
        '<td class="' + lcls + '">' + lowPct.toFixed(2) + '</td>' +
        '<td>' + fmtNum(row.market) + '</td>';
      tbody.appendChild(tr);
    }});
    table.appendChild(tbody);
    box.appendChild(table);
  }});
  window._detailRows = allRows;
  prefetchPanelCodes('detail', allRows.map(function (r) {{ return r.code; }}));
  document.getElementById('detail-count').textContent = m.slice(0, 4) + '年' + m.slice(4, 6) + '月 共选股 ' + total + ' 只（' + dates.length + ' 个交易日）';
  // 默认选中：保留已在看的个股；换月后原个股不在本月则回落到本月第一只
  if (allRows.length) {{
    const keep = allRows.find(x => x.code === current.detailCode) || allRows[0];
    current.detailCode = keep.code;
    klineHighlight.detail = ymdDash(keep.date);
    document.querySelectorAll('#detail-groups tr[data-code]').forEach(tr => {{
      tr.classList.toggle('row-selected', tr.dataset.code === keep.code);
    }});
    // 面板未激活时（如刚打开页面）不渲染：隐藏容器高度为 0，切到本 TAB 时 switchTab 会重绘
    if (document.getElementById('panel-detail').classList.contains('active')) {{
      selectDetailStock(keep.code, keep.date);
    }}
  }}
}}
function selectDetailStock(code, date) {{
  klineTarget = 'detail';                 // K 线渲染到策略选股面板
  current.detailCode = code;
  if (date) klineHighlight.detail = ymdDash(date);   // 该行卖出日（T-0）在 K 线上高亮
  document.querySelectorAll('#detail-groups tr[data-code]').forEach(tr => {{
    tr.classList.toggle('row-selected', tr.dataset.code === code);
  }});
  selectStock(code);
}}
function initDetailKlineControls() {{
  const ps = document.getElementById('detail-kline-period');
  if (ps) ps.onchange = e => {{
    klineState.period = e.target.value;
    klineTarget = 'detail';
    const k = current.detailCode && DATA.kline[current.detailCode];
    document.getElementById('detail-kline-title').innerHTML = klineTitleHtml(k, current.detailCode || '');
    rerenderKline();
  }};
  const b = document.getElementById('detail-kline-boll');
  if (b) b.onchange = e => {{ klineState.showBOLL = e.target.checked; klineTarget = 'detail'; rerenderKline(); }};
  const v = document.getElementById('detail-kline-vwap');
  if (v) v.onchange = e => {{ klineState.showVWAP = e.target.checked; klineTarget = 'detail'; rerenderKline(); }};
  // 指标栏 / MA 配置 / 涨跌颜色：复用候选池的渲染函数（按 klineTarget 落到本面板）
  const barsPanel = document.getElementById('detail-kline-bars');
  const barBtn = document.getElementById('detail-kline-bar-btn');
  if (barBtn) barBtn.onclick = () => {{
    klineTarget = 'detail';
    const show = (barsPanel.style.display === 'none' || barsPanel.style.display === '');
    barsPanel.style.display = show ? 'block' : 'none';
    if (show) renderBarConfig();
  }};
  const maBtn = document.getElementById('detail-kline-ma-btn');
  const maCfg = document.getElementById('detail-kline-ma-config');
  if (maBtn) maBtn.onclick = () => {{
    klineTarget = 'detail';
    const show = (maCfg.style.display === 'none' || maCfg.style.display === '');
    maCfg.style.display = show ? 'block' : 'none';
    if (show) renderMaConfig();
  }};
  const addBtn = document.getElementById('detail-kline-ma-add');
  if (addBtn) {{
    addBtn.onclick = () => {{
      klineTarget = 'detail';
      klineState.ma.push({{ p: 5, c: '#aab0bc', visible: true }});
      renderMaConfig(); rerenderKline();
    }};
    addBtn.style.display = 'inline-block';
  }}
  const colorBtn = document.getElementById('detail-kline-color-btn');
  const colorCfg = document.getElementById('detail-kline-color-config');
  if (colorBtn) colorBtn.onclick = () => {{
    klineTarget = 'detail';
    const show = (colorCfg.style.display === 'none' || colorCfg.style.display === '');
    colorCfg.style.display = show ? 'block' : 'none';
    if (show) renderColorConfig();
  }};
  klineTarget = 'detail';
  renderBarConfig();
}}
function initDetailTab() {{
  const sel = document.getElementById('detail-strategy');
  DATA.strategies.forEach(s => {{
    const opt = document.createElement('option'); opt.value = s; opt.textContent = s; sel.appendChild(opt);
  }});
  sel.value = DATA.strategies[0];
  sel.onchange = fillDetailDates;
  document.getElementById('detail-date').onchange = loadDetail;
  fillDetailDates();
}}
function fillDetailDates() {{
  const s = document.getElementById('detail-strategy').value;
  const dates = Object.keys(DATA.strategy_detail[s] || {{}}).sort().reverse();
  // 提取月份 YYYYMM 去重降序（日期为 20260814，取前 6 位即 202608）
  const months = Array.from(new Set(dates.map(d => d.slice(0, 6))));
  const ds = document.getElementById('detail-date');
  ds.innerHTML = '';
  months.forEach(mth => {{
    const opt = document.createElement('option');
    opt.value = mth;
    opt.textContent = mth.slice(0, 4) + '年' + mth.slice(4, 6) + '月';  // 202608 -> 2026年08月
    ds.appendChild(opt);
  }});
  if (months.length) ds.value = months[0];
  loadDetail();
}}
/* initDetailTab() 不再在开页调用：策略选股面板改为首次点进该 TAB 时才初始化（见 ensureTab），
   减轻开页负担。此处只绑定 K 线控件的事件（不依赖数据）。 */
initDetailKlineControls();

strategySelect.addEventListener('change', loadStrategy);
strategySelect2.addEventListener('change', loadCandidates);
document.getElementById('bt-year-select').addEventListener('change', e => {{
  btYear = e.target.value;
  const st = backtestPayload();
  if (st) renderBtYearView(st);
}});

/* ==================== 左侧快捷命令 ==================== */
// 离线看板不输出侧栏，此时回退为游离的哑元素：
// 命令按钮的 appendChild / logCmd 都是脚本加载期执行的，取不到真实节点会抛错并中断整页脚本
const cmdList = document.getElementById('cmd-list') || document.createElement('div');
const cmdOutput = document.getElementById('cmd-output') || document.createElement('pre');
const STRATEGIES = DATA.strategies || [];

function logCmd(msg) {{
  cmdOutput.textContent = (cmdOutput.textContent ? cmdOutput.textContent + '\\n' : '') + '[' + new Date().toLocaleTimeString() + '] ' + msg;
  cmdOutput.scrollTop = cmdOutput.scrollHeight;
}}

/* 访问方式：file://（双击打开）用 marcoai:// 协议触发命令；http 服务用 fetch
   注意：IS_FILE_PROTOCOL 的 const 声明已上移到脚本开头——加载器(ensureStock)与初始化流程
   会先于本处执行，留在原地会因 const 的 TDZ 触发 "Cannot access ... before initialization"
   并中断整个初始化（页面卡在"正在加载数据"）。 */

/* 通过 marcoai:// 自定义协议触发本地 Python 命令（无需服务，双击即用） */
function runViaProtocol(cmd, payload, btn) {{
  btn.classList.add('running');
  btn.querySelector('.spinner').style.display = 'inline-block';
  logCmd('执行: ' + cmd + '（通过 marcoai:// 协议）');
  let url = 'marcoai://run?cmd=' + encodeURIComponent(cmd);
  if (payload && payload.strategy) url += '&strategy=' + encodeURIComponent(payload.strategy);
  if (payload && payload.step) url += '&step=' + encodeURIComponent(payload.step);
  try {{
    location.href = url;
    logCmd('已发起，结果将弹窗显示');
  }} catch (err) {{
    logCmd('发起失败: ' + err + '（请确认已运行 register_protocol.py 注册协议）');
  }}
  btn.classList.remove('running');
  btn.querySelector('.spinner').style.display = 'none';
}}

/* 轮询数据更新日志，实时显示各步骤进度，完成后刷新页面 */
function pollUpdateLog() {{
  const poll = async () => {{
    try {{
      const res = await fetch('/api/update_log');
      const data = await res.json();
      if (data.log) {{
        // 后端已精简：仅含失败行（!!!!!）与当前单行进度，直接整体替换显示（进度条单行刷新）
        const text = data.log;
        const pre = document.getElementById('cmd-output');
        if (pre.textContent !== text) {{
          pre.textContent = text;
          pre.scrollTop = pre.scrollHeight;
        }}
      }}
      // 更新完成条件：日志出现"全部数据更新完成"或"数据更新失败"
      const doneMark = data.log.includes('全部数据更新完成') || data.log.includes('数据更新失败');
      if (doneMark || (!data.running && data.done)) {{
        logCmd('数据更新完成，正在刷新页面...');
        setTimeout(() => location.reload(), 1000);
        return;
      }}
      if (data.running) setTimeout(poll, 1000);
    }} catch (err) {{
      setTimeout(poll, 1500);
    }}
  }};
  poll();
}}

/* 统一命令执行入口 */
async function runCommand(cmd, payload, btn) {{
  if (IS_FILE_PROTOCOL) {{
    runViaProtocol(cmd, payload, btn);
    return;
  }}
  btn.classList.add('running');
  btn.querySelector('.spinner').style.display = 'inline-block';
  try {{
    logCmd('执行: ' + cmd);
    const res = await fetch('/api/cmd', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify(Object.assign({{ cmd }}, payload || {{}})),
    }});
    const data = await res.json();
    if (data.ok) {{
      logCmd(data.output || '完成');
      // 数据更新改为异步：轮询 /api/update_log 实时显示各步骤日志，完成后刷新
      if (cmd === 'UPDATE_DATA') {{
        pollUpdateLog();
      }} else if (cmd === 'RUN_STEP') {{
        logCmd('完成，1 秒后刷新页面以载入新数据...');
        setTimeout(function () {{ location.reload(); }}, 1200);
      }}
    }} else {{
      logCmd('失败: ' + (data.error || '未知错误'));
    }}
    return data;
  }} catch (err) {{
    logCmd('请求失败: ' + err + '（离线看板无需本地服务；如需在线取数请检查网络/服务）');
    return null;
  }} finally {{
    btn.classList.remove('running');
    btn.querySelector('.spinner').style.display = 'none';
  }}
}}

/* ---- 命令1：数据更新 ---- */
function onClickUpdateData(btn) {{
  const ok = confirm('将更新通达信日线数据和 MarcoAI\\\\AIData\\\\INFO\\\\SZ100.xlsx 股票池。\\n\\n确定开始更新吗？');
  if (!ok) {{ logCmd('已取消数据更新'); return; }}
  runCommand('UPDATE_DATA', null, btn);
}}

/* ---- 命令2：更新同花顺板块 ---- */
function onClickUpdateTHS(btn) {{
  if (!STRATEGIES.length) {{ logCmd('无可用策略'); return; }}
  const sel = document.getElementById('ths-strategy');
  const strategy = sel ? sel.value : '';
  if (!strategy) {{ logCmd('请先选择策略'); return; }}
  const ok = confirm('将根据策略 ' + strategy + ' 更新同花顺板块 blockstockV3.xml，\\n最新日期股票->TPO3，前一日期->TPO31，并覆盖同花顺用户目录下的同名文件。\\n\\n确定继续吗？');
  if (!ok) {{ logCmd('已取消同花顺更新'); return; }}
  runCommand('UPDATE_THS', {{ strategy }}, btn);
}}

/* ---- 命令3：git 同步 ---- */
function onClickGitSync(btn) {{
  const ok = confirm('将执行 git add . && git commit -m "Updated" && git push，\\n把当前改动提交并推送到远程仓库。\\n\\n确定继续吗？');
  if (!ok) {{ logCmd('已取消 git 同步'); return; }}
  runCommand('GIT_SYNC', null, btn);
}}

/* 渲染侧边栏命令按钮 */
const btnData = {{
  title: '数据更新',
  desc: '通达信日线 + SZ100 股票池',
  danger: true,
  onClick: onClickUpdateData,
}};
function addCmdBtn(label, desc, danger, onClick, container) {{
  const host = container || cmdList;
  const btn = document.createElement('button');
  btn.className = 'cmd' + (danger ? ' danger' : '');
  btn.innerHTML = '<span class="spinner"></span><span class="dot"></span><span>' + label + '</span>';
  btn.onclick = () => onClick(btn);
  host.appendChild(btn);
  if (desc) {{
    const tip = document.createElement('div');
    tip.style.cssText = 'font-size:11px;color:#6b7280;margin:-4px 2px 8px;line-height:1.4;';
    tip.textContent = desc;
    host.appendChild(tip);
  }}
}}
addCmdBtn('数据更新', '更新通达信日线数据与 SZ100.xlsx 股票池', true, onClickUpdateData);

/* 同花顺更新：策略下拉 + 按钮 */
const thsRow = document.createElement('div');
thsRow.style.cssText = 'margin:6px 0 4px;';
thsRow.innerHTML = '<div style="font-size:11px;color:#9aa0a6;margin-bottom:4px;">选择策略</div>';
const sel = document.createElement('select');
sel.id = 'ths-strategy';
sel.style.cssText = 'width:100%;background:#1c2029;color:#e4e6eb;border:1px solid #2a3140;border-radius:6px;padding:7px 9px;font-size:13px;';
STRATEGIES.forEach(s => {{
  const opt = document.createElement('option'); opt.value = s; opt.textContent = s; sel.appendChild(opt);
}});
thsRow.appendChild(sel);
cmdList.appendChild(thsRow);

addCmdBtn('更新同花顺板块', '按策略把最新/前一日股票写入 blockstockV3.xml 并拷贝到实盘机', false, onClickUpdateTHS);

/* git 同步按钮 */
addCmdBtn('git 同步', 'git add . && commit && push 推送到远程仓库', false, onClickGitSync);

/* ---- 单项数据更新：每个步骤单独触发（RUN_STEP） ---- */
const UPDATE_STEPS = [
  {{ step: 'UPDATE_TRADING_DATES', label: '① 交易日历', desc: '更新交易日历' }},
  {{ step: 'UPDATE_STOCK_CODES', label: '② 股票池', desc: 'SZ100.xlsx -> 股票列表(全市场)' }},
  {{ step: 'UPDATE_1D_ORIGIN', label: '③ 日线原始', desc: '通达信前复权日线(全市场,较慢)' }},
  {{ step: 'UPDATE_5M_ORIGIN', label: '④ 5分钟原始', desc: '通达信前复权5分钟线(全市场,很慢)' }},
  {{ step: 'UPDATE_TOP', label: '⑤ 涨停列表', desc: '生成每日涨停股 TOP' }},
  {{ step: 'UPDATE_1D', label: '⑥ 加工日线', desc: 'MA/连板/is_top 加工' }},
  {{ step: 'UPDATE_TOP_FIRST', label: '⑦ 首板涨停', desc: '生成首板涨停 TOP_FIRST' }},
  {{ step: 'UPDATE_STRATEGY_TPO_3', label: '⑧ TPO_3 回测', desc: '策略回测数据' }},
  {{ step: 'UPDATE_STRATEGY_TPO_TOP', label: '⑧ TPO_TOP 回测', desc: '策略回测数据' }},
  {{ step: 'UPDATE_STRATEGY_TPO_M5', label: '⑧ TPO_M5 回测', desc: '策略回测数据(200~1300亿)' }},
  {{ step: 'UPDATE_TARGET_TPO_3', label: '⑨ TPO_3 候选', desc: '实盘候选池' }},
  {{ step: 'UPDATE_TARGET_TPO_TOP', label: '⑨ TPO_TOP 候选', desc: '实盘候选池' }},
  {{ step: 'UPDATE_TARGET_TPO_M5', label: '⑨ TPO_M5 候选', desc: '实盘候选池(200~1300亿)' }},
  {{ step: 'UPDATE_TOP_FIRST_VOL_SUN', label: '⑨ 首板放量连阳', desc: '首板涨停放量连阳股' }},
];
function onClickRunStep(step, btn) {{
  if (step.indexOf('ORIGIN') >= 0) {{
    const ok = confirm('[' + step + '] 将拉取全市场股票原始行情，可能较慢并依赖通达信联网。\\n确定开始吗？');
    if (!ok) {{ logCmd('已取消 ' + step); return; }}
  }}
  runCommand('RUN_STEP', {{ step }}, btn);
}}
const cmdSteps = document.getElementById('cmd-steps') || document.createElement('div');
UPDATE_STEPS.forEach(function (s) {{
  addCmdBtn(s.label, s.desc, false, function (btn) {{ onClickRunStep(s.step, btn); }}, cmdSteps);
}});
</script>
</div><!-- /.main -->
</body>
</html>
"""

    if external:
        html = html.replace('__EXTERNAL_DATA_SCRIPT__', '<script src="data/index.js"></script>')
        # 兜底：若 HTML 被单独移走导致 data/index.js 加载失败，页面仍能渲染（空数据）而非白屏崩溃
        html = html.replace(
            'const DATA = __DATA_DECL__;',
            'const DATA = window.__IDX || {"strategies":[],"backtest":{},"candidates":{},"top":{},'
            '"top_first":{},"strategy_detail":{},"sentiment":{},"kline":{},"fiveMin":{},'
            '"_stockBase":"data/stock/"};'
        )
    else:
        html = html.replace('__EXTERNAL_DATA_SCRIPT__', '')
        html = html.replace('const DATA = __DATA_DECL__;', 'const DATA = ' + payload + ';')
    return html


def _list_strategy_files(strategy_name: str) -> list[str]:
    """返回实盘候选池(TARGET)目录下按日期升序的全部文件名（仅数字日期），无则返回空列表"""
    base = PATH_AIDATA_TARGET(strategy_name)
    if not os.path.isdir(base):
        return []
    return sorted(d for d in os.listdir(base) if d.isdigit())


def _read_strategy_stocks(strategy_name: str, date: str) -> list[str]:
    """读取某策略某日期的实盘候选池股票代码列表（带 .SH/.SZ 后缀，如 603087.SH）"""
    path = os.path.join(PATH_AIDATA_TARGET(strategy_name), date)
    if not os.path.isfile(path):
        return []
    codes = []
    for line in _read_text(path).splitlines():
        line = line.strip()
        if not line:
            continue
        code = line.split("|")[0].strip()
        if code:
            codes.append(code)
    return codes


def _code_to_ths_security(code: str) -> str:
    """把带后缀代码转成同花顺板块 security 行，如 603087.SH -> <security market="USHA" code="603087" />"""
    c = code.strip()
    pure = c.split(".")[0]
    market = "USHA" if c.endswith(".SH") else "USZA"
    return f'    <security market="{market}" code="{pure}" />'


def CMD_UPDATE_DATA() -> str:
    """【快捷命令】更新全部数据，返回各步骤详细日志：通达信日线、SZ100 股票池、加工日线、策略、候选池等"""
    import contextlib
    import io
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            UPDATE_ALL()
        logs = buf.getvalue().strip()
        return (logs + "\n数据更新完成") if logs else "数据更新完成"
    except Exception as exc:
        return (buf.getvalue().strip() + f"\n数据更新失败: {exc}").strip()


# 单项更新步骤映射（供 UI 侧边栏「单项数据更新」单独触发，等价于 UPDATE_ALL 的单个步骤）
_UPDATE_STEPS = {
    "UPDATE_TRADING_DATES": UPDATE_TRADING_DATES,
    "UPDATE_STOCK_CODES": UPDATE_STOCK_CODES,
    "UPDATE_1D_ORIGIN": UPDATE_1D_ORIGIN,
    "UPDATE_5M_ORIGIN": UPDATE_5M_ORIGIN,
    "UPDATE_TOP": UPDATE_TOP,
    "UPDATE_1D": UPDATE_1D,
    "UPDATE_TOP_FIRST": UPDATE_TOP_FIRST,
    "UPDATE_TOP_FIRST_VOL": UPDATE_TOP_FIRST_VOL,
    "UPDATE_TOP_FIRST_VOL_SUN": UPDATE_TOP_FIRST_VOL_SUN,
    "UPDATE_STRATEGY_TPO_3": UPDATE_STRATEGY_TPO_3,
    "UPDATE_STRATEGY_TPO_TOP": UPDATE_STRATEGY_TPO_TOP,
    "UPDATE_STRATEGY_TPO_M5": UPDATE_STRATEGY_TPO_M5,
    "UPDATE_TARGET_TPO_3": UPDATE_TARGET_TPO_3,
    "UPDATE_TARGET_TPO_TOP": UPDATE_TARGET_TPO_TOP,
    "UPDATE_TARGET_TPO_M5": UPDATE_TARGET_TPO_M5,
    "UPDATE_INDEX_CODES": UPDATE_INDEX_CODES,
    "UPDATE_INDEX_1D_ORIGIN": UPDATE_INDEX_1D_ORIGIN,
    "UPDATE_INDEX_1D": UPDATE_INDEX_1D,
}


def CMD_RUN_STEP(step: str) -> str:
    """【快捷命令】单独运行某一步数据更新（与服务端 RUN_STEP / marcoai://run?cmd=RUN_STEP&step=xxx 对应）"""
    fn = _UPDATE_STEPS.get(step)
    if fn is None:
        return f"未知更新步骤: {step}（可用：{', '.join(_UPDATE_STEPS)}）"
    import contextlib
    import io
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            summary = fn()
        logs = buf.getvalue().strip()
        return (f"[{step}] 完成: {summary}\n{logs}".strip() if logs
                else f"[{step}] 完成: {summary}")
    except Exception as exc:
        return f"[{step}] 失败: {type(exc).__name__}: {exc}"


def _sort_by_cap_desc(codes: list[str], trading_date: str) -> list[str]:
    """按流通市值(流通股本 × 收盘价)倒序排序代码列表；无法取值的排末尾。"""
    scored: list[tuple[float, str]] = []
    for c in codes:
        cap = 0.0
        try:
            info = GET_STOCK_INFO(c)
            rec = GET_SZ200_1D_PREVIOUS(c, trading_date, 0)
            if info is not None and len(info) > 1 and info[1] > 0 and rec is not None and rec.close > 0:
                cap = float(info[1]) * rec.close
        except Exception:
            cap = 0.0
        scored.append((cap, c))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored]


def _load_his_codes() -> list[str]:
    """HIS 板块选股：UI「首板涨停放量股」TAB 最近 5 个交易日（以今日为例 08/09/12/13/14）的全部个股，
    剔除「首板涨停日之后其它日也出现涨停」的个股（如 10/12 首板、10/13 再涨停则剔除）。

    口径：
      - 取 TOP_FIRST_VOL 最近 5 个交易日日期，合并其全部个股为候选池（即该 TAB 最近 5 日所有股）；
      - 每只个股以其窗口内最早「首板日」（出现在 TOP_FIRST_VOL 的日期）为参照；
      - 若个股在「参照首板日之后」的任一日（窗口内）出现在权威涨停列表 TOP 中（含连板 / 再涨停 /
        反复涨停），则剔除；
      - 仅保留首板日之后窗口内再无涨停的个股。
    返回股票代码列表。
    """
    tfv = _load_top_first_vol()
    dates = sorted(tfv.keys(), reverse=True)   # 日期倒序
    if len(dates) < 5:
        return []
    window = dates[:5]        # 最近 5 个交易日（倒序）[T0..T4]
    # 候选池：最近 5 日首板涨停放量股并集（code -> 最早首板日）
    first_days: dict[str, str] = {}
    for d in window:
        for row in tfv.get(d, []):
            if row[0] not in first_days or d < first_days[row[0]]:
                first_days[row[0]] = d
    if not first_days:
        return []
    # 预构建窗口内每日涨停 code 集合（TOP 为权威涨停列表，含连板）
    top = _load_top()
    top_sets = {d: {r[0] for r in top.get(d, [])} for d in window}
    out: list[str] = []
    for code, ref_day in first_days.items():
        # 参照首板日之后的窗口日期
        later = [d for d in window if d > ref_day]
        if any(code in top_sets[d] for d in later):
            continue  # 首板日之后仍有涨停 → 剔除
        out.append(code)
    return out


def CMD_UPDATE_THS(strategy_name: str) -> str:
    """【快捷命令】生成同花顺板块 XML 并拷贝到实盘机目录。

    板块口径（单一数据源均为一条龙落盘文件，与 UI 各 TAB 一致）：
    - ===TPO3===  : 最近 1 日首板涨停放量股（TOP_FIRST_VOL 最新交易日）
    - ===TPO31=== : 前 1 日首板涨停放量股（TOP_FIRST_VOL 次新交易日，为空则板块留空）
    - ===TOP===   : 当天涨停股（TOP_FIRST 最新交易日，与 UI「首板涨停股」TAB 一致）
    - ===HIS===   : 最近 5 日首板涨停放量股（TOP_FIRST_VOL），剔除首板日后其它日又涨停的个股
    - 拷贝模板到 THS_TARGET_DIR 覆盖同名文件。

    注：strategy_name 仅保留以兼容既有调用入口，TPO3/TPO31 已不再依赖策略候选池。
    """
    if not strategy_name:
        return "未选择策略"
    if not os.path.isfile(THS_TEMPLATE_FILE):
        return f"同花顺模板不存在: {THS_TEMPLATE_FILE}"

    # TPO3 / TPO31：最近 1 日 / 前 1 日首板涨停放量股（UI「首板涨停放量股」TAB，TOP_FIRST_VOL）
    tfv = _load_top_first_vol()
    tfv_dates = sorted(tfv.keys(), reverse=True)
    latest_tfv = tfv_dates[0] if tfv_dates else None
    prev_tfv = tfv_dates[1] if len(tfv_dates) >= 2 else None

    def _tfv_codes(date):
        # 按流通市值(行内第 3 列)倒序，与 TOP 排序口径一致
        return [r[0] for r in sorted(tfv.get(date, []),
                                     key=lambda r: float(r[2]), reverse=True)] if date else []

    tpo3 = _tfv_codes(latest_tfv)
    tpo31 = _tfv_codes(prev_tfv)

    # 首板涨停股：直接读一条龙更新落盘的 TOP_FIRST 文件（单一数据源，与 UI「首板涨停股」TAB 一致）
    top_first_dir = PATH_AIDATA_TOP_FIRST()
    top_first_dates = sorted(d for d in os.listdir(top_first_dir) if d.isdigit()) if os.path.isdir(top_first_dir) else []
    top_date = top_first_dates[-1] if top_first_dates else None
    tops = [c.strip() for c in _read_text(os.path.join(top_first_dir, top_date)).splitlines() if c.strip()] if top_date else []
    # ===TOP=== 按流通市值倒序排序（大市值在前）
    tops = _sort_by_cap_desc(tops, top_date) if top_date else []

    tpo3_block = "\n".join(_code_to_ths_security(c) for c in tpo3)
    tpo31_block = "\n".join(_code_to_ths_security(c) for c in tpo31)
    top_block = "\n".join(_code_to_ths_security(c) for c in tops)

    # HIS 板块：最近 5 日首板涨停放量股（TOP_FIRST_VOL，UI「首板涨停放量股」TAB），
    # 剔除首板日之后其它日又涨停的个股 -> ===HIS===
    his_codes = _load_his_codes()
    history_block = "\n".join(_code_to_ths_security(c) for c in his_codes)

    # 读取模板并替换占位符：有股票则填入 securities（首尾不加换行），为空则整行清理（不留占位符/空行，兼容 CRLF/LF）
    raw = _read_text(THS_TEMPLATE_FILE)
    for ph, block in ((PLACEHOLDER_TPO3, tpo3_block),
                      (PLACEHOLDER_TPO31, tpo31_block),
                      (PLACEHOLDER_TOP, top_block),
                      (PLACEHOLDER_HIS, history_block)):
        if block:
            raw = raw.replace(ph, block)
        else:
            raw = re.sub(r"\r?\n" + re.escape(ph), "", raw).replace(ph, "")

    # 拷贝模板到目标目录覆盖同名文件
    # newline="" 保持模板原始换行（CRLF），避免文本模式把 \n 再转成 \r\n 导致 \r\r\n
    if not os.path.isdir(THS_TARGET_DIR):
        return f"同花顺目标目录不存在: {THS_TARGET_DIR}"
    target_file = os.path.join(THS_TARGET_DIR, THS_BLOCK_NAME)
    with open(target_file, "w", encoding="utf-8", newline="") as f:
        f.write(raw)

    detail = (
        f"首板放量(TPO3) {latest_tfv or '无'} 共 {len(tpo3)} 只, "
        f"前日(TPO31) {prev_tfv or '无'} 共 {len(tpo31)} 只, "
        f"涨停(TOP) {top_date or '无'} 共 {len(tops)} 只, "
        f"首板放量(HIS) 近5日 共 {len(his_codes)} 只"
    )
    print(f"CMD_UPDATE_THS: 已写入 {target_file}\n{detail}")
    return f"同花顺板块已更新:\n{detail}\n已覆盖: {target_file}"


def _inject_gen_time(html: str) -> str:
    """在看板标题下插入可见的生成时间戳，便于一眼确认是否看到最新文件（避免 file:// 缓存误判）。"""
    from datetime import datetime
    t = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    badge = ('<div style="font-size:12px;color:#9aa0a6;margin:2px 0 12px">'
             '看板生成时间：' + t + '（数据更新后请重新生成并刷新本页）</div>')
    marker = '<h1>📊 策略回测 & 实盘目标股看板</h1>'
    return html.replace(marker, marker + '\n' + badge, 1)


def GENERATE_STRATEGY_UI(strategy_name: str | None = None, open_browser: bool = True) -> str:
    """生成策略回测 + 实盘目标股综合看板 HTML 并返回文件路径。

    参数:
        strategy_name: 指定策略名；None 时包含所有策略
        open_browser:  是否自动打开浏览器
    """
    if strategy_name:
        strategies = [strategy_name]
    else:
        strategies = _list_strategies()
        if not strategies:
            print("STRATEGY_UI: Strategy 目录下无策略")
            return ""

    # 回测数据：同时预计算 day（日线卖出）与 5m（5 分钟日内卖出）两套
    backtest = {}
    for name in strategies:
        backtest[name] = {
            "day": _build_strategy_payload(name, "day"),
            "5m": _build_strategy_payload(name, "5m"),
        }

    # 候选池 + K 线
    candidates = {}
    all_codes = set()
    code_names: dict[str, str] = {}
    for name in strategies:
        candidates[name] = _load_candidates(name)
        for rows in candidates[name].values():
            for r in rows:
                all_codes.add(r[0])
                if len(r) >= 2 and r[0] not in code_names:
                    code_names[r[0]] = r[1]
    kline = _load_kline(all_codes, code_names)

    # 涨停列表（按市值倒序）
    top = _load_top()
    top_codes = set()
    top_names: dict[str, str] = {}
    for rows in top.values():
        for r in rows:
            top_codes.add(r[0])
            if r[0] not in top_names:
                top_names[r[0]] = r[1]
    # 涨停股 K 线并入：不再截断。此前 max_days=120 的截断版经 update() 覆盖掉候选池的
    # 完整历史，导致三个面板的 K 线都只剩最近 120 根（约 4 月起）
    top_kline = _load_kline(top_codes, top_names)
    for code, val in top_kline.items():
        kline.setdefault(code, val)     # 已有完整历史的候选股不覆盖

    # 首板涨停股 K 线并入（与涨停股同逻辑）
    top_first = _load_top_first()
    top_first_codes: set[str] = set()
    top_first_names: dict[str, str] = {}
    for rows in top_first.values():
        for r in rows:
            top_first_codes.add(r[0])
            if r[0] not in top_first_names:
                top_first_names[r[0]] = r[1]
    top_first_kline = _load_kline(top_first_codes, top_first_names)
    for code, val in top_first_kline.items():
        kline.setdefault(code, val)

    # 首板涨停放量股 K 线并入（同逻辑；本 TAB 不限市值，个股可能不在涨停/首板列表中）
    top_first_vol = _load_top_first_vol()
    top_first_vol_codes: set[str] = set()
    top_first_vol_names: dict[str, str] = {}
    for rows in top_first_vol.values():
        for r in rows:
            top_first_vol_codes.add(r[0])
            if r[0] not in top_first_vol_names:
                top_first_vol_names[r[0]] = r[1]
    top_first_vol_kline = _load_kline(top_first_vol_codes, top_first_vol_names)
    for code, val in top_first_vol_kline.items():
        kline.setdefault(code, val)

    # 首板涨停放量连阳股 K 线并入（同逻辑；在首板涨停放量股基础上再筛 T-1 阳线/创新高）
    top_first_vol_sun = _load_top_first_vol_sun()
    top_first_vol_sun_codes: set[str] = set()
    top_first_vol_sun_names: dict[str, str] = {}
    for rows in top_first_vol_sun.values():
        for r in rows:
            top_first_vol_sun_codes.add(r[0])
            if r[0] not in top_first_vol_sun_names:
                top_first_vol_sun_names[r[0]] = r[1]
    top_first_vol_sun_kline = _load_kline(top_first_vol_sun_codes, top_first_vol_sun_names)
    for code, val in top_first_vol_sun_kline.items():
        kline.setdefault(code, val)

    # 策略选股详情（第三个 TAB）
    strategy_detail = _load_strategy_detail(strategies)

    # 策略选股详情个股的 K 线并入：这些个股不一定在候选池/涨停列表中，
    # 但点击详情行需要展示其 K 线，故单独加载并合并（已存在的完整历史不覆盖）
    detail_codes: set[str] = set()
    detail_names: dict[str, str] = {}
    for _d in strategy_detail.values():
        for _rows in _d.values():
            for _it in _rows:
                _code = _it.get("code")
                if _code:
                    _code = str(_code)
                    detail_codes.add(_code)
                    _nm = _it.get("name")
                    if _code not in detail_names and _nm:
                        detail_names[_code] = str(_nm)
    detail_kline = _load_kline(detail_codes, detail_names)
    for _code, _val in detail_kline.items():
        kline.setdefault(_code, _val)

    # 情绪曲线与具体策略无关，放顶层只算一次（避免每个策略重复计算 4 条线）
    five_min = _build_five_min(strategies)
    # 涨停股 / 首板的 5 分钟窗口：按各自出现的日期精确生成（与策略选股同口径），
    # 避免点击历史日期时回退到「最新窗口」导致显示范围错误
    _cd = _collect_code_dates(top)
    for _c, _ds in _collect_code_dates(top_first).items():
        _cd.setdefault(_c, set()).update(_ds)
    for _c, _ds in _collect_code_dates(top_first_vol).items():
        _cd.setdefault(_c, set()).update(_ds)
    for _c, _ds in _collect_code_dates(top_first_vol_sun).items():
        _cd.setdefault(_c, set()).update(_ds)
    _extend_five_min_top(_cd, five_min)
    data = {
        "strategies": strategies,
        "backtest": backtest,
        "candidates": candidates,
        "top": top,
        "top_first": top_first,
        "top_first_vol": top_first_vol,
        "top_first_vol_sun": top_first_vol_sun,
        "kline": kline,
        "strategy_detail": strategy_detail,
        "fiveMin": five_min,
        "sentiment": BUILD_SENTIMENT_KLINE(),
    }

    # 指数 1D K 线（数据源 INDEX_ORIGIN，起始日期与 1D 一致；无需 5M）
    index_codes = set(INDEX_CODES())
    index_names = {c: (GET_INDEX_NAME(c) or c) for c in index_codes}
    index_kline = _load_kline(index_codes, index_names, origin_dir=PATH_AIDATA_INDEX_ORIGIN())
    data["index_kline"] = index_kline

    html = _render_html(data)
    html = _inject_gen_time(html)
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "UI", "StrategyDashboard.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"STRATEGY_UI: 综合看板已生成 {out_path}")

    if open_browser:
        webbrowser.open("file:///" + out_path.replace("\\", "/") + "?v=" + str(int(os.path.getmtime(out_path))))
    return out_path


def GENERATE_STRATEGY_UI_OFFLINE(strategy_name: str | None = None, open_browser: bool = True) -> str:
    """生成完全离线（单文件、内联图表库、零外网依赖）的策略看板 HTML。

    与 GENERATE_STRATEGY_UI 的唯一区别：把 chart.js / lightweight-charts 两个库直接
    内联进 HTML，因此把该 HTML 拷到任意无外网环境、用 file:// 直接打开都能完整显示，
    不再依赖 CDN。命令面板在 file:// 下本就走自定义协议（IS_FILE_PROTOCOL），无需后端。

    返回生成的文件路径；无策略时返回空串。
    """
    # 记录本次构建所基于的源数据时间戳（构建前取样），供「看板是否过期」判断使用
    src_mtime = _source_data_mtime()

    if strategy_name:
        strategies = [strategy_name]
    else:
        strategies = _list_strategies()
        if not strategies:
            print("STRATEGY_UI: Strategy 目录下无策略")
            return ""

    # 回测数据：同时预计算 day（日线卖出）与 5m（5 分钟日内卖出）两套
    backtest = {}
    for name in strategies:
        backtest[name] = {
            "day": _build_strategy_payload(name, "day"),
            "5m": _build_strategy_payload(name, "5m"),
        }

    # 候选池 + K 线
    candidates = {}
    all_codes = set()
    code_names: dict[str, str] = {}
    for name in strategies:
        candidates[name] = _load_candidates(name)
        for rows in candidates[name].values():
            for r in rows:
                all_codes.add(r[0])
                if len(r) >= 2 and r[0] not in code_names:
                    code_names[r[0]] = r[1]
    kline = _load_kline(all_codes, code_names)

    # 涨停列表（按市值倒序）
    top = _load_top()
    top_codes = set()
    top_names: dict[str, str] = {}
    for rows in top.values():
        for r in rows:
            top_codes.add(r[0])
            if r[0] not in top_names:
                top_names[r[0]] = r[1]
    # 涨停股 K 线并入：不再截断。此前 max_days=120 的截断版经 update() 覆盖掉候选池的
    # 完整历史，导致三个面板的 K 线都只剩最近 120 根（约 4 月起）
    top_kline = _load_kline(top_codes, top_names)
    for code, val in top_kline.items():
        kline.setdefault(code, val)     # 已有完整历史的候选股不覆盖

    # 首板涨停股 K 线并入（与涨停股同逻辑）
    top_first = _load_top_first()
    top_first_codes: set[str] = set()
    top_first_names: dict[str, str] = {}
    for rows in top_first.values():
        for r in rows:
            top_first_codes.add(r[0])
            if r[0] not in top_first_names:
                top_first_names[r[0]] = r[1]
    top_first_kline = _load_kline(top_first_codes, top_first_names)
    for code, val in top_first_kline.items():
        kline.setdefault(code, val)

    # 首板涨停放量股 K 线并入（同逻辑；本 TAB 不限市值，个股可能不在涨停/首板列表中）
    top_first_vol = _load_top_first_vol()
    top_first_vol_codes: set[str] = set()
    top_first_vol_names: dict[str, str] = {}
    for rows in top_first_vol.values():
        for r in rows:
            top_first_vol_codes.add(r[0])
            if r[0] not in top_first_vol_names:
                top_first_vol_names[r[0]] = r[1]
    top_first_vol_kline = _load_kline(top_first_vol_codes, top_first_vol_names)
    for code, val in top_first_vol_kline.items():
        kline.setdefault(code, val)

    # 首板涨停放量连阳股 K 线并入（同逻辑；在首板涨停放量股基础上再筛 T-1 阳线/创新高）
    top_first_vol_sun = _load_top_first_vol_sun()
    top_first_vol_sun_codes: set[str] = set()
    top_first_vol_sun_names: dict[str, str] = {}
    for rows in top_first_vol_sun.values():
        for r in rows:
            top_first_vol_sun_codes.add(r[0])
            if r[0] not in top_first_vol_sun_names:
                top_first_vol_sun_names[r[0]] = r[1]
    top_first_vol_sun_kline = _load_kline(top_first_vol_sun_codes, top_first_vol_sun_names)
    for code, val in top_first_vol_sun_kline.items():
        kline.setdefault(code, val)

    # 策略选股详情
    strategy_detail = _load_strategy_detail(strategies)

    # 策略选股详情个股的 K 线并入：这些个股不一定在候选池/涨停列表中，
    # 但点击详情行需要展示其 K 线，故单独加载并合并（已存在的完整历史不覆盖）
    detail_codes: set[str] = set()
    detail_names: dict[str, str] = {}
    for _d in strategy_detail.values():
        for _rows in _d.values():
            for _it in _rows:
                _code = _it.get("code")
                if _code:
                    _code = str(_code)
                    detail_codes.add(_code)
                    _nm = _it.get("name")
                    if _code not in detail_names and _nm:
                        detail_names[_code] = str(_nm)
    detail_kline = _load_kline(detail_codes, detail_names)
    for _code, _val in detail_kline.items():
        kline.setdefault(_code, _val)

    # 情绪曲线与具体策略无关，放顶层只算一次（避免每个策略重复计算 4 条线）
    five_min = _build_five_min(strategies)
    # 涨停股 / 首板的 5 分钟窗口：按各自出现的日期精确生成（与策略选股同口径），
    # 避免点击历史日期时回退到「最新窗口」导致显示范围错误
    _cd = _collect_code_dates(top)
    for _c, _ds in _collect_code_dates(top_first).items():
        _cd.setdefault(_c, set()).update(_ds)
    for _c, _ds in _collect_code_dates(top_first_vol).items():
        _cd.setdefault(_c, set()).update(_ds)
    for _c, _ds in _collect_code_dates(top_first_vol_sun).items():
        _cd.setdefault(_c, set()).update(_ds)
    _extend_five_min_top(_cd, five_min)
    data = {
        "strategies": strategies,
        "backtest": backtest,
        "candidates": candidates,
        "top": top,
        "top_first": top_first,
        "top_first_vol": top_first_vol,
        "top_first_vol_sun": top_first_vol_sun,
        "kline": kline,
        "strategy_detail": strategy_detail,
        "fiveMin": five_min,
        "sentiment": BUILD_SENTIMENT_KLINE(),
    }

    # 指数 1D K 线（数据源 INDEX_ORIGIN，起始日期与 1D 一致；无需 5M）
    index_codes = set(INDEX_CODES())
    index_names = {c: (GET_INDEX_NAME(c) or c) for c in index_codes}
    index_kline = _load_kline(index_codes, index_names, origin_dir=PATH_AIDATA_INDEX_ORIGIN())
    data["index_kline"] = index_kline

    # 不输出左侧命令侧边栏：离线单文件拷到别处后命令按钮（依赖本地服务/自定义协议）无意义
    # 离线零内嵌：先把数据写到 data/ 伴随文件（HTML 不内嵌任何数据），再生成仅引用数据的 HTML
    here = os.path.dirname(os.path.abspath(__file__))
    _write_offline_data(here, data)
    html = _render_html({}, show_sidebar=False, external=True)
    html = _inject_gen_time(html)

    # 把 CDN <script src> 替换为本地内联库，使 HTML 彻底离线、可独立分发
    vendor = os.path.join(here, "UI", "vendor")
    vendor = os.path.join(here, "UI", "vendor")
    lib_map = {
        "https://cdn.jsdelivr.net/npm/chart.js":
            "chart.umd.js",
        "https://unpkg.com/lightweight-charts@5.0.8/dist/lightweight-charts.standalone.production.js":
            "lightweight-charts.standalone.production.js",
    }
    for cdn, fname in lib_map.items():
        path = os.path.join(vendor, fname)
        if not os.path.isfile(path):
            print(f"STRATEGY_UI: 离线库缺失，跳过内联（仍将依赖 CDN）：{path}")
            continue
        with open(path, "r", encoding="utf-8") as f:
            lib = f.read()
        # 防止库内含 </script> 字面量截断 HTML：转义其中的斜杠
        lib = lib.replace("</script>", "<\\/script>")
        inline = "<script>/* inlined vendor lib: " + fname + " */\n" + lib + "\n</script>"
        html = html.replace('<script src="' + cdn + '"></script>', inline)

    out_path = os.path.join(here, "UI", "StrategyDashboardOffline.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    # 落盘元信息：本次构建对应的源数据时间戳，供下次判断是否需要重建
    try:
        from datetime import datetime as _dt2
        with open(out_path + ".meta.json", "w", encoding="utf-8") as f:
            json.dump({"src_mtime": src_mtime,
                       "generated": _dt2.now().strftime("%Y-%m-%d %H:%M:%S")}, f)
    except Exception as exc:
        print(f"STRATEGY_UI: 元信息写入失败（不影响看板）：{exc}")
    print(f"STRATEGY_UI: 离线看板已生成 {out_path}")

    if open_browser:
        webbrowser.open("file:///" + out_path.replace("\\", "/") + "?v=" + str(int(os.path.getmtime(out_path))))
    return out_path


if __name__ == "__main__":
    GENERATE_STRATEGY_UI()
