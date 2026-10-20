"""M5_DATA —— 5 分钟 K 线数据的读取与解析技能。

把 5min 数据格式、路径、常用计算固化在这里，避免每次重复摸索。

数据位置
--------
- 5 分钟 K 线: ``AIData/5M/{code}.SH`` / ``AIData/5M/{code}.SZ``
  （code 形如 600000.SH / 000001.SZ；文件按股票単位，含该股票全部历史交易日）

每行格式（``|`` 分隔）
----------------------
    datetime|open|high|low|close|volume|amount|pre_close|ma5|ma10|ma20|ma30|ma60|ma120
  - datetime : "YYYY-MM-DD HH:MM:SS"（首根 09:35:00，末根 15:00:00）
  - open/high/low/close : float
  - volume  : 成交量（股）
  - amount  : 成交额（元，万/亿单位依数据源）
  - pre_close: 昨收（用于算涨跌幅）
  - ma5..ma120: 移动均线（部分行可能为空或 0.0）

交易日历与口径
--------------
- 交易日历: ``AIData/TRADING_DATES``（每行 YYYYMMDD，升序）
- 目标股列表: ``AIData/TARGET/TPO_M5/{YYYYMMDD}``（每行 ``code|name|market_value``）

关键约定
--------
- 每天 **48 根** 5 分钟 K 线：上午 09:35–11:30 共 24 根，下午 13:05–15:00 共 24 根（午休 11:30–13:00）。
- ``Bar.index`` 为该根在**当日**内的 1-based 序号（1..48），由文件出现顺序推算，与 chronological 顺序一致。
- ``Bar.date`` 为 "YYYY-MM-DD"；与日历/目标股目录的 "YYYYMMDD" 互转见 ``date_window`` / ``hl_positions``。
"""
import os
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


def _find_root() -> str:
    """向上查找含 AIData 目录的项目根（与包嵌套深度无关）。"""
    d = os.path.dirname(os.path.abspath(__file__))
    while d and d != os.path.dirname(d):
        if os.path.isdir(os.path.join(d, "AIData")):
            return d
        d = os.path.dirname(d)
    return d


_ROOT = _find_root()
FIVE_M_DIR = os.path.join(_ROOT, "AIData", "5M")
TRADING_DATES_FILE = os.path.join(_ROOT, "AIData", "TRADING_DATES")
TARGET_TPO_M5_DIR = os.path.join(_ROOT, "AIData", "TARGET", "TPO_M5")


@dataclass
class Bar:
    """一根 5 分钟 K 线。"""

    datetime: str       # "2026-09-30 09:35:00"
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float
    pre_close: float
    index: int          # 1-based 序号（当日内）

    @property
    def date(self) -> str:
        return self.datetime.split(" ")[0]            # "2026-09-30"

    @property
    def time(self) -> str:
        return self.datetime.split(" ")[1]            # "09:35:00"

    @property
    def date_compact(self) -> str:
        return self.date.replace("-", "")             # "20260930"


def _to_float(s: str, default: float = 0.0) -> float:
    try:
        return float(s)
    except (ValueError, TypeError):
        return default


def _read_lines(path: str) -> List[str]:
    """按行读取文本，编码容错：先 utf-8，失败回退 gbk，再回退 latin-1。"""
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read().splitlines()
        except UnicodeDecodeError:
            continue
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read().splitlines()


def _resolve_path(code: str) -> str:
    """根据 code 解析 5M 文件路径；找不到时返回带 .SH 后缀的猜测路径。"""
    candidates = [code]
    if not code.endswith((".SH", ".SZ")):
        candidates += [code + ".SH", code + ".SZ"]
    for c in candidates:
        p = os.path.join(FIVE_M_DIR, c)
        if os.path.exists(p):
            return p
    return os.path.join(FIVE_M_DIR, candidates[-1])


def load_5m(code: str) -> Dict[str, List[Bar]]:
    """读取 ``AIData/5M/{code}`` 全部 5 分钟 K 线。

    返回 ``{ "YYYY-MM-DD": [Bar, ...] }``（按日期分组，组内按时间升序，index 1..N）。
    code 可带或不带 .SH/.SZ 后缀。文件不存在返回空 dict。
    """
    path = _resolve_path(code)
    by_date: Dict[str, List[Bar]] = {}
    if not os.path.exists(path):
        return by_date
    cur_date: Optional[str] = None
    idx_in_day = 0
    for line in _read_lines(path):
            line = line.strip()
            if not line:
                continue
            parts = line.split("|")
            if len(parts) < 7:
                continue
            dt = parts[0]
            d = dt.split(" ")[0] if " " in dt else dt
            if d != cur_date:
                cur_date = d
                idx_in_day = 0
            idx_in_day += 1
            by_date.setdefault(d, []).append(
                Bar(
                    datetime=dt,
                    open=_to_float(parts[1]),
                    high=_to_float(parts[2]),
                    low=_to_float(parts[3]),
                    close=_to_float(parts[4]),
                    volume=_to_float(parts[5]),
                    amount=_to_float(parts[6]),
                    pre_close=_to_float(parts[7]) if len(parts) > 7 else 0.0,
                    index=idx_in_day,
                )
            )
    return by_date


def trading_dates() -> List[str]:
    """返回交易日历 [YYYYMMDD, ...]（升序）。"""
    out: List[str] = []
    if os.path.exists(TRADING_DATES_FILE):
        with open(TRADING_DATES_FILE, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(line)
    return out


def date_window(t0: str, n: int = 5, clamp: bool = False) -> List[str]:
    """返回以 ``t0`` 结尾的连续 n 个交易日 [T-(n-1) .. T-0]。

    ``t0`` 接受 "YYYYMMDD" 或 "YYYY-MM-DD"。
    ``clamp=False``（默认）：若 t0 之前不足 n 个交易日则抛 ValueError；
    ``clamp=True``：不足时返回从首个交易日起到 t0 的可用窗口（至少含 t0）。
    """
    t0c = t0.replace("-", "")
    dates = trading_dates()
    if t0c not in dates:
        raise ValueError(f"t0={t0} 不在交易日历中")
    i = dates.index(t0c)
    start = i - n + 1
    if start < 0:
        if not clamp:
            raise ValueError(f"t0={t0} 之前不足 {n} 个交易日")
        start = 0
    return dates[start: i + 1]


def target_stocks(t0: str) -> List[Tuple[str, str, str]]:
    """返回 ``AIData/TARGET/TPO_M5/{t0}`` 的目标股列表 [(code, name, market_value), ...]。

    ``t0`` 接受 "YYYYMMDD" 或 "YYYY-MM-DD"。文件不存在返回空列表。
    """
    t0c = t0.replace("-", "")
    path = os.path.join(TARGET_TPO_M5_DIR, t0c)
    out: List[Tuple[str, str, str]] = []
    if not os.path.exists(path):
        return out
    for line in _read_lines(path):
        p = line.rstrip("\n").split("|")
        if p and p[0].strip():
                code = p[0].strip()
                name = p[1].strip() if len(p) > 1 else ""
                mv = p[2].strip() if len(p) > 2 else ""
                out.append((code, name, mv))
    return out


def first_high(bars: List[Bar]) -> Optional[Bar]:
    """返回当日**首次**触达最高价的 K 线（index 最小者）。空列表返回 None。"""
    if not bars:
        return None
    m = max(b.high for b in bars)
    for b in bars:
        if b.high == m:
            return b
    return None


def last_low(bars: List[Bar]) -> Optional[Bar]:
    """返回当日**末次**触达最低价的 K 线（index 最大者）。空列表返回 None。"""
    if not bars:
        return None
    m = min(b.low for b in bars)
    for b in reversed(bars):
        if b.low == m:
            return b
    return None


def hl_positions(code: str, dates: List[str]) -> Dict[str, dict]:
    """对 ``code`` 在 ``dates``（YYYYMMDD 列表）各日，提取：

    - 首次最高价的 K 线位置（first_high_index / first_high_time / first_high_price）
    - 末次最低价的 K 线位置（last_low_index / last_low_time / last_low_price）
    - bar_count：当日实际 K 线数

    返回 ``{ YYYYMMDD: {...} }``。某日无数据则对应字段为 None。
    """
    data = load_5m(code)
    out: Dict[str, dict] = {}
    for d in dates:
        dd = d[:4] + "-" + d[4:6] + "-" + d[6:]   # YYYYMMDD -> YYYY-MM-DD
        bars = data.get(dd, [])
        fh = first_high(bars)
        ll = last_low(bars)
        out[d] = {
            "first_high_index": fh.index if fh else None,
            "first_high_time": fh.time if fh else None,
            "first_high_price": fh.high if fh else None,
            "last_low_index": ll.index if ll else None,
            "last_low_time": ll.time if ll else None,
            "last_low_price": ll.low if ll else None,
            "bar_count": len(bars),
        }
    return out


def write_hl_file(t0: str, out_dir: Optional[str] = None, clamp: bool = False) -> str:
    """提取 ``t0``（YYYYMMDD）的 T-4..T-0 每日首次最高价/末次最低价位置并落盘。

    输出: ``{out_dir}/{t0}``，每行一只目标股；列 = code|name | 随后每个交易日(早->晚)的
        ``{date}_firstHighIdx|{date}_firstHighTime|{date}_firstHighPrice
         |{date}_lastLowIdx|{date}_lastLowTime|{date}_lastLowPrice``

    ``out_dir`` 默认 ``AIData/TARGET_5M/TPO_M5``；``clamp=True`` 时前置交易日不足 5 天
    自动取可用窗口。返回输出文件绝对路径（供管道/CLI 共用）。
    """
    dates = date_window(t0, 5, clamp=clamp)
    stocks = target_stocks(t0)
    if out_dir is None:
        out_dir = os.path.join(os.path.dirname(FIVE_M_DIR), "TARGET_5M", "TPO_M5")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, t0)

    header = ["code", "name"]
    for d in dates:
        header += [f"{d}_firstHighIdx", f"{d}_firstHighTime", f"{d}_firstHighPrice",
                   f"{d}_lastLowIdx", f"{d}_lastLowTime", f"{d}_lastLowPrice"]

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("# T-0=%s  窗口=%s\n" % (t0, ",".join(dates)))
        f.write("|".join(header) + "\n")
        for code, name, _mv in stocks:
            pos = hl_positions(code, dates)
            row = [code, name]
            for d in dates:
                v = pos.get(d, {})
                row += [
                    str(v.get("first_high_index") or ""),
                    str(v.get("first_high_time") or ""),
                    str(v.get("first_high_price") or ""),
                    str(v.get("last_low_index") or ""),
                    str(v.get("last_low_time") or ""),
                    str(v.get("last_low_price") or ""),
                ]
            f.write("|".join(row) + "\n")
    return out_path


def list_target_dates() -> List[str]:
    """返回 TARGET/TPO_M5 下已有的目标股日期列表（YYYYMMDD，升序）。"""
    if not os.path.isdir(TARGET_TPO_M5_DIR):
        return []
    return sorted(
        p for p in os.listdir(TARGET_TPO_M5_DIR)
        if os.path.isfile(os.path.join(TARGET_TPO_M5_DIR, p))
    )


def update_tpo_m5_hl_all(out_dir: Optional[str] = None) -> str:
    """批量解析所有目标股日期（TARGET/TPO_M5 下全部日期）的 T-4..T-0 首高/末低位置。

    每个日期写出一份 ``{out_dir}/{date}``（与单日 write_hl_file 同格式）。
    最早几个日期若不足 5 个前置交易日，自动按 clamp 取可用窗口。返回摘要字符串。
    """
    dates = list_target_dates()
    if not dates:
        return "TPO_M5_HL_ALL: 无目标股日期"
    dst = out_dir or os.path.join(os.path.dirname(FIVE_M_DIR), "TARGET_5M", "TPO_M5")
    ok = 0
    skipped = 0
    for d in dates:
        try:
            write_hl_file(d, out_dir=out_dir, clamp=True)
            ok += 1
        except BaseException as exc:  # 单日失败不影响其余日期
            skipped += 1
            print(f"  [TPO_M5_HL skip {d}] {type(exc).__name__}: {exc}", file=sys.stderr)
    return f"TPO_M5_HL_ALL: 完成 {ok}/{len(dates)} 个日期 (跳过 {skipped}) -> {dst}"


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print("ROOT        :", _ROOT)
    print("FIVE_M_DIR  :", FIVE_M_DIR)
    print("dates count :", len(trading_dates()))

    code = "600000.SH"
    data = load_5m(code)
    print(f"\n[{code}] 交易日数={len(data)}")
    sample_date = "2026-09-30"
    bars = data.get(sample_date, [])
    print(f"  {sample_date}: 根数={len(bars)}  首根={bars[0].time} 末根={bars[-1].time}  index范围={bars[0].index}..{bars[-1].index}")
    fh, ll = first_high(bars), last_low(bars)
    print(f"  首次最高价: idx={fh.index} time={fh.time} high={fh.high}")
    print(f"  末次最低价: idx={ll.index} time={ll.time} low={ll.low}")

    t0 = "20260930"
    wk = date_window(t0, 5)
    print(f"\nT-0={t0} 窗口={wk}")
    targets = target_stocks(t0)
    print(f"目标股数={len(targets)}: {[t[0] for t in targets]}")
    for c, name, _mv in targets:
        pos = hl_positions(c, wk)
        print(f"  {c} {name}:")
        for d, v in pos.items():
            print(f"    {d}: 首高#{v['first_high_index']}@{v['first_high_time']} "
                  f"末低#{v['last_low_index']}@{v['last_low_time']} (bars={v['bar_count']})")
