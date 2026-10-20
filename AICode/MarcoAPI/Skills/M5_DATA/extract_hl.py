"""CLI: 提取某 T-0 的 T-4..T-0 首次最高价/末次最低价位置（落盘到 AIData/TARGET_5M/TPO_M5/{t0}）。

用法:
    python extract_hl.py            # 默认最新交易日
    python extract_hl.py 20260930   # 指定 T-0

解析与落盘逻辑见 m5_data.write_hl_file（与一条龙更新 UPDATE_ALL 共用，避免重复实现）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from m5_data import write_hl_file, trading_dates


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    t0 = sys.argv[1] if len(sys.argv) > 1 else trading_dates()[-1]
    path = write_hl_file(t0)
    print(f"[ok] 写出 {path}")
