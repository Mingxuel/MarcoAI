"""
TPO_M5（用户称 TPO_MA5）实盘自动交易入口（CLI）

用法（在 AICode 目录下运行，因 AITrading 现已位于 AICode/AITrading）：
    cd e:/Lazy/MarcoAI/AICode
    python -m AITrading.tpo_m5_trader buy [--force]   # T-1 尾盘买入（--force 离线验证）
    python -m AITrading.tpo_m5_trader sell            # T-0 盘中卖出监控
    python -m AITrading.tpo_m5_trader watch            # 常驻，按时间窗自动触发
"""

import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from AITrading import config as C
from AITrading import commands as CMD
from AITrading.Structure import callbacks as CALL


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    mode = argv[0] if argv else "buy"
    if mode == "buy":
        CMD.cmd_buy(force=("--force" in argv))
    elif mode == "sell":
        CMD.cmd_sell()
    elif mode == "watch":
        CALL.watch()
    else:
        print("用法：python -m AITrading.tpo_m5_trader [buy|sell|watch] [--force]")


if __name__ == "__main__":
    main()
