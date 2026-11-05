# 文件放置速查（FILE_ROUTING）

> **一句话：新东西该放哪，先看这张表；拿不准，问小文（文件管理大师）。**
> 本文件是"快查版"（约 6 KB），只回答**放哪 / 叫什么 / 要联动改哪**；
> 每个目录、每个文件的完整职责与数据字典在 [ARCHITECTURE.md](ARCHITECTURE.md)（约 70 KB，需要细节再查）。
> 目录树一键看：`python tools/print_tree.py`（默认 3 层）/ `python tools/print_tree.py AICode -d 4 --files`。
>
> 维护者：小文　｜　最后核对：2026-11-04（旧 UI / 离线看板已删除，新 UI = `dashboard/` + `tools/dashboard_server.py`）

## 1. 顶层各管什么（先看这一行）

| 位置 | 只负责 | 不要放 |
|---|---|---|
| `Run.py` | 唯一交互入口：菜单 + 非交互子命令 | 业务逻辑（放 AICode） |
| `AICode/MarcoAPI/Update/` | 数据管线：交易日历/股票池/1D/5M/指数/涨停/策略选股/路径 | 看板、回测、UI 代码 |
| `AICode/MarcoAPI/` | 长期模块：回测 `Backtest.py`、快捷命令 `StrategyUI.py`、K线 `KLine.py`、协议等 | 一次性研究脚本 |
| `AICode/MarcoAPI/UI/` | **旧前端残留**：仅 `MarcoUI/backend_data.py`（新 UI 的数据适配层，勿删）+ `__init__.py`；其余旧 UI 已删 | 新 UI 代码（放 `dashboard/`） |
| `dashboard/` | **新 UI 前端**（唯一看板）：`index.html` + `js/views/*` + `css/` + `vendor/`，免构建 | 业务数据、API 服务代码 |
| `tools/` | 服务与工具：`dashboard_server.py`（新 UI 服务）、`daily_update.py`（盘后 6 步）、`realtime_feed.py`、`next_day_strategy.py`、`export_index_5m.py`、`tdx_*`、`print_tree.py` | 业务脚本（放 AICode） |
| `AICode/` 根 | **一次性**研究/回测/诊断脚本 | 新的主链路模块 |
| `AIData/` | 全部数据（源数据入库，生成数据不入库）：`1D` `1D_ORIGIN` `5M` `INDEX` `INDEX_ORIGIN` `INDEX_5M` `INFO` `NEXT_DAY` `STRATEGY` `THS` `TOP` `TOP_FIRST` `TOP_ORIGIN` `DAILY` + 根清单文件 | 代码、脚本、文档 |
| `journals/`<br>`journals/coach/` | 复盘日志体系：`journals/` = 用户手工日志 + 小志的结构化总结/索引/标签；`journals/coach/` = 小小A 的 PLAYBOOK/USER_PROFILE/RUBRIC/REVIEW | 代码、数据、生成物 |
| `AIBook/` | 学习资料（PDF / 精读 md） | 项目文档 |
| 仓库根 | 仅 `README.md` / `ARCHITECTURE.md` / `FILE_ROUTING.md` / 入口 / 配置 | 新业务文件 |

## 2. 我要加 X，放哪？（决策表）

| 你要加的东西 | 放哪 | 命名 | 必须联动（漏了会不一致） |
|---|---|---|---|
| 数据更新步骤 | `AICode/MarcoAPI/Update/<领域>.py` 里的 `UPDATE_XXX()` | `UPDATE_<大写>` | ① `Update/Update1D.py::UPDATE_ALL` 的 `steps` 顺序　② `StrategyUI.py::_UPDATE_STEPS`　③ `Run.py::_UPDATE_STEP_ITEMS` |
| 新数据目录 | `AIData/<目录>/` | 与现有风格一致 | ① `Update/Path.py` 加路径函数　② `.gitignore` 判断（动态数据忽略 / 手工源数据用 `!` 入库）　③ ARCHITECTURE §5 登记 |
| 新策略 | `Update/SZ200Strategy.py` 加 `UPDATE_STRATEGY_XXX()` | 策略名大写，如 `TPO_M5` | 数据落 `AIData/STRATEGY/<策略>/YYYYMMDD`（29 列）；`StrategyUI._list_strategies()` 自动发现，新 UI/菜单 3 免改；进一条龙要加进 `UPDATE_ALL.steps` |
| 一次性研究/回测脚本 | `AICode/` 根 | `run_<主题>_backtest.py` / `diagnose_<主题>.py` | 文件头 docstring 写清：目的、数据源、产出目录、运行命令 |
| 长期维护模块 | `AICode/MarcoAPI/<领域>.py` | 大写开头，如 `Backtest.py` | 顶部 docstring（数据流/文件格式/API）；项目根 `sys.path` 注入的导入写法 |
| 新 UI 页面/交互 | `dashboard/`（页面 `js/views/<页面>.js` + 导航 `index.html`） | — | 无构建：改完刷新浏览器；新增数据要同步 `tools/dashboard_server.py` 与 `js/api.js` |
| 新 UI 接口 | `tools/dashboard_server.py` 的 `do_GET/do_POST` 路由 | `/api/<资源>` | 前端 `dashboard/js/api.js` 加封装；只读 AIData，不改业务数据 |
| 实时看盘数据/信号 | `tools/realtime_feed.py` + `dashboard/js/views/realtime.js` | — | 只读 AIData、不下单；持仓字段同步 `dashboard/holdings.json` 与 `/api/realtime/holdings` |
| 下一交易日名单 | `tools/next_day_strategy.py` → `AIData/NEXT_DAY/strategy.json` | — | 选股口径须与 `SZ200Strategy` 的 TPO_M5 一致；由 `daily_update.py` 第 5 步调用 |
| 盘后步骤 | `tools/daily_update.py` 的 `step_*` 函数 | — | 登记 6 步日志编号 + `--skip-*` 参数 + 失败是否阻断；ARCHITECTURE §3.3 同步 |
| 图表/前端库 | `dashboard/vendor/` | 保持原文件名 | `index.html` 的 `<script src>` 引用；不要引入 Node/打包流程 |
| 项目文档 | 根 `README.md` / `ARCHITECTURE.md`；快速查表 `FILE_ROUTING.md` | — | 文档索引同步（README §5） |
| 临时排查脚本 | `tools/` 或 `_` 前缀 | `_*.py` | 用完删除，不要留在根目录 |
| 复盘日志 / 教练知识库 | `journals/`（日志 + 结构化总结/索引/标签）或 `journals/coach/`（PLAYBOOK/USER_PROFILE/RUBRIC/REVIEW） | 文本 md，按日期/主题 | 文本入库，不进更新菜单；`journals/coach/` 只由小小A 维护 |

## 3. 命名规范（沿用现状）

- 数据文件：按日 `YYYYMMDD`（无扩展名）；股票/指数代码 `6 位数字 + .SH/.SZ`；策略目录大写（`TPO_M5`）。
- Python：模块大写开头（`SZ2001D.py`）；更新函数 `UPDATE_*`；私有工具 `_` 前缀。
- 一次性脚本：`diagnose_*.py`（只诊断不产数据）、`run_*_backtest.py`（产研究数据/回测）；`tools/` 下按用途命名（`dashboard_server.py`、`daily_update.py`…）。
- 新 UI：`dashboard/` 源码直接入库、**无构建产物**；`dashboard/holdings.json` 为用户本地数据（`dashboard/.gitignore` 忽略）；图表库放 `dashboard/vendor/`。
- 旧看板产物（`UI/StrategyDashboardOffline.html`、`UI/data/*`、`UI/vendor|lib`）已删除，**不要再生成或恢复**。

## 4. 绝对不要

1. **手改动态/生成数据**：`AIData/1D|1D_ORIGIN|5M|INDEX*|TOP*|STRATEGY|NEXT_DAY`（更新时整目录重建或工具原子重写，手工改动会丢）。
2. **在仓库根新增业务代码或数据**（根目录只留入口/文档/配置/日志）。
3. **建平行目录而不登记**：像 `AIData/5M_ORIGIN`、`AIData/ORIGIN` 那样只存在代码引用里的"幽灵目录"已造成 19 个失效路径函数；新目录必须先在 `Path.py` 登记。
4. **复活旧 UI**：`UI/MarcoUI/` 除 `backend_data.py` 外、离线看板 `StrategyDashboardOffline.html` + `UI/data/` 均已删除，新 UI 只走 `dashboard/` + HTTP API。
5. 把临时脚本/调试文件留在 `AICode/MarcoAPI/`（会被误认为主链路）。

## 5. 拿不准怎么办

问**小文（文件管理大师）**：告诉它三件事——**要加什么、属于哪条链路（数据/策略/新 UI/盘后工具/文档/复盘）、谁会用**。
它会用 3 行回答：**放哪 → 理由 → 要联动改哪**。若涉及删除/移动/改业务代码，它会转给 Lead 确认。
