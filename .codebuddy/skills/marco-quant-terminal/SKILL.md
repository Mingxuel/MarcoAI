---
name: marco-quant-terminal
description: MarcoAI 量化数据终端的整体架构、入口脚本与"离线看板"使用流程。当用户提到量化数据终端、看板、StrategyUI/Run.py/StrategyService、刷新数据、TAB 为空、离线看板时使用。This skill should be used when working on the MarcoAI quant dashboard UI, viewing or regenerating the offline dashboard, or diagnosing empty tabs.
---

# MarcoAI 量化数据终端

量化数据终端把 `AIData/*` 下的计算结果渲染成一个单文件 HTML 看板（图表用 ECharts / K 线）。

## 关键事实（务必先读，避免走弯路）
- **用户只使用离线看板**（浏览器 file:// 打开生成的 HTML），不使用本地 HTTP 服务。需要"看最新数据"时，永远告诉他：重新生成离线看板并重新打开文件，而不是"刷新服务器 / 重启服务"。
- 看板 HTML 在**生成时把数据内联**进 `const DATA = {...}`。因此"TAB 为空"几乎总是因为看的是**旧 HTML 文件**，而非数据缺失。诊断顺序：先确认 `AIData/*` 目录有数据 → 再让其重新生成看板。

## 入口脚本
| 脚本 | 作用 |
|------|------|
| `Run.py` | 主交互菜单（`python Run.py`）。**用户实际操作入口。** |
| `AICode/MarcoAPI/StrategyUI.py` | 看板 HTML 生成器，含 `GENERATE_STRATEGY_UI`（在线/CDN 版）与 `GENERATE_STRATEGY_UI_OFFLINE`（内联库、无外网，菜单 4 使用）。 |
| `AICode/MarcoAPI/StrategyService.py` | 本地 HTTP 服务（localhost:8765）。**用户不用，但代码存在；排障时不要建议刷它。** |
| `AICode/MarcoAPI/MarcoAI_Handler.py` | `marcoai://` 协议处理器，支持直接双击 HTML 文件时跑命令。 |

## Run.py 菜单（当前）
1 更新数据（全量 UPDATE_ALL） · 2 更新5M数据 · 3 更新同花顺板块 · 4 离线看板（生成并打开 StrategyDashboardOffline.html） · 5 单项更新（子菜单，见 marco-quant-update-pipeline） · 6 上传Gitee · 7 上传Github · 77/88 clone · 0 退出。

## 离线看板标准工作流
1. 跑数据更新：`python Run.py` → 1（全量）或 5（单项）。
2. 重新生成看板：`python Run.py` → 4。脚本写出 `AICode/MarcoAPI/UI/StrategyDashboardOffline.html` 并默认用浏览器打开。
3. 在浏览器中重新打开该 HTML（file://）。旧标签不会自动刷新内联数据，需重开文件。

## 输出文件
- 在线版：`AICode/MarcoAPI/UI/StrategyDashboard.html`（用 CDN，需联网）。
- 离线版：`AICode/MarcoAPI/UI/StrategyDashboardOffline.html`（库已内联，无网可用）。**用户用这个。**

## 看板 TAB 与数据来源（速查）
| TAB | 数据来源 |
|-----|---------|
| 策略 / K线 | AIData/STRATEGY + 候选池（合并 kline） |
| 候选池 | AIData/TARGET（TPO_3 / TOP / M5） |
| 涨停股 | AIData/TOP（`_load_top`） |
| 首板涨停股 | AIData/TOP_FIRST（`_load_top_first`） |
| 5分钟 | AIData/5M_ORIGIN + 候选（`_read_5m_window`） |

数据目录根由 `AICode/MarcoAPI/Update/Path.py`（`PATH_AIDATA` 等）定义。PROJECT_ROOT 为 `e:/MarcoAI`，故 `AIData` 实际在 `e:/MarcoAI/AIData`（不在 `AICode/MarcoAPI` 下）。

## 已知问题：首板涨停股 TAB 空（已修复，记入根因）
- **真根因（务必记住）**：`switchTab(name)` 里 回测/候选/选股/涨停 都有 `getElementById('panel-xxx').classList.toggle('active', ...)` 来显示面板，但**首板漏了这一行**（应为 `getElementById('panel-top_first').classList.toggle('active', name === 'top_first')`）。结果点击「首板涨停股」标签高亮了，但 `panel-top_first` 永远是 `display:none`（`.tab-panel` 默认隐藏、`.tab-panel.active` 才显示），列表虽已填好（jsdom 实测 181 天）却永远看不见。涨停股有那行所以正常 → 表现为「涨停正常、首板空」。
- 修正方式：照涨停股镜像，在 `switchTab` 补上上面那行（已加，位于 `StrategyUI.py` 的 `switchTab` 函数内、panel-top 切换行之后）。
- 两侧 JS 逻辑（`loadTop`/`loadTopFirst` 及 `selectTop*`/`selectTopFirst*`）其实**完全对称**，仅数据源 `DATA.top` vs `DATA.top_first` 不同；Python 的 `_load_top` 与 `_load_top_first` 返回结构也一致（{日期: [[code,name,market_value],...]}）。所以"唯一区别是数据源"这句判断是对的——本次故障不在数据、也不在 JS，而在面板切换漏行。
- file:// 缓存坑（次要）：`webbrowser.open` 对已打开的同 URL 标签只聚焦、不重新读文件。已加：① `<head>` `Cache-Control: no-store`；② 自动打开 URL 带 `?v=<文件mtime>` cache-buster；③ 标题下「看板生成时间」戳；④ 页面顶/底有 `__errbox` 状态条（启动黄、成功绿、报错红）便于排障。**若改完仍异常，重开文件看状态条颜色**。
- 诊断顺序（不要凭猜）：① `list AIData/TOP_FIRST` 确认有数据；② 打开看板看 `__errbox` 状态条（绿=脚本跑完）；③ 若脚本跑完仍空，先怀疑 `switchTab` 是否给该面板加了 toggle 行，再看面板 id 与 `getElementById` 是否一致。
- 若需单独刷新首板数据：Run.py → 5 → 7（UPDATE_TOP_FIRST，依赖⑤涨停列表与⑥的 is_volume_up）。
