"""M5_DATA 技能：5 分钟 K 线读取与解析。

导入示例::

    from AICode.MarcoAPI.Skills.M5_DATA import m5_data as M
    data = M.load_5m("600000.SH")          # {"YYYY-MM-DD": [Bar,...]}
    wk   = M.date_window("20260930", 5)    # [T-4..T-0]
    pos  = M.hl_positions("600000.SH", wk) # 每日首高/末低位置
"""
from .m5_data import (
    Bar,
    FIVE_M_DIR,
    TRADING_DATES_FILE,
    TARGET_TPO_M5_DIR,
    load_5m,
    trading_dates,
    date_window,
    target_stocks,
    first_high,
    last_low,
    hl_positions,
    write_hl_file,
    list_target_dates,
    update_tpo_m5_hl_all,
)

__all__ = [
    "Bar", "FIVE_M_DIR", "TRADING_DATES_FILE", "TARGET_TPO_M5_DIR",
    "load_5m", "trading_dates", "date_window", "target_stocks",
    "first_high", "last_low", "hl_positions", "write_hl_file",
    "list_target_dates", "update_tpo_m5_hl_all",
]
