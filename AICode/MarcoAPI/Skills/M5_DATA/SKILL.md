# Skill: M5_DATA（5 分钟 K 线读取与解析）

## 定位
把 5min 数据的**格式、路径、常用计算**固化成可复用模块，避免每次重新摸索文件结构。
所有 5min 相关任务（TPO_M5 / TPO_M5_2.0 / 威科夫量价分析等）统一从这里取数。

## 数据事实（已核实）
- **源文件**：`AIData/5M/{code}.SH` / `AIData/5M/{code}.SZ`（每文件一只股票，含全部历史交易日）
- **行格式**（`|` 分隔）：
  `datetime|open|high|low|close|volume|amount|pre_close|ma5|ma10|ma20|ma30|ma60|ma120`
  - `datetime`：`YYYY-MM-DD HH:MM:SS`（首根 `09:35:00`，末根 `15:00:00`）
  - `pre_close`：昨收；`ma5..ma120`：均线（可能为空/0）
- **每天 48 根**：上午 `09:35–11:30` 共 24 根，下午 `13:05–15:00` 共 24 根（午休 `11:30–13:00`）
- **交易日历**：`AIData/TRADING_DATES`（每行 `YYYYMMDD`，升序）
- **目标股列表**：`AIData/TARGET/TPO_M5/{YYYYMMDD}`（每行 `code|name|market_value`）

## API（详见 `m5_data.py`）
- `load_5m(code) -> dict["YYYY-MM-DD", List[Bar]]`：读取某股全部 5min 数据
- `Bar` 字段：`datetime/open/high/low/close/volume/amount/pre_close/index`（1-based 当日序号）；属性 `date`/`time`/`date_compact`
- `trading_dates() -> List["YYYYMMDD"]`
- `date_window(t0, n=5) -> List["YYYYMMDD"]`：以 t0 结尾的 n 个连续交易日 `[T-(n-1)..T-0]`
- `target_stocks(t0) -> List[(code, name, mv)]`：取某 T-0 的目标股
- `first_high(bars) / last_low(bars) -> Optional[Bar]`：当日首次最高价 / 末次最低价 K 线
- `hl_positions(code, dates) -> dict[YYYYMMDD, {...}]`：批量取首高/末低位置（含 index、time、price、bar_count）

## 用法
```python
from AICode.MarcoAPI.Skills.M5_DATA import m5_data as M

data = M.load_5m("600000.SH")        # {"2026-09-30": [Bar(...), ...]}
wk   = M.date_window("20260930", 5)  # ["20260923".."20260930"]
pos  = M.hl_positions("600000.SH", wk)
# pos["20260930"] = {first_high_index, first_high_time, first_high_price,
#                    last_low_index, last_low_time, last_low_price, bar_count}
```

## 约定
- `Bar.index` 为当日 1-based 序号（1..48），由文件顺序推算，等于时间先后。
- `load_5m` 的日期键是 `YYYY-MM-DD`；`date_window`/`target_stocks`/`hl_positions` 用 `YYYYMMDD`，内部自动互转。
- 浮点比较（首高/末低）用精确相等；因文件中价均为字符串原样解析，同源一致可放心。
