#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""5m ↔ 1D 数据对齐校验（一条龙 UPDATE_5M_ORIGIN 之后自动调用）。

背景
----
通达信本地 vipdoc 的 5m/lday 存**原始价**，而 AIData/1D（及策略文件）存**前复权价**；
两者直接混用会产生复权偏差（回测虚高 / K 线日均线错位）。本工具做两类校验：

A. 5m ↔ 1D 对齐（AIData/5M 对 AIData/1D）
   - 5m 按日聚合出原始日线收盘（每日最后一根 5m close）→ raw 日线序列；
   - 与 1D 前复权日线按日期对齐（取共同日期），factor(date) = 1D_close / raw_close；
   - 每票取最新交易日 factor 作为当前复权因子，统计 samples / maxDev；
   - 除权日 factor 会突变，允许 ≤2 天突变；其余日偏差应 <0.5%，否则 warning
     （可能 5m 缺 bar / 数据源不一致）。

B. 1D 前复权校验（通达信本地原始日线 vipdoc/lday 对 AIData/1D）
   - factor(date) = 1D_close / raw_lday_close；
   - latestFactor 应 ≈1.0（前复权基准=最新交易日，允许 0.5%，否则 warning「1D 基准不是最新交易日」）；
   - 前复权 factor 应随日期**单调不减**（阶梯上升；允许 0.5% 容差以吸收价格四舍五入噪声），
     出现下降即异常（nonMonotonic）；
   - factorAlwaysOne：全期 factor 恒为 1 的票（无除权；需人工抽查是否有“该复权未复权”）；
   - originSameAs1D：AIData/1D_ORIGIN 与 AIData/1D 是否逐日完全相同。相同则说明 1D_ORIGIN
     也是前复权数据、**不能**作为原始价交叉验证（必须用 vipdoc/lday）。

输出：AIData/5M_ALIGN/alignment.json（UTF-8，原子写）
{
  "generatedAt", "asOf",
  "stocks": {code: {factor, samples, maxDev, status, lastDate}},
  "warnings": [{code, date, dev}],
  "summary": {total, ok, warning},
  "validation_1d": {
      "stocks": {code: {latestFactor, latestDate, samples, nonMonotonic, factorAlwaysOne, originSameAs1D, status}},
      "factorAlwaysOne": {count, codes},
      "originSameAs1D": {allSame, same, diff, diffCodes, note},
      "summary_1d": {total, latest_ok, warnings}
  }
}

用法：
    python tools/align_5m_1d.py              # 校验并写 alignment.json
    python tools/align_5m_1d.py --dry-run    # 只打印，不写文件
    python tools/align_5m_1d.py --limit 5    # 只处理前 N 只（调试）

退出码：0 成功（含 warning）；2 无输入数据；3 写入失败。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AIDATA = os.path.join(ROOT, "AIData")
DIR_5M = os.path.join(AIDATA, "5M")
DIR_1D = os.path.join(AIDATA, "1D")
DIR_1D_ORIGIN = os.path.join(AIDATA, "1D_ORIGIN")
OUT_DIR = os.path.join(AIDATA, "5M_ALIGN")
OUT_FILE = os.path.join(OUT_DIR, "alignment.json")

TDX_PLUGIN_DIR = os.environ.get("TDX_PLUGIN_PATH", r"C:\new_tdx64\PYPlugins\user")
# C:\new_tdx64\PYPlugins\user -> C:\new_tdx64 -> vipdoc
VIPDOC = os.path.join(os.path.dirname(os.path.dirname(TDX_PLUGIN_DIR)), "vipdoc")

TOL_PCT = 0.5          # 允许偏差 0.5%
MAX_JUMP_DAYS = 2      # 除权突变允许 ≤2 天
CODE_RE = re.compile(r"^[0-9]{6}\.(SH|SZ|BJ)$")


def _round(value: float, nd: int = 6) -> float:
    return round(float(value), nd)


# ---------------------------------------------------------------- 数据读取
def read_1d_closes(path: str) -> dict[str, float] | None:
    """AIData/1D/<code>：date|open|high|low|close|... → {date: close}"""
    if not os.path.exists(path):
        return None
    out: dict[str, float] = {}
    with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
        for line in fh:
            parts = line.strip().split("|")
            if len(parts) > 4:
                try:
                    out[parts[0]] = float(parts[4])
                except ValueError:
                    continue
    return out


def read_1d_origin_rows(path: str) -> dict[str, tuple[str, ...]] | None:
    """AIData/1D_ORIGIN/<code>：date|open|high|low|close|volume|amount → {date: 7 列元组}"""
    if not os.path.exists(path):
        return None
    out: dict[str, tuple[str, ...]] = {}
    with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
        for line in fh:
            parts = line.strip().split("|")
            if len(parts) >= 7:
                out[parts[0]] = tuple(parts[:7])
    return out


def read_1d_rows(path: str) -> dict[str, tuple[str, ...]] | None:
    """AIData/1D/<code> 前 7 列（原始行情部分）→ {date: 7 列元组}，与 1D_ORIGIN 同口径比较。"""
    if not os.path.exists(path):
        return None
    out: dict[str, tuple[str, ...]] = {}
    with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
        for line in fh:
            parts = line.strip().split("|")
            if len(parts) >= 7:
                out[parts[0]] = tuple(parts[:7])
    return out


def read_5m_daily_close(path: str) -> dict[str, float] | None:
    """AIData/5M/<code>：time|open|high|low|close|... → {YYYYMMDD: 当日最后一根 5m close}"""
    if not os.path.exists(path):
        return None
    out: dict[str, float] = {}
    with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
        for line in fh:
            parts = line.strip().split("|")
            if len(parts) < 5:
                continue
            day = parts[0][:10].replace("-", "")
            if len(day) != 8:
                continue
            try:
                close = float(parts[4])
            except ValueError:
                continue
            out[day] = close  # 文件按时间升序，后者覆盖前者 = 当日最后一根
    return out


def lday_path(code: str) -> str:
    market = "sh" if code.upper().endswith(".SH") else "sz"
    number = code.split(".")[0]
    return os.path.join(VIPDOC, market, "lday", f"{market}{number}.day")


def read_lday_closes(code: str) -> dict[str, float] | None:
    """通达信原始日线 .day（32 字节/条）：date, open, high, low, close(int, /100), amount, volume, reserved"""
    path = lday_path(code)
    if not os.path.exists(path) or os.path.getsize(path) < 32:
        return None
    out: dict[str, float] = {}
    with open(path, "rb") as fh:
        while True:
            raw = fh.read(32)
            if len(raw) < 32:
                break
            try:
                date_int, _o, _h, _l, close_i, _amt, _vol, _res = struct.unpack("<IIIIIfII", raw)
            except struct.error:
                continue
            close = close_i / 100.0
            if close > 0:
                out[str(date_int)] = close
    return out


def _first7_equal(a: tuple[str, ...], b: tuple[str, ...]) -> bool:
    """比较 1D 与 1D_ORIGIN 行的前 7 列（按浮点近似，规避字符串格式差异）。"""
    if len(a) < 7 or len(b) < 7:
        return False
    for idx in range(7):
        try:
            if abs(float(a[idx]) - float(b[idx])) > 1e-6 * max(1.0, abs(float(a[idx]))):
                return False
        except (TypeError, ValueError):
            if a[idx] != b[idx]:
                return False
    return True


# ---------------------------------------------------------------- 对齐算法
def _factor_series(adjusted: dict[str, float], raw: dict[str, float]) -> list[tuple[str, float]]:
    """按共同日期升序返回 [(date, adjusted/raw), ...]。"""
    common = sorted(set(adjusted) & set(raw))
    out: list[tuple[str, float]] = []
    for day in common:
        raw_close = raw[day]
        if raw_close <= 0:
            continue
        out.append((day, adjusted[day] / raw_close))
    return out


def _align_5m_stock(code: str) -> dict | None:
    closes_1d = read_1d_closes(os.path.join(DIR_1D, code))
    raw_5m = read_5m_daily_close(os.path.join(DIR_5M, code))
    if not closes_1d or not raw_5m:
        return None
    series = _factor_series(closes_1d, raw_5m)
    if len(series) < 2:
        return None
    latest_date, latest_factor = series[-1]

    def dev_pct(f: float) -> float:
        return abs(f / latest_factor - 1.0) * 100.0

    devs = [(day, dev_pct(f)) for day, f in series]
    max_dev = max(d for _, d in devs)
    # 相邻日 factor 突变（除权日）：|f_i / f_{i-1} - 1| > 0.5%
    jump_days: list[str] = []
    for i in range(1, len(series)):
        if abs(series[i][1] / series[i - 1][1] - 1.0) * 100.0 > TOL_PCT:
            jump_days.append(series[i][0])
    # 孤立尖刺（5m 缺 bar / 数据源不一致）：该日 factor 与前后两天都不一致，而前后两天彼此一致
    spikes: list[str] = []
    for i in range(1, len(series) - 1):
        if devs[i][1] <= TOL_PCT:
            continue
        prev_f, cur_f, next_f = series[i - 1][1], series[i][1], series[i + 1][1]
        if abs(prev_f / cur_f - 1.0) * 100.0 > TOL_PCT and abs(next_f / cur_f - 1.0) * 100.0 > TOL_PCT \
                and abs(prev_f / next_f - 1.0) * 100.0 <= TOL_PCT:
            spikes.append(series[i][0])

    warning = len(jump_days) > MAX_JUMP_DAYS or bool(spikes)
    bad_dates = set(spikes)
    if warning:
        # 报警时列出偏差超阈值、且不是“除权突变”解释掉的日期
        for day, dev in devs[:-1]:
            if dev > TOL_PCT and day not in jump_days:
                bad_dates.add(day)
    return {
        "factor": _round(latest_factor),
        "samples": len(series),
        "maxDev": _round(max_dev, 4),
        "status": "warning" if warning else "ok",
        "lastDate": latest_date,
        "_warnings": [{"code": code, "date": day, "dev": _round(dev_pct(f), 4)}
                      for day, f in series if dev_pct(f) > TOL_PCT and day not in jump_days]
                     if warning else [],
    }


def _validate_1d_stock(code: str) -> dict | None:
    closes_1d = read_1d_closes(os.path.join(DIR_1D, code))
    raw_lday = read_lday_closes(code)
    if not closes_1d or not raw_lday:
        return None
    series = _factor_series(closes_1d, raw_lday)
    if len(series) < 2:
        return None
    latest_date, latest_factor = series[-1]
    latest_ok = abs(latest_factor - 1.0) * 100.0 <= TOL_PCT

    non_monotonic: list[str] = []
    for i in range(1, len(series)):
        # 前复权 factor 应随日期单调不减；下降超容差视为异常
        if (series[i][1] - series[i - 1][1]) / series[i - 1][1] * 100.0 < -TOL_PCT:
            non_monotonic.append(series[i][0])

    factor_always_one = all(abs(f - 1.0) <= 1e-6 for _, f in series)

    origin_rows = read_1d_origin_rows(os.path.join(DIR_1D_ORIGIN, code))
    own_rows = read_1d_rows(os.path.join(DIR_1D, code))
    if origin_rows is None:
        origin_same = False
        origin_note = "缺 1D_ORIGIN"
    elif set(origin_rows) != set(own_rows or {}):
        origin_same = False
        origin_note = "日期集合不同"
    else:
        origin_same = all(_first7_equal(origin_rows[d], own_rows[d]) for d in origin_rows)
        origin_note = "逐日未变" if origin_same else "存在差异"

    status = "ok"
    notes: list[str] = []
    if not latest_ok:
        status = "warning"
        notes.append(f"1D 基准不是最新交易日（latestFactor={latest_factor:.6f}）")
    if non_monotonic:
        status = "warning"
        notes.append(f"factor 非单调（{len(non_monotonic)} 处下降）")
    return {
        "latestFactor": _round(latest_factor),
        "latestDate": latest_date,
        "samples": len(series),
        "nonMonotonic": non_monotonic[:50],
        "factorAlwaysOne": factor_always_one,
        "originSameAs1D": origin_same,
        "originNote": origin_note,
        "status": status,
        "_notes": notes,
    }


# ---------------------------------------------------------------- 主流程
def build(limit: int = 0) -> dict:
    codes = sorted(name for name in os.listdir(DIR_5M) if CODE_RE.match(name)) if os.path.isdir(DIR_5M) else []
    if limit > 0:
        codes = codes[:limit]
    if not codes:
        raise RuntimeError(f"{DIR_5M} 下没有 5M 文件，无法对齐校验")

    stocks: dict[str, dict] = {}
    warnings: list[dict] = []
    as_of = ""
    for code in codes:
        item = _align_5m_stock(code)
        if item is None:
            continue
        warnings.extend(item.pop("_warnings") or [])
        stocks[code] = item
        if item["lastDate"] > as_of:
            as_of = item["lastDate"]

    v1d: dict[str, dict] = {}
    latest_bad = 0
    mono_bad = 0
    always_one_codes: list[str] = []
    origin_same = 0
    origin_diff: list[str] = []
    origin_missing = 0
    for code in codes:
        item = _validate_1d_stock(code)
        if item is None:
            continue
        item.pop("_notes", None)
        v1d[code] = item
        if not item["latestFactor"] or abs(item["latestFactor"] - 1.0) * 100.0 > TOL_PCT:
            latest_bad += 1
        if item["nonMonotonic"]:
            mono_bad += 1
        if item["factorAlwaysOne"]:
            always_one_codes.append(code)
        if item["originSameAs1D"]:
            origin_same += 1
        elif item["originNote"] == "缺 1D_ORIGIN":
            origin_missing += 1
        else:
            origin_diff.append(code)

    status_count = sum(1 for s in stocks.values() if s["status"] == "ok")
    result = {
        "generatedAt": dt.datetime.now().isoformat(timespec="seconds"),
        "asOf": as_of,
        "stocks": stocks,
        "warnings": warnings,
        "summary": {
            "total": len(stocks),
            "ok": status_count,
            "warning": len(stocks) - status_count,
        },
        "validation_1d": {
            "stocks": v1d,
            "factorAlwaysOne": {"count": len(always_one_codes), "codes": always_one_codes[:50]},
            "originSameAs1D": {
                "allSame": len(origin_diff) == 0 and origin_missing == 0,
                "same": origin_same,
                "diff": len(origin_diff),
                "diffCodes": origin_diff[:50],
                "note": ("AIData/1D_ORIGIN 与 AIData/1D 逐日完全相同 → "
                         "1D_ORIGIN 也是前复权数据，无法作为原始价交叉验证（原始价请用 vipdoc/lday）"
                         if len(origin_diff) == 0 and origin_missing == 0 else
                         "1D_ORIGIN 与 AIData/1D 存在差异，可作为部分交叉验证"),
            },
            "summary_1d": {
                "total": len(v1d),
                "latest_ok": len(v1d) - latest_bad,
                "warnings": sum(1 for s in v1d.values() if s["status"] == "warning"),
            },
        },
    }
    return result


def _print_summary(result: dict) -> None:
    summary = result["summary"]
    v = result["validation_1d"]
    top = sorted(result["stocks"].items(), key=lambda kv: kv[1]["maxDev"], reverse=True)[:5]
    top_text = ", ".join(f"{code} {item['maxDev']}%" for code, item in top) or "-"
    print(f"[1/3] 5m↔1D 对齐：{summary['total']} 只，ok={summary['ok']}，warning={summary['warning']}"
          f"（asOf={result['asOf']}）")
    print(f"[2/3] 5m↔1D 最大偏差 top5：{top_text}")
    s1d = v["summary_1d"]
    print(f"[3/3] 1D 前复权校验：{s1d['total']} 只，latestFactor 异常={s1d['total'] - s1d['latest_ok']}，"
          f"单调异常={sum(1 for s in v['stocks'].values() if s['nonMonotonic'])}，"
          f"恒为1={v['factorAlwaysOne']['count']}，1D_ORIGIN 与 1D 相同={v['originSameAs1D']['same']}/"
          f"{s1d['total']}（allSame={v['originSameAs1D']['allSame']}）")
    if summary["warning"]:
        for w in result["warnings"][:10]:
            print(f"  ! {w['code']} {w['date']} dev={w['dev']}%")
    for code, item in v["stocks"].items():
        if item["status"] == "warning":
            print(f"  ! {code} 1D 校验异常：latestFactor={item['latestFactor']}，"
                  f"nonMonotonic={len(item['nonMonotonic'])} 处")


def write_result(result: dict) -> str:
    os.makedirs(OUT_DIR, exist_ok=True)
    tmp = OUT_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT_FILE)
    return OUT_FILE


def run(limit: int = 0, dry_run: bool = False) -> str:
    """一条龙入口：对齐校验并写 alignment.json，返回一行摘要（失败抛异常由调用方处理）。"""
    result = build(limit=limit)
    _print_summary(result)
    if not dry_run:
        path = write_result(result)
        print(f"[输出] {path}")
    summary = result["summary"]
    v = result["validation_1d"]["summary_1d"]
    return (f"5M_ALIGN: 5m/1D {summary['total']} 只 ok={summary['ok']} warning={summary['warning']}；"
            f"1D 校验 {v['total']} 只 latest异常={v['total'] - v['latest_ok']} "
            f"warnings={v['warnings']} 恒为1={result['validation_1d']['factorAlwaysOne']['count']} "
            f"1D_ORIGIN相同={result['validation_1d']['originSameAs1D']['allSame']}")


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="5m↔1D 数据对齐校验")
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 只（调试用），0=全部")
    parser.add_argument("--dry-run", action="store_true", help="只打印，不写 alignment.json")
    args = parser.parse_args(argv)

    try:
        summary = run(limit=args.limit, dry_run=args.dry_run)
    except Exception as exc:
        print(f"[失败] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3
    print(f"[汇总] {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
