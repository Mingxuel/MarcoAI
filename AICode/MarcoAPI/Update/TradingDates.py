"""
交易日历（TRADING_DATES）管理模块

数据来源:
    通达信接口 tq.get_trading_dates 拉取上证交易日历

存储文件:
    MarcoAI/AIData/TRADING_DATES —— 每行一个交易日（YYYYMMDD）

API 说明:
    TRADING_DATES() -> list[str]
        返回全部交易日列表（升序，带缓存，日期格式 YYYYMMDD）
        示例: ['20250102', '20250103', ...]

    UPDATE_TRADING_DATES() -> list[str]
        从通达信重新拉取交易日，覆盖写入 TRADING_DATES 文件并刷新缓存；
        返回完整交易日列表

    TRADING_DATE_PREVIOUS(date, index) -> str | None
        返回 date 之前第 index 个交易日；index=0 返回 date 本身；
        date 无效或向前越界返回 None

    TRADING_DATE_AFTER(date, index) -> str | None
        返回 date 之后第 index 个交易日；index=0 返回 date 本身；
        date 无效或向后越界返回 None
"""

import os
import sys

_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _root not in sys.path:
    sys.path.insert(0, _root)
from AICode.MarcoAPI.Update.Constants import *
from AICode.MarcoAPI.Update.Path import *

_TRADING_DATES_CACHE: dict[str, list[str]] = {}

def TRADING_DATES():
    if "data" not in _TRADING_DATES_CACHE:
        with open(PATH_AIDATA_TRADING_DATES(), "r") as file:
            _TRADING_DATES_CACHE["data"] = file.read().splitlines()
    return _TRADING_DATES_CACHE["data"]

def UPDATE_TRADING_DATES():
    # 通达信(tq)仅在离线更新时才需要，惰性导入避免实盘加载本模块时触碰通达信
    sys.path.append(PATH_TDX())  # 确保 tqcenter 模块所在目录在 sys.path 中
    from tqcenter import tq
    tq.initialize(__file__)
    trading_dates = tq.get_trading_dates(market = 'SH', start_time = START_DATE, end_time = '', count = -1)
    with open(PATH_AIDATA_TRADING_DATES(), "w") as file:
        file.write("\n".join(trading_dates))
    _TRADING_DATES_CACHE["data"] = trading_dates
    return trading_dates

def TRADING_DATE_PREVIOUS(date: str, index: int) -> str | None:
    """返回 date 之前第 index 个交易日；index=0 返回 date 本身；date 无效或超出范围返回 None"""
    if index == 0:
        return date
    trading_dates = TRADING_DATES()
    try:
        position = trading_dates.index(date) - index
    except ValueError:
        return None
    if position < 0:
        return None
    return trading_dates[position]

def TRADING_DATE_AFTER(date: str, index: int) -> str | None:
    """返回 date 之后第 index 个交易日；index=0 返回 date 本身；date 无效或超出范围返回 None"""
    if index == 0:
        return date
    trading_dates = TRADING_DATES()
    try:
        position = trading_dates.index(date) + index
    except ValueError:
        return None
    if position > len(trading_dates) - 1:
        return None
    return trading_dates[position]

if __name__ == "__main__":
    UPDATE_TRADING_DATES()
