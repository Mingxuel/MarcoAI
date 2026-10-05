"""
涨停股票（TOP）计算与管理模块

数据来源:
    MarcoAI/AIData/TOP_ORIGIN —— 每日涨停股原始 xlsx（文件名含日期）

存储文件:
    MarcoAI/AIData/TOP     —— 每日涨停股列表，文件名为交易日（YYYYMMDD），每行一个代码

API 说明:
    UPDATE_TOP() -> None
        遍历 TOP_ORIGIN 下的涨停 xlsx，提取股票代码（6 开头加 .SH，其余加 .SZ），
        以涨停日期命名写入 TOP 目录；多进程并行处理

    GET_TOP() -> dict[str, set[str]]
        返回跨进程共享的 Manager.dict 代理（{交易日: 涨停代码集合}），供 worker 进程使用

    IS_TOP(stock_code, trading_date) -> bool
        判断某股票在指定交易日是否涨停；优先读缓存（主进程/worker），兜底读文件

    GENERATE_TOP
        UPDATE_TOP 的 worker 函数，供 ProcessPoolExecutor 并行调度
"""

import os
import re
import sys
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from functools import partial
from multiprocessing import Manager
from typing import Optional
from .progress import ProgressBar as tqdm

from openpyxl import load_workbook

_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _root not in sys.path:
    sys.path.insert(0, _root)
from AICode.MarcoAPI.Update.Constants import *
from AICode.MarcoAPI.Update.StockCodes import *
from AICode.MarcoAPI.Update.TradingDates import *
from AICode.MarcoAPI.Update.Path import *

_TOP_CACHE: dict[str, set[str]] = {}
_WORKER_TOP_CACHE: Optional[dict[str, set[str]]] = None  # worker 进程中由 initializer 注入

def INIT_TOP(proxy: dict[str, set[str]]):
    """ProcessPoolExecutor initializer: 将 Manager.dict 代理注入 worker 全局变量"""
    global _WORKER_TOP_CACHE
    _WORKER_TOP_CACHE = proxy  # pyright: ignore[reportConstantRedefinition]

_MANAGER: Optional[Manager] = None

def GET_TOP() -> dict[str, set[str]]:
    """创建并返回跨进程共享的 Manager.dict 代理（从已填充的 _TOP_CACHE 构建）"""
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = Manager()  # pyright: ignore[reportConstantRedefinition]
    proxy: dict[str, set[str]] = _MANAGER.dict()  # pyright: ignore[reportOptionalMemberAccess]
    proxy.update(_TOP_CACHE)
    return proxy

def UPDATE_TOP():
    """从 TOP_ORIGIN 的每日涨停 xlsx 生成 TOP 目录下的涨停股列表文件（代码带 .SZ/.SH 后缀）"""
    top_origin_dir = PATH_AIDATA_TOP_ORIGIN()
    if not os.path.exists(top_origin_dir):
        print(f"UPDATE_TOP: TOP_ORIGIN 目录不存在 {top_origin_dir}")
        return
    xlsx_files = [
        os.path.join(top_origin_dir, file_name)
        for file_name in sorted(os.listdir(top_origin_dir))
        if file_name.endswith(".xlsx") and re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", file_name) is not None
    ]
    with ProcessPoolExecutor(max_workers=32) as pool:
        future_to_file = {pool.submit(GENERATE_TOP, f): f for f in xlsx_files}
        with tqdm(total=len(future_to_file), desc="TOP", ncols=90, disable=False) as bar:
            for fut in as_completed(future_to_file):
                fut.result()
                bar.set_postfix(file=os.path.basename(future_to_file[fut]), refresh=False)
                bar.update(1)
    return f"TOP: 完成 {len(xlsx_files)} 个涨停文件"

def _READ_TOP_CODES(top_file: str) -> list[str]:
    """读取 TOP 列表文件（每行一个带后缀代码），返回去重后的代码列表"""
    codes: list[str] = []
    seen: set[str] = set()
    if not os.path.exists(top_file):
        return codes
    with open(top_file, "r", encoding="utf-8") as file:
        for line in file:
            code = line.strip()
            if code and code not in seen:
                seen.add(code)
                codes.append(code)
    return codes

def UPDATE_TOP_FIRST():
    """从 TOP 计算每日【首板涨停】列表落盘到 TOP_FIRST：

    首板 = 当日涨停 − 前一交易日涨停（连板剔除），且当日日线 is_volume_up==1（放量）。
    文件格式与 TOP 一致：AIData/TOP_FIRST/{交易日}，每行一个带 .SZ/.SH 后缀的代码。
    口径与 UI「首板涨停股」TAB 及同花顺板块 ===TOP=== 完全一致（单一数据源）。
    """
    from .SZ2001D import GET_SZ200_1D_PREVIOUS, _rotate_dir
    top_dir = PATH_AIDATA_TOP()
    first_dir = PATH_AIDATA_TOP_FIRST()
    _rotate_dir(first_dir)
    if not os.path.isdir(top_dir):
        return "TOP_FIRST: 无 TOP 目录"
    dates = sorted(d for d in os.listdir(top_dir) if d.isdigit())
    top_sets = {d: set(_READ_TOP_CODES(os.path.join(top_dir, d))) for d in dates}
    for i, d in enumerate(dates):
        prev = top_sets[dates[i - 1]] if i >= 1 else set()
        out: list[str] = []
        for code in top_sets[d]:
            if code in prev:                  # 昨日也涨停 → 连板，非首板
                continue
            try:
                rec = GET_SZ200_1D_PREVIOUS(code, d, 0)
            except OSError:
                continue                      # 无加工日线文件 → 无法判定放量，跳过
            if rec is None or rec.is_volume_up != 1:
                continue
            out.append(code)
        with open(os.path.join(first_dir, d), "w", encoding="utf-8") as file:
            if out:
                file.write("\n".join(out) + "\n")
    return f"TOP_FIRST: 完成 {len(dates)} 天"

def UPDATE_TOP_FIRST_VOL():
    """生成每日【首板涨停放量股】落盘到 TOP_FIRST_VOL：

    条件（与 TPO_M5 候选池的 T-3 / T-2 口径一致，但**不筛选市值**）：
        T-3（前一日）：涨停 is_top==1 且 首板 lian_ban==1 且 放量 is_volume_up==1
        T-2（当日）  ：上涨 is_up==1（涨跌幅为正）且 放量 is_volume_up==1 且 未涨停 is_top==0
    即「首板涨停后的次日放量上涨、但未涨停」的股票，市值不设上下限。

    文件格式与 TOP 一致：AIData/TOP_FIRST_VOL/{交易日}，每行一个带 .SZ/.SH 后缀的代码。
    """
    from .SZ2001D import GET_SZ200_1D_PREVIOUS, _rotate_dir
    out_dir = PATH_AIDATA_TOP_FIRST_VOL()
    _rotate_dir(out_dir)
    trading_dates = TRADING_DATES()
    stock_codes = STOCK_CODES_ALL()
    if not trading_dates or not stock_codes:
        return "TOP_FIRST_VOL: 无交易日或股票池"
    with ProcessPoolExecutor(max_workers=32) as pool:
        fn = partial(GENERATE_TOP_FIRST_VOL, stock_codes, out_dir)
        future_to_date = {pool.submit(fn, d): d for d in trading_dates}
        with tqdm(total=len(future_to_date), desc="TOP_FIRST_VOL", ncols=90, disable=False) as bar:
            for fut in as_completed(future_to_date):
                fut.result()
                bar.set_postfix(date=future_to_date[fut], refresh=False)
                bar.update(1)
    return f"TOP_FIRST_VOL: 完成 {len(trading_dates)} 个交易日"


# T-1 股价创新高：相对之前 N 个交易日的最高价。如需改窗口（60日/历史），改此常量即可。
NEW_HIGH_WINDOW = 20


def UPDATE_TOP_FIRST_VOL_SUN():
    """生成每日【首板涨停放量连阳股】落盘到 TOP_FIRST_VOL_SUN。

    条件 = 首板涨停放量股(TOP_FIRST_VOL) 基础上，再加两个 T-1 条件：
        T-3（前一日）：涨停 is_top==1 且 首板 lian_ban==1 且 放量 is_volume_up==1
        T-2（当日）  ：上涨 is_up==1 且 放量 is_volume_up==1 且 未涨停 is_top==0
        T-1（次日）  ：① 收盘价 > 开盘价（阳线 is_red==1）
                      ② 最高价创阶段新高（> 之前 NEW_HIGH_WINDOW 个交易日的最高价）
    T-1 不存在（如最新交易日尚无下一交易日）时该股跳过。

    文件格式与 TOP 一致：AIData/TOP_FIRST_VOL_SUN/{交易日}，每行一个带 .SZ/.SH 后缀的代码。
    """
    from .SZ2001D import GET_SZ200_1D_PREVIOUS, _rotate_dir
    out_dir = PATH_AIDATA_TOP_FIRST_VOL_SUN()
    _rotate_dir(out_dir)
    trading_dates = TRADING_DATES()
    stock_codes = STOCK_CODES_ALL()
    if not trading_dates or not stock_codes:
        return "TOP_FIRST_VOL_SUN: 无交易日或股票池"
    with ProcessPoolExecutor(max_workers=32) as pool:
        fn = partial(GENERATE_TOP_FIRST_VOL_SUN, stock_codes, out_dir)
        future_to_date = {pool.submit(fn, d): d for d in trading_dates}
        with tqdm(total=len(future_to_date), desc="TOP_FIRST_VOL_SUN", ncols=90, disable=False) as bar:
            for fut in as_completed(future_to_date):
                fut.result()
                bar.set_postfix(date=future_to_date[fut], refresh=False)
                bar.update(1)
    return f"TOP_FIRST_VOL_SUN: 完成 {len(trading_dates)} 个交易日"


def GENERATE_TOP_FIRST_VOL_SUN(stock_codes: list[str], out_dir: str, trading_date: str):
    """worker: 以 trading_date 为 T-2，找出「首板涨停放量 + T-2 上涨放量未涨停 + T-1 阳线创新高」的股票。

    在 GENERATE_TOP_FIRST_VOL 的 T-3/T-2 判定之上，再校验 T-1（T-2 之后第 1 个交易日）：
        - T-1 收 > 开（阳线 is_red==1）
        - T-1 最高价 > 之前 NEW_HIGH_WINDOW 个交易日的最高价（阶段新高）
    T-1 不存在则跳过该股（最新交易日无下一交易日）。
    """
    from .SZ2001D import GET_SZ200_1D_PREVIOUS, GET_SZ200_1D_AFTER
    out: list[str] = []
    for stock_code in stock_codes:
        stock = stock_code.split('|')
        code = stock[0]
        # T-3：首板涨停放量
        rec_prev = GET_SZ200_1D_PREVIOUS(code, trading_date, 1)
        if rec_prev is None or rec_prev.is_top != 1 or rec_prev.lian_ban != 1 or rec_prev.is_volume_up != 1:
            continue
        # T-2：上涨 + 放量 + 未涨停
        rec_cur = GET_SZ200_1D_PREVIOUS(code, trading_date, 0)
        if rec_cur is None or rec_cur.is_up != 1 or rec_cur.is_volume_up != 1 or rec_cur.is_top != 0:
            continue
        # T-1：次日
        rec_t1 = GET_SZ200_1D_AFTER(code, trading_date, 1)
        if rec_t1 is None:
            continue
        # T-1 收 > 开（阳线）
        if rec_t1.is_red != 1:
            continue
        # T-1 创新高：最高价 > 之前 N 个交易日最高价
        max_prev_high = 0.0
        for k in range(1, NEW_HIGH_WINDOW + 1):
            prev = GET_SZ200_1D_PREVIOUS(code, rec_t1.date, k)
            if prev is None:
                break
            if prev.high > max_prev_high:
                max_prev_high = prev.high
        if rec_t1.high <= max_prev_high:
            continue
        out.append(code)
    with open(os.path.join(out_dir, trading_date), "w", encoding="utf-8") as file:
        if out:
            file.write("\n".join(out) + "\n")


def GENERATE_TOP_FIRST_VOL(stock_codes: list[str], out_dir: str, trading_date: str):
    """worker: 以 trading_date 为 T-2，找出「T-3 首板涨停放量 + T-2 上涨放量未涨停」的股票。

    与 GENERATE_TARGET_CANDIDATE 的 T-3/T-2 判定完全一致，唯一区别是不做市值筛选。
    """
    from .SZ2001D import GET_SZ200_1D_PREVIOUS
    out: list[str] = []
    for stock_code in stock_codes:
        stock = stock_code.split('|')
        code = stock[0]
        # T-3：首板涨停放量
        rec_prev = GET_SZ200_1D_PREVIOUS(code, trading_date, 1)
        if rec_prev is None:
            continue
        if rec_prev.is_top != 1:            # 涨停
            continue
        if rec_prev.lian_ban != 1:          # 首板（非连板）
            continue
        if rec_prev.is_volume_up != 1:      # 放量
            continue
        # T-2：上涨 + 放量 + 未涨停（涨跌幅为正当日 is_up==1）
        rec_cur = GET_SZ200_1D_PREVIOUS(code, trading_date, 0)
        if rec_cur is None:
            continue
        if rec_cur.is_up != 1:              # 上涨（涨跌幅为正）
            continue
        if rec_cur.is_volume_up != 1:       # 放量
            continue
        if rec_cur.is_top != 0:             # 未涨停
            continue
        out.append(code)
    with open(os.path.join(out_dir, trading_date), "w", encoding="utf-8") as file:
        if out:
            file.write("\n".join(out) + "\n")


def GENERATE_TOP(xlsx_file: str):
    match = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", os.path.basename(xlsx_file))
    if match is None:
        return
    trading_date = f"{match.group(1)}{int(match.group(2)):02d}{int(match.group(3)):02d}"
    top_file = f"{PATH_AIDATA_TOP()}/{trading_date}"
    stock_codes = _READ_TOP_ORIGIN(xlsx_file)
    with open(top_file, "w") as file:
        for stock_code in stock_codes:
            file.write(f"{stock_code}\n")

def _READ_TOP_ORIGIN(xlsx_file: str) -> list[str]:
    """读取涨停 xlsx，返回带后缀的股票代码列表（去重、保持顺序）"""
    stock_codes: list[str] = []
    seen: set[str] = set()
    with warnings.catch_warnings():
        # 抑制 openpyxl 读取部分 xlsx 时的无害警告：
        # "Workbook contains no default style, apply openpyxl's default"
        warnings.simplefilter("ignore", UserWarning)
        workbook = load_workbook(xlsx_file)
    try:
        sheet = workbook.active
        if sheet is None:
            return stock_codes
        for row in sheet.iter_rows(min_row=2, values_only=True):
            if len(row) < 2 or row[1] is None:
                continue
            code = str(row[1]).strip()
            if code.endswith(".0"):
                code = code[:-2]
            if not code.isdigit() or len(code) != 6:
                continue
            code = f"{code}.SH" if code.startswith("6") else f"{code}.SZ"
            if code not in seen:
                seen.add(code)
                stock_codes.append(code)
    finally:
        workbook.close()
    return stock_codes

def IS_TOP(stock_code: str, trading_date: str):
    # 主进程：使用模块级普通 dict
    stock_set = _TOP_CACHE.get(trading_date)
    if stock_set is not None:
        return stock_code in stock_set
    # worker 进程：使用 Manager.dict 代理（通过 initializer 注入）
    if _WORKER_TOP_CACHE is not None:
        stock_set = _WORKER_TOP_CACHE.get(trading_date)
        if stock_set is not None:
            return stock_code in stock_set
    # 缓存未填充时，回退到文件读取（兜底）
    top_file = f"{PATH_AIDATA_TOP()}/{trading_date}"
    if not os.path.exists(top_file):
        return False
    with open(top_file, "r") as file:
        for line in file:
            if line.strip() == stock_code:
                return True
    return False

if __name__ == "__main__":
    UPDATE_TOP()
