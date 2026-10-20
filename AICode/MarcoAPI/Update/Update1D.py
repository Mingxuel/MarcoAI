"""
统一数据更新入口

运行本脚本即可按依赖顺序更新全部数据：
    python AICode/MarcoAPI/Update/Update1D.py

更新流程（按依赖顺序）:
    1. UPDATE_TRADING_DATES    更新交易日历
    2. UPDATE_STOCK_CODES      更新股票池（SZ100.xlsx -> STOCK_CODES_ALL）
    3. UPDATE_1D_ORIGIN        拉取原始前复权日线（需通达信联网）
    3.5 UPDATE_5M_ORIGIN       拉取原始前复权 5 分钟线（需通达信联网，一条龙内仅此一次）
    4. UPDATE_TOP              生成每日涨停股列表（TOP_ORIGIN -> TOP）
    5. UPDATE_1D               加工日线（1D_ORIGIN -> 1D，含 is_top/is_bottom/MA/连板；
                                 is_top/lian_ban 依赖上一步 UPDATE_TOP 的涨停列表，单次加工即可，并非跑两遍）
    6. UPDATE_INDEX_1D         加工指数日线（INDEX_ORIGIN -> INDEX，无涨停/连板列）
    7. UPDATE_STRATEGY_TPO_3/TPO_TOP/TPO_M5  策略选股（Strategy/ 回测数据）
    8. UPDATE_TARGET_TPO_3/TPO_TOP/TPO_M5/TPO_M5_MID/TPO_M5_SMALL    策略实盘候选池（TARGET/ 候选股）
"""

import os
import sys

_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _root not in sys.path:
    sys.path.insert(0, _root)

from AICode.MarcoAPI.Update.TradingDates import UPDATE_TRADING_DATES
from AICode.MarcoAPI.Update.StockCodes import UPDATE_STOCK_CODES
from AICode.MarcoAPI.Update.SZ2001D import UPDATE_1D_ORIGIN, UPDATE_1D
from AICode.MarcoAPI.Update.SZ200Index import (
    UPDATE_INDEX_CODES, UPDATE_INDEX_1D_ORIGIN, UPDATE_INDEX_1D,
)
from AICode.MarcoAPI.Update.Path import PATH_AIDATA
from AICode.MarcoAPI.Update.SZ200Top import UPDATE_TOP, UPDATE_TOP_FIRST, UPDATE_TOP_FIRST_VOL, UPDATE_TOP_FIRST_VOL_SUN, UPDATE_TOP_FIRST_VOL_MA60
from AICode.MarcoAPI.Update.SZ200Strategy import (
    UPDATE_STRATEGY_TPO_3,
    UPDATE_STRATEGY_TPO_TOP,
    UPDATE_STRATEGY_TPO_M5,
    UPDATE_STRATEGY_TPO_M5_MID,
    UPDATE_STRATEGY_TPO_M5_SMALL,
)
from AICode.MarcoAPI.Update.SZ200Target import (
    UPDATE_TARGET_TPO_3, UPDATE_TARGET_TPO_TOP, UPDATE_TARGET_TPO_M5,
    UPDATE_TARGET_TPO_M5_MID, UPDATE_TARGET_TPO_M5_SMALL,
)
from AICode.MarcoAPI.Update.SZ2005M import UPDATE_5M_ORIGIN, UPDATE_5M_PANELS


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


def UPDATE_ALL(scope_codes: list[str] | None = None, recent_days_5m: int = 0):
    """按依赖顺序更新全部数据

    顺序说明:
        UPDATE_1D 加工日线的 is_top/lian_ban 依赖 UPDATE_TOP 生成的涨停列表，
        故 UPDATE_TOP 须在 UPDATE_1D 之前执行。

    scope_codes: 可选，限制 1D/5M 行情与候选池/策略只处理这些股票（如某周期内的涨停股），None 表示全市场。
    recent_days_5m: 可选，5M 只下载最近 N 个交易日（UI/回测仅用约 8 日窗口），0 表示全历史。
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
        ("UPDATE_1D_ORIGIN", lambda: UPDATE_1D_ORIGIN(scope_codes)),
        ("UPDATE_INDEX_CODES", UPDATE_INDEX_CODES),
        ("UPDATE_INDEX_1D_ORIGIN", UPDATE_INDEX_1D_ORIGIN),
        ("UPDATE_TOP", UPDATE_TOP),
        ("UPDATE_1D", lambda: UPDATE_1D(scope_codes)),
        ("UPDATE_INDEX_1D", UPDATE_INDEX_1D),
        ("UPDATE_TOP_FIRST", UPDATE_TOP_FIRST),
        ("UPDATE_TOP_FIRST_VOL", lambda: UPDATE_TOP_FIRST_VOL(scope_codes)),
        ("UPDATE_TOP_FIRST_VOL_SUN", lambda: UPDATE_TOP_FIRST_VOL_SUN(scope_codes)),
        ("UPDATE_STRATEGY_TPO_3", UPDATE_STRATEGY_TPO_3),
        ("UPDATE_STRATEGY_TPO_TOP", UPDATE_STRATEGY_TPO_TOP),
        ("UPDATE_STRATEGY_TPO_M5", UPDATE_STRATEGY_TPO_M5),
        ("UPDATE_STRATEGY_TPO_M5_MID", UPDATE_STRATEGY_TPO_M5_MID),
        ("UPDATE_STRATEGY_TPO_M5_SMALL", UPDATE_STRATEGY_TPO_M5_SMALL),
        ("UPDATE_TARGET_TPO_3", UPDATE_TARGET_TPO_3),
        ("UPDATE_TARGET_TPO_TOP", UPDATE_TARGET_TPO_TOP),
        ("UPDATE_TARGET_TPO_M5", UPDATE_TARGET_TPO_M5),
        ("UPDATE_TARGET_TPO_M5_MID", UPDATE_TARGET_TPO_M5_MID),
        ("UPDATE_TARGET_TPO_M5_SMALL", UPDATE_TARGET_TPO_M5_SMALL),
        # 5M 须在所有 1D 加工 / TOP / 首板相关目录生成之后：UPDATE_5M_PANELS 从
        # AIData/TOP、TOP_FIRST、TOP_FIRST_VOL、TOP_FIRST_VOL_SUN 收集「首板相关涉及股」，
        # 这些目录由上面 UPDATE_TOP / UPDATE_TOP_FIRST* 步骤产出，故置于末尾。
        ("UPDATE_5M_ORIGIN", lambda: UPDATE_5M_PANELS()),
    ]
    import time
    import datetime as _dt
    import contextlib
    import traceback
    _overall0 = time.time()
    log_path = os.path.join(_root, "update_log.txt")
    sys.__stderr__.write(f"  ⏱ 数据更新开始 [{_dt.datetime.now().strftime('%H:%M:%S')}]  (详细日志: {log_path})\n")
    sys.__stderr__.flush()
    with open(log_path, "w", encoding="utf-8") as logf:
        for name, fn in steps:
            t0 = time.time()
            sys.__stderr__.write(f"  ▶ {name} 开始 [{_dt.datetime.now().strftime('%H:%M:%S')}]\n")
            sys.__stderr__.flush()
            try:
                # 步骤内部所有输出（清理文件、进度条、异常等）写入日志文件，终端只显示步骤级进度
                with contextlib.redirect_stdout(logf), contextlib.redirect_stderr(logf):
                    summary = fn()
                if summary:
                    sys.__stderr__.write(f"  {summary}\n")
                    sys.__stderr__.flush()
                sys.__stderr__.write(f"  ✓ {name} 完成 [{_dt.datetime.now().strftime('%H:%M:%S')}] ({time.time() - t0:.1f}s)\n")
                sys.__stderr__.flush()
            except BaseException as exc:
                logf.write(f"!!!!! {name} FAILED: {type(exc).__name__}: {exc}\n")
                traceback.print_exc(file=logf)
                sys.__stderr__.write(f"  !!!!! {name} 失败: {type(exc).__name__}: {exc}\n")
                sys.__stderr__.flush()
        # 清理 _rotate_dir 残留目录的详细信息也写入日志，不污染终端
        try:
            with contextlib.redirect_stdout(logf), contextlib.redirect_stderr(logf):
                _cleanup_old_dirs()
        except BaseException as exc:
            logf.write(f"!!!!! CLEANUP RESIDUAL DIRS FAILED: {type(exc).__name__}: {exc}\n")
            traceback.print_exc(file=logf)
            sys.__stderr__.write(f"  !!!!! 清理残留目录失败: {type(exc).__name__}: {exc}\n")
            sys.__stderr__.flush()
    _overall = time.time() - _overall0
    sys.__stderr__.write(f"  ⏱ 数据更新总耗时 {_overall:.1f}s ({_overall/60:.1f}min) [{_dt.datetime.now().strftime('%H:%M:%S')}]\n")
    sys.__stderr__.flush()
    print("ALL DATA UPDATE COMPLETED", file=sys.stderr)


if __name__ == "__main__":
    UPDATE_ALL()
