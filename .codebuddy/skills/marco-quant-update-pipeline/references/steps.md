# 更新步骤明细

## step 名 → 函数 → 文件
| step | 函数 | 文件 |
|------|------|------|
| UPDATE_TRADING_DATES | UPDATE_TRADING_DATES | AICode/MarcoAPI/Update/TradingDates.py |
| UPDATE_STOCK_CODES | UPDATE_STOCK_CODES | AICode/MarcoAPI/Update/StockCodes.py |
| UPDATE_1D_ORIGIN | UPDATE_1D_ORIGIN | AICode/MarcoAPI/Update/SZ2001D.py |
| UPDATE_5M_ORIGIN | UPDATE_5M_ORIGIN | AICode/MarcoAPI/Update/SZ2005M.py |
| UPDATE_TOP | UPDATE_TOP | AICode/MarcoAPI/Update/SZ200Top.py |
| UPDATE_1D | UPDATE_1D | AICode/MarcoAPI/Update/SZ2001D.py |
| UPDATE_TOP_FIRST | UPDATE_TOP_FIRST | AICode/MarcoAPI/Update/SZ200Top.py |
| UPDATE_STRATEGY_TPO_3 | UPDATE_STRATEGY_TPO_3 | AICode/MarcoAPI/Update/SZ200Strategy.py |
| UPDATE_STRATEGY_TPO_TOP | UPDATE_STRATEGY_TPO_TOP | AICode/MarcoAPI/Update/SZ200Strategy.py |
| UPDATE_STRATEGY_TPO_M5 | UPDATE_STRATEGY_TPO_M5 | AICode/MarcoAPI/Update/SZ200Strategy.py |
| UPDATE_TARGET_TPO_3 | UPDATE_TARGET_TPO_3 | AICode/MarcoAPI/Update/SZ200Target.py |
| UPDATE_TARGET_TPO_TOP | UPDATE_TARGET_TPO_TOP | AICode/MarcoAPI/Update/SZ200Target.py |
| UPDATE_TARGET_TPO_M5 | UPDATE_TARGET_TPO_M5 | AICode/MarcoAPI/Update/SZ200Target.py |
| UPDATE_TPO_M5_HL | UPDATE_TPO_M5_HL | AICode/MarcoAPI/Update/SZ200TPO_M5_HL.py |

## 步骤登记点（新增步骤时改这三处）
- `AICode/MarcoAPI/StrategyUI.py`：`_UPDATE_STEPS` 字典（`CMD_RUN_STEP` 分发用）。
- `AICode/MarcoAPI/Run.py`：`_UPDATE_STEP_ITEMS` 元组（菜单 5 子菜单用）。
- `AICode/MarcoAPI/StrategyUI.py`：JS 数组 `UPDATE_STEPS`（位于 `_render_html` 的 f-string 内，侧边栏按钮用，注：模板内花括号需双写 `{{ }}`）。

## 数据落盘位置（PATH 见 Update/Path.py）
- 原始日线：`AIData/1D_ORIGIN/`
- 原始 5 分钟：`AIData/5M_ORIGIN/`
- 涨停列表：`AIData/TOP/`
- 首板涨停：`AIData/TOP_FIRST/`
- 策略回测：`AIData/STRATEGY/`
- 候选池：`AIData/TARGET/`
- 交易日历 / 股票池：由 TradingDates / StockCodes 维护（非按日文件）

## 典型调用链
- 全量：`UPDATE_ALL()`（Update1D.py）→ 顺序调用上方 1~14（其中 7 UPDATE_TOP_FIRST 位于 6 之后）。
- 单项：`CMD_RUN_STEP(step)`（StrategyUI.py）→ `_UPDATE_STEPS[step]()`。
- 前端触发：`runCommand('RUN_STEP', {step}, btn)`（Web）/ `marcoai://run?cmd=RUN_STEP&step=...`（协议）→ 均落到 `POST /api/cmd` 的 `RUN_STEP` 分支或 `MarcoAI_Handler._run_cmd`。
