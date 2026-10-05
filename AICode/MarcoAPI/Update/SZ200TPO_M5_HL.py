"""
5M TPO_M5 高低点解析（一条龙更新步骤）

位置: UPDATE_5M_ORIGIN（5M 刷新）之后、同花顺板块更新（CMD_UPDATE_THS）之前。
作用: 在 5M 数据就绪、目标股（TPO_M5）生成后，提取 T-4..T-0 每日首次最高价 / 末次最低价
      的 K 线位置，落盘到 AIData/TARGET_5M/TPO_M5/{t0}，供威科夫量价趋势分析与同花顺板块使用。

解析/落盘逻辑全部复用 M5_DATA 技能（AICode/MarcoAPI/Skills/M5_DATA/m5_data.py），
不在本模块重复实现格式与路径。
"""

import os
import sys

_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _root not in sys.path:
    sys.path.insert(0, _root)

from AICode.MarcoAPI.Skills.M5_DATA import m5_data as M


def UPDATE_TPO_M5_HL(t0: str | None = None) -> str:
    """提取 T-0（默认最新交易日）的 T-4..T-0 首高/末低位置并落盘。

    返回摘要字符串；T-0 无目标股时跳过。
    """
    if t0 is None:
        t0 = M.trading_dates()[-1]
    dates = M.date_window(t0, 5)
    stocks = M.target_stocks(t0)
    if not stocks:
        return f"TPO_M5_HL: T-0={t0} 无目标股，跳过"
    path = M.write_hl_file(t0)
    return f"TPO_M5_HL: T-0={t0} 窗口={dates} 目标股={len(stocks)} 已写出 {path}"


def UPDATE_TPO_M5_HL_ALL() -> str:
    """批量解析 TARGET/TPO_M5 下全部目标股日期的 T-4..T-0 首高/末低位置。

    用于历史数据一次性补齐；单日失败不中断其余日期。
    """
    return M.update_tpo_m5_hl_all()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print(UPDATE_TPO_M5_HL())
