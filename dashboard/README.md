# MarcoAI 新看板 v1.4（dashboard/）

免构建前端（原生 ES Modules，不依赖 Node）+ 零依赖 Python 服务。深色主题，只读 AIData。

## 启动

```powershell
cd C:\MarcoAI
python tools/dashboard_server.py --port 8765
# 浏览器打开 http://127.0.0.1:8765/
```

服务启动后会在后台线程预热「策略选股」缓存（首次约 30–60s），预热期间页面其它功能可用；
`/api/picks` 首次请求若预热未完成会等待并缓存，之后毫秒级返回。

## 页面

- **K 线工作区**（默认）：2 图上下（上 1d、下 5m），支持 1/2上下/2左右/4 图；每面板独立周期
  （1d/5m/15m/30m；60m/周/月按 P1-10 灰显）与指标（MA/BOLL 主图，VOL/MACD/KDJ 副图）；
  股票联动 / 时间轴联动可开关，**周期永不联动**；命名工作区 + 内置 3 预设（竞价盯盘/打板盯盘/复盘验证），
  localStorage 持久化；快捷键 `1/2/4` 布局、`F` 自适应、`[ ]` 切周期、`L/S` 联动、`Esc` 关弹层。
- **策略回测**：策略 / 买入方式 / 卖出方式三下拉；8 指标卡；每日资金 K 线 + MA5/10/20/30/60/120 开关；
  月/季/年盈亏条形；近 20 日 / 全部收益分布直方图。空数据一律显示「—」。
- **策略选股（v1.2 左右分栏单页）**：左侧 K 线工作区（占 65%，可拖拽分隔条调宽并记忆）+ 右侧选股列表（35%）；
  策略 + 近 12 个月 + 刷新；TPO 窗口 T / T-1 与日期分组**同一套表格**（同列/表头/行高/颜色/排序，标题带 (T)/(T-1)，分组行可折叠）；
  日期分组表（代码/名称/涨跌幅/实际卖出涨幅(5m,扣费)/最高/最低/市值/操作），点表头排序，
  涨红 `#d62828` / 跌蓝 `#0077b6` / 涨停金 `#f5c518`；候选未回测显示「— 暂无数据 —」，缺失字段显示「—」；
  **点行只联动左侧 K 线**并标注「选股日 T-2（交易日历反查）/ 卖出日 T-0」，不跳页、不丢列表滚动/排序；
  窗口 <1200px 右栏可收起。点 `+` 把股票加入左侧工作区。

## 实时看盘（v1.4 / v2 布局）

- 页面：导航「实时看盘」。顶部 10 个指数（成长端 7 + 上证 / 中证银行 / 红利）、市场状态 / 数据时间 / 环境徽章。
- 布局：左 58% 5 分钟 K 线（可隐藏，localStorage 记忆，隐藏后右栏占满）；右 42% 当日策略 + 列表（窄屏上下堆叠）。
- K 线：`GET /api/realtime/kline?code=&period=5m`，直接读 `C:\new_tdx64\vipdoc\{sh,sz}\fzline\*.lc5`（缺文件回退 AIData/5M），
  最近 10 个交易日 ~480 根；默认 4 条均线：5m MA5/MA60 + 日均 MA5/MA60（日线按「截至前一交易日」计算，step line，避免未来函数），
  其它均线默认关闭可在「均线」弹层开启；今日 5m 未落盘时显示「数据截至 asOf（今日 5m 未落盘）」。
- 右侧：
  - 「当日策略」卡片：策略名 + 文件日期（T-0 卖出日）、T-1 环境 n/7 + 盘中宽度 n/7、自动结论（好环境→持有到 14:55；差+宽度≥4→B+ 抗到 14:55；差+宽度≤3→10:00 卖出）、规则摘要。
  - 「今日持仓 · 昨日尾盘买入（今日卖出）」= T 来源 4 只，成本=昨收，列 代码/名称/成本/现价/盈亏%/卖出判断/理由。
  - 「候选股 · 明日预选」= T-1 来源 6 只，列 代码/名称/现价/涨幅/买入判断(参考)/理由。
  - 「昨日已了结（T-0，复盘用）」默认折叠弱化；「我的持仓（holdings.json 手动）」默认折叠。
  - 点任意行 → 左侧 K 线切换该股；默认选中今日持仓第一只，无持仓选候选第一只。
- API：`GET /api/realtime` 增加 `strategy/holdingsToday/candidatesTomorrow/closedYesterday`（保留原 indices/candidates/holdings/env）；
  `GET/POST /api/realtime/holdings` 保持；`GET /api/realtime/kline` 新增。
- 行情：tqcenter 快照后台线程 ~2s 轮询（不用 subscribe_hq），前端 2s 轮询、切走暂停；只判断不下单。 

## v1.2 数据口径修复（/api/picks 包装层）

- 根因：`backend_data.get_strategy_pick()` 把最新两个候选日（如 20261103/20261102）归入
  `cand_group_dates`，只渲染候选池、不渲染 STRATEGY 回测明细，导致 2026-11 显示无数据。
- 修复：`tools/dashboard_server.py` 在 `/api/picks` 包装层用 `_load_strategy_detail` 把**有回测明细的日期**
  补成历史行结构并覆盖 picks，再重算 `months`（dates/count/hasData）与 `dateMeta`；
  不改 AICode、不写 AIData。返回新增 `candidate_dates`/`tpoWindow.prev`，`picks["20261103"]` 现含 600118.SH 等明细。
- 5m/15m/30m 窗口化数据：图表只绘制最近一段连续窗口，避免把两段窗口拼成连续走势。

## v1.1 组件化（便于以后多列表/条件选股）

- `js/components/pick_list.js`：`PickList` 组件，只负责列表渲染与交互（策略/月份/刷新/TPO/排序/选中/+）。
- `js/adapters/picks_adapter.js`：`picksAdapter` 数据适配层，当前走 `/api/picks`；预留
  `listSources / getSettings / setSettings / getBacktestRequest` 扩展点，并提供
  `picksAdapterRegistry` 注册表。以后新增「不同策略/条件的选股列表」或 `/api/screen`，只加 adapter、UI 不改。
- 左侧 K 线与主工作区共用同一 `WorkspaceView` + 同一套 store（布局按钮只作用于左侧区域）。

## 目录

```
dashboard/
  index.html              入口（顶栏 + 三个视图容器）
  css/styles.css          暗色主题样式
  js/main.js              顶栏装配 / 视图切换 / 快捷键
  js/api.js               fetch 封装（超时、JSON 校验）
  js/store.js             工作区状态模型 + 预设 + localStorage
  js/chart_adapter.js     lightweight-charts 适配层 + 指标计算（MA/BOLL/MACD/KDJ/VOL）
  js/views/workspace.js   多面板 K 线工作区（主工作区与选股页左侧共用，每实例独立 grid）
  js/views/backtest.js    策略回测页
  js/views/picks.js       策略选股页（左 K 线 + 右列表分栏、可拖拽分隔条）
  js/views/realtime.js    实时看盘页（候选买点 + 持仓卖点，2s 轮询、切走暂停）
  js/components/pick_list.js  PickList 组件（列表渲染/TPO/排序/选中）
  js/adapters/picks_adapter.js 选股数据适配层 + 适配器注册表（未来多来源扩展点）
  css/realtime.css        实时看盘样式
  holdings.json           持仓（用户可编辑；.gitignore 已忽略）
  js/util.js              DOM/格式化/toast/modal/popover
  vendor/                 图表库（lightweight-charts 5.0.8 + klinecharts 10.1.0 候选）
```

## 依赖的后端接口（tools/dashboard_server.py）

| 接口 | 说明 |
|---|---|
| `GET /api/meta` | 数据日（T-1）/版本/5M 覆盖数/默认标的/非实时标识 |
| `GET /api/strategies` | 策略列表 |
| `GET /api/dashboard?strategy=&pick_mode=first\|avg\|last&sell_mode=5m\|day` | 回测指标/资金 K 线/月季年/分布 |
| `GET /api/picks?strategy=` | 选股明细（含修复后的 2026-11 等回测明细）+ TPO 窗口 + 月份索引 + T-2 映射 + `candidate_dates` |
| `GET /api/kline?code=&period=1d\|5m\|15m\|30m\|60m\|1w\|1mo&count=` | K 线（缺文件返回 `exists:false` + `reason`，不触发通达信补数） |
| `GET /api/symbols` | 代码联想 |
| `GET /api/realtime` | 指数 + 当日策略 + 今日持仓(T) + 明日预选(T-1) + 昨日已了结(T-0)（tqcenter 快照） |
| `GET /api/realtime/kline?code=&period=5m` | 5m K 线（TDX vipdoc lc5）+ 5m/日均 MA 数据 |
| `GET/POST /api/realtime/holdings` | 读取 / 保存 `dashboard/holdings.json` |

## v1 已知缺口（未做，避免假功能）

- 画线工具、表格批量勾选加入工作区、表格 ↑/↓/Enter 键盘导航：P0 的最小集里未实现（行内 `＋` 加入工作区已实现）。
- 最新两期候选池：`AIData/STRATEGY/TPO_M5/20261103` 有 1 只、`20261102` 为空文件，
  故「候选·未回测」行只显示空态（数据本身如此，未臆造）。
- 5M 仅 253 只且窗口不连续；无数据面板显示空态 + 不自动补数（避免阻塞 /api/kline 与碰通达信）。
- 周/月/60m：服务端已正确重采样，UI 按 P1-10 灰显未开放。
- 实时行情/情绪条/涨停明细：P1/P2，不做。
