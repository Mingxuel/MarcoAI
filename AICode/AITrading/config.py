"""
miniQMT（xtquant）实盘配置 —— AITrading/QMT

运行方式：
    1. 安装并登录 QMT 客户端（极速交易 / miniQMT 模式，保持客户端运行）
    2. 在同目录 config.json 中填入账号与 userdata 路径（也可直接改本文件常量）
    3. 买入：交易日 T-1 尾盘集合竞价前
        cd e:/Lazy/MarcoAI/AICode
        python -m AITrading.tpo_m5_trader buy
       卖出：交易日 T-0 盘中
        python -m AITrading.tpo_m5_trader sell
    也可 watch 模式常驻，由 tick/时间窗自动触发买卖。

策略说明：
    TPO_M5（用户口中的 TPO_MA5）策略：以 TARGET/TPO_M5 最新文件为预选买入池，
    在买入确认日（T-1）尾盘按完整 TPO_M5 形态 + MA5 预测条件做实时判定，单股全仓买入；
    次日（T-0）按“最低价<止损→止损卖 / 最高价触涨停→涨停卖 / 否则收盘卖”规则卖出。

外部配置（config.json，热加载）：
    同目录 config.json 可覆盖本文件任意可覆盖常量（账号、参数），并控制日志开关。
    修改 config.json 后无需重启即可生效：
        {
          "QMT_USERDATA_PATH": "D:/QMT/userdata_mini",
          "ACCOUNT_ID": "123456",
          "log": { "buy": true, "sell": true, "tick": false, "qmt": true, "watch": true }
        }
    "log" 可为布尔（全局开关）或按 tag 的字典（细粒度开关）。
"""

import os
import json

# ======================================================================
# 一、QMT / miniQMT 连接配置（也可在 config.json 覆盖）
# ======================================================================
QMT_USERDATA_PATH = r""
ACCOUNT_ID = ""
ACCOUNT_TYPE = 2  # xtconstant.ACCOUNT_TYPE_STOCK = 2

# ======================================================================
# 二、资金与仓位
# ======================================================================
INIT_CAPITAL = 100000.0
POSITION_RATIO = 1.0
MIN_BUY_AMOUNT = 0

# ======================================================================
# 三、交易时间（24h 制，本地时间）
# ======================================================================
BUY_TIME = "14:57:00"
SELL_STOP_TIME = "09:30:00"
SELL_LIMIT_MONITOR_TIME = "09:30:00"
SELL_CLOSE_TIME = "14:55:00"

# 收盘强平三阶段（自 SELL_CLOSE_TIME 起算；14:57 进入集合竞价后不可撤单）
FORCE_CLOSE_P1_SEC = 60      # 阶段一：卖一价挂单，每 FORCE_CLOSE_RETRY_SEC 撤单重挂
FORCE_CLOSE_P2_SEC = 30      # 阶段二：卖一价 - P2_TICK，最多 P2_MAX 次
FORCE_CLOSE_P2_MAX = 2       # 阶段二最多挂单次数
FORCE_CLOSE_P2_TICK = 0.01   # 阶段二让价幅度（元）
FORCE_CLOSE_RETRY_SEC = 15   # 阶段一/二撤单重挂间隔（秒）；阶段三为每 tick 撤挂

# ======================================================================
# 四、TPO_M5 策略参数（与回测 UPDATE_STRATEGY_TPO_M5 保持一致）
# ======================================================================
STRATEGY_NAME = "TPO_M5"
MAX_RATIO = 0.03
MARKET_MIN = 2e10
MARKET_MAX = 1.3e11
STOP_LOSS = -0.05

# ======================================================================
# 五、路径（基于项目根目录，自动加入 sys.path）
# ======================================================================
# 文件位于 <根>/AICode/AITrading/QMT/，上溯 4 层得到项目根 <根>，
# 并同时将 <根>/AICode 加入 sys.path，以便 import AITrading 与 import AICode.MarcoAPI 均可用。
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
_AICODE = os.path.join(_ROOT, "AICode")
_sys = __import__("sys")
for _p in (_ROOT, _AICODE):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

# ======================================================================
# 六、外部 config.json 热加载 + 日志热开关
# ======================================================================
_CFG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
_cfg_mtime = 0.0
_LOG_CFG = True  # 默认全开

# 允许被 config.json 覆盖的键（即本文件顶层常量名）
_OVERRIDABLE = [
    "QMT_USERDATA_PATH", "ACCOUNT_ID", "ACCOUNT_TYPE",
    "INIT_CAPITAL", "POSITION_RATIO", "MIN_BUY_AMOUNT",
    "BUY_TIME", "SELL_STOP_TIME", "SELL_LIMIT_MONITOR_TIME", "SELL_CLOSE_TIME",
    "FORCE_CLOSE_P1_SEC", "FORCE_CLOSE_P2_SEC", "FORCE_CLOSE_P2_MAX",
    "FORCE_CLOSE_P2_TICK", "FORCE_CLOSE_RETRY_SEC",
    "STRATEGY_NAME", "MAX_RATIO", "MARKET_MIN", "MARKET_MAX", "STOP_LOSS",
]


def reload_config():
    """检查 config.json 是否变化，变化则热加载覆盖项（每次 log 前自动触发）。"""
    global _cfg_mtime, _LOG_CFG
    if not os.path.exists(_CFG_PATH):
        return
    try:
        m = os.path.getmtime(_CFG_PATH)
    except OSError:
        return
    if m == _cfg_mtime:
        return
    try:
        with open(_CFG_PATH, encoding="utf-8") as f:
            ov = json.load(f)
        _cfg_mtime = m
        applied = 0
        for k in _OVERRIDABLE:
            if k in ov:
                globals()[k] = ov[k]
                applied += 1
        if "log" in ov:
            _LOG_CFG = ov["log"]
        print(f"[config] 已热加载 config.json（覆盖 {applied} 项配置）")
    except Exception as e:
        print(f"[config][warn] 加载 config.json 失败：{e}")


def log_enabled(tag: str) -> bool:
    reload_config()
    lg = _LOG_CFG
    if isinstance(lg, bool):
        return lg
    if isinstance(lg, dict):
        return lg.get(tag, True)
    return True


def log(tag: str, msg: str):
    """统一日志出口，受 config.json 的 log 开关热控。"""
    if log_enabled(tag):
        print(f"[{tag}] {msg}")


# 模块导入即应用一次外部覆盖（若 config.json 已存在）
reload_config()
