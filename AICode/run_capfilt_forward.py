"""前向测试（防过拟合）：训练期 2026H1 选否决规则，验证期 2026H2 直接套用。

做法：
  1) 在 TPO_M5 全部候选上，枚举候选"单条否决条件"，用 H1 收益选出对训练期有正贡献的规则；
  2) 把选出的规则并集作为固定否决集，分别写入 H1 / H2 两个策略文件夹；
  3) 对 H1、H2 各自跑 Backtest，对比 CAPFILT(固定规则) 与 M5(大盘优先) 基线；
  4) 同时给出"你之前定的 3 条规则"在 H1/H2 的表现，便于对照。

运行：cd e:/MarcoAI/AICode && python run_capfilt_forward.py
"""
import os
import re
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from AICode.MarcoAPI.Update.SZ2001D import GET_SZ200_1D_PREVIOUS  # noqa: E402
from AICode.MarcoAPI import Backtest  # noqa: E402

SRC_DIR = os.path.join(_ROOT, "AIData", "Strategy", "TPO_M5")
OUT = os.path.join(_ROOT, "AIData", "Strategy")

TRAIN = ["202601", "202602", "202603", "202604", "202605", "202606"]
TEST = ["202607", "202608", "202609"]
UP_SHORT = 0.3


def _body(r):
    return abs(r.close - r.open) or (max(r.close, 1e-9) * 0.01)


def _up(r):
    return (r.high - max(r.open, r.close)) / _body(r)


def _feat(r1, r2, r3):
    pred = (r1.high + (r1.high - r3.high)) if (r3 and r1.high < r2.high) else (2 * r1.high - r2.high)
    room = (pred - r1.close) / r1.close if r1.close > 0 else -9
    up1, up2 = _up(r1), _up(r2)
    above60 = (r1.ma60 > 0) and (r1.close > r1.ma60)
    slope = r1.ma60 - r2.ma60
    red1 = r1.is_red == 1
    red2 = r2.is_red == 1
    hu = r1.high > r2.high
    lu = r1.low > r2.low
    return dict(pred=pred, room=room, up1=up1, up2=up2, above60=above60, slope=slope,
                red1=red1, red2=red2, hu=hu, lu=lu, low1=r1.low, low2=r2.low)


# 候选单条否决条件
CANDIDATES = {
    "nospace":   lambda f: f["room"] <= 0,
    "smallroom": lambda f: f["room"] < 0.03,
    "shortup":   lambda f: UP_SHORT <= f["up1"] < 1.0,
    "longup":    lambda f: f["up1"] >= 1.0,
    "doubleup":  lambda f: f["up1"] >= 1.0 and f["up2"] >= 1.0,
    "yang2yin":  lambda f: (not f["red1"]) and f["red2"],
    "lianyin":   lambda f: (not f["red1"]) and (not f["red2"]),
    "qijiang":   lambda f: (not f["hu"]) and (not f["lu"]),
    "below60":   lambda f: not f["above60"],
    "down60":    lambda f: f["above60"] and f["slope"] < 0,
    "breaklow":  lambda f: f["low1"] < f["low2"],
}
# 你之前定的 3 条固定规则
FIXED = ["nospace", "shortup", "down60"]


def _load_dates(prefix):
    dates = []
    for d in sorted(f for f in os.listdir(SRC_DIR) if f.isdigit()):
        if d[:6] in prefix:
            dates.append(d)
    return dates


def _rows_of(d):
    with open(os.path.join(SRC_DIR, d), "r", encoding="gbk", errors="ignore") as fh:
        lines = [ln.rstrip("\n") for ln in fh if ln.strip()]
    return [ln.split("|") for ln in lines if len(ln.split("|")) >= 11]


def _picks(dates, veto_fn):
    picks = []
    for d in dates:
        for c in _rows_of(d):  # 已按大盘顺序
            r1 = GET_SZ200_1D_PREVIOUS(c[0], d, 1)
            r2 = GET_SZ200_1D_PREVIOUS(c[0], d, 2)
            r3 = GET_SZ200_1D_PREVIOUS(c[0], d, 3)
            if r1 is None or r2 is None:
                continue
            if not veto_fn(_feat(r1, r2, r3)):
                picks.append(c)
                break
        else:
            picks.append(None)
    return picks


def _compound_first(picks):
    cap = 100000.0
    for cols in picks:
        if cols is None:
            continue
        sp = Backtest._sell_price_1d(cols)
        try:
            pre = float(cols[10])
        except (ValueError, IndexError):
            continue
        if sp is None or pre <= 0:
            continue
        cap *= (1 + Backtest._trade_net_return(pre, sp, cap))
    return cap / 100000.0 - 1.0


def _write_strategy(name, picks_by_date):
    d = os.path.join(OUT, name)
    os.makedirs(d, exist_ok=True)
    for date, cols in picks_by_date:
        with open(os.path.join(d, date), "w", encoding="utf-8") as fh:
            fh.write(("|".join(cols) + "\n") if cols else "\n")


def _totals(name):
    res = Backtest.BACKTEST(name, sell_modes=["first", "5m"])
    rx = re.compile(r"总收益率:\s*([-\d.]+)%")
    out = {}
    for mode in ("first", "5m"):
        txt = res.get(mode, "")
        m = rx.search(txt)
        out[mode] = float(m.group(1)) if m else None
    return out


def main():
    train_dates = _load_dates(TRAIN)
    test_dates = _load_dates(TEST)
    print(f"训练期(H1)日期数: {len(train_dates)} | 验证期(H2)日期数: {len(test_dates)}\n")

    # 基线 M5（大盘优先=首行）
    m5_train = [(_d, _rows_of(_d)[0] if _rows_of(_d) else None) for _d in train_dates]
    m5_test = [(_d, _rows_of(_d)[0] if _rows_of(_d) else None) for _d in test_dates]
    m5_tr_picks = [c for _, c in m5_train]
    m5_te_picks = [c for _, c in m5_test]

    # --- 训练期选规则 ---
    base_tr = _compound_first(m5_tr_picks)
    print(f"[训练期] M5 基线 first 收益: {base_tr*100:.2f}%")
    selected = []
    for nm, fn in CANDIDATES.items():
        ret = _compound_first(_picks(train_dates, fn))
        tag = "[保留]" if ret > base_tr else "-"
        if ret > base_tr:
            selected.append(nm)
        print(f"  单否 [{nm:<9}] H1收益 {ret*100:>7.2f}%  {tag}")
    print(f"\n训练期选出的规则并集: {selected}\n")

    # 组合否决
    sel_fns = [CANDIDATES[n] for n in selected]
    fixed_fns = [CANDIDATES[n] for n in FIXED]

    def union(fns):
        return lambda f: any(g(f) for g in fns)

    # 写四个策略文件夹
    _write_strategy("TPO_M5_TRAIN", m5_train)
    _write_strategy("TPO_M5_TEST", m5_test)
    _write_strategy("TPO_CAPSEL_TRAIN", list(zip(train_dates, _picks(train_dates, union(sel_fns)))))
    _write_strategy("TPO_CAPSEL_TEST", list(zip(test_dates, _picks(test_dates, union(sel_fns)))))
    _write_strategy("TPO_CAPFIX_TRAIN", list(zip(train_dates, _picks(train_dates, union(fixed_fns)))))
    _write_strategy("TPO_CAPFIX_TEST", list(zip(test_dates, _picks(test_dates, union(fixed_fns)))))

    m5t = _totals("TPO_M5_TRAIN")
    m5e = _totals("TPO_M5_TEST")
    selt = _totals("TPO_CAPSEL_TRAIN")
    sele = _totals("TPO_CAPSEL_TEST")
    fixt = _totals("TPO_CAPFIX_TRAIN")
    fixe = _totals("TPO_CAPFIX_TEST")

    def g(x):
        return f"{x:.2f}%" if x is not None else "   --"

    print("== 总收益率对比（first=收盘卖 / 5m=日内卖，单位 %）==")
    print(f"  {'策略':<22}{'H1(first)':>12}{'H2(first)':>12}{'H1(5m)':>12}{'H2(5m)':>12}")
    print(f"  {'M5基线(大盘优先)':<22}{g(m5t['first']):>12}{g(m5e['first']):>12}{g(m5t['5m']):>12}{g(m5e['5m']):>12}")
    print(f"  {'CAPSEL(训练选出)':<22}{g(selt['first']):>12}{g(sele['first']):>12}{g(selt['5m']):>12}{g(sele['5m']):>12}")
    print(f"  {'CAPFIX(你定3条)':<22}{g(fixt['first']):>12}{g(fixe['first']):>12}{g(fixt['5m']):>12}{g(fixe['5m']):>12}")

    # 是否过拟合：CAPFILT/CAPSEL 在 H2 是否仍跑赢 M5
    print("\n== 过拟合判定（H2 是否仍跑赢 M5 基线）==")
    for nm, val, base in [("CAPSEL", sele['first'], m5e['first']),
                          ("CAPFIX", fixe['first'], m5e['first'])]:
        if val is not None and base is not None:
            print(f"  {nm}: H2 first {val:.2f}% vs M5 {base:.2f}% -> {'[赢]' if val > base else '[输]'}")
    if sele['5m'] is not None and m5e['5m'] is not None:
        print(f"  CAPSEL: H2 5m {sele['5m']:.2f}% vs M5 {m5e['5m']:.2f}% -> {'[赢]' if sele['5m'] > m5e['5m'] else '[输]'}")
    if fixe['5m'] is not None and m5e['5m'] is not None:
        print(f"  CAPFIX: H2 5m {fixe['5m']:.2f}% vs M5 {m5e['5m']:.2f}% -> {'[赢]' if fixe['5m'] > m5e['5m'] else '[输]'}")


if __name__ == "__main__":
    main()
