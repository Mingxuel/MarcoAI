import os
import sys

_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _root not in sys.path:
    sys.path.insert(0, _root)
from AICode.MarcoAPI.Update.TradingDates import TRADING_DATES


# ── 所有对齐数据文件统一使用这个基准日期列表 ──
# 跳过第一个交易日（因无法与前一交易日对比），确保每个文件行数一致
_ALIGNED_DATES = None


def _get_aligned_dates():
    """获取对齐基准日期列表（跳过第一个交易日）。"""
    global _ALIGNED_DATES
    if _ALIGNED_DATES is None:
        _ALIGNED_DATES = TRADING_DATES()[1:]
    return _ALIGNED_DATES


def WRITE_ALIGNED_FILE(file_path, dates_dict, fill_value, line_fmt):
    """写入全宽日期对齐的数据文件。

    所有调用此函数的文件，都会写入完全相同的日期行数，
    确保垂直方向日期一一对应。

    Args:
        file_path: 输出文件路径
        dates_dict: dict[str, str] 日期 -> 值字符串（日期后面的全部内容，不含 '|'）
        fill_value: 缺失日期时使用的填充值
        line_fmt: 格式模板，如 '{date}|{value}'，其中 {date} 替换为日期，{value} 替换为值
    """
    dates = _get_aligned_dates()
    with open(file_path, "w") as f:
        for date in dates:
            val = dates_dict.get(date, fill_value)
            f.write(line_fmt.format(date=date, value=val) + "\n")


def READ_ALIGNED_LINES(file_path):
    """按基准日期顺序读取对齐数据文件，缺失日期返回空字符串。

    Returns:
        list[tuple[str, str]]: [(date, raw_line_or_empty), ...]
    """
    data = {}
    if os.path.isfile(file_path):
        with open(file_path, "r") as f:
            for line in f:
                parts = line.strip().split("|")
                if parts:
                    data[parts[0]] = line.strip()

    dates = _get_aligned_dates()
    return [(date, data.get(date, "")) for date in dates]


def ALIGNED_DATES():
    """获取对齐基准日期列表。"""
    return _get_aligned_dates()
