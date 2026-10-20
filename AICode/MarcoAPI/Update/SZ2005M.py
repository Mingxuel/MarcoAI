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
  MarcoAI/AIData/5M/CODE        前复权 5 分钟线（每只股票一个文件）
      每行: time|open|high|low|close|volume|amount|ma5|ma10|ma20|ma30|ma60|ma120
        time 形如 2025-01-02 09:35:00（含日期与时分秒）
        ma* 为收盘价 N 根 5 分钟 K 线均价（需满 N 根，不足为 0.00），与 1D 均线口径一致

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
import datetime
import os
import sys
import pandas as pd
from .progress import ProgressBar as tqdm

_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _root not in sys.path:
    sys.path.insert(0, _root)
from AICode.MarcoAPI.Update.Constants import *
from AICode.MarcoAPI.Update.StockCodes import *
from AICode.MarcoAPI.Update.Path import *
from AICode.MarcoAPI.Update.Data import DATA_5M
from AICode.MarcoAPI.Update.SZ2001D import _rotate_dir, _MA_PERIODS


def _round_ma(value: float) -> float:
    """价格四舍五入到分（两位），两步 ROUND_HALF_UP（先3位再2位），与 1D 的 _ROUND_PRICE 口径一致。"""
    d = int(value * 1000 + 0.5) / 1000.0
    return int(d * 100 + 0.5) / 100.0

_SZ200_5M_ALL_CACHE: dict[str, list[DATA_5M]] = {}


def _PARSE_DATA_5M(line: str) -> DATA_5M:
    """解析 5M 文件一行 time|open|high|low|close|volume|amount|ma5|ma10|ma20|ma30|ma60|ma120"""
    parts = line.strip().split("|")
    return DATA_5M(
        time=parts[0],
        open=float(parts[1]),
        high=float(parts[2]),
        low=float(parts[3]),
        close=float(parts[4]),
        volume=float(parts[5]),
        amount=float(parts[6]),
        ma5=float(parts[7]) if len(parts) > 7 else 0.0,
        ma10=float(parts[8]) if len(parts) > 8 else 0.0,
        ma20=float(parts[9]) if len(parts) > 9 else 0.0,
        ma30=float(parts[10]) if len(parts) > 10 else 0.0,
        ma60=float(parts[11]) if len(parts) > 11 else 0.0,
        ma120=float(parts[12]) if len(parts) > 12 else 0.0,
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
        # 先收集非停牌（非 NaN）的 5M 棒，保证 MA 窗口基于连续真实成交棒（与 1D 一致）
        rows: list[tuple] = []
        for dt, ov, hv, lv, cv, vv, av in zip(
            o.index, o.values, h.values, l.values, c.values, v.values, a.values
        ):
            if pd.isna(ov):
                continue
            rows.append((str(dt), ov, hv, lv, cv, vv, av))
        closes = [r[4] for r in rows]
        n = len(closes)
        # 各周期 MA = 收盘价 N 根 5 分钟 K 线滑动均价，需满 N 根才计算，不足为 0.00
        ma: dict[int, list[float]] = {p: [0.0] * n for p in _MA_PERIODS}
        for p in _MA_PERIODS:
            run = 0.0
            for i in range(n):
                run += closes[i]
                if i >= p:
                    run -= closes[i - p]
                if i >= p - 1:
                    ma[p][i] = _round_ma(run / p)
        with open(f"{PATH_AIDATA_5M()}/{stock_code}", "w") as file:
            for i, r in enumerate(rows):
                ma_str = "|".join(f"{ma[p][i]:.2f}" for p in _MA_PERIODS)
                file.write(f"{r[0]}|{r[1]}|{r[2]}|{r[3]}|{r[4]}|{r[5]}|{r[6]}|{ma_str}\n")
        written.append(stock_code)
    return written


def UPDATE_5M_ORIGIN(stock_codes: list[str] | None = None, recent_days: int = 0, start_date: str = '20260101') -> str:
    """拉取原始前复权 5 分钟线：父进程单批拉取数据，再分片多进程写出（同 1D 模式）。

    数据为前复权行情，并在写出时追加 MA5/10/20/30/60/120 均线（收盘价 N 根 5 分钟 K 线均价），与 1D 加工口径一致。

    多进程并行的是"写出文件"这一步（每只股票独立成文件），tqcenter 仅在父进程初始化一次；
    全量 data 按股票分批切片后交给进程池，避免把整份数据重复 pickle 给每个任务。

    tqcenter 在 period='5m' 时返回 dict（而非 1D 的 DataFrame）：
        {field: DataFrame[index=datetime, columns=stock_codes], ...}

    recent_days>0 时只下载「最近 recent_days 个交易日」的 5M（UI/回测实际只用到约 8 个交易日窗口，
    见 StrategyUI._read_5m_window）。前复权由 tqcenter 按下载当天基准算好；每次先 _rotate_dir 丢弃旧文件
    再重拉，保证所有 5M 文件前复权基准一致（无历史混合导致的对齐问题）。默认 recent_days=0 为全历史（兼容旧行为）。
    """
    _rotate_dir(PATH_AIDATA_5M())

    if stock_codes is None:
        stock_codes = STOCK_CODES()
    stock_codes = list(stock_codes)  # 兼容 set 入参；下方按切片分批需要可索引序列

    # 前复权基准以"下载当天"为准；recent_days>0 时只拉最近一段，大幅缩减下载量
    if recent_days and recent_days > 0:
        start_time = (datetime.date.today() - datetime.timedelta(days=int(recent_days) * 2 + 7)).strftime("%Y%m%d")
    else:
        start_time = start_date   # 5M 仅从 2026-01-01 起（解决早期 5 分钟不显示、并减小体积）；如需全历史可传 START_DATE

    sys.path.append(PATH_TDX())  # 确保 tqcenter 模块所在目录在 sys.path 中
    from tqcenter import tq  # 仅在离线更新时惰性导入，避免实盘加载本模块时触碰通达信
    tq.initialize(__file__)
    data = tq.get_market_data(
        field_list=["Open", "High", "Low", "Close", "Volume", "Amount"],
        stock_list=stock_codes, start_time=start_time, end_time="", count=-1,
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
        with tqdm(total=len(future_to_batch), desc="5M_ORIGIN", ncols=90, disable=False) as bar:
            for fut in as_completed(future_to_batch):
                try:
                    done += len(fut.result())
                except BaseException as exc:
                    print(f"  [5M batch FAILED] {type(exc).__name__}: {exc}")
                bar.update(1)
    return f"5M_ORIGIN: 完成 {done}/{len(stock_codes)} 只股票"


def _write_5m_one(stock_code: str, rows: list) -> str:
    """把单只股票的 5M 棒（[(time,o,h,l,c,v,a)...]）去重排序、算 MA、写出到 5M 目录。"""
    seen = set()
    uniq = []
    for r in sorted(rows, key=lambda x: x[0]):
        if r[0] in seen:
            continue
        seen.add(r[0])
        uniq.append(r)
    n = len(uniq)
    if n == 0:
        return stock_code
    closes = [r[4] for r in uniq]
    ma = {p: [0.0] * n for p in _MA_PERIODS}
    for p in _MA_PERIODS:
        run = 0.0
        for i in range(n):
            run += closes[i]
            if i >= p:
                run -= closes[i - p]
            if i >= p - 1:
                ma[p][i] = _round_ma(run / p)
    with open(f"{PATH_AIDATA_5M()}/{stock_code}", "w") as file:
        for i, r in enumerate(uniq):
            ma_str = "|".join(f"{ma[p][i]:.2f}" for p in _MA_PERIODS)
            file.write(f"{r[0]}|{r[1]}|{r[2]}|{r[3]}|{r[4]}|{r[5]}|{r[6]}|{ma_str}\n")
    return stock_code


def UPDATE_5M_PANELS() -> str:
    """仅下载「首板相关面板」涉及股票的 5 分钟行情，且每只股只下其关键日（首板/涨停日）附近的
    T-2~T+5 窗口（约 8 个交易日），而非整段 2026 全年——下载量再降约两个数量级。

    涉及股票与关键日来自：AIData/TOP_FIRST、TOP_FIRST_VOL、TOP_FIRST_VOL_SUN、TOP（首板/涨停），
    以及 AIData/TARGET 各策略目录（候选池 / 策略详情）各日期文件。
    前复权以「下载当天」为基准；本函数整批同日下载 + _rotate_dir 重建，保证所有 5M 前复权一致。
    """
    from .Path import (PATH_AIDATA_TOP_FIRST, PATH_AIDATA_TOP_FIRST_VOL,
                       PATH_AIDATA_TOP_FIRST_VOL_SUN, PATH_AIDATA_TOP,
                       PATH_AIDATA_TARGET)
    import os
    from collections import defaultdict
    dirs = [PATH_AIDATA_TOP_FIRST(), PATH_AIDATA_TOP_FIRST_VOL(),
            PATH_AIDATA_TOP_FIRST_VOL_SUN(), PATH_AIDATA_TOP()]
    code_anchors: dict[str, set] = defaultdict(set)
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            fp = os.path.join(d, fn)
            if not os.path.isfile(fp):
                continue
            date8 = fn.replace('-', '').replace('.', '')[:8]
            try:
                anchor = datetime.datetime.strptime(date8, '%Y%m%d').date()
            except Exception:
                continue
            try:
                with open(fp, encoding='utf-8', errors='ignore') as f:
                    for line in f:
                        parts = line.split()
                        if not parts:
                            continue
                        code = parts[0]
                        if code.endswith(('.SZ', '.SH')):
                            code_anchors[code].add(anchor)
            except Exception:
                continue
    # 候选池 / 策略详情（同源：AIData/TARGET/<策略名>，code 带后缀，锚定日 = 文件名日期）
    target_base = PATH_AIDATA_TARGET()
    if os.path.isdir(target_base):
        for sub in os.listdir(target_base):
            if sub.endswith('_RATIO'):
                continue
            subdir = os.path.join(target_base, sub)
            if not os.path.isdir(subdir):
                continue
            for fn in os.listdir(subdir):
                fp = os.path.join(subdir, fn)
                if not os.path.isfile(fp):
                    continue
                date8 = fn.replace('-', '').replace('.', '')[:8]
                try:
                    anchor = datetime.datetime.strptime(date8, '%Y%m%d').date()
                except Exception:
                    continue
                try:
                    with open(fp, encoding='utf-8', errors='ignore') as f:
                        for line in f:
                            parts = line.replace('|', ' ').split()
                            if not parts:
                                continue
                            code = parts[0]
                            if code.endswith(('.SZ', '.SH')):
                                code_anchors[code].add(anchor)
                except Exception:
                    continue
    if not code_anchors:
        return "UPDATE_5M_PANELS: 未收集到涉及股票（请先更新 TOP / TOP_FIRST / TARGET 等数据）"
    _rotate_dir(PATH_AIDATA_5M())
    sys.path.append(PATH_TDX())
    from tqcenter import tq
    tq.initialize(__file__)
    # 按关键日分组下载（同关键日的多股一次请求），逐股累积其所有窗口的 5M 棒
    anchor_groups: dict = defaultdict(list)
    for code, anchors in code_anchors.items():
        for a in anchors:
            anchor_groups[a].append(code)
    all_rows: dict[str, list] = defaultdict(list)
    field_list = ["Open", "High", "Low", "Close", "Volume", "Amount"]
    bar = tqdm(total=len(anchor_groups), desc="5M下载", file=sys.stderr)
    for a, codes_a in anchor_groups.items():
        bar.update(1)
        start_t = (a - datetime.timedelta(days=5)).strftime('%Y%m%d')
        end_t = (a + datetime.timedelta(days=7)).strftime('%Y%m%d')
        try:
            data = tq.get_market_data(field_list=field_list, stock_list=codes_a,
                                      start_time=start_t, end_time=end_t, count=-1,
                                      dividend_type='front', period='5m', fill_data=False)
        except BaseException as exc:
            print(f"  [5M anchor {a} FAILED] {type(exc).__name__}: {exc}")
            continue
        if not data or "Open" not in data:
            continue
        open_df = data["Open"]
        for code in codes_a:
            if code not in open_df.columns:
                continue
            o = open_df[code]; h = data["High"][code]; l = data["Low"][code]
            c = data["Close"][code]; v = data["Volume"][code]; am = data["Amount"][code]
            for dt, ov, hv, lv, cv, vv, av in zip(
                o.index, o.values, h.values, l.values, c.values, v.values, am.values
            ):
                if pd.isna(ov):
                    continue
                all_rows[code].append((str(dt), float(ov), float(hv), float(lv),
                                       float(cv), float(vv), float(av)))
    bar.close()
    # 逐股合并所有窗口、去重排序、算 MA、写文件
    done = 0
    for code, rows in all_rows.items():
        if not rows:
            continue
        _write_5m_one(code, rows)
        done += 1
    return f"5M_PANELS: 完成 {done}/{len(code_anchors)} 只股票（逐股按关键日 T-2~T+5 窗口下载）"


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
