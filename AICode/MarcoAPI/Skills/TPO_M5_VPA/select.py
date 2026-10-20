"""T-1 选股策略回测：用 TPO_M5 形态 + VPA，从每天 3 只候选里挑最优。

时间轴（已验证）：文件日 D = 涨停日=选股池日；买=T-1(D+1)收盘；卖=T-0(D+2)。
选股信号全部在 D（T-1 买入前）即可知：TPO_M5 形态 + decision_vpa。
"""
import os, sys, csv, statistics
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from AICode.MarcoAPI.Skills.M5_DATA import m5_data as M
from AICode.MarcoAPI.Skills.TPO_M5_VPA import run_all as R

TPO_DIR = os.path.join(ROOT, "AIData", "TARGET_5M", "TPO_M5")


def _min(tstr):
    h, m, _ = tstr.split(":")
    return (int(h) - 9) * 60 + (int(m) - 30)


def parse_tpo(D):
    """返回 [(code,name,feat)]；feat 含 D 日与 5 日趋势特征。"""
    p = os.path.join(TPO_DIR, D)
    if not os.path.exists(p):
        return []
    lines = [l.rstrip("\n") for l in open(p, encoding="utf-8", errors="ignore") if l.strip()]
    if len(lines) < 3:
        return []
    hdr = lines[0]
    wins = hdr.split("窗口=")[-1].split(",") if "窗口=" in hdr else []
    cols = lines[1].split("|")
    out = []
    for ln in lines[2:]:
        parts = ln.split("|")
        if len(parts) < 3:
            continue
        code, name = parts[0], parts[1]
        # 逐窗口日特征（真正读取 TPO_M5 形态字段）
        fhs, lls = [], []        # firstHighPrice, lastLowPrice
        lltimes, fhtimes = [], []  # lastLow / firstHigh 的分钟
        for k, d in enumerate(wins):
            base = 2 + k * 6
            if base + 5 >= len(parts):
                break
            try:
                fh = float(parts[base + 2])
                ll = float(parts[base + 5])
                fht = _min(parts[base + 1])
                llt = _min(parts[base + 4])
            except (ValueError, IndexError):
                continue
            fhs.append(fh); lls.append(ll)
            fhtimes.append(fht); lltimes.append(llt)
        if not fhs:
            continue
        d_fh, d_ll = fhs[-1], lls[-1]
        d_fht, d_llt = fhtimes[-1], lltimes[-1]
        d_range = (d_fh - d_ll) / d_ll if d_ll else 0.0
        low_growth = (lls[-1] / lls[0] - 1) if lls[0] else 0.0
        high_growth = (fhs[-1] / fhs[0] - 1) if fhs[0] else 0.0
        # TPO_M5 形态字段派生：
        # 1) 开盘缺口强度：D日 firstHigh 出现在最早(09:35=开盘即冲高=跳空)→ 缺口需求
        d_gap = max(0.0, (45 - d_fht) / 45.0)          # 09:35→1.0, 10:20→0
        # 2) 缺口一致性：窗口内多少天 firstHigh 在 09:40 前(开盘跳空)
        gap_days = sum(1 for t in fhtimes if t <= 50) / len(fhtimes)
        # 3) 控制形态 b/P：lastLow 晚于 firstHigh(先高后低=P供应) 取负，先低后高=b需求 取正
        shape_d = (d_llt - d_fht) / 270.0               # 正=需求日, 负=供应日
        # 4) 5日缺口驱动积累：末日相对首日的缺口强度提升
        gap_growth = d_gap - (max(0.0, (45 - fhtimes[0]) / 45.0))
        feat = {
            "d_llt": d_llt, "d_range": d_range,
            "low_growth": low_growth, "high_growth": high_growth,
            "d_gap": d_gap, "gap_days": gap_days,
            "shape_d": shape_d, "gap_growth": gap_growth,
            "d_fht": d_fht,
        }
        out.append((code, name, feat))
    return out


CAT_RANK = {"BULL": 4, "UP_NOD": 3, "SIDE": 2, "DOWN_EXH": 1, "BEAR": 0, "NA": -1}


def actual_return_5m_enh(code, t1, t0):
    """T-0 出场增强：在 run_all 原卖出逻辑(涨停/止损-5%/14:55)基础上，
    增加 T-0 盘中累计 VPA 早退——当日累计上涨量比<0.45(供应主导) 且 回撤≥-2% 时提前离场。"""
    data = R.load(code)
    t1dd = t1[:4] + "-" + t1[4:6] + "-" + t1[6:]
    pb = data.get(t1dd, [])
    if not pb:
        return None
    pre_close = pb[-1].close
    if pre_close <= 0:
        return None
    dd = t0[:4] + "-" + t0[4:6] + "-" + t0[6:]
    bars = data.get(dd, [])
    if not bars:
        return None
    limit_p = R._limit_price(pre_close, R._limit_ratio(code))
    n = min(len(bars), 47)
    cum_up = 0
    cum_tot = 0
    sell = sell_idx = None
    sell_time = reason = None
    for i in range(n):
        b = bars[i]
        cum_up += b.volume if b.close >= b.open else 0
        cum_tot += b.volume
        up_share = cum_up / cum_tot if cum_tot else 1.0
        dd_pct = (b.close - pre_close) / pre_close
        if b.high >= limit_p:
            sell, sell_idx, sell_time, reason = limit_p, i, b.time, "涨停"
            break
        if dd_pct < R.STOP_LOSS:
            sell, sell_idx, sell_time, reason = b.close, i, b.time, "止损"
            break
        # T-0 盘中 VPA 早退：供应主导 + 回撤≥-2%（需一定成交量，i>=12 即约10:30后）
        if i >= 12 and dd_pct <= -0.02 and up_share < 0.45:
            sell, sell_idx, sell_time, reason = b.close, i, b.time, "VPA早退"
            break
    if sell is None:
        last = bars[46] if len(bars) >= 47 else bars[-1]
        sell, sell_idx, sell_time, reason = last.close, (46 if len(bars) >= 47 else len(bars) - 1), last.time, "收盘"
    return {"ret": (sell - pre_close) / pre_close * 100, "buy": pre_close, "reason": reason}


def build_dataset():
    ds = []  # per (D, code): dict
    for D in M.list_target_dates():
        m = R.map_days(D)
        if m is None:
            continue
        t3, t2, t1, t0 = m
        cands = parse_tpo(D)
        for code, name, feat in cands:
            dv = R.decision_vpa(code, t2)
            ar = R.actual_return_5m(code, t1, t0)
            ar_e = actual_return_5m_enh(code, t1, t0)
            lim = R.buy_day_limit_up(code, t1)
            if ar is None or ar_e is None:
                continue
            cat = dv["cat"] if dv else "NA"
            ds.append({
                "D": D, "code": code, "name": name, "feat": feat,
                "cat": cat, "net_pct": dv["net_pct"] if dv else 0.0,
                "up_share": dv["up_share"] if dv else 0.0,
                "ret": ar_e["ret"], "ret_base": ar["ret"], "lim": bool(lim),
                "t1": t1, "t0": t0, "buy": ar_e["buy"], "reason": ar_e["reason"],
            })
    return ds


def apply_rule(day_rows, rule):
    """day_rows: 同一 D 的候选列表；返回 (chosen_ret, chosen_code, chosen_name) 或 None。"""
    elig = [r for r in day_rows if not r["lim"]]
    if not elig:
        return None
    if rule == "AVG":
        rs = [r["ret"] for r in day_rows if not r["lim"]]
        return (statistics.mean(rs), "AVG", "候选均值", None)
    if rule == "VPA":
        # 严格选最优：按 verdict 对所有候选排序取第1；若最优封板买不进，则当日空仓(不凑次优)
        allr = sorted(day_rows, key=lambda r: (CAT_RANK[r["cat"]], r["net_pct"], r["up_share"]), reverse=True)
        ch = allr[0]
        if ch["lim"]:
            return None
        return (ch["ret"], ch["code"], ch["name"], ch.get("reason"))
    if rule == "VPA_BASE":
        # 同 VPA 选股，但用原卖出逻辑(无 T-0 VPA 早退) 做对比
        allr = sorted(day_rows, key=lambda r: (CAT_RANK[r["cat"]], r["net_pct"], r["up_share"]), reverse=True)
        ch = allr[0]
        if ch["lim"]:
            return None
        return (ch["ret_base"], ch["code"], ch["name"], None)
    elif rule == "VPA_SUB":
        elig.sort(key=lambda r: (CAT_RANK[r["cat"]], r["net_pct"], r["up_share"]), reverse=True)
    elif rule == "TPO_EARLYLOW":
        elig.sort(key=lambda r: r["feat"]["d_llt"])  # 末次探低越早越强
    elif rule == "TPO_RANGE":
        elig.sort(key=lambda r: r["feat"]["d_range"], reverse=True)
    elif rule == "TPO_TREND":
        elig.sort(key=lambda r: (r["feat"]["low_growth"] + r["feat"]["high_growth"]), reverse=True)
    elif rule == "COMPOSITE":
        def score(r):
            f = r["feat"]
            ear = max(0.0, (270 - f["d_llt"]) / 270.0)
            rng = min(1.0, f["d_range"] / 0.15)
            trd = max(0.0, (f["low_growth"] + f["high_growth"]) / 0.3)
            return CAT_RANK[r["cat"]] * 1.0 + ear + rng + trd
        elig.sort(key=score, reverse=True)
    elif rule == "TPO_M5":
        def tpo_score(r):
            f = r["feat"]
            # 纯 TPO_M5 形态：开盘缺口强度 + 缺口一致性 + 控制形态(b/P) + 5日积累
            return (f["d_gap"] + f["gap_days"] + f["shape_d"]
                    + max(0.0, f["low_growth"]) + max(0.0, f["high_growth"]))
        elig.sort(key=tpo_score, reverse=True)
    elif rule == "TPO_M5_VPA":
        def tv_score(r):
            f = r["feat"]
            tpo = (f["d_gap"] + f["gap_days"] + f["shape_d"]
                   + max(0.0, f["low_growth"]) + max(0.0, f["high_growth"]))
            return tpo + CAT_RANK[r["cat"]] * 0.5
        elig.sort(key=tv_score, reverse=True)
    elif rule == "ORACLE":
        elig.sort(key=lambda r: r["ret"], reverse=True)  # 用未来收益(仅作上限参考)
    ch = elig[0]
    return (ch["ret"], ch["code"], ch["name"], None)


RULES = ["AVG", "VPA_BASE", "VPA", "VPA_SUB", "TPO_M5", "TPO_M5_VPA", "TPO_EARLYLOW", "TPO_RANGE", "TPO_TREND", "COMPOSITE", "ORACLE"]


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ds = build_dataset()
    by_day = defaultdict(list)
    for r in ds:
        by_day[r["D"]].append(r)

    rule_res = {ru: [] for ru in RULES}
    rule_picks = {ru: [] for ru in RULES}
    for D, rows in by_day.items():
        for ru in RULES:
            res = apply_rule(rows, ru)
            if res is None:
                continue
            ret, code, name, reason = res
            rule_res[ru].append(ret)
            if ru != "AVG" and ru != "ORACLE":
                rule_picks[ru].append((D, code, name, ret, rows[0]["t1"], rows[0]["t0"], reason))

    print("=" * 92)
    print("T-1 选股策略回测（买=D+1收盘 / 卖=D+2；全期）")
    print("=" * 92)
    print(f"  {'规则':<16}{'有选天数':>8}{'胜率%':>8}{'均收益%':>9}{'中位%':>8}{'累计%':>10}{'最佳%':>8}{'最差%':>8}")
    for ru in RULES:
        rs = rule_res[ru]
        if not rs:
            continue
        win = sum(1 for r in rs if r > 0)
        cum = sum(rs)
        tag = "  (上限参考)" if ru == "ORACLE" else ("  (基线)" if ru == "AVG" else
              ("  (官方·TPO_M5形态+VPA)" if ru == "TPO_M5_VPA" else ("  (纯TPO_M5形态)" if ru == "TPO_M5"
               else ("  (对比·纯VPA)" if ru == "VPA_BASE" else ("  (已测未采用)" if ru == "VPA"
               else ("  (替代·封板换次优)" if ru == "VPA_SUB" else ""))))))
        print(f"  {ru:<14}{len(rs):>8}{win/len(rs)*100:>7.1f}{statistics.mean(rs):>9.2f}"
              f"{statistics.median(rs):>8.2f}{cum:>10.2f}{max(rs):>8.2f}{min(rs):>8.2f}{tag}")

    # 官方策略：TPO_M5 形态 + VPA 选最优 + 原 T-0 出场(涨停/止损-5%/14:55)。
    best = "TPO_M5_VPA"
    print(f"\n=> 官方策略(TPO_M5形态+VPA选最优 + 原T-0出场): {best}")

    # T-0 出场增强效果：VPA_BASE(原卖出) vs VPA(增强)
    rb = rule_res.get("VPA_BASE", [])
    rv = rule_res.get("VPA", [])
    if rb and rv:
        print(f"   [已集成已测·未采用] T-0 VPA 早退增强: 原卖出累计={sum(rb):.2f}%  增强后={sum(rv):.2f}%  "
              f"(Δ={sum(rv)-sum(rb):+.2f}%)  —— 早退把尾盘可收回的小坑提前锁亏，净减收益")

    # 出场原因分布（官方原出场）
    rc = defaultdict(int)
    for p in rule_picks["VPA"]:
        rc[p[6] or "收盘"] += 1
    print("   [增强版]出场原因分布: " + "  ".join(f"{k}={v}" for k, v in sorted(rc.items(), key=lambda x: -x[1])))

    # 月度（按 D 涨停日所在月）
    print("\n" + "=" * 92)
    print(f"月度收益（规则={best}；单只单调，每天1笔，按涨停日D所在月）")
    print("=" * 92)
    msum = defaultdict(list)
    for D, rows in by_day.items():
        res = apply_rule(rows, best)
        if res is None:
            continue
        ret, code, name, _ = res
        msum[D[:6]].append(ret)
    print(f"  {'月份':<8}{'天数':>5}{'胜率%':>8}{'日均%':>9}{'累计%':>10}")
    allm = []
    for mon in sorted(msum):
        rs = msum[mon]
        win = sum(1 for r in rs if r > 0)
        allm += rs
        print(f"  {mon:<8}{len(rs):>5}{win/len(rs)*100:>7.1f}{statistics.mean(rs):>9.2f}{sum(rs):>10.2f}")
    print(f"  {'全期':<8}{len(allm):>5}{sum(1 for r in allm if r>0)/len(allm)*100:>7.1f}"
          f"{statistics.mean(allm):>9.2f}{sum(allm):>10.2f}")

    # 9月逐笔
    print("\n" + "=" * 92)
    print(f"202609 月 · 逐笔实际选股（规则={best}；买=T-1(D+1)收盘 / 卖=T-0(D+2)）")
    print("=" * 92)
    print(f"  {'D涨停':<10}{'买日T-1':<10}{'卖日T0':<10}{'代码':<11}{'名称':<10}{'收益%':>8}{'出场':>8}")
    sept = [p for p in rule_picks[best] if p[0][:6] == "202609"]
    sept.sort(key=lambda x: x[0])
    sret = []
    for D, code, name, ret, t1, t0, reason in sept:
        sret.append(ret)
        print(f"  {D:<10}{t1:<10}{t0:<10}{code:<11}{name:<10}{ret:>8.2f}{(reason or '—'):>8}")
    if sret:
        win = sum(1 for r in sret if r > 0)
        print(f"  {'':<10}{'':<10}{'':<10}{'':<11}{'合计':<10}{sum(sret):>8.2f}  (胜{win}/{len(sret)})")


if __name__ == "__main__":
    main()
