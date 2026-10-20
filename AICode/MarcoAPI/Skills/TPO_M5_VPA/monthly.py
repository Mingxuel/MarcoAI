"""单只单调口径（每天满仓1只）· 按正确时间轴：
    文件 D=T-3(涨停日), T-2=D+1(选股池), T-1=D+2(买入), T-0=D+3(卖出)
每天 TARGET/TPO_M5/{D} 给 3 只候选，实盘取 1 只。数据/代码无"3选1"规则，
故主数取"排除买入日封板后当日候选均值"为单只期望收益，并给当日最优/最差边界。
买入=T-1(D+2)收盘；卖出=T-0(D+3)当日5M；收益=(卖-买)/买（毛收益未扣费）。
"""
import os
import sys
import statistics
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from AICode.MarcoAPI.Skills.TPO_M5_VPA import run_all as R
from AICode.MarcoAPI.Skills.M5_DATA import m5_data as M


def build():
    rows = []
    for D in M.list_target_dates():
        m = R.map_days(D)
        if m is None:
            continue
        t3, t2, t1, t0 = m
        for code, name, mv in M.target_stocks(D):
            ar = R.actual_return_5m(code, t1, t0)
            if ar is None:
                continue
            lim = R.buy_day_limit_up(code, t1)
            rows.append({
                "D": D, "t2": t2, "t1_buy": t1, "t0_sell": t0,
                "code": code, "name": name, "mv": mv,
                "buy": ar["buy"], "sell_time": ar["sell_time"],
                "sell": ar["sell"], "reason": ar["reason"],
                "ret": ar["ret"], "limit": bool(lim),
            })
    return rows


def daily_groups(rows):
    g = defaultdict(list)
    for r in rows:
        g[r["D"]].append(r)
    return g


def day_stats(rs):
    exe = [r for r in rs if not r["limit"]]
    if not exe:
        return None
    rets = [r["ret"] for r in exe]
    return {"exp": statistics.mean(rets), "best": max(rets), "worst": min(rets),
            "n": len(exe), "win": sum(1 for x in rets if x > 0)}


def monthly_single(rows):
    g = daily_groups(rows)
    # 按月：以 T-3 涨停日 D 所在月
    by_month = defaultdict(list)
    for D, rs in g.items():
        ds = day_stats(rs)
        if ds is not None:
            by_month[D[:6]].append((D, ds))
    print("=" * 86)
    print("单只单调 · 按月收益（D=T-3涨停日所在月；每天1笔；主数=排除封板后候选均值）")
    print("=" * 86)
    print(f"{'月份':<8}{'交易日':>6}{'胜率%':>8}{'期望均%':>9}{'累计期望%':>11}{'累计最优%':>11}{'累计最差%':>11}")
    for mm in sorted(by_month):
        days = by_month[mm]
        exp_sum = sum(d[1]["exp"] for d in days)
        best_sum = sum(d[1]["best"] for d in days)
        worst_sum = sum(d[1]["worst"] for d in days)
        win = sum(d[1]["win"] for d in days)
        nt = sum(d[1]["n"] for d in days)
        print(f"{mm:<8}{len(days):>6}{win/nt*100:>7.1f}{statistics.mean(d[1]['exp'] for d in days):>9.2f}"
              f"{exp_sum:>11.2f}{best_sum:>11.2f}{worst_sum:>11.2f}")
    alld = [(D, ds) for mm in by_month.values() for (D, ds) in mm]
    exp_sum = sum(d["exp"] for _, d in alld)
    best_sum = sum(d["best"] for _, d in alld)
    worst_sum = sum(d["worst"] for _, d in alld)
    win = sum(d["win"] for _, d in alld)
    nt = sum(d["n"] for _, d in alld)
    print("-" * 86)
    print(f"{'全期':<8}{len(alld):>6}{win/nt*100:>7.1f}{statistics.mean(d['exp'] for _,d in alld):>9.2f}"
          f"{exp_sum:>11.2f}{best_sum:>11.2f}{worst_sum:>11.2f}")


def month_detail_single(rows, month="202609"):
    g = daily_groups(rows)
    days = sorted((D, rs) for D, rs in g.items() if D[:6] == month)
    print()
    print("=" * 124)
    print(f"{month} 月 · 单只单调逐日（D=涨停日=选股池日；买=T-1(D+1)收盘 / 卖=T-0(D+2)；封板=买不进）")
    print("=" * 124)
    print(f"{'D(T-3)':<10}{'买日T-1':<10}{'卖日T-0':<10}{'代码':<10}{'名称':<9}{'买价':>9}{'卖时':>8}{'卖价':>9}{'卖因':>5}{'收益%':>8}{'封板':>5}")
    exp_sum = 0.0
    ndays = 0
    for D, rs in days:
        t1 = rs[0]["t1_buy"]
        t0 = rs[0]["t0_sell"]
        ds = day_stats(rs)
        for r in rs:
            flag = "封板" if r["limit"] else ""
            print(f"{D:<10}{t1:<10}{t0:<10}{r['code']:<10}{r['name'][:7]:<9}{r['buy']:>9.2f}"
                  f"{str(r['sell_time']):>8}{r['sell']:>9.2f}{r['reason']:>5}{r['ret']:>8.2f}{flag:>5}")
        if ds:
            exp_sum += ds["exp"]
            ndays += 1
            print(f"  >> 当日单只(期望)= {ds['exp']:>6.2f}%  [最优 {ds['best']:.2f}% / 最差 {ds['worst']:.2f}%]  可执行 {ds['n']} 只, 胜 {ds['win']}")
        else:
            print(f"  >> 当日候选全封板，无交易")
        print()
    print("-" * 124)
    print(f"{month} 单只单调：{ndays} 个有交易日，累计期望收益 {exp_sum:.2f}%")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    rows = build()
    monthly_single(rows)
    month_detail_single(rows, "202609")
