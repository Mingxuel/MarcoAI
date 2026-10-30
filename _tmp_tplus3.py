import sys
from collections import defaultdict
sys.path.insert(0, 'c:/MarcoAI'); sys.path.insert(0, 'c:/MarcoAI/AICode')
from AICode.MarcoAPI.StrategyUI import _mode3_candidates_by_d, _load_top_first_vol_ma60_mode3
from AICode.MarcoAPI.Update.SZ2001D import GET_SZ200_1D_PREVIOUS
from AICode.MarcoAPI.Update.TradingDates import TRADING_DATE_AFTER

by_d = _mode3_candidates_by_d()          # 全集(首板涨停+前4日量价异动)，按涨停日D
mode3 = _load_top_first_vol_ma60_mode3()  # 现版(剔除T日涨停)，按关注日T

def tplus3_compound(daily_by_T: dict) -> float:
    """买关注日T收盘，持有到 T+3 收盘，逐日等权复利（模拟面板/T+3口径）。"""
    INIT = 100000.0
    cap = INIT
    cnt = 0
    for T in sorted(daily_by_T):
        T3 = TRADING_DATE_AFTER(T, 3)
        if not T3:
            continue
        rs = daily_by_T[T]
        rets = []
        for code, name, mv in rs:
            a = GET_SZ200_1D_PREVIOUS(code, T, 0)
            b = GET_SZ200_1D_PREVIOUS(code, T3, 0)
            if a is None or b is None or a.close <= 0:
                continue
            rets.append((b.close - a.close) / a.close)
        if not rets:
            continue
        day_ret = sum(rets) / len(rets)
        alloc = cap / len(rets)
        cap += alloc * sum(day_ret for _ in rets)  # 等权近似
        cnt += 1
    return cap / INIT - 1, cnt

# 旧版 universe：by_d 按 关注日T=D+1 归档（含T日涨停股）
old_by_T: dict = defaultdict(list)
for D, rows in by_d.items():
    T = TRADING_DATE_AFTER(D, 1)
    if T:
        old_by_T[T].extend(rows)

old_ret, old_n = tplus3_compound(old_by_T)
new_ret, new_n = tplus3_compound(mode3)
print(f"持有T+3 回测（买关注日T，拿3天，等权复利）:")
print(f"  旧版(含T日涨停股): 总收益 {old_ret*100:.2f}%  交易日(关注日){old_n}")
print(f"  现版(剔除T日涨停): 总收益 {new_ret*100:.2f}%  交易日(关注日){new_n}")
