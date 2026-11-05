# dashboard/vendor

第三方图表库（本地文件，免构建、离线可用）：

| 文件 | 版本 | 来源 | 用途 |
|---|---|---|---|
| `lightweight-charts.standalone.production.js` | 5.0.8 | 复制自 `AICode/MarcoAPI/UI/vendor/`（TradingView lightweight-charts） | **当前实际使用**：`js/chart_adapter.js` 的 `KlineChart` / `CapitalChart` |
| `klinecharts.min.js` | 10.1.0 | `https://cdn.jsdelivr.net/npm/klinecharts@10.1.0/dist/umd/klinecharts.min.js` | 候选图表库（已成功下载并验证可加载：`window.klinecharts.init`） |

## 为什么 v1 用 lightweight-charts？

- 本机 `AICode/MarcoAPI/UI/vendor/lightweight-charts...js` 已验证为 **5.0.8**，原生支持多 pane
  （`chart.addSeries(..., paneIndex)` + `chart.panes()`），主图 + VOL/MACD/KDJ 副图实现稳定；
- klinecharts UMD 能加载，但 v10 的 canvas chart 实例 **没有 v9 的 `applyNewData`**（K 线方法改名）
  且十字光标订阅接口与 v9 不同，v1 工期优先稳定；已把 UMD 留作候选。
- 后续替换：只改 `js/chart_adapter.js` 的 `KlineChart` 实现即可，视图层不感知具体图表库。
