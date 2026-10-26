import os, glob

ROOT     = r"C:/MarcoAI"
SIG_DIR  = os.path.join(ROOT, "AIData", "TOP_FIRST_VOL_MA60")
ONE_D    = os.path.join(ROOT, "AIData", "1D")

HOLD_DAYS = 5           # 持有交易日数
BUY_MODE  = "T1_OPEN"   # T1_OPEN=信号日后一交易日开盘买；T_CLOSE=信号日收盘买

_1d_cache = {}

def load_1d(code):
    if code in _1d_cache:
        return _1d_cache[code]
    p = os.path.join(ONE_D, code)
    s = {}
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            for ln in f:
                parts = ln.strip().split("|")
                if len(parts) < 5:
                    continue
                try:
                    s[parts[0]] = (float(parts[1]), float(parts[4]))  # (open, close)
                except ValueError:
                    continue
    _1d_cache[code] = s
    return s

def nth_trading_day(series, date, n):
    keys = sorted(series.keys())
    if date not in series:
        for k in keys:
            if k >= date:
                date = k
                break
        else:
            return None
    i = keys.index(date)
    j = i + n
    return keys[j] if 0 <= j < len(keys) else None

signals = {}
for fp in glob.glob(os.path.join(SIG_DIR, "*")):
    d = os.path.basename(fp)
    if not (len(d) == 8 and d.isdigit()):
        continue
    with open(fp, encoding="utf-8") as f:
        codes = [ln.split("|")[0].split()[0].strip() for ln in f if ln.strip()]
    if codes:
        signals[d] = codes

daily = {}
for d, codes in signals.items():
    rets = []
    for code in codes:
        s = load_1d(code)
        if not s:
            continue
        if BUY_MODE == "T_CLOSE":
            if d not in s:
                continue
            buy_d, buy = d, s[d][1]
        else:
            buy_d = nth_trading_day(s, d, 1)
            if buy_d is None or buy_d not in s:
                continue
            buy = s[buy_d][0]
        sell_d = nth_trading_day(s, buy_d, HOLD_DAYS)
        if sell_d is None or sell_d not in s:
            continue
        sell = s[sell_d][1]
        if buy > 0:
            rets.append(sell / buy - 1)
    if rets:
        daily[d] = sum(rets) / len(rets)

monthly = {}
for d, r in daily.items():
    monthly.setdefault(d[:6], []).append(r)

print(f"[脚本1] 首板+MA60 平均买入每月收益  信号日数={len(daily)}  持有={HOLD_DAYS}日  买入={BUY_MODE}")
print(f"{'月份':<8}{'信号日':>6}{'月均收益%':>12}{'赢率%':>8}")
cum = 1.0
for m in sorted(monthly):
    rs = monthly[m]
    avg = sum(rs) / len(rs) * 100
    win = sum(1 for x in rs if x > 0) / len(rs) * 100
    print(f"{m:<8}{len(rs):>6}{avg:>12.2f}{win:>8.1f}")
    cum *= (1 + sum(rs) / len(rs))
print(f"\n全期信号日等权复合收益: {(cum - 1) * 100:.2f}%")
print(f"全期单信号日均收益: {sum(daily.values())/len(daily)*100:.2f}%  赢率: {sum(1 for x in daily.values() if x>0)/len(daily)*100:.1f}%")
