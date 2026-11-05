#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""用 tqcenter.refresh_kline 刷新通达信本地 K 线数据（替代手工“选项→盘后数据下载”）。

原理（官方 TdxQuant 文档）：refresh_kline 会按股票+周期定向下载历史 K 线到客户端本地缓存，
支持 1d / 1m / 5m；盘中调用 1m/5m 只能补到上一交易日，盘后调用才包含当天。

前置条件：通达信客户端已启动并登录（脚本不负责登录），客户端需为支持 TQ 的版本。

用法：
    python tools/tdx_refresh.py --codes 600000.SH,000001.SZ --periods 1d,5m
    python tools/tdx_refresh.py --codes-file AIData/STOCK_CODES_ALL --periods 1d --limit 5
    python tools/tdx_refresh.py --codes 600000.SH --periods 1d,5m --check-local-only

输出：每个股票/周期刷新前后的本地文件时间戳 + 末条数据日期，便于验证是否真正更新。
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TDX_PLUGIN_DIR = os.environ.get("TDX_PLUGIN_PATH", r"C:\new_tdx64\PYPlugins\user")
# C:\new_tdx64\PYPlugins\user -> C:\new_tdx64（上两级）
TDX_ROOT = os.path.dirname(os.path.dirname(TDX_PLUGIN_DIR))
VIPDOC = os.path.join(TDX_ROOT, "vipdoc")


def _log(text: str) -> None:
    print(text, flush=True)


def _local_file(code: str, period: str) -> str:
    market = "sh" if code.upper().endswith(".SH") else "sz"
    number = code.split(".")[0]
    if period == "1d":
        return os.path.join(VIPDOC, market, "lday", f"{market}{number}.day")
    if period == "5m":
        return os.path.join(VIPDOC, market, "fzline", f"{market}{number}.lc5")
    if period == "1m":
        return os.path.join(VIPDOC, market, "minline", f"{market}{number}.lc1")
    raise ValueError(f"不支持的周期：{period}")


def _last_date(path: str, period: str) -> str:
    """读本地文件末条记录的日期，用于判断数据是否更新到目标交易日。"""
    if not os.path.exists(path) or os.path.getsize(path) < 32:
        return "无文件"
    with open(path, "rb") as fh:
        fh.seek(-32, os.SEEK_END)
        raw = fh.read(32)
    try:
        if period == "1d":
            date_int = struct.unpack("<I", raw[:4])[0]
            return str(date_int)
        date_raw, time_raw = struct.unpack("<HH", raw[:4])
        year = date_raw // 2048 + 2004
        rest = date_raw % 2048
        month, day = rest // 100, rest % 100
        hour, minute = time_raw // 60, time_raw % 60
        return f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}"
    except Exception:
        return "解析失败"


def _state(code: str, period: str) -> dict:
    path = _local_file(code, period)
    if not os.path.exists(path):
        return {"file": path, "exists": False}
    stat = os.stat(path)
    return {
        "file": path,
        "exists": True,
        "size": stat.st_size,
        "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
        "last_date": _last_date(path, period),
    }


def _load_codes(args) -> list[str]:
    codes: list[str] = []
    if args.codes:
        codes.extend(c.strip() for c in args.codes.split(",") if c.strip())
    if args.codes_file:
        with open(args.codes_file, encoding="utf-8-sig", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                code = line.split("|")[0].strip()
                if code:
                    codes.append(code)
    # 去重保序
    seen: set[str] = set()
    out: list[str] = []
    for code in codes:
        if code not in seen:
            seen.add(code)
            out.append(code)
    if args.limit > 0:
        out = out[: args.limit]
    return out


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="用 tqcenter.refresh_kline 刷新通达信本地 K 线")
    parser.add_argument("--codes", default="", help="逗号分隔的代码，如 600000.SH,000001.SZ")
    parser.add_argument("--codes-file", default="", help="代码清单文件（每行 代码 或 代码|名称）")
    parser.add_argument("--periods", action="append", default=None,
                        help="周期，可重复传入：--periods 1d --periods 5m；默认 1d,5m")
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 只（调试用），0=全部")
    parser.add_argument("--check-local-only", action="store_true", help="只打印本地数据状态，不调用刷新")
    args = parser.parse_args(argv)

    codes = _load_codes(args)
    if not codes:
        _log("[错误] 没有股票代码：用 --codes 或 --codes-file 指定")
        return 1
    periods: list[str] = []
    for item in (args.periods or ["1d,5m"]):
        for part in item.replace(";", ",").split(","):
            part = part.strip()
            if part:
                periods.append(part)
    _log(f"[参数] 股票 {len(codes)} 只，周期 {periods}，插件目录 {TDX_PLUGIN_DIR}")

    before = {(c, p): _state(c, p) for c in codes for p in periods}
    if args.check_local_only:
        for (code, period), state in before.items():
            _log(f"{code} {period}: {json.dumps(state, ensure_ascii=False)}")
        return 0

    sys.path.insert(0, TDX_PLUGIN_DIR)
    try:
        from tqcenter import tq
    except Exception as exc:
        _log(f"[错误] 导入 tqcenter 失败：{type(exc).__name__}: {exc}")
        return 2

    t0 = time.time()
    tq.initialize(__file__)
    _log(f"[初始化] tqcenter 连接成功（{time.time() - t0:.1f}s）")

    for period in periods:
        t1 = time.time()
        try:
            result = tq.refresh_kline(stock_list=codes, period=period)
            _log(f"[刷新] period={period} 用时 {time.time() - t1:.1f}s，返回：{result}")
        except Exception as exc:
            _log(f"[刷新] period={period} 失败：{type(exc).__name__}: {exc}")

    after = {(c, p): _state(c, p) for c in codes for p in periods}
    changed = 0
    for key in before:
        b, a = before[key], after[key]
        if b.get("mtime") != a.get("mtime") or b.get("last_date") != a.get("last_date"):
            changed += 1
            _log(f"[校验] {key[0]} {key[1]}: {b.get('mtime')} / {b.get('last_date')}  ->  {a.get('mtime')} / {a.get('last_date')}")
        else:
            _log(f"[校验] {key[0]} {key[1]}: 未变化（本地已是最新？） {a.get('mtime')} / {a.get('last_date')}")

    _log(f"[汇总] {len(codes)} 只 × {len(periods)} 周期，{changed} 项文件有变化，总耗时 {time.time() - t0:.1f}s")
    try:
        tq.close()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
