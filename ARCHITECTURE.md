# MarcoAI 文件架构权威文档（ARCHITECTURE）

> **定位**：本文件是 C:\MarcoAI 仓库的“文件地图”，回答两类问题：**某个文件/目录是做什么的**、**新东西该放在哪**。
> **维护规则**：新增/删除/改名文件、数据目录或更新步骤时，**必须同步改本文件**；代码与文档冲突时以代码为准，并在“§8 已知问题”登记差异。
>
> - 文档版本：v1.1　更新日期：2026-11-04（旧 UI / 离线看板下线，新 UI 上线）
> - 数据快照：AIData 覆盖 **20260105 ~ 20261104**
> - 核验方式：逐文件读源码/抽样读真实数据（见 §10 核验记录），统计脚本现场生成；未实际读到的内容一律标 **【待确认】**，不做臆测。
> - 规模：仓库工作区共 **约 8,149 个文件**（不含 `.git`，约 434 MB；含本文件）；`git` 跟踪 **298 个文件**（旧 UI/看板已提交删除，见 §8.11）。
> - 姊妹文档：[README.md](README.md)（快速开始）；结构查看工具：[tools/print_tree.py](tools/print_tree.py)。

---

## 目录

1. [项目一句话定位](#1-项目一句话定位)
2. [顶层目录树](#2-顶层目录树)
3. [入口与运行方式](#3-入口与运行方式)
4. [代码文件清单（AICode）](#4-代码文件清单aicode)
5. [数据集字典（AIData）](#5-数据集字典aidata)
6. [端到端数据流](#6-端到端数据流)
7. [文件放置约定（新增东西放哪）](#7-文件放置约定新增东西放哪)
8. [已知问题与待清理项](#8-已知问题与待清理项)
9. [环境与外部依赖](#9-环境与外部依赖)
10. [核验记录与待确认问题](#10-核验记录与待确认问题)

---

## 1. 项目一句话定位

**MarcoAI = 中国 A 股「数据下载 → 加工 → 涨停/策略选股 → 回测 → 看板/同花顺落盘」的个人量化研究终端。**

- 数据源：通达信 `tqcenter` 插件（行情/交易日历）+ 同花顺「涨停分析」导出的 Excel（涨停股清单）+ `INFO/SZ100.xlsx`（股票池与流通股本）。
- 加工主线：前复权日线/5 分钟线 → 派生字段（涨跌幅/阴阳/量能/MA/连板/涨跌停）→ TOP 涨停清单与 TOP_FIRST 首板 → TPO_M5 策略选股 → 回测 → **同花顺板块 XML / 新本地看板（`dashboard/` + `tools/dashboard_server.py`）**。
- 入口三件套：`python Run.py`（交互菜单：数据更新 / 同花顺 / Git）；`python tools/dashboard_server.py`（新 UI：浏览器打开 http://127.0.0.1:8765）；`python tools/daily_update.py`（盘后 6 步总控）。旧 `MarcoUI` 桌面端与离线看板均已下线（2026-11-04 删除）。

---

## 2. 顶层目录树

`[D]` = 目录，`[F]` = 文件。文件数/体积为 2026-11-03 现场统计（不含 `.git`）。

```
C:\MarcoAI\                                        约 8,149 files ≈ 434 MB（含本文档；不含 .git）
├─ [F] Run.py                         27,752 B    ★ 唯一总入口：交互菜单 + 非交互子命令
├─ [F] README.md                     约 8.3 KB    ★ 项目门面（快速开始）
├─ [F] ARCHITECTURE.md               约 70 KB     ★ 本文件（文件地图）
├─ [F] FILE_ROUTING.md               约 7 KB      ★ 文件放置速查（快查版，新人先看）
├─ [F] XIAOA_UI_REQUIREMENTS.md     约 52 KB      新 UI v1 需求与验收清单（小小A 维护）
├─ [F] .gitignore                      1,514 B    忽略数据/构建产物/日志的规则
├─ [F] pyrightconfig.json                612 B    Pyright 类型检查放宽配置
├─ [F] update_log.txt                  527,701 B  一条龙数据更新日志（每次被覆盖；已 gitignore）
├─ [F] _check_inline.py                  1,174 B  一次性排查脚本：校验离线看板是否真内联了图表库
├─ [F] _esprima_final.py                 779 B    一次性排查脚本：用 esprima 检查看板内嵌 JS 语法
├─ [F] _regen_proper.py                  504 B    一次性排查脚本：重新生成离线看板并校验内联
│
├─ [D] AICode\                            36 files  529.2 KB   ★ 全部业务代码
│   ├─ [F] _update_log.txt              66,326 B   历史日志（2026-08 旧运行，仍被 git 跟踪）
│   ├─ [F] diagnose_cap.py               3,851 B   一次性研究：市值效应/排序键贡献诊断
│   ├─ [F] diagnose_composite.py         4,307 B   一次性研究：组合特征诊断
│   ├─ [F] diagnose_signals.py           3,640 B   一次性研究：形态信号有效性诊断
│   ├─ [F] run_capfilt_backtest.py       5,679 B   一次性研究：大盘优先+形态否决回测
│   ├─ [F] run_capfilt_forward.py        8,051 B   一次性研究：防过拟合前向测试
│   ├─ [F] run_decision_backtest.py     10,751 B   一次性研究：决策树选股回测
│   ├─ [F] run_score_backtest.py         9,136 B   一次性研究：加权打分选股回测
│   ├─ [D] __pycache__\                  3 files           Run.py 等的字节码
│   └─ [D] MarcoAPI\                     28 files 420.1 KB  ★ 核心包
│       ├─ [F] __init__.py                   0 B
│       ├─ [F] Backtest.py              20,154 B    ★ 回测引擎（first/last/avg/5m 四种卖出）
│       ├─ [F] KLine.py                 30,916 B    独立 K 线 HTML 生成工具（当前无调用方）
│       ├─ [F] StrategyUI.py           217,423 B    ★ 快捷命令中心（CMD_*；旧看板生成部分已下线，4283 行）
│       ├─ [F] MarcoAPI.py               1,689 B    旧版 BaoStock 管线入口（import 的文件已不存在）
│       ├─ [F] MarcoAI_Handler.py        3,942 B    `marcoai://` 协议处理器
│       ├─ [F] register_protocol.py      1,883 B    注册 `marcoai://` 协议到 Windows 注册表
│       ├─ [F] EntryTimingAnalysis.py   11,781 B    旧的情感/入场时机分析（读已不存在的数据）
│       ├─ [D] Update\                  54 files  0.5 MB   ★ 数据管线（14 个 .py + __pycache__）
│       ├─ [D] Skills\                   4 files  0.0 MB   TPO_M5_2.0 策略骨架 + 威科夫参考文档
│       └─ [D] UI\                       2 files  0.0 MB   旧前端残留（2026-11-04 清理，仅剩 backend_data.py）
│           ├─ [F] __init__.py                 0 B
│           └─ [D] MarcoUI\              1 file   18.5 KB   backend_data.py：只读数据适配层（dashboard_server 复用）
│
├─ [D] AIData\                         6,155 files 119.0 MB  ★ 全部数据（多数不入库）
│   ├─ [F] TRADING_DATES                  1,998 B   200 行交易日（YYYYMMDD）
│   ├─ [F] STOCK_CODES                    7,445 B   677 行代码（无名称；无代码引用，来历待确认）
│   ├─ [F] STOCK_CODES_ALL              103,741 B   3,048 行 `代码|名称|流通股本`
│   ├─ [F] INDEX_CODES                      245 B   11 行 `代码|名称`
│   ├─ [F] INDEX_5M_CODES                   378 B   17 行 `代码|名称`（指数/宽基/ETF 5m 代码清单）
│   ├─ [D] 1D\                          2,522 files 56.0 MB    加工日线（25 列）
│   ├─ [D] 1D_ORIGIN\                   2,522 files 24.4 MB    原始前复权日线（7 列）
│   ├─ [D] 5M\                            253 files 12.8 MB    5 分钟线（13 列，窗口化，不连续）
│   ├─ [D] INDEX\                          11 files  0.3 MB    加工指数日线（25 列）
│   ├─ [D] INDEX_ORIGIN\                   11 files  0.1 MB    原始指数日线（7 列）
│   ├─ [D] INDEX_5M\                       17 files 18.0 MB    指数/宽基/ETF 5 分钟全量（13 列，20260105~）
│   ├─ [D] TOP\                           200 files  0.2 MB    每日涨停代码（YYYYMMDD）
│   ├─ [D] TOP_FIRST\                     200 files  0.1 MB    每日首板涨停代码
│   ├─ [D] TOP_ORIGIN\                    200 files  5.8 MB    同花顺涨停分析 xlsx（手工导入源）
│   ├─ [D] STRATEGY\                      200 files  0.1 MB    `STRATEGY/TPO_M5/YYYYMMDD`（29 列，GBK）
│   ├─ [D] NEXT_DAY\                         1 file  1.3 KB    `strategy.json`：下一交易日 TPO_M5 名单（新 UI 实时看盘读）
│   ├─ [D] INFO\                            2 files  0.4 MB    SZ100.xlsx（股票池）、指数.xlsx（指数池）
│   ├─ [D] THS\                             1 file   0.0 MB    同花顺板块 XML 模板
│   └─ [D] DAILY\                           1 file   0.0 MB    Daily.txt：手工交易笔记（149 行）
│
├─ [D] AIBook\                             2 files 39.4 MB    学习资料（威科夫盘口解读 PDF + 精读 md）
├─ [D] tools\                              9 files 177.4 KB   新 UI 服务 / 盘后总控 / 通达信导出 / 目录树工具
├─ [D] dashboard\                         22 files 601.6 KB  ★ 新 UI 前端（免构建 ES Modules + 本地 vendor 图表库）
├─ [D] journals\                         14 files  93.3 KB   用户复盘日志体系：手工日志 + 小志的结构化总结/索引/标签（文本，入库）
│   └─ [D] coach\                          5 files  60.6 KB   小小A 超短线教练知识库：PLAYBOOK/USER_PROFILE/RUBRIC/REVIEW（文本，入库）
├─ [D] .codebuddy\                         4 files           AI 助手本地配置 + 2 份**已过期**的 SKILL.md
├─ [D] .vscode\                            2 files           VSCode 调试/分析配置
├─ [D] __pycache__\                        2 files           根目录字节码（Run.py 等）
└─ [D] .git\                                             版本库（298 个跟踪文件）
```

### 2.1 体积构成（回答“现在为什么 ≈434 MB”）

| 部分 | 文件数 | 体积 | 是否入库 | 说明 |
|---|---:|---:|---|---|
| `AIData/1D + 1D_ORIGIN` | 5,046 | 80.9 MB | 否 | 动态数据，可用 UPDATE_ALL 重生成 |
| `AIData/5M` | 255 | 12.9 MB | 否 | 窗口化数据，可重下 |
| `AIData/INDEX_5M` | 17 | 18.0 MB | 否 | 指数/宽基/ETF 5m 全量，`tools/export_index_5m.py` 重建 |
| `AIData/TOP_ORIGIN` | 202 | 5.8 MB | **是** | 手工导入的源数据，丢了无法重造 |
| `dashboard/` | 22 | 0.6 MB | 是 | 新 UI 前端源码（含 `vendor/` 图表库 0.4 MB） |
| `journals/` | 14 | 0.1 MB | 是 | 复盘日志与教练知识库（纯文本） |
| 其余代码/文档 | ~250 | ~3 MB | 是 | `AICode/` 36 文件 0.5 MB + `tools/` 0.2 MB + 根文档 |

> 结论：旧 `UI/MarcoUI/.venv|build|dist`（约 1.3 GB）与 `UI/data`（98.6 MB）已随旧 UI 删除，仓库从约 1.54 GB 降到约 **434 MB**；`.tools/`、`.edge-profile/`、`logs/` 等本地运行时目录不入库。当前最大项是 `AIData` 的日线数据。

### 2.2 哪些数据入库（`.gitignore` 实际效果）

`.gitignore` 的核心策略：**代码 + 手工源数据入库；动态生成的数据/构建产物/日志/虚拟环境不入库。**

| 规则 | 实际效果 |
|---|---|
| `AIData/*` + 4 条 `!` 反选（`TOP_ORIGIN/`、`INFO/`、`THS/`、`DAILY/`） | 只有 **手工源数据**入库；`1D`、`1D_ORIGIN`、`5M`、`INDEX*`、`TOP`、`TOP_FIRST`、`STRATEGY`、`INDEX_5M`、`NEXT_DAY`、`STOCK_CODES*`、`TRADING_DATES` 等动态数据全部忽略 |
| `dashboard/.gitignore` | `holdings.json`（用户持仓，本地数据）不入库 |
| `.tools/`、`.edge-profile/`、`.downloads/`、`logs/` | 本地自动化运行态（浏览器配置 / 下载 / 盘后日志）忽略 |
| `*.log`、`update_log.txt`、`__pycache__/`、`*.pyc`、`.codebuddy/`、`AIData/5M/` | 日志/字节码/本地 AI 配置忽略 |
| `.venv/`、`venv/`、`dist/`、`build/`、`*.spec`、旧 `UI/MarcoUI/*` 排查日志规则 | 旧桌面端遗留规则：对应文件已删除，规则仍残留在 `.gitignore`（待清理，见 §8.1） |
| **未被忽略、仍被跟踪** | `dashboard/`（22 文件）、`tools/`、`journals/`、`AIData/TOP_ORIGIN`、`AIData/INFO`、`AIData/THS`、`AIData/DAILY`、旧日志 `AICode/_update_log.txt` |

---

## 3. 入口与运行方式

### 3.1 `Run.py`（唯一总入口）

- 位置：仓库根 `Run.py`；运行方式 `cd C:\MarcoAI && python Run.py`。
- 结构：`main()` → 无参数进 `_menu_loop()`；有参数走**非交互子命令**（供 `tools/` 脚本/快捷调用使用，不重写更新逻辑）。旧桌面端桥接已移除。

**交互菜单（实测输出；菜单 4「离线看板」与菜单 8「启动新UI」已于 2026-11-04 删除）**：

| 菜单 | 名称 | 实际调用 | 写入/副作用 |
|---|---|---|---|
| 1 | 更新数据 | `UPDATE_ALL()`（`Update/Update1D.py`，11 步，无看板步骤） | 全套 AIData（见 §6.1） |
| 2 | 更新5M数据 | `UPDATE_5M_PANELS()`（`Update/SZ2005M.py`） | 重写 `AIData/5M`（仅策略涉及股、按关键日 T-2~T+5 窗口） |
| 3 | 更新同花顺 | `CMD_UPDATE_THS(策略)`（`StrategyUI.py`） | 覆盖同花顺目录下 `blockstockV3.xml` |
| 5 | 单项更新 | `CMD_RUN_STEP(step)`（11 个 step，见 §6.2） | 只跑所选那一步 |
| 6 | 上传 Gitee | `_git_push("origin")` → gitee.com/mingxuel/MarcoAI | git commit/push |
| 7 | 上传 GitHub | `_git_push("github")` → github.com/mingxuel/MarcoAI | git commit/push |
| 88 | 一条龙更新 | 倒计时选择策略/周期 → 更新数据(含5M) → 更新同花顺（Gitee 默认关闭） | 同 1+3；**不再有看板步骤** |
| 0 | 退出 | — | — |

**非交互子命令**（`python Run.py <cmd>`）：

| 命令 | 行为 |
|---|---|
| `update_all` | 等价菜单 1（`UPDATE_ALL` 已不含看板生成；不含同花顺/Git 上传） |
| `update_5m` | 等价菜单 2，并清理 `5M.old_*` 残留目录 |
| `update_ths [策略]` | 等价菜单 3，默认策略 `TPO_M5` |
| `step <UPDATE_标识>` | 等价菜单 5 的单项更新 |

> `python Run.py ui` 已删除（随菜单 8 一起移除）。

### 3.2 新 UI（唯一看板）—— `dashboard/` + `tools/dashboard_server.py`

```
启动：python tools/dashboard_server.py --port 8765   （或 dashboard/启动看板.bat）
浏览器：http://127.0.0.1:8765/
  dashboard/index.html（免构建，原生 ES Modules + vendor/lightweight-charts 本地库）
   └─ js/main.js → views/{workspace,backtest,picks,realtime}.js
        └─ fetch /api/* → tools/dashboard_server.py（ThreadingHTTPServer 静态托管 + API）
             └─ 只读 AIData：importlib 加载 UI/MarcoUI/backend_data.py → StrategyUI 解析器 + Update.Path
```

- 四个页面 TAB：**K 线工作区 / 策略回测 / 策略选股 / 实时看盘**（v1.4）。
- API：`/api/health`、`/api/meta`、`/api/strategies`、`/api/dashboard`、`/api/picks`、`/api/kline`、`/api/symbols`、`/api/realtime`、`/api/realtime/kline`、`/api/realtime/holdings`（GET/POST）。
- 实时看盘：`tools/realtime_feed.py` 用 tqcenter 快照 ~2s 轮询（只判断、不下单）；`AIData/NEXT_DAY/strategy.json` 提供下一交易日 TPO_M5 名单；持仓 `dashboard/holdings.json`（本地不入库，POST 由服务端原子写回）。
- 服务只读 AIData、不写业务数据；`backend_data` 不可用时接口降级为 `ok=false / degraded=true`，服务仍可启动。
- 无构建、无 Node、无 PySide6；前端全部原生 ES Modules + 本地 vendor 库，可离线渲染。
- 旧 `UI/MarcoUI` 桌面端、`StrategyUI.GENERATE_STRATEGY_UI_OFFLINE()` 生成的离线看板及 `UI/data|lib|vendor` 均已删除（函数本体保留但无调用方）。

### 3.3 `tools/daily_update.py` —— 盘后 6 步总控

供「每日更新大师」在交易日 15:50 后执行；结果写控制台 + `logs/daily_update_<时间>.json/.log`。

| # | 步骤 | 动作 | 失败策略 |
|---|---|---|---|
| 1 | 网页导出 | Edge 从通达信「问小达」导出当日涨停 xlsx → `AIData/TOP_ORIGIN`（内容相同则跳过；不同先备份 `.bak`） | 中断（返回码 3） |
| 2 | 通达信本地数据 | **默认不自动刷新**（数据由用户手动执行「盘后数据下载」），但**仍校验**是否当日最新；不新鲜标 `NEEDS_MANUAL`。加 `--with-tdx` 才尝试 `refresh_kline` 自动刷新 | 中断（返回码 2） |
| 3 | 指数/宽基 5m | `tools/export_index_5m.py` 全量导出 → `AIData/INDEX_5M`（17 只，13 列） | 只告警 |
| 4 | 一条龙 | 复用 `UPDATE_ALL(scope=近 N 个月涨停股, recent_days_5m)`；**同花顺板块默认自动更新**（`--no-ths` 可跳过）；**Gitee 默认关闭**（`--with-git` 才上传） | 中断（返回码 4） |
| 5 | 下一交易日名单 | `tools/next_day_strategy.py` → `AIData/NEXT_DAY/strategy.json` | 不阻断 |
| 6 | 重启新 UI 服务 | 停旧 `dashboard_server` 进程并重启（避免页面用到启动时的旧缓存） | 不阻断，汇总标记 |

常用参数：`--dry-run`（只体检）/ `--with-tdx`（自动检测/尝试刷新通达信本地数据；默认跳过，改手动）/ `--skip-export` / `--skip-pipeline` / `--months 12` / `--no-ths`（跳过同花顺；**默认自动更新**）/ `--with-git`（上传 Gitee；默认关闭）。

### 3.4 `marcoai://` 协议（可选）

`register_protocol.py`（注册表）→ `MarcoAI_Handler.py`（解析 `marcoai://run?cmd=UPDATE_DATA|UPDATE_THS|GIT_SYNC|RUN_STEP&strategy=...&step=...`）→ 调 `StrategyUI.CMD_*` → tkinter 弹框显示结果，并追加日志到 `AIData/run.log`。
> 现状：仅 `StrategyUI.py` 内一段界面文案提到它；`Run.py` 不使用。

---

## 4. 代码文件清单（AICode）

> 表头说明：**被谁 import** 指仓库内引用方（只统计实际 `import`/字符串引用）；**读写数据** 只列 AIData 路径；**状态**：★活跃 / 备用（可运行但无主链路调用）/ 遗留（不可运行或已被替代）。

### 4.1 `AICode/MarcoAPI/Update/` —— 数据管线（14 个 .py）

| 文件 | 职责 | 关键函数/入口 | 被谁 import | 读写数据 | 状态 |
|---|---|---|---|---|---|
| `__init__.py` | 空包标记 | — | Python 包机制 | — | ★ |
| `Path.py` | **所有数据路径的唯一来源**；`PROJECT_ROOT` 由本文件位置上溯 4 级推导 | `PATH_AIDATA*()`、`PATH_TDX()` 等 40+ 个函数 | 几乎所有模块（`from ...Path import *`） | 只造路径，不读写 | ★（含大量失效函数，见 §8.5） |
| `Constants.py` | 全局常量 | `START_DATE = "20260101"`、`MAX_WORKERS = 16` | Update 各模块 `import *` | — | ★ |
| `Data.py` | 数据模型（dataclass） | `DATA_1D`（25 字段）、`DATA_5M`（13 字段）、`DATA_1D_TARGET`（未使用） | SZ2001D / SZ2005M / SZ200Strategy | — | ★ |
| `progress.py` | 兼容 tqdm 接口的单行进度条（强制 `\r` 原地刷新，日志里不刷屏） | `ProgressBar(total, desc)`、`update()`、`set_postfix()` | Update 各模块 | — | ★ |
| `TradingDates.py` | 交易日历维护与查询 | `TRADING_DATES()`、`UPDATE_TRADING_DATES()`、`TRADING_DATE_PREVIOUS/AFTER()`、`EFFECTIVE_LATEST_TRADING_DATE()` | SZ2001D/SZ200Top/SZ200Index/SZ200Strategy/Update1D/StrategyUI/DataAligned | 读/写 `AIData/TRADING_DATES` | ★ |
| `StockCodes.py` | 股票池与流通股本 | `STOCK_CODES()`、`UPDATE_STOCK_CODES()`、`STOCK_CODES_ALL()`、`GET_STOCK_INFO()` | SZ2001D/SZ200Top/SZ2005M/SZ200Strategy/StrategyUI/Skills | 读 `AIData/INFO/SZ100.xlsx`；读写 `AIData/STOCK_CODES_ALL` | ★ |
| `SZ200Top.py` | 涨停/首板清单 | `UPDATE_TOP()`（TOP_ORIGIN xlsx→TOP）、`UPDATE_TOP_FIRST()`（涨停−昨日涨停）、`IS_TOP()`、`GET_TOP()` | Update1D、StrategyUI | 读 `TOP_ORIGIN/*.xlsx`；写 `TOP/`、`TOP_FIRST/`；读 `TOP/`（判首板） | ★ |
| `SZ2001D.py` | **日线核心**：原始下载 + 加工 | `UPDATE_1D_ORIGIN()`、`UPDATE_1D()`、`GET_SZ200_1D_PREVIOUS/AFTER/ALL()`、`_rotate_dir()`、`_PARSE_DATA_1D()`、`_MA_PERIODS` | Update1D、SZ200Index、SZ2005M、SZ200Strategy、StrategyUI、`AICode/*.py` 研究脚本、Skills | 读写 `1D_ORIGIN/`、`1D/`；读 `TOP/`（判 is_top/lian_ban）；经 tqcenter 拉行情 | ★ |
| `SZ200Index.py` | 指数日线（与 1D 平行，无涨停/连板） | `UPDATE_INDEX_CODES()`、`UPDATE_INDEX_1D_ORIGIN()`、`UPDATE_INDEX_1D()`、`INDEX_CODES()`、`GET_INDEX_NAME()` | Update1D、StrategyUI | 读 `INFO/指数.xlsx`；读写 `INDEX_CODES`、`INDEX_ORIGIN/`、`INDEX/` | ★ |
| `SZ2005M.py` | 5 分钟线：全历史下载 / 窗口下载 / 按需补数 | `UPDATE_5M_ORIGIN()`、`UPDATE_5M_PANELS()`、`DOWNLOAD_5M_ONE()`、`GET_SZ200_5M*()` | Update1D、Run.py、StrategyUI、backend_data | 读写 `5M/`；读 `STRATEGY/*` 收集涉及股；经 tqcenter 拉行情 | ★ |
| `SZ200Strategy.py` | **策略选股**（TPO 家族）+ 情绪曲线 | `UPDATE_STRATEGY_TPO_M5/TPO_3/TPO_TOP/TPO_M5_SMALL()`、`GENERATE_STRATEGY_TPO()`、`GET_STRATEGY_TPO_WINDOW()`、`BUILD_SENTIMENT_KLINE()`、`_rotate_dir`（转出口） | Update1D、StrategyUI、Skills | 读 `1D/`、`STOCK_CODES_ALL`、`TRADING_DATES`；写 `STRATEGY/<策略>/YYYYMMDD`（29 列） | ★（仅 TPO_M5 进主链路） |
| `Update1D.py` | **一条龙总编排** `UPDATE_ALL()`：按依赖顺序跑 11 步，逐步日志写 `update_log.txt`，末尾清 `.old_*` | `UPDATE_ALL(scope_codes=None, recent_days_5m=0)`、`_remove_dir_safe()`、`_cleanup_old_dirs()` | Run.py、StrategyUI | 写根目录 `update_log.txt`；调度所有数据目录 | ★ |
| `DataAligned.py` | 全宽日期对齐文件读写工具（旧） | `WRITE_ALIGNED_FILE()`、`READ_ALIGNED_LINES()`、`ALIGNED_DATES()` | 无（0 引用） | 按 `TRADING_DATES` 对齐写文件 | 遗留 |

### 4.2 `AICode/MarcoAPI/` 根模块

| 文件 | 职责 | 关键函数/入口 | 被谁 import | 读写数据 | 状态 |
|---|---|---|---|---|---|
| `__init__.py` | 空包标记 | — | — | — | ★ |
| `Backtest.py` | **回测引擎**：复利、买卖双边手续费（佣金万1免5 + 印花税千0.5）、四种卖出：`first`/`last`/`avg`/`5m`（5 分钟日内：触涨停→涨停价、跌破止损→当根收盘、否则 14:55 收盘） | `BACKTEST(strategy_name, sell_modes)`（返回 `{卖出方式: 结果文本}`）、`_load_strategy()`、`_sell_price_1d/5m()`、`_trade_net_return()`、`_backtest()` | StrategyUI（复用内部函数）、7 个 `AICode/*.py` 研究脚本 | 读 `STRATEGY/<策略>/`、`5M/`。**注意**：模块 docstring 声称输出 `STRATEGY/RESULT/<策略>.txt`，但实现只返回文本、不写文件（见 §8.8） | ★ |
| `KLine.py` | 独立图表工具：任意 `|` 分隔 OHLCV 文件 → 单文件 K 线 HTML（含 MA、HP 趋势、信号、涨跌家数柱状图） | `SHOW_K_LINE()`、`SHOW_K_LINE_WITH_SIGNALS()`、`SHOW_WIN_COUNT()` | 无（0 引用） | 读调用方传入文件；写 `UI/<输入文件名>.html`、`*_with_signals.html`、`*.win_count.html` | 遗留（仍可用） |
| `StrategyUI.py` | **快捷命令中心 + 看板生成器（生成部分已下线）**（4283 行，主体是内联 HTML/JS 模板）：在用 `CMD_UPDATE_DATA()`、`CMD_UPDATE_THS()`、`CMD_RUN_STEP()`、`_list_strategies()`、`_build_strategy_payload()`、`_load_candidates/top/top_first`、`_read_5m_window(s)`；死代码 `GENERATE_STRATEGY_UI_OFFLINE()`、`GENERATE_STRATEGY_UI()`、`_write_offline_data()`、`_render_html()`（0 调用方） | Run.py、MarcoAI_Handler（延迟导入）、`UI/MarcoUI/backend_data.py`（新 UI 经 dashboard_server 复用） | 读 `STRATEGY/`、`1D/`、`1D_ORIGIN/`、`INDEX_ORIGIN/`、`INDEX/`、`TOP/`、`TOP_FIRST/`、`5M/`、`THS/*.xml`、`INFO`；写同花顺 `blockstockV3.xml`（**不再写任何 UI 产物**） | ★ |
| `MarcoAPI.py` | 旧版 BaoStock 数据管线入口（交易日/复权因子/原始行情/复权转换） | `UPDATE_ORIGIN_DATA_1D/5M()`、`SZ200_ORIGIN_*()` 等 | 无 | 会写 `AIData/ORIGIN`、`AIData/ORIGIN/ADJUST_FACTOR` 等 | 遗留（**不可运行**：`BaoStockAPI`/`Converter` 模块已不存在） |
| `MarcoAI_Handler.py` | `marcoai://` 协议处理器：解析 URL → 执行 `UPDATE_DATA/UPDATE_THS/GIT_SYNC/RUN_STEP` → tkinter 弹框 + 写 `AIData/run.log` | `main(argv)`、`_run_cmd()`、`GIT_SYNC()` | Windows 协议注册（非 import） | 写 `AIData/run.log` | 备用 |
| `register_protocol.py` | 把 `marcoai://` 写入注册表（HKCR 或 HKCU `--user`），指向 `pythonw MarcoAI_Handler.py "%1"` | `main()` | 无 | 注册表（非文件） | 备用 |
| `EntryTimingAnalysis.py` | 旧版“入场时机分析”：9 类信号 × 6 个持仓周期回测排名 | `main()`、`load_data()`、`build_features()`、`backtest_strategy()` | 无 | 读 `AIData/1D_MOTION`（**当前不存在**）；只打印，不落盘 | 遗留 |

### 4.3 `AICode/MarcoAPI/Skills/TPO_M5_2.0/`（策略 Skill 骨架）

| 文件 | 职责 | 状态 |
|---|---|---|
| `SKILL.md` | TPO_M5_2.0 的定位：与 TPO_M5 基础条件一致，**待改进 2 处**（选股排序 `rank_select`、T-0 卖出 `t0_sell`），参考威科夫量价方法 | 骨架 |
| `__init__.py` | 包说明（5 行 docstring） | 骨架 |
| `tpo_m5_2_0.py` | `GENERATE_TPO_M5_2_0()`：复用 TPO_M5 基础过滤，两个 TODO 钩子当前默认等价 TPO_M5；输出 `AIData/Strategy/TPO_M5_2.0`（**尚未生成**） | 骨架（TODO 未实现） |
| `威科夫盘口解读方法_总结.md` | 威科夫《Studies in Tape Reading》结构化笔记（三大定律/吸筹派发结构/量价信号速查/第十节落地建议） | 参考文档 |

### 4.4 `AICode/MarcoAPI/UI/` —— 旧前端残留（已清理，仅 backend_data.py 保留）

**UI 根（2 个文件）**

| 文件 | 是什么 | 状态 |
|---|---|---|
| `__init__.py` | 空包标记 | ★ |
| `MarcoUI/backend_data.py` | 数据适配层：`get_dashboard()`、`load_kline()`（1d/5m/15m/30m；5M 缺失走 `DOWNLOAD_5M_ONE` 按需补数）、`get_strategy_pick()`、`get_strategies()`；**只读 AIData**；被 `tools/dashboard_server.py` 复用 | ★ |
| 已删除（2026-11-04） | `StrategyDashboardOffline.html(.meta.json)`、`UI/data/`、`UI/lib/`、`UI/vendor/`、`lc.min.js`、15 个旧图表 HTML；`MarcoUI/` 除 `backend_data.py` 外全部（app.py、build.py、build/、dist/、.venv/、*.js/*.css/*.html、bat、spec、install.ps1） | — |

### 4.5 `dashboard/` —— 新 UI 前端（免构建）

| 文件/目录 | 职责 |
|---|---|
| `index.html` | 入口：顶栏 + 四个视图容器；加载 `vendor/lightweight-charts…js` 与 `js/main.js`（module） |
| `css/styles.css` / `css/realtime.css` | 暗色主题样式 |
| `js/main.js` / `store.js` / `api.js` / `util.js` / `chart_adapter.js` / `realtime_chart.js` | 顶栏装配/视图切换/快捷键；工作区状态 + 预设 + localStorage；fetch 封装（超时/JSON 校验）；轻量图表适配 + 指标（MA/BOLL/MACD/KDJ/VOL）；实时看盘迷你图 |
| `js/views/workspace.js` | 多面板 K 线工作区（1/2/4 图；主工作区与选股页左侧共用） |
| `js/views/backtest.js` | 策略回测页（策略/买入/卖出方式三下拉 + 资金曲线 + 月度盈亏） |
| `js/views/picks.js` | 策略选股页（左 65% K 线 + 右 35% 列表，可拖拽分栏） |
| `js/views/realtime.js` | 实时看盘页（候选买点 + 持仓卖点，2s 轮询） |
| `js/components/pick_list.js` / `js/adapters/picks_adapter.js` | 列表渲染组件 `PickList` 与数据适配层（`/api/picks`，预留多来源扩展点） |
| `vendor/` | 本地图表库（lightweight-charts 等 3 个文件，0.4 MB），离线可用 |
| `holdings.json` | 用户持仓（本地数据，`dashboard/.gitignore` 忽略） |
| `启动看板.bat` / `README.md` | 一键启动脚本 / 页面功能说明 |

### 4.6 `tools/` —— 新 UI 服务与盘后工具

| 文件 | 职责 |
|---|---|
| `dashboard_server.py` | 新 UI 唯一服务：静态托管 `dashboard/` + 只读 API（见 §3.2），复用 `UI/MarcoUI/backend_data.py` |
| `daily_update.py` | 盘后 6 步总控（见 §3.3） |
| `realtime_feed.py` | 实时看盘数据源：tqcenter 快照 ~2s 轮询 + 环境/宽度/买卖判断 |
| `next_day_strategy.py` | 下一交易日 TPO_M5 名单（选股口径同 `SZ200Strategy`）→ `AIData/NEXT_DAY/strategy.json` |
| `export_index_5m.py` | 指数/宽基/ETF 5m 全量导出 → `AIData/INDEX_5M`（并维护 `INDEX_5M_CODES`） |
| `tdx_download.py` / `tdx_refresh.py` / `tdx_top_export.py` | 通达信盘后数据下载 / `refresh_kline` 刷新 / 「问小达」涨停 xlsx 导出 |
| `print_tree.py` | 目录树查看器 |

### 4.7 `AICode/` 根下的一次性研究脚本（7 个）

均为“读 `STRATEGY/TPO_M5` + `1D`，用 `Backtest` 口径重排/打分，产出对比回测”的一次性研究；**不进入任何主链路**，`SRC_DIR` 固定为 `AIData/Strategy/TPO_M5`。

| 文件 | 目的 | 产出目录（当前均不存在） |
|---|---|---|
| `diagnose_cap.py` | 诊断市值效应与各排序键的独立贡献 | 无（只打印） |
| `diagnose_composite.py` | 组合特征（空间/形态/MA/影线）叠加市值约束的诊断 | 无（只打印） |
| `diagnose_signals.py` | 把候选按 Daily.txt 各理解维度分组，看哪些维度真有 edge | 无（只打印） |
| `run_score_backtest.py` | 加权 `BuyScore`（7 因子）+ 门槛选股，回测对比 | `AIData/Strategy/TPO_SCORE` |
| `run_decision_backtest.py` | 一票否决 + 及格线 + 字典序排序键的决策树选股 | `AIData/Strategy/TPO_DECISION` |
| `run_capfilt_backtest.py` | 大盘优先 + 3 条形态否决（无空间/短上影/MA60 上方下坡） | `AIData/Strategy/TPO_CAPFILT` |
| `run_capfilt_forward.py` | 防过拟合前向测试（H1 选规则 → H2 验证） | `AIData/Strategy/TPO_CAPFILT_H1/H2`（脚本内命名） |

### 4.8 `AICode` 内部 import 关系（文字版）

```
Run.py
 ├─ Update.Update1D.UPDATE_ALL
 ├─ Update.SZ2005M.UPDATE_5M_ORIGIN/PANELS
 ├─ Update.Path.PATH_AIDATA
 └─ StrategyUI.{CMD_UPDATE_THS, CMD_RUN_STEP, _list_strategies}

StrategyUI
 ├─ Backtest（复用 _load_strategy/_sell_price_*/_trade_net_return…）
 └─ Update.SZ2001D / SZ200Index / SZ200Strategy / StockCodes /
     TradingDates / SZ200Top / SZ2005M / Path / Update1D

Update.Update1D.UPDATE_ALL（11 步）
 ├─ TradingDates.UPDATE_TRADING_DATES
 ├─ StockCodes.UPDATE_STOCK_CODES
 ├─ SZ2001D.UPDATE_1D_ORIGIN / UPDATE_1D
 ├─ SZ200Index.UPDATE_INDEX_CODES / UPDATE_INDEX_1D_ORIGIN / UPDATE_INDEX_1D
 ├─ SZ200Top.UPDATE_TOP / UPDATE_TOP_FIRST
 ├─ SZ200Strategy.UPDATE_STRATEGY_TPO_M5
 └─ SZ2005M.UPDATE_5M_PANELS（置末尾）
    （2026-11-04 起不再调用任何看板生成函数）

新 UI：tools/dashboard_server.py → importlib 加载 UI/MarcoUI/backend_data.py
        backend_data.py → StrategyUI（解析器）+ Update.Path + SZ2005M.DOWNLOAD_5M_ONE
        dashboard/js/* → fetch /api/* → dashboard_server.py
盘后总控：tools/daily_update.py → tdx_top_export / tdx_refresh / export_index_5m
        → UPDATE_ALL → CMD_UPDATE_THS → next_day_strategy → dashboard_server 重启
```

---

## 5. 数据集字典（AIData）

> 通用约定：股票代码 `6 位数字 + .SH/.SZ`（6/9 开头 .SH，其余 .SZ；指数按 3 开头 .SZ、其余 .SH）；日期文件名一律 `YYYYMMDD`；文本文件一律 `|` 分隔、无表头、一行一条。
> **编码**：`1D/1D_ORIGIN/INDEX*/TOP*/TRADING_DATES/STOCK_CODES*/INDEX_CODES` 均为 ASCII/UTF-8；**`STRATEGY/` 下文件由 `open(..., "a")` 以系统默认编码写入，本机为 GBK**（股票名为中文），读取端一律用多编码回退（`_read_text`/`_read_lines`）。

### 5.1 根目录 5 个输入/索引文件

| 文件 | 格式/样例 | 行数 | 生成者 | 消费者 |
|---|---|---:|---|---|
| `TRADING_DATES` | `20260105` / `20260106` … | 200（2026-01-05 ~ 2026-11-03） | `UPDATE_TRADING_DATES()`（tqcenter `get_trading_dates`） | 全部加工/回测/新 UI |
| `STOCK_CODES_ALL` | `000001.SZ\|平安银行\|19405684736`（代码\|名称\|流通股本-股） | 3,048 | `UPDATE_STOCK_CODES()`（`INFO/SZ100.xlsx`） | 策略选股（市值=流通股本×T-2收盘）、新 UI |
| `STOCK_CODES` | `601288.SH` …（仅代码） | 677 | **无代码生成/引用**【待确认来历，疑为早期手工清单】 | 无（`PATH_AIDATA_STOCK_CODES()` 0 引用） |
| `INDEX_CODES` | `000001.SH\|上证指数` | 11 | `UPDATE_INDEX_CODES()`（`INFO/指数.xlsx`） | 指数行情下载、新 UI「指数 K 线」 |
| `INDEX_5M_CODES` | `000001.SH\|上证指数` | 17 | `tools/export_index_5m.py`（首次运行生成） | `AIData/INDEX_5M` 导出范围、实时看盘环境宽度 |

### 5.2 子目录总表

| 目录 | 文件数 | 体积 | 命名 | 覆盖范围 | 生成者 | 消费者 |
|---|---:|---:|---|---|---|---|
| `1D_ORIGIN/` | 2,522 | 24.4 MB | `<代码>`（如 `000002.SZ`） | 20260105~20261104，单只 28~200 行（中位 200） | `UPDATE_1D_ORIGIN()`（tqcenter 前复权日线；`_rotate_dir` 整目录重建） | `UPDATE_1D`、StrategyUI（K 线、回测辅助）、新 UI（1d K 线） |
| `1D/` | 2,522 | 56.0 MB | `<代码>` | 同上，25 列 | `UPDATE_1D()`（从 1D_ORIGIN 计算派生字段） | 策略选股、新 UI 详情、研究脚本 |
| `5M/` | 253 | 12.8 MB | `<代码>` | **窗口化不连续**：全局 2026-01-05 09:35 ~ 2026-11-03 15:00；单只中位 432 根（约 9 个交易日），192~1,728 根 | `UPDATE_5M_PANELS()`（按策略候选日 T-2~T+5 下载）；`UPDATE_5M_ORIGIN()`（全历史，单步/旧路径）；`DOWNLOAD_5M_ONE()`（按需补数） | 回测 `5m` 卖法、新 UI 5 分钟窗口 |
| `INDEX_5M/` | 17 | 18.0 MB | `<指数/ETF 代码>` | 20260105 起每交易日 48 根（全量 9648 行），13 列（同 `5M/` 格式） | `tools/export_index_5m.py`（由 `daily_update.py` 第 3 步调用） | 新 UI「实时看盘」环境宽度、指数 5m K 线 |
| `INDEX_ORIGIN/` | 11 | 0.1 MB | `<指数代码>` | 20260105~20261103，每只 200 行，7 列 | `UPDATE_INDEX_1D_ORIGIN()` | `UPDATE_INDEX_1D`、StrategyUI（指数K线） |
| `INDEX/` | 11 | 0.3 MB | `<指数代码>` | 同上，25 列（涨停/连板列恒 0） | `UPDATE_INDEX_1D()` | 新 UI（指数 K 线回退）、StrategyUI 指数面板 |
| `TOP/` | 200 | 0.2 MB | `YYYYMMDD` | 20260105~20261104，每天 27~198 行（均值 71.5） | `UPDATE_TOP()`（`TOP_ORIGIN/*.xlsx` 提取代码） | `UPDATE_1D`（is_top/lian_ban）、`UPDATE_TOP_FIRST`、新 UI 涨停面板、Run.py 周期圈定 |
| `TOP_FIRST/` | 200 | 0.1 MB | `YYYYMMDD` | 同 TOP 日期 | `UPDATE_TOP_FIRST()`（当日涨停 − 前一交易日涨停） | 新 UI 首板面板 |
| `TOP_ORIGIN/` | 200 | 5.8 MB | `主板，YYYY年M月D日涨停所有股.xlsx` | 20260105~20261103（**全部为“主板”**，见 §8.9） | **人工导入**（同花顺“涨停分析”导出），唯一非代码生成的源数据 | `UPDATE_TOP()` |
| `STRATEGY/TPO_M5/` | 200 | 0.1 MB | `YYYYMMDD`（= T-0 卖出日） | 20260105~20261104；**65 天无票（空行）**，135 天有票，共 334 行，单日最多 10 行 | `UPDATE_STRATEGY_TPO_M5()` | `Backtest`、StrategyUI、新 UI、`UPDATE_5M_PANELS`、`tools/next_day_strategy.py`、7 个研究脚本 |
| `NEXT_DAY/strategy.json` | 1 | 1.3 KB | — | 下一交易日 TPO_M5 名单（`generatedAt/buyDate/forTradeDate/env/firstPick/buyList/candidates`） | `tools/next_day_strategy.py`（`daily_update.py` 第 5 步） | 新 UI「实时看盘」（今日持仓 / 明日候选） |
| `INFO/` | 2 | 0.4 MB | `SZ100.xlsx`、`指数.xlsx` | 股票池/指数池快照 | 人工导出（同花顺） | `UPDATE_STOCK_CODES`、`UPDATE_INDEX_CODES` |
| `THS/` | 1 | 0.0 MB | `blockstockV3.xml` | 板块模板 | 人工提供 | `CMD_UPDATE_THS()` |
| `DAILY/` | 1 | 0.0 MB | `Daily.txt` | 149 行手工笔记（阴阳/预测最高低价/T-N 形态经验） | 人工维护 | **无代码读取**；仅研究脚本文档里被引用为“理解维度来源” |

### 5.3 列定义（关键格式）

**`1D_ORIGIN/<代码>` / `INDEX_ORIGIN/<代码>`（7 列，原始前复权）**

```
date|open|high|low|close|volume|amount
20260105|4.64|4.78|4.63|4.75|193853520.0|91714.35
```
- `volume` 单位 = 股；`amount` 单位 = 万元（样例：4.75 元 × 1.9385 亿股 ≈ 92,059 万元 ≈ 91,714.35，吻合）。
- 停牌日**不写行**（`fill_data=False`），故行数可少于交易日数（`row_min=28` 多为新股）。

**`1D/<代码>` / `INDEX/<代码>`（25 列 = 原始 7 列 + 18 列派生）**

| # | 字段 | 含义 / 算法 |
|---:|---|---|
| 1-7 | `date,open,high,low,close,volume,amount` | 原始行情 |
| 8 | `pre_close` | 前一日收盘价，四舍五入到分（首行 0.00） |
| 9 | `is_top` | 当日涨停（依据 `TOP/<date>` 清单，1/0） |
| 10 | `is_toped` | 盘中触及涨停价（high ≥ 前收×1.1，1/0） |
| 11 | `ratio` | 涨跌幅(%) = (close−pre_close)/pre_close×100 |
| 12-13 | `is_up,is_down` | ratio 正 / 负 |
| 14-15 | `is_red,is_green` | 阳线 / 阴线（close vs open） |
| 16-17 | `is_volume_up,is_volume_down` | 放量 / 缩量（与前一日 volume 比） |
| 18-23 | `ma5,ma10,ma20,ma30,ma60,ma120` | 收盘价 N 日均价（**满 N 日才计算，不足为 0.00**） |
| 24 | `lian_ban` | 连板数：当日涨停则 +1，否则归零 |
| 25 | `is_bottom` | 收盘价 == 前收×0.9（跌停），1/0 |

> 指数 `INDEX/` 同 25 列，但 `is_top/is_toped/lian_ban/is_bottom` 恒为 0。

**`5M/<代码>`（13 列）**

```
2026-10-08 09:35:00|4.11|4.2|4.06|4.17|145806592.0|60212.29|0.00|0.00|0.00|0.00|0.00|0.00
```
`time|open|high|low|close|volume|amount|ma5|ma10|ma20|ma30|ma60|ma120`
- `time` 是**全仓库唯一带横线的时间格式** `YYYY-MM-DD HH:MM:SS`；每交易日 48 根（09:35~15:00）。
- `ma*` = 收盘价 N 根 5 分钟 K 线滑动均价（不足为 0.00，与 1D 口径一致）。

**`INDEX_5M/<代码>`（13 列，同 `5M/` 格式）**

```
2026-01-05 09:35:00|3986.97|3990.29|3983.58|3987.33|1200928218|120092819456.00|0.00|0.00|0.00|0.00|0.00|0.00
```
- 指数/宽基/ETF 的 5 分钟**全量**数据（`AIData/5M` 只存策略涉及个股的窗口数据、且不含指数），由 `tools/export_index_5m.py` 从通达信本地 `vipdoc/<mkt>/fzline/*.lc5` 导出。
- 列与 `5M/` 完全一致：`time|open|high|low|close|volume|amount|ma5|ma10|ma20|ma30|ma60|ma120`；单只约 9,648 行（200 交易日 × 48 根）。
- 代码清单 `AIData/INDEX_5M_CODES`（17 行 `代码|名称`，首次运行自动生成）。

**`NEXT_DAY/strategy.json`（下一交易日名单，UTF-8）**

```json
{"generatedAt":"...","buyDate":"20261104","forTradeDate":"20261105","approx":true,"strategy":"TPO_M5",
 "env":{"t1":"差","above":0,"total":7,"date":"20261104"},
 "firstPick":{"code":"002558.SZ","name":"巨人网络","buyPrice":21.66,"marketValue":40842916119.04},
 "buyList":[{"code":"...","name":"...","buyPrice":0.0,"marketValue":0.0,"ma5Pred":true}],
 "candidates":[{"code":"...","name":"..."}]}
```
- 语义：`buyDate` = T-1（今日盘后数据已就绪），`forTradeDate` = T-0（下一交易日卖出）；`env` 为成长端 7 宽基 T-1 日线 MA60/宽度结论；`firstPick` 为首选（实际只买首选）。
- 只由 `tools/next_day_strategy.py` 写（原子写），新 UI 只读；失败时不阻断盘后总控。

**`STRATEGY/<策略>/<YYYYMMDD>`（29 列，GBK）**

```
000960.SZ|产业股份|52390552842.24|20260109|30.65|33.62|30.65|33.46|56886416.0|188018.16|31.01|0|0|7.9007|1|0|1|0|1|0|31.0|0.0|...|0|0|-0.05
```
`code|name|market_value|date|open|high|low|close|volume|amount|pre_close|is_top|is_toped|ratio|is_up|is_down|is_red|is_green|is_volume_up|is_volume_down|ma5|ma10|ma20|ma30|ma60|ma120|lian_ban|is_bottom|stop_loss`
- 第 3 列 `market_value` = 流通股本 × T-2 日收盘价（元），策略内已按市值倒序，**首行 = 首选**（`first` 选股方式）。
- 第 4 列 `date` = **T-0 卖出日**；第 29 列 `stop_loss` = 本策略止损线（TPO_M5 = -0.05），回测按它覆盖默认 -6%。
- 空行 = 当日不选股（回测跳过）。中文名称字段为 GBK 字节。

**`TOP/YYYYMMDD`、`TOP_FIRST/YYYYMMDD`**：每行一个带后缀代码（如 `002931.SZ`），无表头；`TOP_FIRST` 为空文件表示当日无首板。

**`TOP_ORIGIN/主板，YYYY年M月D日涨停所有股.xlsx`**（同花顺“涨停分析”导出，20 列，`SZ200Top._READ_TOP_ORIGIN` 只取 B 列股票代码）：
`序号 | 股票代码 | 股票简称 | 现价 | 涨跌幅(%) | 所属行业 | 发生日期 | 封单金额 | 首次涨停时间 | 最近涨停时间 | 涨停打开次数 | 涨停原因 | 连续涨停天数 | 几天几板 | 原因揭秘 | 板型 | 涨停成交额(万) | 涨停最大封单额(万) | 封成比 | 封单量`

**`INFO/SZ100.xlsx`**（10 列，`StockCodes` 取 B 代码 / C 名称 / J 流通股本）：`序号 | 股票代码 | 股票简称 | 现价 | 涨跌幅(%) | 所属行业 | 最新流通市值(元) | 所属概念 | 概念个数 | 最新流通股本(股)`

**`INFO/指数.xlsx`**（5 列，`SZ200Index` 取 B 代码 / C 名称）：`序号 | 指数代码 | 指数名称 | 现价 | 涨跌幅(%)`

**`THS/blockstockV3.xml`**（同花顺板块模板，8 行）：

```xml
<hevo version="5586" sort_list="25,27,">
  <Block name="T" id="39" ...>===T===</Block>
  <Block name="T-1" id="37" ...>===T-1===</Block>
</hevo>
```
`CMD_UPDATE_THS()` 把 `===T===` / `===T-1===` 替换为 `<security market="USHA|USZA" code="xxxxxx" />` 列表，写到 `THS_TARGET_DIR/blockstockV3.xml`（默认 `C:\同花顺远航版\bin\users\狗蛋儿家的金`，可用环境变量 `THS_TARGET_DIR` 覆盖）。

### 5.4 代码引用但磁盘不存在的路径（Path.py 失效函数）

`Path.py` 里 40+ 个函数中，以下 **19 个函数指向的路径当前不存在，且全仓库引用计数为 0**（可安全清理或补数据）；另有 3 个旧策略路径函数（`TPO_3` / `TPO_TOP` / `TPO_M5_SMALL`）各只在自身生成函数里出现 1 次、无调用方：

| 函数 | 路径 | 说明 |
|---|---|---|
| `PATH_AIDATA_ORIGIN` | `AIData/ORIGIN` | 旧 BaoStock 原始数据根（`MarcoAPI.py` 时代），已废弃 |
| `PATH_AIDATA_TOPPED` | `AIData/TOPPED` | 旧“曾涨停”集合 |
| `PATH_AIDATA_BOTTOM` | `AIData/BOTTOM` | 旧“跌停/底部”集合 |
| `PATH_AIDATA_BOTTOMED` | `AIData/BOTTOMED` | 旧“曾跌停”集合 |
| `PATH_AIDATA_1D_MOTION_PRICE` | `AIData/1D_MOTION_PRICE` | 旧动量价曲线（对应 UI 遗留 html） |
| `PATH_AIDATA_1D_MOTION_PRICE_VOLUME` | `AIData/1D_MOTION_PRICE_VOLUME` | 同上（含量） |
| `PATH_AIDATA_1D_WIN_COUNT` | `AIData/1D_MOTION_WIN_COUNT` | 旧涨跌家数 |
| `PATH_AIDATA_1D_MOTION_COUNT` | `AIData/1D_MOTION_COUNT` | 旧动量计数 |
| `PATH_AIDATA_5M_MOTION_PRICE` / `_VOLUME` / `PATH_AIDATA_5M_WIN_COUNT` | `AIData/5M_MOTION_*` | 5 分钟版动量系列 |
| `PATH_AIDATA_1D_SIGNALS` / `PATH_AIDATA_5M_SIGNALS` | `AIData/*_MOTION_SIGNALS` | 旧信号文件 |
| `PATH_AIDATA_1D_PANIC_INDEX` / `PATH_AIDATA_1D_PRICE` | `AIData/1D_PANIC_INDEX`、`AIData/1D_PRICE` | 旧恐慌指数/价格 |
| `PATH_AIDATA_MOTION` | `AIData/MOTION` | 旧动量根目录 |
| `PATH_ADJUST_FACTOR` | `AIData/ORIGIN/ADJUST_FACTOR` | 旧复权因子 |
| `PATH_STOCK_CODES` | `AIData/ORIGIN/SZ200.config` | 旧股票池 config |
| `PATH_TRADING_DATES` | `AIData/TradingDates.config` | 旧交易日历 config |
| `PATH_AIDATA_STRATEGY_TPO_3` / `_TPO_TOP` / `_TPO_M5_SMALL` | `AIData/Strategy/{TPO_3,TPO_TOP,TPO_M5_SMALL}` | 对应 `UPDATE_STRATEGY_*` 函数存在但未被主链路调用，数据未生成 |

> 另注：`PATH_AIDATA_STRATEGY()` 返回 `AIData/Strategy`（小写），磁盘实际目录是 `AIData/STRATEGY`；Windows 大小写不敏感所以能跑，**换到 Linux/macOS 或某些同步工具会失效**。

---

## 6. 端到端数据流

### 6.1 主链路（一张文字图）

```
① 人工导入源数据（只做一次/每日手工）
   同花顺「涨停分析」导出 ──► AIData/TOP_ORIGIN/主板，YYYY年M月D日涨停所有股.xlsx
   同花顺股票池导出       ──► AIData/INFO/SZ100.xlsx（代码/名称/流通股本）
   同花顺指数池导出       ──► AIData/INFO/指数.xlsx
   （模板）               ──► AIData/THS/blockstockV3.xml

② UPDATE_ALL()（Run.py 菜单 1 / 88 第②步 / python Run.py update_all）
   [1] UPDATE_TRADING_DATES   tqcenter.get_trading_dates ─────► AIData/TRADING_DATES
   [2] UPDATE_STOCK_CODES     INFO/SZ100.xlsx ────────────────► AIData/STOCK_CODES_ALL（3,048 行）
   [3] UPDATE_1D_ORIGIN       tqcenter 前复权日线 ────────────► AIData/1D_ORIGIN/（2,522 只，7 列）
   [4] UPDATE_INDEX_CODES     INFO/指数.xlsx ─────────────────► AIData/INDEX_CODES（11 只）
   [5] UPDATE_INDEX_1D_ORIGIN tqcenter 指数前复权日线 ────────► AIData/INDEX_ORIGIN/（11 只，7 列）
   [6] UPDATE_TOP             TOP_ORIGIN/*.xlsx ──────────────► AIData/TOP/YYYYMMDD（涨停代码）
   [7] UPDATE_1D              1D_ORIGIN + TOP ────────────────► AIData/1D/（2,522 只，25 列；
                                                               is_top/lian_ban 依赖 [6]，故必须在其后）
   [8] UPDATE_INDEX_1D        INDEX_ORIGIN ───────────────────► AIData/INDEX/（11 只，25 列）
   [9] UPDATE_TOP_FIRST       TOP（当日−昨日）────────────────► AIData/TOP_FIRST/YYYYMMDD
  [10] UPDATE_STRATEGY_TPO_M5 1D + STOCK_CODES_ALL ───────────► AIData/STRATEGY/TPO_M5/YYYYMMDD（29 列）
  [11] UPDATE_5M_PANELS       STRATEGY 涉及股 + 关键日 ──────► AIData/5M/（253 只窗口数据）
   （全程日志写根目录 update_log.txt；`_cleanup_old_dirs()` 清理 .old_* 残留）
   （2026-11-04 起 UPDATE_ALL 不再生成任何看板产物；新 UI 通过 /api/* 实时读 AIData）

③ 消费端（读 AIData，不再写业务数据）
   ├─ 新 UI      tools/dashboard_server.py（http://127.0.0.1:8765）→ backend_data.py → 读 1D/1D_ORIGIN/5M/INDEX*/STRATEGY/TOP/TOP_FIRST/NEXT_DAY
   ├─ 实时看盘   tools/realtime_feed.py（tqcenter 快照轮询）+ AIData/NEXT_DAY/strategy.json
   ├─ 同花顺      CMD_UPDATE_THS(策略)：读 STRATEGY 最新日 + 1D 重扫 TPO 窗口 → 写 blockstockV3.xml 到 THS_TARGET_DIR
   └─ 脚本/研究   Backtest.BACKTEST(策略) / 7 个 AICode/*.py（产出 TPO_SCORE 等研究目录）

④ 盘后总控（tools/daily_update.py，6 步）
   网页导出 TOP_ORIGIN → 通达信数据刷新 → 指数 5m 全量 → UPDATE_ALL → NEXT_DAY 名单 → 重启新 UI 服务
   （详见 §3.3；同花顺默认自动更新（`--no-ths` 跳过）、通达信默认不自动刷新（`--with-tdx` 才自动）、Gitee 默认关闭（`--with-git`））
```

### 6.2 单项更新（`Run.py` 菜单 5 / `CMD_RUN_STEP`）

| 编号 | 显示名 | step 标识 | 实际函数 |
|---|---|---|---|
| 1 | 交易日历 | `UPDATE_TRADING_DATES` | `TradingDates.UPDATE_TRADING_DATES` |
| 2 | 股票池 | `UPDATE_STOCK_CODES` | `StockCodes.UPDATE_STOCK_CODES` |
| 3 | 日线原始 | `UPDATE_1D_ORIGIN` | `SZ2001D.UPDATE_1D_ORIGIN` |
| 4 | 5分钟原始 | `UPDATE_5M_ORIGIN` | `SZ2005M.UPDATE_5M_ORIGIN`（**全历史**，与菜单 2 的窗口下载不同） |
| 5 | 涨停列表 | `UPDATE_TOP` | `SZ200Top.UPDATE_TOP` |
| 6 | 加工日线 | `UPDATE_1D` | `SZ2001D.UPDATE_1D` |
| 7 | 首板涨停 | `UPDATE_TOP_FIRST` | `SZ200Top.UPDATE_TOP_FIRST` |
| 8 | TPO_M5 回测 | `UPDATE_STRATEGY_TPO_M5` | `SZ200Strategy.UPDATE_STRATEGY_TPO_M5` |
| 12 | 指数列表 | `UPDATE_INDEX_CODES` | `SZ200Index.UPDATE_INDEX_CODES` |
| 13 | 指数日线原始 | `UPDATE_INDEX_1D_ORIGIN` | `SZ200Index.UPDATE_INDEX_1D_ORIGIN` |
| 14 | 指数加工日线 | `UPDATE_INDEX_1D` | `SZ200Index.UPDATE_INDEX_1D` |

> 依赖：`UPDATE_TOP` → `UPDATE_1D`（is_top/lian_ban）→ `UPDATE_TOP_FIRST`（首板靠 TOP 差分）→ `UPDATE_STRATEGY_TPO_M5` → `UPDATE_5M_PANELS`。`UPDATE_ALL` 的步骤顺序即依赖顺序。

### 6.3 一条龙（菜单 88）与 UPDATE_ALL 的差异

- `UPDATE_ALL` 现在只做数据（11 步），**不含任何看板生成**；`Run.py._do_pipeline()` 也只剩 ②数据(含5M) → ③同花顺，Gitee 默认关闭（`daily_update.py --with-git` 才上传）。盘后自动流程 `daily_update.py` 默认**自动更新同花顺**（`--no-ths` 跳过）、默认**不自动刷新通达信**（数据由用户手动「盘后数据下载」，`--with-tdx` 才自动校验/刷新）。
- 一条龙会先用“周期”把 5M 与 1D 限定到“最近 N 个月涨停过的股票集合”（`_top_codes_in_period`），再调 `UPDATE_ALL(scope_codes=..., recent_days_5m=30)`；因此**菜单 1（全量）与一条龙产生的 1D/5M 覆盖范围不同**，切换使用后 1D 文件数可能在 2,522 / 更少之间变化。
- 盘后无人值守场景用 `tools/daily_update.py`（6 步总控，见 §3.3），比手工跑菜单 88 更完整（多了网页导出、指数 5m、NEXT_DAY、重启 UI）。

---

## 7. 文件放置约定（新增东西放哪）

### 7.1 快速决策表

| 你要做的事 | 放哪里 | 必须同步改 |
|---|---|---|
| 新增一个**数据更新步骤** | `AICode/MarcoAPI/Update/<领域>.py` 里写 `UPDATE_XXX()` | ① `Update/Update1D.py::UPDATE_ALL` 的 `steps` 顺序；② `StrategyUI.py::_UPDATE_STEPS` 字典；③ `Run.py::_UPDATE_STEP_ITEMS` 元组（新 UI 暂无单项更新入口） |
| 新增一个**数据目录** | `AIData/<新目录>/`；路径函数加在 `Update/Path.py` | `Path.py` 加 `PATH_AIDATA_XXX()`；确认 `.gitignore`（动态数据默认忽略，只有“源数据/手工输入”才用 `!` 入库）；写生成函数（用 `_rotate_dir()` 整目录重建，不要就地改）；在本文件 §5 登记 |
| 新增一个**策略** | 选股逻辑加在 `Update/SZ200Strategy.py`（`UPDATE_STRATEGY_XXX()`，内部复用 `_UPDATE_STRATEGY_TPO`） | 数据落 `AIData/STRATEGY/<策略名>/YYYYMMDD`（29 列、最后一行止损线）；`StrategyUI._list_strategies()` 自动发现目录，看板下拉/菜单 3 无需改；要进同花顺则在 `StrategyUI._TPO_MARKET_PARAMS` 登记市值区间；要进一条龙则在 `UPDATE_ALL.steps` 加一步 |
| **策略研究/一次性脚本** | `AICode/` 根目录，命名 `run_<主题>_backtest.py` / `diagnose_<主题>.py` | 文件头写 docstring：目的、数据源、产出目录、运行命令；不要写进 `MarcoAPI`（会被误认为主链路） |
| **长期维护的模块** | `AICode/MarcoAPI/` 下按领域命名（大写开头的 `<领域>.py` 或 `Update/<领域>.py`） | 顶部写模块 docstring（数据流/文件格式/API）；`from AICode...` 绝对导入；本项目统一用 `_ROOT` 上溯 + `sys.path` 注入的写法 |
| **改新 UI（看板前端）** | `dashboard/`：`index.html`、`css/`、`js/views/*`、`js/components/*`、`js/adapters/*` | 无构建步骤，改完刷新浏览器；新增接口要同步 `tools/dashboard_server.py` 与 `js/api.js`；第三方图表库放 `dashboard/vendor/` |
| **改实时看盘数据/信号** | `tools/realtime_feed.py` + `dashboard/js/views/realtime.js` | 只读 AIData、不写、不下单；持仓字段同步 `dashboard/holdings.json` 与 `/api/realtime/holdings` |
| **新增盘后步骤** | `tools/daily_update.py` 的 `step_*` 函数 | 登记到 6 步日志编号与 `--skip-*` 参数；明确“失败是否阻断”（当前仅 1/2/4 阻断） |
| **复盘日志 / 教练知识库** | `journals/`（日志 + 结构化总结/索引/标签）；`journals/coach/`（PLAYBOOK/USER_PROFILE/RUBRIC/REVIEW） | 纯文本入库；不进更新菜单；`journals/coach/` 只由小小A 维护 |
| **新增文档** | 项目级：仓库根 `README.md` / `ARCHITECTURE.md`；策略说明：`AICode/MarcoAPI/Skills/<策略>/SKILL.md` | 建议放 `docs/` 的候选内容：本仓库尚未有 `docs/`，暂放根目录；改完在本文件 §2/§4 更新索引 |
| **新数据源**（新 Excel/新接口） | 源文件放 `AIData/INFO/`（手工输入，入库）或 `AIData/<源>/`；解析函数放 `Update/<源>.py`；在 `Path.py` 登记 | 在本文件 §5 补“格式/列定义/生成者/消费者” |

### 7.2 命名规范（现状约定，新代码请遵守）

- **数据文件（按日）**：`YYYYMMDD`，无扩展名；策略目录用大写名（`TPO_M5`）。
- **股票/指数代码**：`6 位数字 + .SH/.SZ`；同花顺 security 行：`.SH → market="USHA"`，`.SZ → USZA`。
- **Python 模块**：领域名 + 大写开头（`SZ2001D.py`、`SZ200Index.py`）；更新函数全大写下划线 `UPDATE_*`；私有工具 `_` 前缀。
- **一次性脚本**：`diagnose_*.py`（只诊断、不产数据）、`run_*_backtest.py`（产研究数据/回测）；带 `_` 前缀的是临时排查脚本（如 `_check_inline.py`），用完应删。
- **新 UI 前端**：`dashboard/` 下源码直接入库，**无构建产物**；`dashboard/holdings.json` 为用户本地数据（`dashboard/.gitignore` 忽略）。
- **日志**：根目录 `update_log.txt`（UPDATE_ALL 写）；`*.log`/`*.err` 默认 gitignore。

### 7.3 新增更新步骤的“三处登记”检查清单（来自现有代码结构）

1. `Update/Update1D.py` → `UPDATE_ALL()` 的 `steps` 列表（决定一条龙顺序）。
2. `AICode/MarcoAPI/StrategyUI.py` → `_UPDATE_STEPS` 字典（`CMD_RUN_STEP` 分发，供菜单 5 / 协议使用）。
3. `Run.py` → `_UPDATE_STEP_ITEMS` 元组（菜单 5 的显示名与编号）。
4. （已下线）`StrategyUI._render_html()` 内嵌 JS 的 `UPDATE_STEPS`：随离线看板一起废弃，无需再改。
5. （已下线）`MarcoUI/modules.js` 的“数据更新中心”按钮列表：桌面端已删除。

---

## 8. 已知问题与待清理项

> **纪律：本文件只记录，不擅自删改。** 下列每条都给出“证据 → 建议动作”，动作需用户确认后执行。

### 8.1 旧 UI / 构建产物（已删除，2026-11-04）

| 路径（已不存在） | 原体积 | 状态 |
|---|---:|---|
| `AICode/MarcoAPI/UI/MarcoUI/.venv` | 801.0 MB | 已删（桌面端整体下线，`install.ps1` 一并删除） |
| `AICode/MarcoAPI/UI/MarcoUI/build` | 258.9 MB | 已删（PyInstaller 中间产物） |
| `AICode/MarcoAPI/UI/MarcoUI/dist/MarcoTerminal.exe` | 249.6 MB | 已删（单文件 exe） |
| `AICode/MarcoAPI/UI/data`、`lib`、`vendor`、`StrategyDashboardOffline.html(.meta.json)`、15 个旧 HTML | ~99 MB | 已删（离线看板下线） |
| `.gitignore` 中旧 UI/构建规则 | — | **残留未清理**：`.venv/`、`dist/`、`build/`、`*.spec`、`UI/MarcoUI/config.json`、`UI/MarcoUI/_*` 等规则仍在文件里（路径已不存在，无害但建议清理） |

### 8.2 入库生成物（已随旧看板删除）

- 原被跟踪的 `UI/data/*.js`（98.6 MB）、`UI/StrategyDashboardOffline.html(.meta.json)`、`UI/` 根 15 个遗留 HTML 均已删除并提交；git 索引不再包含它们。
- 剩余 `AIData` 动态数据仍被 `.gitignore` 忽略，不再有“每次一条龙产生海量二进制 diff”的问题。

### 8.3 遗留 HTML（已删除）

2026-11-04 已随旧 UI 清理，`AICode/MarcoAPI/UI/` 根不再有任何 `.html`。
（`KLine.py` 的生成规则仍在：`SHOW_K_LINE()` 会写 `UI/<输入文件名>.html`、`SHOW_K_LINE_WITH_SIGNALS()` 写 `*_with_signals.html`、`SHOW_WIN_COUNT()` 写 `*.win_count.html`——若将来用它，产物不应入库。）

### 8.4 遗留数据文件（已删除）

- `UI/data/top_first_vol*.js` 等旧看板数据残留随 `UI/data/` 整体删除。

### 8.5 Path.py 失效路径

见 §5.4 表：19 个函数指向不存在的目录，且全仓库引用计数为 0；另有 3 个旧策略路径函数（`TPO_3`/`TPO_TOP`/`TPO_M5_SMALL`）各只在自身生成函数里出现 1 次、无调用方；`AIData/ORIGIN`、`TOPPED`、`BOTTOM`、`BOTTOMED`、`MOTION`、`1D_MOTION_*`、`5M_MOTION_*`、`1D_PRICE`、`1D_PANIC_INDEX`、`ADJUST_FACTOR` 等。
建议：确认无历史脚本依赖后，删除函数或标注 `# deprecated`，避免误导（**注意**：`_render_html` 等模板字符串可能间接引用；删除前需全仓库 grep 函数名确认 0 命中）。

### 8.6 遗留/不可运行代码

| 文件/函数 | 证据 | 影响 | 建议 |
|---|---|---|---|
| `MarcoAPI/MarcoAPI.py` | `from AICode.MarcoAPI.BaoStockAPI import ...`、`...Converter import ...`，两个模块都不存在 | 一旦 import 即 `ModuleNotFoundError` | 确认无用后删除或移入归档目录 |
| `MarcoAPI/EntryTimingAnalysis.py` | 读 `AIData/1D_MOTION`（不存在） | 运行即 `FileNotFoundError` | 同上是独立脚本，可留作历史 |
| `MarcoAPI/KLine.py` | 全仓库 0 处 import；输出到 `UI/` | 仍是可用的独立图表工具 | 保留，但若清理遗留 HTML 应一并说明 |
| `Update/DataAligned.py` | 0 引用 | 无影响，纯死代码 | 归档/删除 |
| `Update/SZ200Strategy.py::UPDATE_STRATEGY_TPO_3 / TPO_TOP / TPO_M5_SMALL` | 函数存在但未被 `UPDATE_ALL` 或任何入口调用；`AIData/Strategy/TPO_3`、`TPO_TOP`、`TPO_M5_SMALL` 不存在 | 潜在策略但无数据 | 【待确认】是否弃用；若弃用可删函数与 `Path` 项 |
| `StrategyUI.GENERATE_STRATEGY_UI_OFFLINE / GENERATE_STRATEGY_UI / _write_offline_data / _render_html` | 旧看板生成函数：`UPDATE_ALL`/`Run.py` 的看板步骤已删除，当前 0 调用方；`UI/data`、`UI/vendor` 已删除 | 死代码（约 2,000 行内联模板） | 建议整体删除；删前全仓库 grep 函数名确认 0 命中 |
| `StrategyUI` 模板中的 `panel-candidate` / `panel-top` | 模板有面板、JS 有 `switchTab('candidate'/'top')` 分支，但**顶部 TAB 只有 回测/选股/指数 三个**（`StrategyUI.py:1200-1202`） | 这两个面板当前**从 UI 不可达**（等于死 UI） | 【待确认】是计划内简化还是漏了 TAB 按钮 |
| `backend_data.get_index_codes()` | `return list(PATH_AIDATA_INDEX and set())` 恒为 `[]`；新 UI 未调用 | 无实际影响 | 修或删 |
| `Skills/TPO_M5_2.0` | `rank_select`（TODO-1）/`t0_sell`（TODO-2）未实现，默认等价 TPO_M5；输出目录未生成 | 骨架状态 | 按用户口述继续实现 |
| `AICode/` 根 7 个研究脚本 | 产出的 `TPO_SCORE/TPO_DECISION/TPO_CAPFILT*` 目录都不存在（研究结论未采纳） | 不影响主链路 | 归档到 `AICode/research/` 或根目录保留（现约定即“一次性脚本放 AICode 根”） |
| 根 `_check_inline.py` / `_esprima_final.py` / `_regen_proper.py` | 硬编码 `c:/MarcoAI`，一次性排查；`_esprima_final.py` 依赖 `esprima`（未在 requirements） | 不影响主链路 | 建议删除或移入 `tools/` |

### 8.7 旧日志与历史文件

| 路径 | 大小 | 说明 |
|---|---:|---|
| `AICode/_update_log.txt` | 66 KB | **被 git 跟踪**的历史更新日志；内容为 2026-08-31 的旧运行（含 `e:\Lazy\MarcoAI` 旧路径、`共 160 个交易日`、`股票列表: 共 1155 只`、TPO_3/TPO_TOP 步骤），与当前管线不符 → 建议删除并取消跟踪 |
| `update_log.txt`（根） | 528 KB | 当前一条龙日志，每次覆盖；已被 `.gitignore` 忽略 |
| `MarcoUI/_build.err` / `_build.log` / `_update_all.err` / `_update_all.log` | 原 24 KB~76 B | 旧桌面端排查日志，已随 `MarcoUI/` 删除 |

### 8.8 行为不一致 / 说明滞后

| 位置 | 现象 | 证据 |
|---|---|---|
| `Run.py` 菜单 3 说明 | 写“自动关闭/重启同花顺生效”，但 `CMD_UPDATE_THS()` 只做“读模板→替换占位符→覆盖目标 XML”，**没有任何关闭/重启进程的代码** | `StrategyUI.CMD_UPDATE_THS()`；全文件无 `taskkill/Popen` 等 |
| `Run.py` 菜单 1 说明 | 写“同步…目标池”，但 TARGET/候选池链路已移除（无 `SZ200Target.py`、无 `AIData/TARGET`） | `Run.py::_MENU_GROUPS` |
| `Run.py` 单项更新第 7 项说明 | 写“⑦首板涨停依赖⑥的 is_volume_up”，但 `UPDATE_TOP_FIRST()` 已不检查放量（docstring 也明确“不要求放量”） | `Run.py::_do_single_update` vs `SZ200Top.py` |
| `Run.py` 单项更新第 4 项 | `UPDATE_5M_ORIGIN` 是**全历史下载**（`start_date=20260101` 且 `recent_days=0`），与菜单 2 的窗口下载口径不同，误操作会让 5M 体积暴增 | `Run.py` step 列表 → `StrategyUI._UPDATE_STEPS` → `SZ2005M.UPDATE_5M_ORIGIN` |
| `tools/daily_update.py` docstring | 顶部只列 0~5 步，实现含 `[6/6] 重启新 UI 服务`（文档滞后） | 文档字符串 vs `step_restart_dashboard()` |
| `tools/dashboard_server.py` docstring | 顶部 API 列表只写 7 个 GET，实现另有 `/api/realtime`、`/api/realtime/kline`、`/api/realtime/holdings` | 文档字符串 vs `do_GET/do_POST` |
| `StrategyUI.py` 顶部 docstring | 仍写“数据来源 AIData/TARGET/{策略}/{日期} 候选池”“生成 StrategyDashboard.html（在线版）”，均已过期 | `StrategyUI.py:1-19` |
| `StrategyUI.py` 部分注释 | 提到已删除函数 `GENERATE_TOP_FIRST_VOL_MA60` 与旧面板 `top_first_vol` | 历史残留，不影响运行 |
| `Backtest.py` 模块 docstring | 声称“输出 `AIData/STRATEGY/RESULT/{策略名}.txt`”，但 `BACKTEST()` 只 `return result_text`，不写文件；该目录不存在 | 结果实际由调用方打印 |
| 单项更新登记清单 | `StrategyUI._UPDATE_STEPS` 与 `Run.py._UPDATE_STEP_ITEMS` 均为 11 项（编号含 12/13/14），一致；原离线看板内嵌 JS 的 8 项清单已随看板删除 | 现无“三份清单不一致”问题 |
| `.gitignore` | 旧 UI/构建规则残留（`.venv/`、`dist/`、`build/`、`*.spec`、`UI/MarcoUI/*`），路径已不存在 | 见 §8.1 |

### 8.9 数据口径 / 数据一致性

| 问题 | 事实 | 影响 | 建议 |
|---|---|---|---|
| 1D 与股票池数量不一致 | `1D`/`1D_ORIGIN` 各 **2,522** 只；`STOCK_CODES_ALL` **3,048** 只。其中 **673 只**在池中但无 1D 文件，**147 只**有 1D 但不在当前池 | 策略用 `STOCK_CODES_ALL` 遍历、`GET_SZ200_1D_PREVIOUS` 缺失即跳过，故回测“候选宇宙”与实际日线覆盖不完全一致 | 【待确认】是否补全 1D 或说明“历史 scope 差异”；文档已如实记录 |
| TOP 仅覆盖“主板” | `TOP_ORIGIN` 200 个文件全部以 `主板，` 开头（创业板/科创板/北交所涨停未导入） | `is_top`/`lian_ban`/TPO 选股只认主板涨停；`TOP_FIRST` 同理 | 【重要待确认】这是业务假设还是数据源缺失 |
| 5M 不是连续全历史 | 253 只；全局时间 2026-01-05~2026-11-03，但单只中位仅 432 根（约 9 个交易日），按策略关键日窗口拼接 | 回测/新 UI 只能用“关键日附近窗口”；旧文档若声称“全历史 5M”是错的 | 文档已按现状描述（指数 5m 全量在 `INDEX_5M/`） |
| STRATEGY 仅 TPO_M5 | `AIData/STRATEGY/` 下只有 `TPO_M5` 一个策略目录（200 天，135 天有票，共 334 行） | 新 UI 下拉/同花顺策略列表当前只有 1 项 | 若新增策略见 §7.1 |
| `STOCK_CODES`（677 行）来历不明 | 无代码生成/引用，`PATH_AIDATA_STOCK_CODES` 0 引用；内容只有代码 | 可能是早期手工清单 | 【待确认】删除或说明 |
| `AIData/DAILY/Daily.txt` 编码损坏 | 前半 UTF-8 正常；`Select-Object -Skip 120` 之后的中文为“GBK 被当 UTF-8”式乱码（文件本身是 UTF-8 但部分行是二次编码产物） | 只是人工笔记，无代码读取 | 需人工重贴/重存；低优先级 |

### 8.10 编码坑（读写本仓库必读）

| 文件/数据 | 现状 | 建议 |
|---|---|---|
| `Update/SZ200Strategy.py` | **UTF-8 带 BOM**（其余 .py 均无 BOM）。直接 `open(f).read()` 后用 `ast.parse` 会报 `invalid character U+FEFF`；用 `utf-8-sig` 正常。Python 直接 import 不受影响 | 读取脚本统一用 `utf-8-sig` 回退 |
| `AIData/STRATEGY/TPO_M5/*` | 写入端 `open(..., "a")` 未指定 encoding → 本机为 **GBK**；股票名是中文 | 读取端用 `_read_text`/`_read_lines`（内置 utf-8→gbk→gb2312→latin-1 回退）；建议未来写入显式 `encoding="utf-8"` |
| 全部 `.py` | 项目自有 `.py` 共 **46 个**（AICode 33 + 根 4 + tools 9；另有本地 `.tools/` 下 147 个自动化脚本不计），用 `ast.parse(utf-8-sig)` 全部通过（2026-11-04 实测） | — |
| `AIData/DAILY/Daily.txt` | 部分中文乱码（见 §8.9 最后一行） | 人工修复 |

### 8.11 版本库工作区状态（2026-11-04）

- 旧 UI / 离线看板的 111 个删除文件已随 commit `7cc0d8b updated` 提交，`git ls-files` 由 409 降到 **298**。
- 当前 `git status --porcelain`：仅本次文档更新（`ARCHITECTURE.md` / `README.md` / `FILE_ROUTING.md`）为修改态，无 `D`/`??` 残留。
- `.tools/`、`.edge-profile/`、`.logs/`、`logs/` 等本地运行时目录被忽略，不产生噪音。

### 8.12 已过期的 AI 助手文档（`.codebuddy/`）

`.codebuddy/skills/` 下两份 SKILL.md 与现状严重不符，**不要照它排查问题**：

| 过期说法 | 现状 |
|---|---|
| `AICode/MarcoAPI/StrategyService.py`（localhost:8765 服务） | 文件不存在；8765 服务现在是 `tools/dashboard_server.py` |
| `AICode/MarcoAPI/Update/SZ200Target.py`、`AIData/TARGET/` 候选池 | 文件/目录不存在（候选池已并入 `STRATEGY/` + `_load_candidates`） |
| `AIData/5M_ORIGIN/` | 不存在（现在只有 `AIData/5M/` 与 `AIData/INDEX_5M/`） |
| “UPDATE_ALL 共 14 步（含 TPO_3/TPO_TOP/TARGET/HL）” | 现在是 **11 步**，只有 TPO_M5 |
| 项目根 `e:/MarcoAI` | 现在是 `C:\MarcoAI` |
| 菜单含 `77/88 clone`、`4=离线看板`、`8=启动新UI` | 现在菜单 **1/2/3/5/6/7/88/0**（4、8 已于 2026-11-04 删除） |
| 看板数据“内联进 HTML 的 const DATA” | 离线看板已删除；新 UI 走 HTTP `/api/*`，前端在 `dashboard/` |

建议：更新或删除该目录（属本地 AI 配置，`.gitignore` 已忽略）。

---

## 9. 环境与外部依赖

| 项 | 事实（本机实测） | 说明 |
|---|---|---|
| Python | 3.13.15（系统，唯一环境；旧 `.venv` 已随桌面端删除） | 依赖：pandas 3.0.6 / numpy 2.5.4 / openpyxl 3.1.5；无 PySide6、无 PyInstaller |
| 通达信插件 | `PATH_TDX()` 默认 `D:/new_tdx_mock/PYPlugins/user`（**不存在**）；本机环境变量 `TDX_PLUGIN_PATH=C:\new_tdx64\PYPlugins\user`（存在，含 `tqcenter.py`） | 数据下载步骤（3/4/5/11）必需；`tq.initialize(__file__)` 由各下载函数内部调用 |
| 同花顺 | `THS_TARGET_DIR` 默认 `C:\同花顺远航版\bin\users\狗蛋儿家的金`（存在） | 写 `blockstockV3.xml`；可用环境变量覆盖 |
| 网络 | 通达信行情接口、Gitee/GitHub push | `Run.py` 菜单 6/7/88 需要 |
| Git remotes | `origin=gitee.com/mingxuel/MarcoAI`、`github=github.com/mingxuel/MarcoAI`；当前分支 `dev` | 上传命令见 §3.1 |
| 打包工具 | — | 旧 PyInstaller 打包链已随 `MarcoUI/`（`.venv`、`build.py`、`MarcoTerminal.spec`）删除 |
| 浏览器 | Microsoft Edge（`daily_update.py` 网页导出用）；新 UI 用任意现代浏览器 | 打开 http://127.0.0.1:8765；无 Node/npm 依赖（`dashboard/` 免构建） |
| 可选 | `esprima`（仅根目录 `_esprima_final.py` 用）、`xtquant`（QMT 实盘 API，未使用） | — |

---

## 10. 核验记录与待确认问题

### 10.1 抽查记录（≥5 个模块“文档描述 = 实际代码”）

| # | 对象 | 核验方式 | 结果 |
|---:|---|---|---|
| 1 | `Run.py` | 全文 582 行读取 + 实跑 `"0" \| python Run.py` | 菜单 1/2/3/5/6/7/88/0 与本文 §3.1 完全一致；菜单 4/8 与 `ui` 子命令已删除 |
| 2 | `Update/Update1D.py` | 全文 158 行 | `UPDATE_ALL` **11 步**顺序（末尾无看板生成）、日志写根 `update_log.txt`、末尾清 `.old_*` 与 §6.1 一致 |
| 3 | `Update/SZ2001D.py` | 全文 429 行 | 25 列字段/舍入/MA 满 N 日/连板/is_bottom 与 §5.3 一致；`_rotate_dir` 语义与 §7.1 一致 |
| 4 | `Update/SZ200Strategy.py` | 全文 359 行 | TPO 选股条件、市值 T-2 口径、29 列写入、`BUILD_SENTIMENT_KLINE` 与 §5.2/§5.3 一致；确认文件带 UTF-8 BOM |
| 5 | `StrategyUI.py` | 函数签名 grep + 关键段精读 | `CMD_UPDATE_THS` 只写 XML 不重启同花顺、`_UPDATE_STEPS` 11 项；`GENERATE_STRATEGY_UI_OFFLINE` 等看板生成函数 0 调用方（死代码） |
| 6 | `Backtest.py` | 头部 + 关键函数（`_sell_price_1d/5m`、`BACKTEST`） | 卖出规则/手续费与 §4.2 一致；不写结果文件（见 §8.8） |
| 7 | 新 UI | `tools/dashboard_server.py`（头部 + `do_GET/do_POST` 路由）、`tools/realtime_feed.py`、`tools/next_day_strategy.py`、`tools/daily_update.py`（6 步）、`dashboard/index.html` 与 `js/api.js` | 8765 端口、静态托管 + `/api/*`、6 步盘后流程与 §3.2/§3.3 一致；`backend_data` 只读 AIData |
| 8 | AIData 抽样 | 直接读 `TRADING_DATES`/`STOCK_CODES_ALL`/`INDEX_CODES`/`INDEX_5M_CODES`/`1D`/`1D_ORIGIN`/`5M`/`INDEX`/`INDEX_5M`/`TOP`/`TOP_FIRST`/`STRATEGY`/`NEXT_DAY`/`THS`；openpyxl 读 `SZ100.xlsx`、`指数.xlsx`、`TOP_ORIGIN xlsx` | 列数 7/25/13/29、编码 GBK、日期范围、文件数、行数与 §5 一致；`INDEX_5M` 13 列 9,648 行、`NEXT_DAY` 字段结构已核对 |
| 9 | 路径存在性/引用计数 | 脚本遍历 `Path.py` 全部函数逐个解析并 `os.path.exists`，同时在全部 46 个 .py 中统计引用 | §5.4 的 19 个失效函数均为“不存在 + 0 引用” |
| 10 | 语法/编码 | `ast.parse(utf-8-sig)` 全部 46 个 .py（2026-11-04 实测，0 失败） | 全部通过；仅 `SZ200Strategy.py` 带 BOM |

### 10.2 待确认问题（请用户/Lead 拍板）

1. **`.codebuddy/skills/` 两份 SKILL.md 是否更新或删除**（当前严重过期，会误导后续 AI/开发者）。
2. **`AIData/STOCK_CODES`（677 行、无引用的纯代码清单）来历与去留**。
3. **`TOP_ORIGIN` 只导入“主板”涨停是否业务有意为之**（若是，本文应写明“20cm 板不参与 is_top/TPO”；若否，需补创业板/科创板 xlsx 并重跑加工）。
4. **`TPO_3` / `TPO_TOP` / `TPO_M5_SMALL` 策略是否弃用**（函数在、数据不在）。
5. **`StrategyUI` 旧看板生成死代码（约 2,000 行）是否删除**（`GENERATE_STRATEGY_UI_OFFLINE` / `_write_offline_data` / `_render_html`）。
6. **1D 覆盖 2,522 只 vs 池 3,048 只**是否需要在 UPDATE_ALL 里补全（当前一条龙按周期 scope 下载，可能长期不一致）。
7. **`.gitignore` 中旧 UI / PyInstaller 规则是否清理**（`.venv/`、`dist/`、`build/`、`*.spec`、`UI/MarcoUI/*`，路径已不存在）。
8. **根目录 `XIAOA_UI_REQUIREMENTS.md` 与 `journals/` 的维护边界**是否需在 README/FILE_ROUTING 写明（谁维护、是否入库）。

### 10.3 文档维护指引

- 目录树：可直接跑 `python tools/print_tree.py AICode -d 4 --files` 重新核对（选项见该脚本 docstring）。
- 统计口径：文件数/体积用 `Get-ChildItem -Recurse -File | Measure-Object Length -Sum`；日期范围读每个文件首尾行。
- 改代码后请顺手更新：§2（目录树）、§4（文件清单，含 `dashboard/` 与 `tools/`）、§5（数据字典）、§6（数据流）、§8（已知问题）；菜单/启动方式变动时同步 §3 与 README。
