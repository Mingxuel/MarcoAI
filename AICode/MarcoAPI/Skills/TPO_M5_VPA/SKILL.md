# Skill: TPO_M5_VPA（威科夫量价趋势分析）

## 定位
把 `TARGET_5M/{t0}` 的「首高/末低」锚点与 `AIData/5M` 实际 5 分钟 K 线结合，做威科夫/库林《量价分析》式的趋势研判。
复用 `M5_DATA` 技能读取与解析 5M 数据，本技能只做分析。

## 方法
1. **之字形折线**：按时间顺序把 T-4..T-0 每日「首次最高价(H)」「末次最低价(L)」连成折线。
   - 横轴用「连续交易分钟」（09:30 起计、午休不计入、忽略隔夜缺口），跨日 `x = day_rank*240 + 当日交易分钟`。
   - 逐段斜率 `slope_per_bar = Δprice / (Δx/5)`，即每根 5 分 K 线的价格变化，反映线段倾斜方向与强度。
2. **量价判定（Effort vs Result）**：统计窗口内上量(收盘≥开盘)/下量(收盘<开盘)占比、净涨跌、T-0 日量能、最大量 K 线。
   - 量价齐升 / 价升量缩(无需求) / 价跌量增(供应) / 价跌量缩(供应枯竭)。
   - 末段斜率转好（跌势减速）作为筑底线索。

## API
- `build_zigzag(code, dates)` → 锚点列表（含 price/time/idx/x 与逐段 slope_per_bar）
- `volume_stats(code, dates)` → 窗口级 + T-0 日级量价统计
- `analyze_stock(code, t0)` → 汇总一只股票的分析结果
- `print_report(t0=None)` → 打印 T-0 全部目标股的可读分析（直接看）

## 用法
```python
from AICode.MarcoAPI.Skills.TPO_M5_VPA import vpa
print(vpa.print_report("20260930"))
```
