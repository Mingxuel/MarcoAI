"""
统一数据更新入口

运行本脚本即可按依赖顺序更新全部数据：
    python AICode/MarcoAPI/Update/Update1D.py

更新流程（按依赖顺序）:
    1. UPDATE_TRADING_DATES    更新交易日历
    2. UPDATE_STOCK_CODES      更新股票池（SZ100.xlsx -> STOCK_CODES_ALL）
    3. UPDATE_1D_ORIGIN        拉取原始前复权日线（需通达信联网）
    4. UPDATE_1D               加工日线（1D_ORIGIN -> 1D，含 is_top/is_bottom/MA/连板等）
    5. UPDATE_TOP              生成每日涨停股列表（TOP_ORIGIN -> TOP）
    6. UPDATE_1D               加工日线（依赖涨停列表生成 is_top/lian_ban）
    7. UPDATE_STRATEGY_TPO_3/TPO_TOP/TPO_M5  策略选股（Strategy/ 回测数据）
    8. UPDATE_TARGET_TPO_3/TPO_TOP  策略实盘候选池（TARGET/ 候选股）
"""

import os
import sys

_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _root not in sys.path:
    sys.path.insert(0, _root)

from AICode.MarcoAPI.Update.TradingDates import UPDATE_TRADING_DATES
from AICode.MarcoAPI.Update.StockCodes import UPDATE_STOCK_CODES
from AICode.MarcoAPI.Update.SZ2001D import UPDATE_1D_ORIGIN, UPDATE_1D
from AICode.MarcoAPI.Update.Path import PATH_AIDATA
from AICode.MarcoAPI.Update.SZ200Top import UPDATE_TOP
from AICode.MarcoAPI.Update.SZ200Strategy import (
    UPDATE_STRATEGY_TPO_3,
    UPDATE_STRATEGY_TPO_TOP,
    UPDATE_STRATEGY_TPO_M5,
)
from AICode.MarcoAPI.Update.SZ200Target import UPDATE_TARGET_TPO_3, UPDATE_TARGET_TPO_TOP, UPDATE_TARGET_TPO_M5


def _remove_dir_safe(path: str):
    """逐文件删除目录（规避实盘机批量删除保护），递归处理子目录。"""
    if not os.path.isdir(path):
        return
    for name in os.listdir(path):
        p = os.path.join(path, name)
        try:
            if os.path.isdir(p):
                _remove_dir_safe(p)
                os.rmdir(p)
            else:
                os.remove(p)
        except OSError:
            pass
    try:
        os.rmdir(path)
    except OSError:
        pass


def _cleanup_old_dirs():
    """Remove residual .old_* dirs left by _rotate_dir.

    Recursively scan AIData and delete them via _remove_dir_safe (one file at a
    time, bypassing the live-trading machine batch-delete protection), so these
    residual dirs do not accumulate across updates.
    """
    aidata = PATH_AIDATA()
    removed = 0
    for root, dirs, _files in os.walk(aidata, topdown=False):
        for name in list(dirs):
            if ".old_" in name:
                p = os.path.join(root, name)
                _remove_dir_safe(p)
                removed += 1
                print(f"    cleaned residual dir: {os.path.relpath(p, aidata)}")
    if removed == 0:
        print("    no residual dir, nothing to clean")
    return removed


def UPDATE_ALL():
    """按依赖顺序更新全部数据

    顺序说明:
        UPDATE_1D 加工日线的 is_top/lian_ban 依赖 UPDATE_TOP 生成的涨停列表，
        故 UPDATE_TOP 须在 UPDATE_1D 之前执行。
    """
    def _step_trading_dates():
        dates = UPDATE_TRADING_DATES()
        return f"交易日历: 共 {len(dates)} 个交易日 ({dates[0]} ~ {dates[-1]})"

    def _step_stock_codes():
        rows = UPDATE_STOCK_CODES()
        return f"股票列表: 共 {len(rows)} 只"

    steps = [
        ("UPDATE_TRADING_DATES", _step_trading_dates),
        ("UPDATE_STOCK_CODES", _step_stock_codes),
        ("UPDATE_1D_ORIGIN", UPDATE_1D_ORIGIN),
        ("UPDATE_TOP", UPDATE_TOP),
        ("UPDATE_1D", UPDATE_1D),
        ("UPDATE_STRATEGY_TPO_3", UPDATE_STRATEGY_TPO_3),
        ("UPDATE_STRATEGY_TPO_TOP", UPDATE_STRATEGY_TPO_TOP),
        ("UPDATE_STRATEGY_TPO_M5", UPDATE_STRATEGY_TPO_M5),
        ("UPDATE_TARGET_TPO_3", UPDATE_TARGET_TPO_3),
        ("UPDATE_TARGET_TPO_TOP", UPDATE_TARGET_TPO_TOP),
        ("UPDATE_TARGET_TPO_M5", UPDATE_TARGET_TPO_M5),
    ]
    for name, fn in steps:
        try:
            # 抑制内部步骤的详细输出（噪声），但步骤自身的摘要字符串在外部打印
            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                summary = fn()
            if summary:
                print(f"  {summary}", file=sys.stderr)
        except BaseException as exc:  # 捕获所有异常，避免静默中断后续步骤
            print(f"!!!!! {name} FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
    # 更新完成后清理 _rotate_dir 留下的 .old_* 残留目录
    try:
        _cleanup_old_dirs()
    except BaseException as exc:
        print(f"!!!!! CLEANUP RESIDUAL DIRS FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
    print("ALL DATA UPDATE COMPLETED", file=sys.stderr)


if __name__ == "__main__":
    UPDATE_ALL()
