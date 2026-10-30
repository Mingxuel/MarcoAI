import sys
sys.path.insert(0, 'c:/MarcoAI'); sys.path.insert(0, 'c:/MarcoAI/AICode')
from AICode.MarcoAPI.StrategyUI import (
    _load_top_first_vol_ma60_mode3, _load_top_first, _code_to_ths_security
)
from AICode.MarcoAPI.Update.TradingDates import TRADING_DATES, EFFECTIVE_LATEST_TRADING_DATE

mode3 = _load_top_first_vol_ma60_mode3()
top_first = _load_top_first()
tdates = TRADING_DATES()
tdict = {d: i for i, d in enumerate(tdates)}

_dday = next((d for d in sorted(mode3, reverse=True) if mode3[d]), None)
_day1 = tdates[tdict[_dday] - 1] if (_dday in tdict and tdict[_dday] > 0) else None

print("EFFECTIVE_LATEST_TRADING_DATE:", EFFECTIVE_LATEST_TRADING_DATE())
print("最新关注日 D-DAY (_dday):", _dday)
print("DAY-1 日期 (_day1 = T-1):", _day1)
print("  top_first 是否含该日:", _day1 in top_first, " -> 该日首板涨停股数:", len(top_first.get(_day1, [])))
print("D-DAY 候选数:", len(mode3.get(_dday, [])))
print()
print("=== DAY-1 block 前 15 只 ===")
for c in sorted(top_first.get(_day1, []), key=lambda r: float(r[2]), reverse=True)[:15]:
    print("  ", c[0], c[1], c[2])
print()
print("=== D-DAY block 前 15 只 ===")
for c in sorted(mode3.get(_dday, []), key=lambda r: float(r[2]), reverse=True)[:15]:
    print("  ", c[0], c[1], c[2])
