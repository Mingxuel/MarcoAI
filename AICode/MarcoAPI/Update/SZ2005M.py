"""
5 分钟线（5M）数据处理模块

====================================================
一、数据流（参照 1D 的下载方式）
====================================================
  通达信接口 ──UPDATE_5M_ORIGIN──▶ 5M（原始前复权 5 分钟线）
  说明:
    - 5M 由 UPDATE_5M_ORIGIN 维护（原始数据，每次删除旧数据后重建）

====================================================
二、存储文件
====================================================
  MarcoAI/AIData/5M/CODE        原始前复权 5 分钟线（每只股票一个文件）
      每行: time|open|high|low|close|volume|amount
        time 形如 2025-01-02 09:35:00（含日期与时分秒）

====================================================
三、API 说明
====================================================
  UPDATE_5M_ORIGIN(stock_codes=None) -> str
      从通达信拉取全股票前复权原始 5 分钟线，删除 5M 旧数据后重建。
      stock_codes 为 None 时取 STOCK_CODES()（全市场）。

  GET_SZ200_5M(stock_code) -> list[DATA_5M]
      读取单只股票全部 5M 数据（优先缓存，兜底读文件），按时间升序。

  GET_SZ200_5M_ALL() -> dict[str, list[DATA_5M]]
      加载全部股票 5M 到缓存并返回 {股票代码: [DATA_5M, ...]}。

  GET_SZ200_5M_RANGE(stock_code, start_time, end_time) -> list[DATA_5M]
      返回时间落在 [start_time, end_time] 闭区间内的 5M 数据（字符串比较，YYYY-MM-DD HH:MM:SS）。
"""

from concurrent.futures import ProcessPoolExecutor, as_completed
import os
import sys
import pandas as pd
from tqdm import tqdm

_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _root not in sys.path:
    sys.path.insert(0, _root)
from AICode.MarcoAPI.Update.Constants import *
from AICode.MarcoAPI.Update.StockCodes import *
from AICode.MarcoAPI.Update.Path import *
from AICode.MarcoAPI.Update.Data import DATA_5M
from AICode.MarcoAPI.Update.SZ2001D import _rotate_dir

_SZ200_5M_ALL_CACHE: dict[str, list[DATA_5M]] = {}


def _PARSE_DATA_5M(line: str) -> DATA_5M:
    """解析 5M 文件一行 time|open|high|low|close|volume|amount"""
    parts = line.strip().split("|")
    return DATA_5M(
        time=parts[0],
        open=float(parts[1]),
        high=float(parts[2]),
        low=float(parts[3]),
        close=float(parts[4]),
        volume=float(parts[5]),
        amount=float(parts[6]),
    )


def _WRITE_5M_BATCH(data: dict[str, pd.DataFrame], stock_codes: list[str]) -> list[str]:
    """worker: 把 data（已切片为本批股票）中每只股票的 5M 数据写出到 5M 目录。

    对应 1D 的 GENERATE_1D_ORIGIN，仅负责逐股票写原始 7 列文件，返回成功写入的代码列表。
    worker 内不连通达信，只做文件写出，故可安全放入进程池并行。
    """
    written: list[str] = []
    open_df = data["Open"]
    for stock_code in stock_codes:
        if stock_code not in open_df.columns:
            continue
        o = data["Open"][stock_code]
        h = data["High"][stock_code]
        l = data["Low"][stock_code]
        c = data["Close"][stock_code]
        v = data["Volume"][stock_code]
        a = data["Amount"][stock_code]
        with open(f"{PATH_AIDATA_5M()}/{stock_code}", "w") as file:
            # o.index 为 datetime（各字段共享同一索引）；按行写出，跳过空值（停牌）
            for dt, ov, hv, lv, cv, vv, av in zip(
                o.index, o.values, h.values, l.values, c.values, v.values, a.values
            ):
                if pd.isna(ov):
                    continue
                _time = str(dt)  # pd.Timestamp -> "2026-01-05 09:35:00"
                file.write(f"{_time}|{ov}|{hv}|{lv}|{cv}|{vv}|{av}\n")
        written.append(stock_code)
    return written


def UPDATE_5M_ORIGIN(stock_codes: list[str] | None = None) -> str:
    """拉取原始前复权 5 分钟线：父进程单批拉取全市场数据，再分片多进程写出（同 1D 模式）。

    数据为原始行情（time|open|high|low|close|volume|amount），不计算任何加工字段。

    多进程并行的是"写出文件"这一步（每只股票独立成文件），tqcenter 仅在父进程初始化一次；
    全量 data 按股票分批切片后交给进程池，避免把整份数据重复 pickle 给每个任务。

    tqcenter 在 period='5m' 时返回 dict（而非 1D 的 DataFrame）：
        {field: DataFrame[index=datetime, columns=stock_codes], ...}
    """
    _rotate_dir(PATH_AIDATA_5M())

    if stock_codes is None:
        stock_codes = STOCK_CODES()

    sys.path.append(PATH_TDX())  # 确保 tqcenter 模块所在目录在 sys.path 中
    from tqcenter import tq  # 仅在离线更新时惰性导入，避免实盘加载本模块时触碰通达信
    tq.initialize(__file__)
    data = tq.get_market_data(
        field_list=["Open", "High", "Low", "Close", "Volume", "Amount"],
        stock_list=stock_codes, start_time=START_DATE, end_time="", count=-1,
        dividend_type="front", period="5m", fill_data=False,
    )
    _SZ200_5M_ALL_CACHE.clear()
    if not data or "Open" not in data:
        return "5M_ORIGIN: 无数据返回（请检查通达信连接）"

    # 按批次切片，交给进程池并行写出（仅切片后的子 dict 会被 pickle 给 worker）
    batch_size = 50
    open_cols = set(data["Open"].columns)
    batches = [
        [c for c in stock_codes[i:i + batch_size] if c in open_cols]
        for i in range(0, len(stock_codes), batch_size)
    ]
    batches = [b for b in batches if b]
    done = 0
    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as pool:
        future_to_batch = {
            pool.submit(_WRITE_5M_BATCH, {k: data[k][batch] for k in data}, batch): batch
            for batch in batches
        }
        with tqdm(total=len(future_to_batch), desc="5M_ORIGIN", ncols=90) as bar:
            for fut in as_completed(future_to_batch):
                try:
                    done += len(fut.result())
                except BaseException as exc:
                    print(f"  [5M batch FAILED] {type(exc).__name__}: {exc}")
                bar.update(1)
    return f"5M_ORIGIN: 完成 {done}/{len(stock_codes)} 只股票"


def GET_SZ200_5M(stock_code: str) -> list[DATA_5M]:
    """读取单只股票全部 5M 数据（优先缓存，兜底读文件），按时间升序返回。"""
    if stock_code in _SZ200_5M_ALL_CACHE:
        return _SZ200_5M_ALL_CACHE[stock_code]
    path = f"{PATH_AIDATA_5M()}/{stock_code}"
    if not os.path.exists(path):
        return []
    result: list[DATA_5M] = []
    with open(path, "r") as file:
        for line in file:
            if line.strip():
                result.append(_PARSE_DATA_5M(line))
    _SZ200_5M_ALL_CACHE[stock_code] = result
    return result


def GET_SZ200_5M_ALL() -> dict[str, list[DATA_5M]]:
    """加载全部股票 5M 到缓存并返回 {股票代码: [DATA_5M, ...]}。"""
    if not _SZ200_5M_ALL_CACHE:
        for stock_code in STOCK_CODES():
            GET_SZ200_5M(stock_code)
    return _SZ200_5M_ALL_CACHE


def GET_SZ200_5M_RANGE(stock_code: str, start_time: str, end_time: str) -> list[DATA_5M]:
    """返回时间落在 [start_time, end_time] 闭区间内的 5M 数据（字符串比较，格式 YYYY-MM-DD HH:MM:SS）。"""
    return [d for d in GET_SZ200_5M(stock_code) if start_time <= d.time <= end_time]


if __name__ == "__main__":
    print(UPDATE_5M_ORIGIN())
