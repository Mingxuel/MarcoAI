"""TPO_M5 威科夫量价趋势分析（VPA）

输入: TARGET_5M/{t0} 的高低点锚（首高/末低）+ AIData/5M 实际 5 分钟 K 线。
方法:
  1. 由 T-4..T-0 每日「首次最高价」「末次最低价」构造时间序锚点折线（之字形 zigzag）；
     以交易日连续交易分钟为横轴（忽略隔夜缺口），逐段算斜率(每根5分K线的价格变化)。
  2. 结合 5M 实际 K 线，按威科夫/库林《量价分析》做 Effort vs Result 判定：
     量价齐升 / 价升量缩(无需求) / 价跌量增(供应) / 价跌量缩(供应枯竭)。
输出: 每只目标股的折线锚点、分段斜率、量价判定与威科夫解读。

用法:
    python vpa.py            # 最新 T-0
    python vpa.py 20260930   # 指定 T-0
"""
import os
import sys

_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
if _root not in sys.path:
    sys.path.insert(0, _root)
from AICode.MarcoAPI.Skills.M5_DATA.m5_data import (  # 复用 5M 读取/解析技能
    load_5m, hl_positions, date_window, target_stocks, trading_dates, FIVE_M_DIR,
)


def trading_minutes(time_str: str) -> int:
    """把 HH:MM:SS 转成「自 09:30 起的交易分钟数」（午休不计入），用于横轴。"""
    h, m, _ = time_str.split(":")
    t = int(h) * 60 + int(m)
    if t <= 11 * 60 + 30:
        return t - (9 * 60 + 30)
    return 120 + (t - 13 * 60)


def build_zigzag(code: str, dates):
    """构造 T-4..T-0 的之字形锚点折线，并算每段斜率(每5分K线价格变化)。"""
    pos = hl_positions(code, dates)
    events = []
    for rank, d in enumerate(dates):
        v = pos.get(d, {})
        if v.get("first_high_index") is None or v.get("last_low_index") is None:
            continue
        events.append((rank, d, "H", v["first_high_price"], v["first_high_time"], v["first_high_index"]))
        events.append((rank, d, "L", v["last_low_price"], v["last_low_time"], v["last_low_index"]))
    events.sort(key=lambda e: (e[0], e[4]))  # 同日按时间，跨日按日序
    pts = []
    for (rank, d, kind, price, time, idx) in events:
        x = rank * 240 + trading_minutes(time)
        pts.append({"date": d, "kind": kind, "price": price, "time": time, "idx": idx, "x": x})
    for i in range(1, len(pts)):
        dx = pts[i]["x"] - pts[i - 1]["x"]
        dp = pts[i]["price"] - pts[i - 1]["price"]
        bars = dx / 5.0 if dx else 0.0
        pts[i]["dp"] = dp
        pts[i]["dx_bars"] = bars
        pts[i]["slope_per_bar"] = (dp / bars) if bars else 0.0
    return pts


def volume_stats(code: str, dates):
    """5M 实际 K 线的量价统计（窗口级 + T-0 日级）。"""
    data = load_5m(code)
    bars = []
    for d in dates:
        dd = d[:4] + "-" + d[4:6] + "-" + d[6:]
        bars.extend(data.get(dd, []))
    empty = {
        "n": 0, "up_vol": 0.0, "down_vol": 0.0, "total": 0.0, "up_vol_share": 0.0,
        "change_pct": 0.0, "t0_up_share": 0.0, "t0_chg": 0.0, "max_vol": 0.0,
        "max_vol_range": 0.0, "max_vol_co": 0.0,
    }
    if not bars:
        return empty
    up = [b for b in bars if b.close >= b.open]
    down = [b for b in bars if b.close < b.open]
    up_vol = sum(b.volume for b in up)
    down_vol = sum(b.volume for b in down)
    total = up_vol + down_vol
    first_close = bars[0].close
    last_close = bars[-1].close
    change_pct = (last_close - first_close) / first_close * 100 if first_close else 0.0
    t0d = dates[-1]
    t0bars = [b for b in bars if b.date_compact == t0d]
    t0_up = sum(b.volume for b in t0bars if b.close >= b.open)
    t0_down = sum(b.volume for b in t0bars if b.close < b.open)
    t0_total = t0_up + t0_down
    t0_up_share = t0_up / t0_total if t0_total else 0.0
    t0_chg = (t0bars[-1].close - t0bars[0].close) / t0bars[0].close * 100 if t0bars else 0.0
    maxb = max(bars, key=lambda b: b.volume)
    return {
        "n": len(bars), "up_vol": up_vol, "down_vol": down_vol, "total": total,
        "up_vol_share": up_vol / total if total else 0.0, "change_pct": change_pct,
        "t0_up_share": t0_up_share, "t0_chg": t0_chg,
        "max_vol": maxb.volume, "max_vol_range": maxb.high - maxb.low,
        "max_vol_co": maxb.close - maxb.open,
    }


def interpret(net_pct, up_vol_share, pts):
    """威科夫量价判定（结合净涨跌与量能结构）。"""
    flags = []
    if net_pct > 0.5 and up_vol_share >= 0.55:
        flags.append("上升趋势·量价齐升（需求主导、强势可延续）")
    elif net_pct > 0.5 and up_vol_share < 0.45:
        flags.append("上升但价升量缩（需求不足/无需求，上涨脆弱）")
    elif net_pct < -0.5 and up_vol_share < 0.45:
        flags.append("下降趋势·价跌量增（供应主导、弱势）")
    elif net_pct < -0.5 and up_vol_share >= 0.55:
        flags.append("下降但价跌量缩（供应枯竭，可能止跌/吸筹）")
    else:
        flags.append("横盘·供需均衡（区间震荡）")
    slopes = [p.get("slope_per_bar", 0.0) for p in pts[1:]]
    if len(slopes) >= 3:
        if slopes[0] < 0 and slopes[-1] > slopes[0]:
            flags.append("末段斜率转好（跌势减速/可能筑底）")
    return "; ".join(flags)


def analyze_stock(code, t0):
    dates = date_window(t0, 5)
    pts = build_zigzag(code, dates)
    vpa = volume_stats(code, dates)
    net = net_pct = overall_slope = 0.0
    if len(pts) >= 2:
        p0, pN = pts[0], pts[-1]
        net = pN["price"] - p0["price"]
        net_pct = net / p0["price"] * 100 if p0["price"] else 0.0
        dx = pN["x"] - p0["x"]
        overall_slope = (net / (dx / 5.0)) if dx else 0.0
    verdict = interpret(net_pct, vpa["up_vol_share"], pts)
    return {
        "code": code, "dates": dates, "pts": pts, "vpa": vpa,
        "net": net, "net_pct": net_pct, "overall_slope": overall_slope,
        "verdict": verdict,
    }


def print_report(t0=None):
    if t0 is None:
        t0 = trading_dates()[-1]
    stocks = target_stocks(t0)
    out = []
    out.append(f"=== TPO_M5 威科夫量价分析  T-0={t0}  窗口={date_window(t0, 5)} ===")
    for code, name, _mv in stocks:
        r = analyze_stock(code, t0)
        out.append("")
        out.append(f"● {code} {name}")
        out.append("  折线锚点(之字形, 时间序):")
        for p in r["pts"]:
            sl = p.get("slope_per_bar")
            sl_s = f"  斜率/bar={sl:+.4f}" if sl is not None else ""
            out.append(f"    [{p['date'][4:]} {p['kind']}] {p['time']} idx{p['idx']:>2} 价{p['price']:.2f}{sl_s}")
        v = r["vpa"]
        out.append(f"  窗口净涨跌: {r['net']:+.2f} ({r['net_pct']:+.2f}%)  整体斜率/bar={r['overall_slope']:+.4f}")
        out.append(f"  量能: 总量={v['total']:.0f}  上量占比={v['up_vol_share']*100:.1f}%  下量占比={(1-v['up_vol_share'])*100:.1f}%")
        out.append(f"  T-0日: 涨跌={v['t0_chg']:+.2f}%  上量占比={v['t0_up_share']*100:.1f}%")
        out.append(f"  最大量K线: vol={v['max_vol']:.0f} 幅度={v['max_vol_range']:.2f} 收盘-开盘={v['max_vol_co']:+.2f}")
        out.append(f"  威科夫解读: {r['verdict']}")
    return "\n".join(out)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    t0 = sys.argv[1] if len(sys.argv) > 1 else None
    print(print_report(t0))
