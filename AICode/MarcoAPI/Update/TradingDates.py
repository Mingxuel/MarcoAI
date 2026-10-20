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


def _top_latest_date() -> str | None:
    """返回 AIData/TOP 目录中最大日期（手动维护的涨停股数据，代表已确认交易日）。"""
    d = PATH_AIDATA_TOP()
    if not os.path.isdir(d):
        return None
    ds = [f for f in os.listdir(d) if f.isdigit()]
    return max(ds) if ds else None


def EFFECTIVE_LATEST_TRADING_DATE() -> str:
    """返回数据已就绪、可安全作为 T-0 的有效最新交易日。

    直接以 AIData/TOP 手动维护的最新日期为准：TOP 由手动导入的涨停股 excel 维护
    （文件名含交易日），其最大日期即用户已确认的最后一个交易日。以此为准可避免
    把盘中/未确认的交易日历最后一天当作 T-0 写入。

    TOP 为空（尚未导入任何涨停数据）时退回交易日历最后一天作为兜底。
    """
    top_latest = _top_latest_date()
    if top_latest is not None:
        return top_latest
    trading_dates = TRADING_DATES()
    if not trading_dates:
        raise RuntimeError("交易日历为空，无法判定最新交易日")
    return trading_dates[-1]


if __name__ == "__main__":
    UPDATE_TRADING_DATES()
