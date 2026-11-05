# MarcoAI

> 中国 A 股**数据下载 + 加工 + 涨停/策略选股 + 回测 + 本地看板**的一体化个人量化研究终端。
> 数据源为通达信 `tqcenter` 插件行情 + 同花顺「涨停分析」导出的 Excel；盘后一条命令跑完更新，用本地网页看板 / 同花顺板块查看结果。

- 数据更新入口：**`python Run.py`**（交互菜单）
- 看板入口：**`python tools/dashboard_server.py`** → 浏览器打开 **http://127.0.0.1:8765/**
- 盘后一条龙：**`python tools/daily_update.py`**（6 步，适合无人值守）
- 权威文件地图：**[ARCHITECTURE.md](ARCHITECTURE.md)**；文件放置速查：**[FILE_ROUTING.md](FILE_ROUTING.md)**
- 目录树速查：`python tools/print_tree.py AICode -d 4 --files`

> 2026-11-04 起：旧 PySide6 桌面端（`UI/MarcoUI/`）与离线单页看板（`StrategyDashboardOffline.html` + `UI/data/`）**已删除**，统一使用新 UI（`dashboard/`）。

---

## 1. 目录导览（先看这 8 个位置）

| 位置 | 是什么 |
|---|---|
| `Run.py` | **唯一总入口**：菜单式数据更新 / 单项更新 / 同花顺 / 上传 Git |
| `AICode/MarcoAPI/Update/` | **数据管线**：交易日历、股票池、1D/5M/指数下载、涨停清单、加工、策略选股（入口 `Update1D.py::UPDATE_ALL`，路径统一由 `Path.py` 提供） |
| `AICode/MarcoAPI/StrategyUI.py` | **快捷命令中心**（`CMD_UPDATE_THS` / `CMD_RUN_STEP` / 策略解析）；旧看板生成函数已无调用方 |
| `AICode/MarcoAPI/Backtest.py` | **回测引擎**（first/last/avg/5m 四种卖出、手续费/印花税） |
| `dashboard/` | **新 UI 前端**：免构建，原生 ES Modules + 本地图表库（4 个页面：K 线工作区 / 策略回测 / 策略选股 / 实时看盘） |
| `tools/` | 新 UI 服务 `dashboard_server.py`、盘后总控 `daily_update.py`、实时数据源 `realtime_feed.py`、下一交易日名单 `next_day_strategy.py`、通达信导出/刷新工具 |
| `AIData/` | **全部数据**：`1D`/`1D_ORIGIN`/`5M`/`INDEX*`（含 `INDEX_5M`）/`TOP`/`TOP_FIRST`/`STRATEGY`/`NEXT_DAY`/`INFO`/`THS`/`DAILY` |
| `journals/` | 用户复盘日志 + 小志的结构化总结/索引/标签；`journals/coach/` 为小小A 的超短线教练知识库 |

完整目录树、逐文件职责、数据列定义、端到端数据流、已知问题 → 见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 2. 快速开始

### 2.1 启动新 UI（看板）

```powershell
cd C:\MarcoAI
python tools/dashboard_server.py --port 8765
# 浏览器打开 http://127.0.0.1:8765/
```

- 服务只读 `AIData`，不写业务数据；首次启动会在后台预热「策略选股」缓存（约 30~60 秒），期间其他页面可用。
- 「实时看盘」页需要通达信客户端已启动并登录（走 `tqcenter` 本地快照，约 2 秒轮询；只判断、不下单）。
- 页面数据随 `AIData` 更新；盘后 `daily_update.py` 第 6 步会自动重启本服务，避免读到启动时的旧缓存。

### 2.2 启动主菜单（数据更新）

```powershell
cd C:\MarcoAI
python Run.py
```

菜单（实测）：

```
[1] 更新数据      同步交易日历 / 日线 / 涨停 / 策略 / 目标池（= UPDATE_ALL，11 步）
[2] 更新5M数据    按策略候选日窗口下载 5 分钟行情（需通达信联网）
[3] 更新同花顺    按策略写入同花顺板块 blockstockV3.xml
[5] 单项更新      列出一条龙各步骤，单独运行任意一项
[6] 上传 Gitee    提交并推送到 Gitee 仓库
[7] 上传 GitHub   提交并推送到 GitHub 仓库
[88] 一条龙更新   倒计时选策略/周期 → 更新数据(含5M) → 更新同花顺（Gitee 默认关）
[0] 退出
```

> 旧菜单 4（离线看板）与菜单 8（启动新UI）已删除；`python Run.py ui` 同步移除。

非交互子命令：

```powershell
python Run.py update_all          # 等价菜单 1
python Run.py update_5m           # 等价菜单 2
python Run.py update_ths TPO_M5   # 等价菜单 3
python Run.py step UPDATE_TOP     # 单项更新（step 见 ARCHITECTURE.md §6.2）
```

### 2.3 盘后一条龙（推荐，6 步）

```powershell
python tools/daily_update.py --dry-run     # 只体检，不动数据
python tools/daily_update.py               # 正式执行（同花顺自动、Gitee 跳过）
python tools/daily_update.py --with-tdx    # 需要时自动检测/尝试刷新通达信本地数据
python tools/daily_update.py --no-ths      # 不自动更新同花顺
python tools/daily_update.py --with-git    # 需要时顺带上传 Gitee
```

6 步：① 导出当日涨停 xlsx → `TOP_ORIGIN`　② 通达信本地数据校验（**默认不自动刷新**，需用户手动执行「盘后数据下载」；`--with-tdx` 才自动检测/刷新，不新鲜会返回码 2）　③ 指数/宽基 5m 全量 → `INDEX_5M`　④ 一条龙 `UPDATE_ALL`（**同花顺默认自动更新**，`--no-ths` 跳过）　⑤ 生成下一交易日 TPO_M5 名单 → `NEXT_DAY/strategy.json`　⑥ 重启新 UI 服务。
结果：控制台摘要 + `logs/daily_update_<时间>.json/.log`。默认行为：**同花顺自动更新**（跳过加 `--no-ths`）、**通达信不自动刷新**（手动盘后下载，需要自动时加 `--with-tdx`）、**Gitee 关闭**（需要时加 `--with-git`）。详见 ARCHITECTURE.md §3.3。

### 2.4 日常最常用

- 收盘后：`python tools/daily_update.py`（或 `python Run.py` → 88）。
- 看最新结果：浏览器打开 **http://127.0.0.1:8765/**（数据更新后刷新页面即可）。

## 3. 数据更新前置条件

| 前置条件 | 说明 |
|---|---|
| **通达信客户端 + tqcenter 插件** | 数据下载（1D/5M/指数/交易日历）与「实时看盘」都要调 `tqcenter`。插件目录默认 `D:/new_tdx_mock/PYPlugins/user`，可用环境变量 `TDX_PLUGIN_PATH` 覆盖（本机为 `C:\new_tdx64\PYPlugins\user`） |
| **Microsoft Edge** | `daily_update.py` 用 Edge 自动导出通达信「问小达」涨停 xlsx（首次需登录，登录态保存在 `.edge-profile/`） |
| **联网** | 通达信行情、Gitee/GitHub push |
| **手工源数据** | `AIData/INFO/SZ100.xlsx`（股票池/流通股本）、`AIData/INFO/指数.xlsx`、`AIData/TOP_ORIGIN/*.xlsx`（每日涨停股，从同花顺“涨停分析”导出，文件名需含 `YYYY年M月D日`）。这些是**手工导入**、丢了无法重造，已纳入 git |
| **同花顺安装路径** | 默认 `C:\同花顺远航版\bin\users\狗蛋儿家的金`，可用环境变量 `THS_TARGET_DIR` 覆盖 |
| **Python 依赖** | 系统 Python 3.10+：pandas / numpy / openpyxl（无需 Node、无需 PySide6） |

> 注意：数据更新会**整目录重建** `1D/1D_ORIGIN/5M/INDEX/INDEX_ORIGIN/TOP/TOP_FIRST/STRATEGY`，不要在更新过程中手工改这些目录里的文件。

## 4. 常见问题

- **看板页面空白 / 数据缺失** → 看 `tools/dashboard_server.py` 控制台日志（`[backend] loaded backend_data.py ...`）；确认 `AIData` 有数据、`python Run.py update_all` 跑过。
- **实时看盘没数据** → 通达信客户端需启动并登录；下一交易日名单由 `daily_update.py` 第 5 步生成（`AIData/NEXT_DAY/strategy.json`）；持仓在 `dashboard/holdings.json`（本地、不入库，可在页面编辑）。
- **5M 只有少量股票/时间不连续** → 正常：`AIData/5M` 是按策略候选日 T-2~T+5 窗口下载的，不是连续全历史；指数 5m 全量在 `AIData/INDEX_5M`。
- **同花顺板块没变化** → 确认策略在 `AIData/STRATEGY/` 下有数据、同花顺目录存在；脚本只覆盖 XML，**不会自动重启同花顺**。
- **想找旧离线看板 / 桌面端** → 已于 2026-11-04 删除，统一用新 UI。
- **文件该放哪/某文件干什么** → [FILE_ROUTING.md](FILE_ROUTING.md)（快查）；细节见 [ARCHITECTURE.md](ARCHITECTURE.md) §4（代码）、§5（数据）、§7（放置约定）。
- **已知遗留与待清理项**（旧 `.gitignore` 规则、失效 `Path` 函数、过期 `.codebuddy` 文档等）→ [ARCHITECTURE.md](ARCHITECTURE.md) §8。

## 5. 文档索引

| 文档 | 用途 |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | **权威文件地图**：目录树、逐文件职责、数据字典、端到端数据流、放置约定、已知问题 |
| [FILE_ROUTING.md](FILE_ROUTING.md) | **文件放置速查**：新文件/新目录放哪、命名、必须联动修改的登记点（3 行快答）|
| `dashboard/README.md` | 新 UI 页面功能与接口说明 |
| `journals/README.md` | 复盘日志体系（目录结构、写作模板、标签、总结流程） |
| `XIAOA_UI_REQUIREMENTS.md` | 新 UI v1 需求与验收清单（小小A 维护） |
| `AICode/MarcoAPI/Skills/TPO_M5_2.0/SKILL.md` | 策略 TPO_M5_2.0（骨架）的改进点与参考方法 |
| `AIBook/威科夫盘口解读方法_量价分析精读.md` | 量价/盘口解读学习资料 |
| `tools/print_tree.py` | 目录结构查看器（`python tools/print_tree.py --help`） |
