import os

def GET_ROOT_PATH() -> str:
    current_path: str = os.path.abspath(__file__)
    keyword = "Lazy"
    index: int = current_path.find(keyword)
    return current_path[:index + len(keyword)]

def PATH_AIDATA_ORIGIN() -> str:
    return GET_ROOT_PATH() + "/MarcoAI/AIData/ORIGIN"

def PATH_AIDATA() -> str:
    return GET_ROOT_PATH() + "/MarcoAI/AIData"

def PATH_AIDATA_TRADING_DATES() -> str:
    return GET_ROOT_PATH() + "/MarcoAI/AIData/TRADING_DATES"

def PATH_AIDATA_STOCK_CODES() -> str:
    return GET_ROOT_PATH() + "/MarcoAI/AIData/STOCK_CODES"

def PATH_AIDATA_STOCK_CODES_ALL() -> str:
    return GET_ROOT_PATH() + "/MarcoAI/AIData/STOCK_CODES_ALL"

def PATH_AIDATA_1D_ORIGIN() -> str:
    return GET_ROOT_PATH() + "/MarcoAI/AIData/1D_ORIGIN"

def PATH_AIDATA_1D() -> str:
    return GET_ROOT_PATH() + "/MarcoAI/AIData/1D"

def PATH_AIDATA_5M() -> str:
    return GET_ROOT_PATH() + "/MarcoAI/AIData/5M"

def PATH_AIDATA_TOP() -> str:
    return GET_ROOT_PATH() + "/MarcoAI/AIData/TOP"

def PATH_AIDATA_INFO_SZ100() -> str:
    return GET_ROOT_PATH() + "/MarcoAI/AIData/INFO/SZ100.xlsx"

def PATH_AIDATA_TOP_ORIGIN() -> str:
    return GET_ROOT_PATH() + "/MarcoAI/AIData/TOP_ORIGIN"

def PATH_AIDATA_TOPPED() -> str:
    return GET_ROOT_PATH() + "/MarcoAI/AIData/TOPPED"

def PATH_AIDATA_BOTTOM() -> str:
    return GET_ROOT_PATH() + "/MarcoAI/AIData/BOTTOM"

def PATH_AIDATA_BOTTOMED() -> str:
    return GET_ROOT_PATH() + "/MarcoAI/AIData/BOTTOMED"

def PATH_AIDATA_TARGET_31() -> str:
    return GET_ROOT_PATH() + "/MarcoAI/AIData/TARGET/31"

def PATH_AIDATA_TARGET_31_RATIO() -> str:
    return GET_ROOT_PATH() + "/MarcoAI/AIData/TARGET/31_RATIO"

def PATH_AIDATA_TARGET_TOP_31() -> str:
    return GET_ROOT_PATH() + "/MarcoAI/AIData/TARGET/TOP_31"

def PATH_AIDATA_TARGET_TOP_31_RATIO() -> str:
    return GET_ROOT_PATH() + "/MarcoAI/AIData/TARGET/TOP_31_RATIO"

def PATH_AIDATA_TARGET_311() -> str:
    return GET_ROOT_PATH() + "/MarcoAI/AIData/TARGET/311"

def PATH_AIDATA_TARGET_311_RATIO() -> str:
    return GET_ROOT_PATH() + "/MarcoAI/AIData/TARGET/311_RATIO"

def PATH_AIDATA_TARGET_TOP_311() -> str:
    return GET_ROOT_PATH() + "/MarcoAI/AIData/TARGET/TOP_311"

def PATH_AIDATA_TARGET_TOP_311_RATIO() -> str:
    return GET_ROOT_PATH() + "/MarcoAI/AIData/TARGET/TOP_311_RATIO"

def PATH_AIDATA_TARGET_HISTORY() -> str:
    return GET_ROOT_PATH() + "/MarcoAI/AIData/TARGET/HISTORY"

def PATH_AIDATA_TARGET_HISTORY_RATIO() -> str:
    return GET_ROOT_PATH() + "/MarcoAI/AIData/TARGET/HISTORY_RATIO"

def PATH_AIDATA_TARGET_TOP_1() -> str:
    return GET_ROOT_PATH() + "/MarcoAI/AIData/TARGET/TOP_1"

def PATH_AIDATA_TARGET_TOP_1_RATIO() -> str:
    return GET_ROOT_PATH() + "/MarcoAI/AIData/TARGET/TOP_1_RATIO"

def PATH_AIDATA_TARGET_TOP_11() -> str:
    return GET_ROOT_PATH() + "/MarcoAI/AIData/TARGET/TOP_11"

def PATH_AIDATA_TARGET_TOP_11_RATIO() -> str:
    return GET_ROOT_PATH() + "/MarcoAI/AIData/TARGET/TOP_11_RATIO"

def PATH_AIDATA_TARGET(strategy_name: str = "") -> str:
    """目标股/候选股票池目录：MarcoAI/AIData/TARGET[/策略名]"""
    if strategy_name:
        return GET_ROOT_PATH() + f"/MarcoAI/AIData/TARGET/{strategy_name}"
    return GET_ROOT_PATH() + "/MarcoAI/AIData/TARGET"

def PATH_AIDATA_STRATEGY() -> str:
    return GET_ROOT_PATH() + "/MarcoAI/AIData/Strategy"

def PATH_AIDATA_STRATEGY_RESULT() -> str:
    return GET_ROOT_PATH() + "/MarcoAI/AIData/STRATEGY/RESULT"

def PATH_AIDATA_STRATEGY_TPO_3() -> str:
    return GET_ROOT_PATH() + "/MarcoAI/AIData/Strategy/TPO_3"

def PATH_AIDATA_STRATEGY_TPO_TOP() -> str:
    return GET_ROOT_PATH() + "/MarcoAI/AIData/Strategy/TPO_TOP"

def PATH_AIDATA_STRATEGY_TPO_M5() -> str:
    return GET_ROOT_PATH() + "/MarcoAI/AIData/Strategy/TPO_M5"


def PATH_AIDATA_1D_MOTION_PRICE() -> str:
    return GET_ROOT_PATH() + "/MarcoAI/AIData/1D_MOTION_PRICE"

def PATH_AIDATA_1D_MOTION_PRICE_VOLUME() -> str:
    return GET_ROOT_PATH() + "/MarcoAI/AIData/1D_MOTION_PRICE_VOLUME"

def PATH_AIDATA_1D_WIN_COUNT() -> str:
    return GET_ROOT_PATH() + "/MarcoAI/AIData/1D_MOTION_WIN_COUNT"

def PATH_AIDATA_1D_MOTION_COUNT() -> str:
    return GET_ROOT_PATH() + "/MarcoAI/AIData/1D_MOTION_COUNT"

def PATH_AIDATA_5M_MOTION_PRICE() -> str:
    return GET_ROOT_PATH() + "/MarcoAI/AIData/5M_MOTION_PRICE"

def PATH_AIDATA_5M_MOTION_PRICE_VOLUME() -> str:
    return GET_ROOT_PATH() + "/MarcoAI/AIData/5M_MOTION_PRICE_VOLUME"

def PATH_AIDATA_5M_WIN_COUNT() -> str:
    return GET_ROOT_PATH() + "/MarcoAI/AIData/5M_MOTION_WIN_COUNT"

def PATH_AIDATA_1D_SIGNALS() -> str:
    return GET_ROOT_PATH() + "/MarcoAI/AIData/1D_MOTION_SIGNALS"

def PATH_AIDATA_1D_PANIC_INDEX() -> str:
    return GET_ROOT_PATH() + "/MarcoAI/AIData/1D_PANIC_INDEX"

def PATH_AIDATA_1D_PRICE() -> str:
    return GET_ROOT_PATH() + "/MarcoAI/AIData/1D_PRICE"

def PATH_AIDATA_5M_SIGNALS() -> str:
    return GET_ROOT_PATH() + "/MarcoAI/AIData/5M_MOTION_SIGNALS"

def PATH_AIDATA_MOTION() -> str:
    return GET_ROOT_PATH() + "/MarcoAI/AIData/MOTION"

def PATH_TDX() -> str:
    return "D:/new_tdx_mock/PYPlugins/user"

def PATH_ADJUST_FACTOR() -> str:
    return PATH_AIDATA_ORIGIN() + "/ADJUST_FACTOR"

def PATH_STOCK_CODES() -> str:
    return PATH_AIDATA() + "/ORIGIN/SZ200.config"

def PATH_TRADING_DATES() -> str:
    return PATH_AIDATA() + "/TradingDates.config"

def PATH_THS_ROOT() -> str:
    return GET_ROOT_PATH() + "/李明学的大A/Data/THS"

def PATH_THS_HISTORY_XLSX() -> str:
    return PATH_THS_ROOT() + "/History.xlsx"

def PATH_THS_HISTORY() -> str:
    return PATH_THS_ROOT() + "/History"

