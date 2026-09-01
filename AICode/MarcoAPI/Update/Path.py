import os

# 项目根目录（MarcoAI 所在目录），由本文件位置向上推导：
#   本文件 = <root>/AICode/MarcoAPI/Update/Path.py
PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)


def GET_ROOT_PATH() -> str:
    """返回项目根目录（MarcoAI）。

    旧版通过字符串查找 "Lazy" 定位项目根（依赖旧部署路径 e:/Lazy/MarcoAI），
    项目迁移后失效；现改为基于本文件位置的相对推导，与部署位置无关。
    """
    return PROJECT_ROOT


def PATH_AIDATA_ORIGIN() -> str:
    return os.path.join(PROJECT_ROOT, "AIData", "ORIGIN")


def PATH_AIDATA() -> str:
    return os.path.join(PROJECT_ROOT, "AIData")


def PATH_AIDATA_TRADING_DATES() -> str:
    return os.path.join(PROJECT_ROOT, "AIData", "TRADING_DATES")


def PATH_AIDATA_STOCK_CODES() -> str:
    return os.path.join(PROJECT_ROOT, "AIData", "STOCK_CODES")


def PATH_AIDATA_STOCK_CODES_ALL() -> str:
    return os.path.join(PROJECT_ROOT, "AIData", "STOCK_CODES_ALL")


def PATH_AIDATA_1D_ORIGIN() -> str:
    return os.path.join(PROJECT_ROOT, "AIData", "1D_ORIGIN")


def PATH_AIDATA_1D() -> str:
    return os.path.join(PROJECT_ROOT, "AIData", "1D")


def PATH_AIDATA_5M() -> str:
    return os.path.join(PROJECT_ROOT, "AIData", "5M")


def PATH_AIDATA_TOP() -> str:
    return os.path.join(PROJECT_ROOT, "AIData", "TOP")


def PATH_AIDATA_INFO_SZ100() -> str:
    return os.path.join(PROJECT_ROOT, "AIData", "INFO", "SZ100.xlsx")


def PATH_AIDATA_TOP_ORIGIN() -> str:
    return os.path.join(PROJECT_ROOT, "AIData", "TOP_ORIGIN")


def PATH_AIDATA_TOPPED() -> str:
    return os.path.join(PROJECT_ROOT, "AIData", "TOPPED")


def PATH_AIDATA_BOTTOM() -> str:
    return os.path.join(PROJECT_ROOT, "AIData", "BOTTOM")


def PATH_AIDATA_BOTTOMED() -> str:
    return os.path.join(PROJECT_ROOT, "AIData", "BOTTOMED")


def PATH_AIDATA_TARGET_31() -> str:
    return os.path.join(PROJECT_ROOT, "AIData", "TARGET", "31")


def PATH_AIDATA_TARGET_31_RATIO() -> str:
    return os.path.join(PROJECT_ROOT, "AIData", "TARGET", "31_RATIO")


def PATH_AIDATA_TARGET_TOP_31() -> str:
    return os.path.join(PROJECT_ROOT, "AIData", "TARGET", "TOP_31")


def PATH_AIDATA_TARGET_TOP_31_RATIO() -> str:
    return os.path.join(PROJECT_ROOT, "AIData", "TARGET", "TOP_31_RATIO")


def PATH_AIDATA_TARGET_311() -> str:
    return os.path.join(PROJECT_ROOT, "AIData", "TARGET", "311")


def PATH_AIDATA_TARGET_311_RATIO() -> str:
    return os.path.join(PROJECT_ROOT, "AIData", "TARGET", "311_RATIO")


def PATH_AIDATA_TARGET_TOP_311() -> str:
    return os.path.join(PROJECT_ROOT, "AIData", "TARGET", "TOP_311")


def PATH_AIDATA_TARGET_TOP_311_RATIO() -> str:
    return os.path.join(PROJECT_ROOT, "AIData", "TARGET", "TOP_311_RATIO")


def PATH_AIDATA_TARGET_HISTORY() -> str:
    return os.path.join(PROJECT_ROOT, "AIData", "TARGET", "HISTORY")


def PATH_AIDATA_TARGET_HISTORY_RATIO() -> str:
    return os.path.join(PROJECT_ROOT, "AIData", "TARGET", "HISTORY_RATIO")


def PATH_AIDATA_TARGET_TOP_1() -> str:
    return os.path.join(PROJECT_ROOT, "AIData", "TARGET", "TOP_1")


def PATH_AIDATA_TARGET_TOP_1_RATIO() -> str:
    return os.path.join(PROJECT_ROOT, "AIData", "TARGET", "TOP_1_RATIO")


def PATH_AIDATA_TARGET_TOP_11() -> str:
    return os.path.join(PROJECT_ROOT, "AIData", "TARGET", "TOP_11")


def PATH_AIDATA_TARGET_TOP_11_RATIO() -> str:
    return os.path.join(PROJECT_ROOT, "AIData", "TARGET", "TOP_11_RATIO")


def PATH_AIDATA_TARGET(strategy_name: str = "") -> str:
    """目标股/候选股票池目录：AIData/TARGET[/策略名]"""
    if strategy_name:
        return os.path.join(PROJECT_ROOT, "AIData", "TARGET", strategy_name)
    return os.path.join(PROJECT_ROOT, "AIData", "TARGET")


def PATH_AIDATA_STRATEGY() -> str:
    return os.path.join(PROJECT_ROOT, "AIData", "Strategy")


def PATH_AIDATA_STRATEGY_RESULT() -> str:
    return os.path.join(PROJECT_ROOT, "AIData", "STRATEGY", "RESULT")


def PATH_AIDATA_STRATEGY_TPO_3() -> str:
    return os.path.join(PROJECT_ROOT, "AIData", "Strategy", "TPO_3")


def PATH_AIDATA_STRATEGY_TPO_TOP() -> str:
    return os.path.join(PROJECT_ROOT, "AIData", "Strategy", "TPO_TOP")


def PATH_AIDATA_STRATEGY_TPO_M5() -> str:
    return os.path.join(PROJECT_ROOT, "AIData", "Strategy", "TPO_M5")


def PATH_AIDATA_1D_MOTION_PRICE() -> str:
    return os.path.join(PROJECT_ROOT, "AIData", "1D_MOTION_PRICE")


def PATH_AIDATA_1D_MOTION_PRICE_VOLUME() -> str:
    return os.path.join(PROJECT_ROOT, "AIData", "1D_MOTION_PRICE_VOLUME")


def PATH_AIDATA_1D_WIN_COUNT() -> str:
    return os.path.join(PROJECT_ROOT, "AIData", "1D_MOTION_WIN_COUNT")


def PATH_AIDATA_1D_MOTION_COUNT() -> str:
    return os.path.join(PROJECT_ROOT, "AIData", "1D_MOTION_COUNT")


def PATH_AIDATA_5M_MOTION_PRICE() -> str:
    return os.path.join(PROJECT_ROOT, "AIData", "5M_MOTION_PRICE")


def PATH_AIDATA_5M_MOTION_PRICE_VOLUME() -> str:
    return os.path.join(PROJECT_ROOT, "AIData", "5M_MOTION_PRICE_VOLUME")


def PATH_AIDATA_5M_WIN_COUNT() -> str:
    return os.path.join(PROJECT_ROOT, "AIData", "5M_MOTION_WIN_COUNT")


def PATH_AIDATA_1D_SIGNALS() -> str:
    return os.path.join(PROJECT_ROOT, "AIData", "1D_MOTION_SIGNALS")


def PATH_AIDATA_1D_PANIC_INDEX() -> str:
    return os.path.join(PROJECT_ROOT, "AIData", "1D_PANIC_INDEX")


def PATH_AIDATA_1D_PRICE() -> str:
    return os.path.join(PROJECT_ROOT, "AIData", "1D_PRICE")


def PATH_AIDATA_5M_SIGNALS() -> str:
    return os.path.join(PROJECT_ROOT, "AIData", "5M_MOTION_SIGNALS")


def PATH_AIDATA_MOTION() -> str:
    return os.path.join(PROJECT_ROOT, "AIData", "MOTION")


def PATH_TDX() -> str:
    """通达信 tqcenter 插件目录（外部依赖）。可用环境变量 TDX_PLUGIN_PATH 覆盖。"""
    return os.environ.get("TDX_PLUGIN_PATH", "D:/new_tdx_mock/PYPlugins/user")


def PATH_ADJUST_FACTOR() -> str:
    return os.path.join(PATH_AIDATA_ORIGIN(), "ADJUST_FACTOR")


def PATH_STOCK_CODES() -> str:
    return os.path.join(PATH_AIDATA(), "ORIGIN", "SZ200.config")


def PATH_TRADING_DATES() -> str:
    return os.path.join(PATH_AIDATA(), "TradingDates.config")
