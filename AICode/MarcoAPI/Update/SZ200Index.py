"""
指数日线（1D）数据处理模块

====================================================
一、数据流（与 SZ2001D 平行，但指数不需要 5M 数据支持）
====================================================
  指数.xlsx（INFO/指数.xlsx）
        │  UPDATE_INDEX_CODES
        ▼
  INDEX_CODES（指数代码|名称，带 .SH/.SZ 后缀）

  通达信接口 ──UPDATE_INDEX_1D_ORIGIN──▶ INDEX_ORIGIN（原始前复权日线）
                                            │
                                       UPDATE_INDEX_1D（加工）
                                            ▼
                                        INDEX（加工日线，含派生字段）
  说明:
    - INDEX_ORIGIN 只由 UPDATE_INDEX_1D_ORIGIN 维护（原始数据，不删除）
    - INDEX 由 UPDATE_INDEX_1D 生成，每次删除旧数据后重建（不触碰 INDEX_ORIGIN）
    - 指数无涨停/跌停/连板概念，故 is_top/is_toped/is_bottom/lian_ban 恒为 0

====================================================
二、存储文件
====================================================
  MarcoAI/AIData/INDEX_ORIGIN —— 原始前复权日线（与 1D_ORIGIN 同格式）
      每行: date|open|high|low|close|volume|amount

  MarcoAI/AIData/INDEX        —— 加工日线（与 1D 同格式，25 列）
      数据起始日期与 1D 一致（START_DATE）

====================================================
三、API 说明
====================================================
  UPDATE_INDEX_CODES() -> list[str]
      从 指数.xlsx 提取指数代码/名称，清空 INDEX_CODES 后写入并缓存
      返回 "代码|名称" 行列表

  INDEX_CODES() -> list[str]
      返回全部指数代码（带 .SH/.SZ 后缀），带缓存

  INDEX_CODES_ALL() -> list[str]
      返回完整 "代码|名称" 行列表，文件缺失时回退生成

  GET_INDEX_NAME(stock_code) -> str | None
      通过指数代码获取名称，找不到返回 None

  UPDATE_INDEX_1D_ORIGIN() -> None
      从通达信拉取全指数前复权原始日线，删除 INDEX_ORIGIN 旧数据后重建

  UPDATE_INDEX_1D() -> None
      读取 INDEX_ORIGIN 原始数据，计算加工字段，删除 INDEX 旧数据后重建（多进程）
"""

from concurrent.futures import ProcessPoolExecutor, as_completed
import os
import sys
from functools import partial
from openpyxl import load_workbook
import pandas as pd

from .progress import ProgressBar as tqdm

_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _root not in sys.path:
    sys.path.insert(0, _root)
from AICode.MarcoAPI.Update.Constants import *
from AICode.MarcoAPI.Update.TradingDates import *
from AICode.MarcoAPI.Update.Path import *
# 复用 1D 模块的派生字段计算与目录轮转工具，保证口径一致
from AICode.MarcoAPI.Update.SZ2001D import (
    DATA_1D, _ROUND_PRICE, _rotate_dir, _safe_rmtree, _MA_PERIODS,
)


_INDEX_CODES_CACHE: dict[str, list[str]] = {}
_INDEX_NAME_CACHE: dict[str, dict[str, str]] = {}


def _normalize_index_code(code: str) -> str:
    """把 6 位指数代码转为带后缀代码。

    规则（指数与个股不同，不按 6→SH 简单映射）:
        - 3 开头（399xxx 等深证系列）-> .SZ
        - 其余（000xxx 上证/中证/沪深300 等）-> .SH
    """
    code = code.strip()
    return f"{code}.SZ" if code.startswith("3") else f"{code}.SH"


def INDEX_CODES():
    if "data" not in _INDEX_CODES_CACHE:
        if os.path.exists(PATH_AIDATA_INDEX_CODES()):
            with open(PATH_AIDATA_INDEX_CODES(), "r", encoding="utf-8") as file:
                _INDEX_CODES_CACHE["data"] = [line.split("|")[0] for line in file.read().splitlines() if line]
        else:
            _INDEX_CODES_CACHE["data"] = [line.split("|")[0] for line in UPDATE_INDEX_CODES()]
    return _INDEX_CODES_CACHE["data"]


def INDEX_CODES_ALL():
    """返回完整指数行列表（"代码|名称"），从 INDEX_CODES 文件读取，缺失时回退生成"""
    if os.path.exists(PATH_AIDATA_INDEX_CODES()):
        with open(PATH_AIDATA_INDEX_CODES(), "r", encoding="utf-8") as file:
            return [line for line in file.read().splitlines() if line]
    return UPDATE_INDEX_CODES()


def GET_INDEX_NAME(stock_code: str) -> str | None:
    """通过指数代码获取名称，支持带/不带后缀，找不到返回 None"""
    code = stock_code.strip().upper()
    if "." not in code and len(code) == 6 and code.isdigit():
        code = _normalize_index_code(code)
    if "data" not in _INDEX_NAME_CACHE:
        _INDEX_NAME_CACHE["data"] = {
            line.split("|")[0]: line.split("|")[1]
            for line in INDEX_CODES_ALL() if len(line.split("|")) >= 2
        }
    return _INDEX_NAME_CACHE["data"].get(code)


def UPDATE_INDEX_CODES():
    """从 指数.xlsx 提取指数代码/名称，清空 INDEX_CODES 文件后写入"""
    data: list[str] = []
    workbook = load_workbook(PATH_AIDATA_INFO_INDEX())
    try:
        sheet = workbook.active
        if sheet is None:
            return data
        for row in sheet.iter_rows(min_row=2, values_only=True):
            if len(row) < 3 or row[1] is None:
                continue
            code = str(row[1]).strip()
            if not code.isdigit() or len(code) != 6:
                continue
            name = str(row[2]).strip() if row[2] is not None else ""
            data.append(f"{_normalize_index_code(code)}|{name}")
    finally:
        workbook.close()
    with open(PATH_AIDATA_INDEX_CODES(), "w", encoding="utf-8") as file:
        file.write("\n".join(data))
    _INDEX_CODES_CACHE["data"] = [line.split("|")[0] for line in data]
    return data


def UPDATE_INDEX_1D_ORIGIN():
    """拉取原始前复权日线：从通达信获取全指数前复权数据，删除 INDEX_ORIGIN 旧数据后重建。

    数据为原始行情（date|open|high|low|close|volume|amount），不计算任何加工字段。
    指数不需要 5M 数据支持，故此处仅拉日线。
    """
    _rotate_dir(PATH_AIDATA_INDEX_ORIGIN())

    index_codes = INDEX_CODES()
    if not index_codes:
        return "INDEX_ORIGIN: 指数列表为空，跳过（请先运行 UPDATE_INDEX_CODES）"

    sys.path.append(PATH_TDX())  # 确保 tqcenter 模块所在目录在 sys.path 中
    from tqcenter import tq  # 仅在离线更新时惰性导入，避免实盘加载本模块时触碰通达信
    tq.initialize(__file__)
    df = tq.get_market_data(
        field_list=["Open", "High", "Low", "Close", "Volume", "Amount"],
        stock_list=index_codes, start_time=START_DATE, end_time='', count=-1,
        dividend_type='front', period='1d', fill_data=False,
    )
    fn_origin = partial(GENERATE_INDEX_1D_ORIGIN, dataframe=df)
    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as pool:
        future_to_code = {pool.submit(fn_origin, c): c for c in index_codes}
        with tqdm(total=len(future_to_code), desc="INDEX_ORIGIN", ncols=90, disable=False) as bar:
            for fut in as_completed(future_to_code):
                fut.result()
                bar.set_postfix(code=future_to_code[fut], refresh=False)
                bar.update(1)
    return f"INDEX_ORIGIN: 完成 {len(index_codes)} 只指数"


def GENERATE_INDEX_1D_ORIGIN(stock_code: str, dataframe: object) -> dict[str, DATA_1D]:
    """worker: 将通达信 DataFrame 中单只指数的原始日线写入 INDEX_ORIGIN 文件。

    按交易日顺序逐行写原始 7 列数据，并返回 {日期: DATA_1D} 缓存。
    fill_data=False 时停牌日无该指数数据，跳过不写。
    """
    stock_cache: dict[str, DATA_1D] = {}
    with open(f"{PATH_AIDATA_INDEX_ORIGIN()}/{stock_code}", "w") as file:
        trading_dates = TRADING_DATES()
        for trading_date in trading_dates:
            try:
                _open = dataframe["Open"].loc[trading_date, stock_code]
            except (KeyError, AttributeError):
                continue  # fill_data=False：该交易日无该指数数据（停牌），跳过
            _high = dataframe["High"].loc[trading_date, stock_code]
            _low = dataframe["Low"].loc[trading_date, stock_code]
            _close = dataframe["Close"].loc[trading_date, stock_code]
            _volume = dataframe["Volume"].loc[trading_date, stock_code]
            _amount = dataframe["Amount"].loc[trading_date, stock_code]
            if any(pd.isna(v) for v in (_open, _high, _low, _close, _volume, _amount)):
                continue  # 停牌/无成交返回 NaN，跳过
            file.write(f"{trading_date}|{_open}|{_high}|{_low}|{_close}|{_volume}|{_amount}\n")
            stock_cache[trading_date] = DATA_1D(
                date=trading_date, open=float(_open), high=float(_high),
                low=float(_low), close=float(_close),
                volume=float(_volume), amount=float(_amount))
    return stock_cache


def UPDATE_INDEX_1D():
    """加工日线：读取 INDEX_ORIGIN 原始数据，计算加工字段，删除 INDEX 旧数据后重建。

    - 删除 INDEX 目录旧数据后重新生成（多进程并行，每只指数一个 worker）
    - 不删除 INDEX_ORIGIN 原始数据
    - 计算字段: pre_close / ratio / is_up / is_down / is_red / is_green /
      is_volume_up / is_volume_down / ma系列
    - is_top / is_toped / lian_ban / is_bottom 恒为 0（指数无涨停/跌停/连板）
    """
    index_codes = INDEX_CODES()
    if not index_codes:
        return "INDEX: 指数列表为空，跳过（请先运行 UPDATE_INDEX_CODES）"
    if not os.path.exists(PATH_AIDATA_INDEX_ORIGIN()):
        print("UPDATE_INDEX_1D: INDEX_ORIGIN 目录不存在，请先运行 UPDATE_INDEX_1D_ORIGIN")
        return
    _rotate_dir(PATH_AIDATA_INDEX())
    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as pool:
        future_to_code = {pool.submit(GENERATE_INDEX_1D, c): c for c in index_codes}
        with tqdm(total=len(future_to_code), desc="INDEX", ncols=90, disable=False) as bar:
            for fut in as_completed(future_to_code):
                fut.result()
                bar.set_postfix(code=future_to_code[fut], refresh=False)
                bar.update(1)
    return f"INDEX: 完成 {len(index_codes)} 只指数"


def GENERATE_INDEX_1D(stock_code: str):
    """worker: 读取单只指数 INDEX_ORIGIN 原始数据，计算加工字段并写入 INDEX 目录。

    与 GENERATE_1D 同口径（pre_close/ratio/涨跌/量能/MA），但涨停/跌停/连板相关列恒为 0。
    """
    origin_file = f"{PATH_AIDATA_INDEX_ORIGIN()}/{stock_code}"
    if not os.path.exists(origin_file):
        return
    records: list[list[str]] = []
    with open(origin_file, "r") as file:
        for line in file:
            parts = line.strip().split("|")
            if len(parts) >= 7:
                records.append(parts)

    processed: list[list[str]] = []
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
                avg = sum(float(r[4]) for r in window) / len(window)
                ma_values.append(_ROUND_PRICE(avg))
            else:
                ma_values.append(0.0)

        processed.append([
            _date, parts[1], parts[2], parts[3], parts[4], parts[5], parts[6],
            f"{pre_close:.2f}",
            "0",   # is_top    指数无涨停
            "0",   # is_toped  指数无涨停
            f"{ratio:.4f}",
            str(is_up), str(is_down), str(is_red), str(is_green),
            str(is_volume_up), str(is_volume_down),
            *[f"{v:.2f}" for v in ma_values],
            "0",   # lian_ban  指数无连板
            "0",   # is_bottom 指数无跌停
        ])

    with open(f"{PATH_AIDATA_INDEX()}/{stock_code}", "w") as file:
        for row in processed:
            file.write("|".join(row) + "\n")


if __name__ == "__main__":
    UPDATE_INDEX_CODES()
    UPDATE_INDEX_1D_ORIGIN()
    UPDATE_INDEX_1D()
