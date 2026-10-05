---
name: marco-quant-update-pipeline
description: 数据更新一条龙(UPDATE_ALL)的 14 个步骤、依赖关系，以及如何单独跑某项(CMD_RUN_STEP / Run.py 菜单5 / Web 侧边栏 / marcoai://)。当用户要更新数据、跑单项更新、新增更新步骤、或问 UPDATE_* 函数之用。This skill should be used when updating quant data, running a single update step, adding a new update step, or working with UPDATE_* functions.
---

# 量化数据更新管线

一条龙更新由 `AICode/MarcoAPI/Update/Update1D.py` 的 `UPDATE_ALL()` 驱动，依序跑 14 步。任一步都可单独触发（见下）。

## 14 个步骤（按依赖顺序，编号对应 Run.py 菜单 5）
详见 `references/steps.md`（含每个 step 名 → 函数 → 文件 → 登记点）。

1 UPDATE_TRADING_DATES 交易日历
2 UPDATE_STOCK_CODES 股票池（SZ100.xlsx → 全市场）
3 UPDATE_1D_ORIGIN 日线原始（通达信，全市场 3045 只，**慢**）
4 UPDATE_5M_ORIGIN 5分钟原始（通达信，全市场，**很慢**）
5 UPDATE_TOP 涨停列表
6 UPDATE_1D 加工日线（MA / 连板 / is_top）
7 UPDATE_TOP_FIRST 首板涨停
8 UPDATE_STRATEGY_TPO_3 策略回测
9 UPDATE_STRATEGY_TPO_TOP 策略回测
10 UPDATE_STRATEGY_TPO_M5 策略回测
11 UPDATE_TARGET_TPO_3 候选池
12 UPDATE_TARGET_TPO_TOP 候选池
13 UPDATE_TARGET_TPO_M5 候选池
14 UPDATE_TPO_M5_HL 5M 高低点

## 依赖
- ⑥ 加工日线 依赖 ⑤ 涨停列表（需要 is_top）。
- ⑦ 首板涨停 依赖 ⑥ 的 `is_volume_up` 字段。
- 候选池 / 高低点 依赖前面的回测与原始数据。
单独跑时按 ① ② ③ … 顺序即可，不必每次全量。

## 如何单独跑某项（三端一致，均走 CMD_RUN_STEP）
`CMD_RUN_STEP(step)` 定义在 `StrategyUI.py`，按 step 名映射到对应 `UPDATE_*` 函数并返回该步日志。
- CLI：`python Run.py` → 5 → 输入步骤编号（循环选择，0 返回）。
- Web：侧边栏「单项数据更新」区块按钮（localhost:8765，用户一般不用）。
- 协议：`marcoai://run?cmd=RUN_STEP&step=UPDATE_TOP`（双击 HTML 时）。
- 未知 step 返回可用列表，不会崩。

## 关键注意事项
- ③ / ④ 拉全市场原始行情依赖**通达信客户端运行 + 联网**，且很慢；UI 对 ORIGIN 步骤有二次确认。
- 跑完数据后，**必须重新生成离线看板（Run.py → 4）** 才能在 TAB 看到，看板不会实时读文件。
- 新增一个更新步骤的标准做法：在对应 `Update/*.py` 写 `UPDATE_XXX` 函数 → 在 `StrategyUI.py` 的 `_UPDATE_STEPS`、`Run.py` 的 `_UPDATE_STEP_ITEMS`、以及 `StrategyUI.py` 内 JS 数组 `UPDATE_STEPS` 三处登记同名 step → 前端 / 菜单自动出现。
