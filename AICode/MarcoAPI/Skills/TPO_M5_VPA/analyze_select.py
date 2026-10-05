"""选股区分度分析：每天3只候选，用 实际T-1->T-0收益最高=赢家，
检验 各特征(TPO_M5形态 + VPA) 能否区分赢家。"""
import os, sys, statistics
from collections import defaultdict
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from AICode.MarcoAPI.Skills.M5_DATA import m5_data as M
from AICode.MarcoAPI.Skills.TPO_M5_VPA import run_all as R
from AICode.MarcoAPI.Skills.TPO_M5_VPA import select as S

CAT_RANK = {"BULL": 4, "UP_NOD": 3, "SIDE": 2, "DOWN_EXH": 1, "BEAR": 0, "NA": -1}


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ds = S.build_dataset()
    by_day = defaultdict(list)
    for r in ds:
        by_day[r["D"]].append(r)

    # 每天赢家 = 收益最高(剔除封板后候选里的实际最高？这里用全部候选比较，封板单独看)
    n_days = 0
    feat_acc = defaultdict(lambda: [0, 0])  # [命中, 总]
    # 特征函数：(day_rows, idx) -> 该候选特征值
    feats = {
        "VPA_verdict": lambda rows, i: CAT_RANK[rows[i]["cat"]],
        "VPA_net_pct": lambda rows, i: rows[i]["net_pct"],
        "VPA_up_share": lambda rows, i: rows[i]["up_share"],
        "TPO_d_llt(早低)": lambda rows, i: -rows[i]["feat"]["d_llt"],  # 越早越大
        "TPO_d_range(振幅)": lambda rows, i: rows[i]["feat"]["d_range"],
        "TPO_low_growth(升低)": lambda rows, i: rows[i]["feat"]["low_growth"],
        "TPO_high_growth(升势)": lambda rows, i: rows[i]["feat"]["high_growth"],
    }
    # VPA 综合分（与 select.COMPOSITE 一致）
    def vpa_score(rows, i):
        r = rows[i]; f = r["feat"]
        ear = max(0.0, (270 - f["d_llt"]) / 270.0)
        rng = min(1.0, f["d_range"] / 0.15)
        trd = max(0.0, (f["low_growth"] + f["high_growth"]) / 0.3)
        return CAT_RANK[r["cat"]] * 1.0 + ear + rng + trd
    feats["COMPOSITE分"] = vpa_score

    for D, rows in by_day.items():
        if len(rows) < 2:
            continue
        n_days += 1
        # 赢家：收益最高的候选（含封板也计入，看特征能否先验区分）
        winner = max(range(len(rows)), key=lambda i: rows[i]["ret"])
        for fname, f in feats.items():
            best = max(range(len(rows)), key=lambda i: f(rows, i))
            feat_acc[fname][0] += (best == winner)
            feat_acc[fname][1] += 1

    print("=" * 70)
    print(f"选股区分度：每天{n_days}天(≥2候选)，赢家=实际T-1->T-0收益最高者")
    print("  指标：'挑特征最大者' 命中赢家的准确率（>1/候选数才算有效）")
    print("=" * 70)
    print(f"  {'特征':<22}{'命中天数':>9}{'准确率%':>10}{'基准%(随机)':>14}")
    base = 100.0 / 3  # 3候选随机
    for fname in feats:
        hit, tot = feat_acc[fname]
        print(f"  {fname:<20}{hit:>9}{hit/tot*100:>9.1f}{base:>13.1f}")

    # 进一步：赢家 vs 输家 的平均特征值
    print("\n" + "=" * 70)
    print("赢家 vs 非赢家 平均特征值（正差=赢家更高）")
    print("=" * 70)
    win_vals, lose_vals = defaultdict(list), defaultdict(list)
    for D, rows in by_day.items():
        if len(rows) < 2:
            continue
        winner = max(range(len(rows)), key=lambda i: rows[i]["ret"])
        for fname, f in feats.items():
            for i in range(len(rows)):
                (win_vals if i == winner else lose_vals)[fname].append(f(rows, i))
    print(f"  {'特征':<22}{'赢家均值':>10}{'非赢家均值':>12}{'差':>8}")
    for fname in feats:
        w = statistics.mean(win_vals[fname]); l = statistics.mean(lose_vals[fname])
        print(f"  {fname:<20}{w:>10.3f}{l:>12.3f}{w-l:>8.3f}")


if __name__ == "__main__":
    main()
