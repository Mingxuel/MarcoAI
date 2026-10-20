"""TPO_M5_2.0 策略骨架。

选股基础条件与 TPO_M5 完全一致（见 SKILL.md）。两处改进以 TODO 钩子占位：
  TODO-1  rank_select : 替代 TPO_M5「市值倒序 + MA5预测选第一只」
  TODO-2  t0_sell     : 替代 Backtest 内置 T-0 卖出口径

当前默认实现 == TPO_M5（rank_select 回退到市值倒序+MA5预测，t0_sell 返回 None 用回测默认），
待用户逐步口述后替换 TODO 段即可，未实现任何"改进"逻辑。
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from AICode.MarcoAPI.Update.Constants import *
from AICode.MarcoAPI.Update.StockCodes import *
from AICode.MarcoAPI.Update.SZ2001D import GET_SZ200_1D_PREVIOUS
from AICode.MarcoAPI.Update.SZ200Strategy import _rotate_dir

# 输出目录（与 TPO_M5 同层级，命名 TPO_M5_2.0）
DST_DIR = os.path.join(_ROOT, "AIData", "Strategy", "TPO_M5_2.0")

MARKET_MIN = 2e10       # 200 亿
MARKET_MAX = 1.3e11     # 1300 亿
MAX_RATIO = 3.0         # T-1 收盘涨跌幅上限（含边界）
MARKET_INDEX = 2        # 市值用 T-2 日收盘价
STOP_LOSS = -0.05       # 止损线 -5%


# ----------------------------------------------------------------------
# 基础过滤：与 TPO_M5 一致，返回满足全部基础条件的候选列表
#   cand = (record_0, code, name, market_value, vol_ratio)
# ----------------------------------------------------------------------
def _base_candidates(trading_date: str) -> list:
    cands = []
    for stock_code in STOCK_CODES_ALL():
        stock = stock_code.split("|")
        code = stock[0]
        name = stock[1] if len(stock) > 1 else ""
        rec3 = GET_SZ200_1D_PREVIOUS(code, trading_date, 3)
        rec2 = GET_SZ200_1D_PREVIOUS(code, trading_date, 2)
        rec1 = GET_SZ200_1D_PREVIOUS(code, trading_date, 1)
        rec0 = GET_SZ200_1D_PREVIOUS(code, trading_date, 0)
        if rec3 is None or rec2 is None or rec1 is None or rec0 is None:
            continue
        # T-3 首板放量涨停
        if rec3.is_top != 1 or rec3.lian_ban != 1 or rec3.is_volume_up != 1:
            continue
        # T-2 上涨放量未涨停
        if rec2.is_up != 1 or rec2.is_volume_up != 1 or rec2.is_top != 0:
            continue
        # T-1 缩量、涨幅<=3%、收盘>MA5
        if rec1.ratio > MAX_RATIO or rec1.is_volume_down != 1 or rec1.close <= rec1.ma5:
            continue
        # 市值区间
        info = GET_STOCK_INFO(code)
        if info is None or info[1] <= 0:
            continue
        mr = {3: rec3, 2: rec2, 1: rec1}[MARKET_INDEX]
        mv = float(info[1]) * mr.close
        if mv < MARKET_MIN or mv > MARKET_MAX:
            continue
        vol_ratio = (rec2.volume / rec3.volume) if (rec3.volume and rec3.volume > 0) else 0.0
        cands.append((rec0, code, name, mv, vol_ratio))
    return cands


# ----------------------------------------------------------------------
# TODO-1 选股改进：替代 TPO_M5「市值倒序 + MA5预测选第一只」
#   入参 cands：_base_candidates 返回的基础候选（已满足 TPO_M5 全部条件）
#   返回：排序/筛选后的候选列表（回测取 rows[0] 为首选）
#   当前默认行为 == TPO_M5（仅供占位，待用户口述后替换）
# ----------------------------------------------------------------------
def rank_select(cands: list, trading_date: str) -> list:
    # ===== TODO-1: 在此实现改进后的排序/选法，替换下方默认逻辑 =====
    cands.sort(key=lambda x: x[3], reverse=True)  # 按市值倒序（默认）
    for d, code, name, mv, _v in cands:
        r1 = GET_SZ200_1D_PREVIOUS(code, trading_date, 1)
        r2 = GET_SZ200_1D_PREVIOUS(code, trading_date, 2)
        r3 = GET_SZ200_1D_PREVIOUS(code, trading_date, 3)
        r4 = GET_SZ200_1D_PREVIOUS(code, trading_date, 4)
        if None in (r1, r2, r3, r4):
            continue
        pred_ma5 = (r1.close * 2 + r2.close + r3.close + r4.close) / 5.0
        if r1.close >= pred_ma5:
            rest = [x for x in cands if x[1] != code]
            return [(d, code, name, mv, 0.0)] + rest
    return []  # 无满足 MA5 预测者：当日空仓（默认）
    # ===== TODO-1 结束 =====


# ----------------------------------------------------------------------
# TODO-2 T-0 卖出规则：替代 Backtest 内置卖出口径
#   入参 cols：候选行（29列，| 分隔，见 SKILL.md 列定义）
#   返回：自定义卖出价 float；返回 None 表示沿用 Backtest 默认（当前默认）
#   注：若在此实现自定义卖价，需配套改写回测口径（_sell_price_*），暂以占位。
# ----------------------------------------------------------------------
def t0_sell(cols: list) -> float | None:
    # ===== TODO-2: 在此实现 TPO_M5_2.0 的 T-0 卖出规则，替换下方默认 =====
    return None  # 沿用 Backtest 默认（first/last/avg/5m）
    # ===== TODO-2 结束 =====


def _write_row(file, date, code, name, mv, d, stop_loss=STOP_LOSS):
    file.write(
        f"{code}|{name}|{mv:.2f}"
        + f"|{date}|{d.open}|{d.high}|{d.low}|{d.close}|{d.volume}|{d.amount}"
        + f"|{d.pre_close}|{d.is_top}|{d.is_toped}|{d.ratio}"
        + f"|{d.is_up}|{d.is_down}|{d.is_red}|{d.is_green}"
        + f"|{d.is_volume_up}|{d.is_volume_down}"
        + f"|{d.ma5}|{d.ma10}|{d.ma20}|{d.ma30}|{d.ma60}|{d.ma120}|{d.lian_ban}|{d.is_bottom}"
        + f"|{stop_loss:.2f}\n"
    )


def GENERATE_TPO_M5_2_0(trading_dates=None):
    """生成 TPO_M5_2.0 回测数据（骨架，当前 == TPO_M5 行为 + 两处 TODO）。

    输出 AIData/Strategy/TPO_M5_2.0/{T-0日期}（29列，与 TPO_M5 同格式）。
    """
    _rotate_dir(DST_DIR)
    dates = trading_dates if trading_dates is not None else TRADING_DATES()
    for sell_date in dates:
        cands = _base_candidates(sell_date)
        chosen = rank_select(cands, sell_date)  # TODO-1 钩子
        with open(os.path.join(DST_DIR, sell_date), "a") as file:
            if not chosen:
                file.write("\n")
                continue
            for d, code, name, mv, _v in chosen:
                _write_row(file, sell_date, code, name, mv, d)


if __name__ == "__main__":
    GENERATE_TPO_M5_2_0()
