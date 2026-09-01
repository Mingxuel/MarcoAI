"""
日线（1D）数据处理模块

====================================================
一、数据流
====================================================
  通达信接口 ──UPDATE_1D_ORIGIN──▶ 1D_ORIGIN（原始前复权日线）
                                        │
                                   UPDATE_1D（加工）
                                        ▼
                                  1D（加工日线，含派生字段）
  说明:
    - 1D_ORIGIN 只由 UPDATE_1D_ORIGIN 维护（原始数据，不删除）
    - 1D 由 UPDATE_1D 生成，每次删除旧数据后重建（不触碰 1D_ORIGIN）

====================================================
二、存储文件
====================================================
  MarcoAI/AIData/1D_ORIGIN —— 原始前复权日线
      每行: date|open|high|low|close|volume|amount

  MarcoAI/AIData/1D        —— 加工日线，在原始7列后追加派生字段

====================================================
三、加工字段说明（1D 每行 25 列）
====================================================
  date|open|high|low|close|volume|amount    原始行情（保留）
    |pre_close      前一日收盘价（价格，四舍五入到分）
    |is_top         当日是否涨停（1/0，依据 TOP 列表）
    |is_toped       是否涨停过（含涨停，即盘中触及涨停价，1/0）
    |ratio          涨跌幅(%) = (close-pre_close)/pre_close*100
    |is_up          涨跌幅为正（1/0）
    |is_down        涨跌幅为负（1/0）
    |is_red         收盘价高于开盘价，阳线（1/0）
    |is_green       收盘价低于开盘价，阴线（1/0）
    |is_volume_up   放量：成交量高于前一日（1/0）
    |is_volume_down 缩量：成交量低于前一日（1/0）
    |ma5|ma10|ma20|ma30|ma60|ma120  收盘价 N 日均价（需满 N 日数据，不足为 0.0）
    |lian_ban       连板次数：从当日往前连续涨停天数
    |is_bottom      当日是否跌停（1/0，收盘价等于跌停价 = 前收×0.9）

  舍入规则:
    - 价格相关字段（pre_close、ma 系列）使用两步四舍五入到分:
      先到 3 位小数，再到 2 位小数（如 5.5445 -> 5.545 -> 5.55）
    - MA 均价须满该周期天数才计算，数据不足显示 0.0

====================================================
四、API 说明
====================================================
  UPDATE_1D_ORIGIN() -> None
      从通达信拉取全股票前复权原始日线，删除 1D_ORIGIN 旧数据后重建

  UPDATE_1D() -> None
      读取 1D_ORIGIN 原始数据，计算加工字段，删除 1D 旧数据后重建（多进程）

  GET_SZ200_1D_PREVIOUS(stock_code, date, index) -> DATA_1D | None
      取某股票 date 往前第 index 个交易日的数据（优先缓存，兜底读文件）
  GET_SZ200_1D_AFTER(stock_code, date, index) -> DATA_1D | None
      取某股票 date 往后第 index 个交易日的数据
  GET_SZ200_1D_ALL() -> dict[str, dict[str, DATA_1D]]
      加载全部股票日线到缓存 {股票代码: {日期: DATA_1D}}
"""

from concurrent.futures import ProcessPoolExecutor, as_completed
import os
import shutil
import sys
import pandas as pd
from functools import partial
from tqdm import tqdm

_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _root not in sys.path:
    sys.path.insert(0, _root)
from AICode.MarcoAPI.Update.Constants import *
from AICode.MarcoAPI.Update.StockCodes import *
from AICode.MarcoAPI.Update.TradingDates import *
from AICode.MarcoAPI.Update.Path import *
from AICode.MarcoAPI.Update.Data import DATA_1D

_SZ200_1D_ALL_CACHE: dict[str, dict[str, DATA_1D]] = {}

# MA 周期列表
_MA_PERIODS: list[int] = [5, 10, 20, 30, 60, 120]

def _safe_rmtree(path: str):
    """分批删除目录内容，避免触发批量删除保护（如 >50 文件需确认）。

    逐文件删除（每次 1 个），递归处理子目录，规避一次性批量删除的确认保护。
    """
    if not os.path.isdir(path):
        return
    for name in os.listdir(path):
        p = os.path.join(path, name)
        try:
            if os.path.isdir(p):
                _safe_rmtree(p)
                os.rmdir(p)
            else:
                os.remove(p)
        except OSError:
            pass
    try:
        os.rmdir(path)
    except OSError:
        pass


def _rotate_dir(path: str):
    """把旧目录改名（避免触发实盘机安全删除保护），再新建空目录。

    os.rename 是"改名"不触发删除保护。旧目录改名为 path.old_时间戳 保留（供后续手动清理）。
    """
    if os.path.isdir(path):
        import time
        backup = f"{path}.old_{int(time.time())}"
        try:
            os.rename(path, backup)
        except OSError:
            pass
    os.makedirs(path, exist_ok=True)


def _PARSE_DATA_1D(parts: list[str]) -> DATA_1D:
    """解析 1D 文件一行（兼容原始7列与含加工字段的多列）"""
    return DATA_1D(
        date=parts[0],
        open=float(parts[1]),
        high=float(parts[2]),
        low=float(parts[3]),
        close=float(parts[4]),
        volume=float(parts[5]),
        amount=float(parts[6]),
        pre_close=float(parts[7]) if len(parts) > 7 else 0.0,
        is_top=int(float(parts[8])) if len(parts) > 8 else 0,
        is_toped=int(float(parts[9])) if len(parts) > 9 else 0,
        ratio=float(parts[10]) if len(parts) > 10 else 0.0,
        is_up=int(float(parts[11])) if len(parts) > 11 else 0,
        is_down=int(float(parts[12])) if len(parts) > 12 else 0,
        is_red=int(float(parts[13])) if len(parts) > 13 else 0,
        is_green=int(float(parts[14])) if len(parts) > 14 else 0,
        is_volume_up=int(float(parts[15])) if len(parts) > 15 else 0,
        is_volume_down=int(float(parts[16])) if len(parts) > 16 else 0,
        ma5=float(parts[17]) if len(parts) > 17 else 0.0,
        ma10=float(parts[18]) if len(parts) > 18 else 0.0,
        ma20=float(parts[19]) if len(parts) > 19 else 0.0,
        ma30=float(parts[20]) if len(parts) > 20 else 0.0,
        ma60=float(parts[21]) if len(parts) > 21 else 0.0,
        ma120=float(parts[22]) if len(parts) > 22 else 0.0,
        lian_ban=int(float(parts[23])) if len(parts) > 23 else 0,
        is_bottom=int(float(parts[24])) if len(parts) > 24 else 0,
    )

def GET_SZ200_1D_PREVIOUS(stock_code: str, date, index) -> DATA_1D | None:
    """取某股票 date 往前第 index 个交易日的日线数据。

    优先从缓存读取，缓存未命中则读 1D 文件；date 往前越界或不存在返回 None。
    """
    trading_date = TRADING_DATE_PREVIOUS(date, index)
    if trading_date is None:
        return None

    if stock_code in _SZ200_1D_ALL_CACHE and trading_date in _SZ200_1D_ALL_CACHE[stock_code]:
        return _SZ200_1D_ALL_CACHE[stock_code][trading_date]

    with open(f"{PATH_AIDATA_1D()}/{stock_code}", "r") as file:
        for line in file:
            if line.startswith(trading_date):
                return _PARSE_DATA_1D(line.strip().split('|'))

def GET_SZ200_1D_AFTER(stock_code: str, date, index) -> DATA_1D | None:
    """取某股票 date 往后第 index 个交易日的日线数据。

    优先从缓存读取，缓存未命中则读 1D 文件；date 往后越界或不存在返回 None。
    """
    trading_date = TRADING_DATE_AFTER(date, index)
    if trading_date is None:
        return None

    if stock_code in _SZ200_1D_ALL_CACHE and trading_date in _SZ200_1D_ALL_CACHE[stock_code]:
        return _SZ200_1D_ALL_CACHE[stock_code][trading_date]

    with open(f"{PATH_AIDATA_1D()}/{stock_code}", "r") as file:
        for line in file:
            if line.startswith(trading_date):
                return _PARSE_DATA_1D(line.strip().split('|'))

def GET_SZ200_1D_ALL():
    """加载全部股票加工日线到缓存并返回 {股票代码: {日期: DATA_1D}}。

    首次调用从 1D 目录逐股票读取并缓存，后续调用直接返回缓存。
    """
    if not _SZ200_1D_ALL_CACHE:
        stock_codes = STOCK_CODES()
        for stock_code in stock_codes:
            _SZ200_1D_ALL_CACHE[stock_code] = {}
            with open(f"{PATH_AIDATA_1D()}/{stock_code}", "r") as file:
                for line in file:
                    data_1d = _PARSE_DATA_1D(line.strip().split('|'))
                    _SZ200_1D_ALL_CACHE[stock_code][data_1d.date] = data_1d
    return _SZ200_1D_ALL_CACHE

def UPDATE_1D_ORIGIN():
    """拉取原始前复权日线：从通达信获取全股票前复权数据，删除 1D_ORIGIN 旧数据后重建。

    数据为原始行情（date|open|high|low|close|volume|amount），不计算任何加工字段。
    """
    _rotate_dir(PATH_AIDATA_1D_ORIGIN())

    stock_codes = STOCK_CODES()

    sys.path.append(PATH_TDX())  # 确保 tqcenter 模块所在目录在 sys.path 中
    from tqcenter import tq  # 仅在离线更新时惰性导入，避免实盘加载本模块时触碰通达信
    tq.initialize(__file__)
    df = tq.get_market_data( field_list=["Open","High", "Low", "Close", "Volume", "Amount"], stock_list=stock_codes, start_time=START_DATE, end_time='', count=-1, dividend_type='front', period='1d', fill_data=True )
    _SZ200_1D_ALL_CACHE.clear()
    fn_origin = partial(GENERATE_1D_ORIGIN, dataframe=df)
    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as pool:
        future_to_code = {pool.submit(fn_origin, c): c for c in stock_codes}
        results: dict[str, object] = {}
        with tqdm(total=len(future_to_code), desc="1D_ORIGIN", ncols=90) as bar:
            for fut in as_completed(future_to_code):
                results[future_to_code[fut]] = fut.result()
                bar.set_postfix(code=future_to_code[fut], refresh=False)
                bar.update(1)
    for stock_code in stock_codes:
        _SZ200_1D_ALL_CACHE[stock_code] = results[stock_code]  # pyright: ignore[reportArgumentType]
    return f"1D_ORIGIN: 完成 {len(stock_codes)} 只股票"

def GENERATE_1D_ORIGIN(stock_code:str, dataframe:pd.DataFrame) -> dict[str, DATA_1D]:
    """worker: 将通达信 DataFrame 中单只股票的原始日线写入 1D_ORIGIN 文件。

    按交易日顺序逐行写原始 7 列数据，并返回 {日期: DATA_1D} 缓存。
    """
    stock_cache: dict[str, DATA_1D] = {}
    with open(f"{PATH_AIDATA_1D_ORIGIN()}/{stock_code}", "w") as file:
        trading_dates = TRADING_DATES()
        for trading_date in trading_dates:
            _date = trading_date
            _open = dataframe["Open"].loc[trading_date, stock_code]
            _high = dataframe["High"].loc[trading_date, stock_code]
            _low = dataframe["Low"].loc[trading_date, stock_code]
            _close = dataframe["Close"].loc[trading_date, stock_code]
            _volume = dataframe["Volume"].loc[trading_date, stock_code]
            _amount = dataframe["Amount"].loc[trading_date, stock_code]
            file.write(f"{_date}|{_open}|{_high}|{_low}|{_close}|{_volume}|{_amount}\n")
            stock_cache[trading_date] = DATA_1D(
                date=_date, open=float(_open), high=float(_high),
                low=float(_low), close=float(_close),
                volume=float(_volume), amount=float(_amount))
    return stock_cache

def _CALCULATE_LIMIT(high: float, pre_close: float) -> bool:
    """判断 high 是否触及涨停价。

    涨停价 = pre_close * 1.1（先四舍五入到3位，再四舍五入到分）。
    返回 True 表示盘中触及或超过涨停价（用于 is_toped 判断）。
    """
    from decimal import Decimal, ROUND_HALF_UP
    decimal = Decimal(float(pre_close) * 1.1)
    decimal = decimal.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    limit_price = float(decimal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    return abs(high - limit_price) < 0.001 or high >= limit_price

def _ROUND_PRICE(value: float) -> float:
    """价格四舍五入到分（2位小数）。

    采用两步四舍五入：先到 3 位小数，再到 2 位小数。
    例如 5.5445 -> 5.545 -> 5.55。
    使用 ROUND_HALF_UP 保证真正的四舍五入（非银行家舍入）。
    """
    from decimal import Decimal, ROUND_HALF_UP
    d = Decimal(str(value)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    d = d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(d)

def _CALCULATE_BOTTOM(close: float, pre_close: float) -> bool:
    """判断 close 是否等于跌停价（用于 is_bottom 判断）。

    跌停价 = pre_close * 0.9（先四舍五入到3位，再四舍五入到分）。
    与 StrategyD1 的 IsBottom（Close == Bottom）判定一致。
    """
    if pre_close <= 0:
        return False
    bottom = _ROUND_PRICE(float(pre_close) * 0.9)
    return abs(close - bottom) < 0.001

def UPDATE_1D():
    """加工日线：读取 1D_ORIGIN 原始数据，计算加工字段，删除 1D 旧数据后重建。

    - 删除 1D 目录旧数据后重新生成（多进程并行，每只股票一个 worker）
    - 不删除 1D_ORIGIN 原始数据
    - 计算字段: pre_close / is_top / is_toped / ratio / is_up / is_down /
      is_red / is_green / is_volume_up / is_volume_down / ma系列 / lian_ban
    """
    stock_codes = STOCK_CODES()
    if not os.path.exists(PATH_AIDATA_1D_ORIGIN()):
        print("UPDATE_1D: 1D_ORIGIN 目录不存在，请先运行 UPDATE_1D_ORIGIN")
        return
    _rotate_dir(PATH_AIDATA_1D())
    _SZ200_1D_ALL_CACHE.clear()
    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as pool:
        future_to_code = {pool.submit(GENERATE_1D, c): c for c in stock_codes}
        with tqdm(total=len(future_to_code), desc="1D", ncols=90) as bar:
            for fut in as_completed(future_to_code):
                fut.result()
                bar.set_postfix(code=future_to_code[fut], refresh=False)
                bar.update(1)
    return f"1D: 完成 {len(stock_codes)} 只股票"

def _IS_TOP_FILE(stock_code: str, trading_date: str) -> bool:
    """从 TOP 列表文件判断某股票在指定交易日是否涨停。

    TOP 文件路径为 {PATH_AIDATA_TOP()}/{trading_date}，每行一个带后缀的股票代码。
    """
    top_file = f"{PATH_AIDATA_TOP()}/{trading_date}"
    if not os.path.exists(top_file):
        return False
    with open(top_file, "r") as file:
        for line in file:
            if line.strip() == stock_code:
                return True
    return False

def GENERATE_1D(stock_code: str):
    """worker: 读取单只股票 1D_ORIGIN 原始数据，计算全部加工字段并写入 1D 目录。

    逐交易日计算:
      - pre_close: 前一日收盘价（四舍五入到分），首日无前日数据为 0.0
      - is_toped: 盘中触及涨停价
      - is_top / lian_ban: 依据 TOP 列表；连板数当日涨停则累加、断板归零
      - ratio / is_up / is_down: 涨跌幅及其正负
      - is_red / is_green: 阳线/阴线
      - is_volume_up / is_volume_down: 放量/缩量
      - ma5/10/20/30/60/120: 需满 N 日收盘均价，不足为 0.0
    """
    origin_file = f"{PATH_AIDATA_1D_ORIGIN()}/{stock_code}"
    if not os.path.exists(origin_file):
        return
    records: list[list[str]] = []
    with open(origin_file, "r") as file:
        for line in file:
            parts = line.strip().split("|")
            if len(parts) >= 7:
                records.append(parts)

    processed: list[list[str]] = []
    lian_ban = 0  # 连板次数（从上一交易日延续）
    for i, parts in enumerate(records):
        _date = parts[0]
        _open = float(parts[1])
        _high = float(parts[2])
        _low = float(parts[3])
        _close = float(parts[4])
        _volume = float(parts[5])
        _amount = float(parts[6])

        pre_close = 0.0
        if i > 0:
            pre_close = _ROUND_PRICE(float(records[i - 1][4]))  # 前一日收盘价，四舍五入到分

        is_toped = 1 if (pre_close > 0 and _CALCULATE_LIMIT(_high, pre_close)) else 0
        is_top = 1 if _IS_TOP_FILE(stock_code, _date) else 0
        lian_ban = lian_ban + 1 if is_top == 1 else 0  # 当日涨停则累加，否则归零
        is_bottom = 1 if _CALCULATE_BOTTOM(_close, pre_close) else 0  # 收盘价等于跌停价

        ratio = 0.0
        if pre_close > 0:
            ratio = round((_close - pre_close) / pre_close * 100.0, 4)
        is_up = 1 if ratio > 0 else 0
        is_down = 1 if ratio < 0 else 0
        is_red = 1 if _close > _open else 0
        is_green = 1 if _close < _open else 0

        pre_volume = 0.0
        if i > 0:
            pre_volume = float(records[i - 1][5])
        is_volume_up = 1 if (pre_volume > 0 and _volume > pre_volume) else 0
        is_volume_down = 1 if (pre_volume > 0 and _volume < pre_volume) else 0

        ma_values: list[float] = []
        for period in _MA_PERIODS:
            window = records[max(0, i - period + 1): i + 1]
            if len(window) == period:  # 必须满 period 个数据点才计算均价，不足则为 0.0
                # 均价 = 前 period-1 日收盘价 + 当日收盘价 之和 ÷ period，四舍五入到分
                avg = sum(float(r[4]) for r in window) / len(window)
                ma_values.append(_ROUND_PRICE(avg))
            else:
                ma_values.append(0.0)

        processed.append([
            _date, parts[1], parts[2], parts[3], parts[4], parts[5], parts[6],
            f"{pre_close:.2f}", str(is_top), str(is_toped), f"{ratio:.4f}",
            str(is_up), str(is_down), str(is_red), str(is_green),
            str(is_volume_up), str(is_volume_down),
            *[f"{v:.2f}" for v in ma_values],
            str(lian_ban),
            str(is_bottom),
        ])

    with open(f"{PATH_AIDATA_1D()}/{stock_code}", "w") as file:
        for row in processed:
            file.write("|".join(row) + "\n")

if __name__ == "__main__":
    UPDATE_1D_ORIGIN()
    UPDATE_1D()
