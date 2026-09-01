from dataclasses import dataclass, field
from typing import List, Optional, Dict


@dataclass
class DATA_1D:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float
    # ---- 加工字段（由 UPDATE_1D 从原始数据计算，默认值保证向后兼容）----
    pre_close: float = 0.0        # 前一日收盘价
    is_top: int = 0               # 当日是否涨停（1=是，0=否），依据 TOP 列表
    is_toped: int = 0             # 是否涨停过（含涨停，即盘中触及涨停价）
    ratio: float = 0.0            # 涨跌幅(%) = (close-pre_close)/pre_close*100
    is_up: int = 0                # 涨跌幅为正
    is_down: int = 0              # 涨跌幅为负
    is_red: int = 0               # 收盘价高于开盘价（阳线）
    is_green: int = 0             # 收盘价低于开盘价（阴线）
    is_volume_up: int = 0         # 放量：成交量高于前一日
    is_volume_down: int = 0       # 缩量：成交量低于前一日
    ma5: float = 0.0              # 5日均价（收盘价均值）
    ma10: float = 0.0             # 10日均价
    ma20: float = 0.0             # 20日均价
    ma30: float = 0.0             # 30日均价
    ma60: float = 0.0             # 60日均价
    ma120: float = 0.0            # 120日均价
    lian_ban: int = 0             # 连板次数：从当日往前连续涨停天数
    is_bottom: int = 0            # 当日是否跌停（1=是，0=否，收盘价等于跌停价）

@dataclass
class DATA_5M:
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float

@dataclass
class DATA_1D_TARGET:
    stock_code: str
    stock_name: str
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float
    pre_close: float
