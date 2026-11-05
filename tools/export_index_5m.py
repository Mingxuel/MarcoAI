#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把指数/宽基/相关 ETF 的 5 分钟全量数据从通达信本地导出到 AIData/INDEX_5M。

背景：
  通达信客户端本地的 vipdoc/<mkt>/fzline/<mkt><code>.lc5 存了全量 5m（当前 200 个交易日、每日 48 根），
  而 AIData/5M 只存策略涉及的股票窗口数据、且不含指数。为了回测/看板方便，这里把指数类标的的
  5m 全量导出成与 AIData/5M 相同的 13 列文本格式（time|o|h|l|c|vol|amount|ma5..ma120）。

  AIData/INDEX_5M_CODES 为代码清单（代码|名称），首次运行会自动生成；
  以后要加指数/ETF，直接改这个清单文件即可。

用法：
    python tools/export_index_5m.py            # 全量导出清单内所有代码
    python tools/export_index_5m.py --codes 000300.SH,399986.SZ
    python tools/export_index_5m.py --check    # 只体检，不写文件
"""

from __future__ import annotations

import argparse
import collections
import os
import struct
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIPDOC = os.environ.get("TDX_VIPDOC_PATH") or os.path.join(
    os.path.dirname(os.path.dirname(os.environ.get("TDX_PLUGIN_PATH", r"C:\new_tdx64\PYPlugins\user"))), "vipdoc")
OUT_DIR = os.path.join(ROOT, "AIData", "INDEX_5M")
CODES_FILE = os.path.join(ROOT, "AIData", "INDEX_5M_CODES")
MA_PERIODS = (5, 10, 20, 30, 60, 120)

DEFAULT_EXTRAS = [
    ("399986.SZ", "中证银行"),
    ("512800.SH", "银行ETF"),
    ("512880.SH", "证券ETF"),
    ("510300.SH", "沪深300ETF"),
    ("510050.SH", "上证50ETF"),
    ("159919.SZ", "300ETF"),
]


def log(text: str) -> None:
    print(text, flush=True)


def read_codes(extra_codes: list[str] | None = None) -> list[tuple[str, str]]:
    codes: list[tuple[str, str]] = []
    if os.path.exists(CODES_FILE):
        with open(CODES_FILE, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if "|" in line:
                    code, name = line.split("|", 1)
                    codes.append((code.strip(), name.strip()))
    else:
        # 首次运行：用 AIData/INDEX_CODES + 默认宽基/ETF 生成清单
        index_codes = os.path.join(ROOT, "AIData", "INDEX_CODES")
        if os.path.exists(index_codes):
            with open(index_codes, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if "|" in line:
                        code, name = line.split("|", 1)
                        codes.append((code.strip(), name.strip()))
        codes.extend(DEFAULT_EXTRAS)
    if extra_codes:
        codes.extend((c, c) for c in extra_codes)
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for code, name in codes:
        if code not in seen:
            seen.add(code)
            out.append((code, name))
    return out


def _local_lc5(code: str) -> str:
    num, mkt = code.split(".")
    mkt = mkt.lower()
    return os.path.join(VIPDOC, mkt, "fzline", f"{mkt}{num}.lc5")


def read_bars(code: str) -> list[tuple] | None:
    path = _local_lc5(code)
    if not os.path.exists(path):
        return None
    bars: list[tuple] = []
    data = open(path, "rb").read()
    for i in range(len(data) // 32):
        d, t, o, h, l, c, amt, vol, _ = struct.unpack("<HHfffffII", data[i * 32:(i + 1) * 32])
        year = d // 2048 + 2004
        rest = d % 2048
        day = f"{year:04d}-{rest // 100:02d}-{rest % 100:02d}"
        hh, mm = t // 60, t % 60
        bars.append((f"{day} {hh:02d}:{mm:02d}:00", o, h, l, c, float(vol), amt))
    bars.sort()
    return bars


def export_one(code: str, name: str) -> tuple[int, str]:
    bars = read_bars(code)
    if not bars:
        return 0, "无本地 5m 数据"
    closes = [b[4] for b in bars]
    lines: list[str] = []
    for i, (t, o, h, l, c, vol, amt) in enumerate(bars):
        mas = []
        for p in MA_PERIODS:
            if i + 1 >= p:
                mas.append(f"{sum(closes[i - p + 1:i + 1]) / p:.2f}")
            else:
                mas.append("0.00")
        lines.append(f"{t}|{o:.2f}|{h:.2f}|{l:.2f}|{c:.2f}|{vol:.0f}|{amt:.2f}|" + "|".join(mas))
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, code), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return len(bars), f"{bars[0][0][:10]} ~ {bars[-1][0][:10]}"


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="导出指数/宽基 5m 全量到 AIData/INDEX_5M")
    parser.add_argument("--codes", default="", help="逗号分隔代码；默认读 AIData/INDEX_5M_CODES")
    parser.add_argument("--check", action="store_true", help="只体检，不写文件")
    args = parser.parse_args(argv)

    extra = [c.strip() for c in args.codes.split(",") if c.strip()] if args.codes else None
    codes = read_codes(extra)
    if not codes:
        log("[错误] 没有可导出的代码（AIData/INDEX_5M_CODES 为空）")
        return 1

    if not os.path.exists(CODES_FILE):
        os.makedirs(os.path.dirname(CODES_FILE), exist_ok=True)
        with open(CODES_FILE, "w", encoding="utf-8") as fh:
            for code, name in codes:
                fh.write(f"{code}|{name}\n")
        log(f"[清单] 已生成 {CODES_FILE}（{len(codes)} 个代码）")

    log(f"{'code':10s} {'名称':12s} {'bar数':>6s}  区间")
    ok = 0
    for code, name in codes:
        if args.check:
            bars = read_bars(code)
            if bars:
                days = len({b[0][:10] for b in bars})
                log(f"{code:10s} {name:12s} {len(bars):6d}  {bars[0][0][:10]} ~ {bars[-1][0][:10]}（{days} 天）")
                ok += 1
            else:
                log(f"{code:10s} {name:12s} 无本地数据")
            continue
        count, info = export_one(code, name)
        if count:
            ok += 1
            log(f"{code:10s} {name:12s} {count:6d}  {info}")
        else:
            log(f"{code:10s} {name:12s} 无本地数据")
    log(f"[完成] {ok}/{len(codes)} 个代码已导出到 {OUT_DIR}")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
