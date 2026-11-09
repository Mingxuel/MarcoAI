"""选股训练数据引擎（tools/training_engine.py）。

按月列出 TPO_M5 首选股（STRATEGY 第一行），用 vipdoc lc5 原始价计算 B+ 原策略卖出价；
训练计算按用户止盈/止损价在 T-0 5m 上模拟（同 bar 双触发按止损；未触发回 B+ 原规则）。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bplus_engine as be  # noqa: E402


def _round(v, n=3):
    return None if v is None else round(float(v), n)


def months(root, strategy="TPO_M5"):
    daily = be._load_strategy(root, strategy)
    ms = sorted({d[:6] for d in daily})
    return {"ok": True, "months": ms, "latest": ms[-1] if ms else None}


def _original_sell(root, strategy, date, code, buy, idx):
    bars = (be._lc5_days(code) or {}).get(date)
    if not buy or not bars:
        return None, "无T-0 5m数据"
    env = idx["env"].get(date)
    width = idx["width10"].get(date)
    bplus_ok = env is not None and width is not None
    if bplus_ok:
        sp, reason = be._bplus_sell(bars, buy, env >= 4, width, code)
        return sp, reason
    sp = be._fallback_sell(buy, bars)
    return sp, "fallback旧卖法"


def list_month(root, strategy="TPO_M5", month=""):
    month = str(month or "").strip()
    daily = be._load_strategy(root, strategy)
    idx = be._load_index_data(root)
    groups = []
    flat = []
    all_dates = sorted(daily)
    # T-1 用交易日历计算（STRATEGY 可能有空文件，如 09-30/10-08）
    trade_dates = []
    try:
        tpath = os.path.join(root, "AIData", "TRADING_DATES")
        for line in open(tpath, "rb").read().decode("utf-8", "ignore").splitlines():
            d = line.strip()[:8]
            if len(d) == 8 and d.isdigit():
                trade_dates.append(d)
        trade_dates = sorted(set(trade_dates))
    except OSError:
        trade_dates = []
    prev_map = {d: (all_dates[i - 1] if i > 0 else None) for i, d in enumerate(all_dates)}
    if trade_dates:
        tprev = {d: (trade_dates[i - 1] if i > 0 else None) for i, d in enumerate(trade_dates)}
        for date in all_dates:
            if tprev.get(date):
                prev_map[date] = tprev[date]
    for date in all_dates:
        if month and not date.startswith(month):
            continue
        cands = []
        for row in daily[date]:
            if not row or not row[0]:
                continue
            code = row[0]
            name = row[1] if len(row) > 1 else ""
            buy = be._raw_buy_price(code, date)
            sp, reason = _original_sell(root, strategy, date, code, buy, idx)
            pnl = (sp / buy - 1) * 100 if (sp and buy) else None
            it = {
                "date": date,
                "dateLabel": f"{date[:4]}-{date[4:6]}-{date[6:8]}",
                "t1": prev_map.get(date),
                "t1Label": (f"{prev_map[date][:4]}-{prev_map[date][4:6]}-{prev_map[date][6:8]}" if prev_map.get(date) else None),
                "code": code, "name": name,
                "buy": _round(buy, 3),
                "originalSell": _round(sp, 3),
                "originalPnlPct": _round(pnl, 2),
                "originalReason": reason,
                "env": ("好" if (idx["env"].get(date) or 0) >= 4 else ("差" if idx["env"].get(date) is not None else None)),
                "width10": idx["width10"].get(date),
            }
            cands.append(it)
            flat.append(it)
        if cands:
            groups.append({"date": date, "dateLabel": f"{date[:4]}-{date[4:6]}-{date[6:8]}",
                           "t1": prev_map.get(date), "count": len(cands), "candidates": cands})
    return {"ok": True, "month": month or (groups[0]["date"][:6] if groups else None),
            "strategy": strategy, "groups": groups, "items": flat}


def compound_daily_returns(rows, field="trainPnlPct"):
    """按日期先等权平均，再逐日复利；+10%/-10% 两天应为 -1%。"""
    by_date = {}
    for r in rows or []:
        if r.get(field) is None:
            continue
        by_date.setdefault(r.get("date"), []).append(r[field])
    acc = 1.0
    used = False
    for date in sorted(by_date):
        vals = by_date[date]
        if not vals:
            continue
        acc *= (1 + (sum(vals) / len(vals)) / 100.0)
        used = True
    return (acc - 1) * 100 if used else None


def calc(root, items, strategy="TPO_M5"):
    idx = be._load_index_data(root)
    rows = []
    for it in items or []:
        code = str(it.get("code") or "").upper()
        date = str(it.get("date") or "").replace("-", "")[:8]
        buy = be._raw_buy_price(code, date)
        bars = (be._lc5_days(code) or {}).get(date)
        tp = be._f(it.get("tp"))
        sl = be._f(it.get("sl"))
        sell = None
        reason = ""
        if not buy or not bars:
            reason = "无买入价/T-0 5m"
        else:
            for minute, _o, hi, lo, cl in bars:
                if minute > 14 * 60 + 55:
                    break
                hit_tp = bool(tp and hi >= tp)
                hit_sl = bool(sl and lo <= sl)
                if hit_tp and hit_sl:
                    sell, reason = sl, "同一根5m同时触发→止损"
                    break
                if hit_tp:
                    sell, reason = tp, "先触发止盈→卖止盈价"
                    break
                if hit_sl:
                    sell, reason = sl, "先触发止损→卖止损价"
                    break
            if sell is None:
                env = idx["env"].get(date)
                width = idx["width10"].get(date)
                if env is not None and width is not None:
                    sell, reason = be._bplus_sell(bars, buy, env >= 4, width, code)
                else:
                    sell, reason = be._fallback_sell(buy, bars), "未触发→旧卖法"
                reason = "未触发 → " + str(reason)
        train_pnl = (sell / buy - 1) * 100 if (sell and buy) else None
        # 原 B+ 结果
        orig_sp, orig_reason = _original_sell(root, strategy, date, code, buy, idx)
        orig_pnl = (orig_sp / buy - 1) * 100 if (orig_sp and buy) else None
        rows.append({
            "date": date, "code": code, "name": it.get("name") or "",
            "buy": _round(buy, 3), "tp": _round(tp, 3), "sl": _round(sl, 3),
            "trainSell": _round(sell, 3), "trainPnlPct": _round(train_pnl, 2),
            "trainReason": reason,
            "originalSell": _round(orig_sp, 3), "originalPnlPct": _round(orig_pnl, 2),
            "originalReason": orig_reason,
        })
    train_vals = [r["trainPnlPct"] for r in rows if r["trainPnlPct"] is not None]
    orig_vals = [r["originalPnlPct"] for r in rows if r["originalPnlPct"] is not None]
    train_avg = sum(train_vals) / len(train_vals) if train_vals else None
    orig_avg = sum(orig_vals) / len(orig_vals) if orig_vals else None
    tw = sum(1 for v in train_vals if v > 0)
    ow = sum(1 for v in orig_vals if v > 0)
    daily = []
    by_date = {}
    for r in rows:
        by_date.setdefault(r["date"], []).append(r)
    for date in sorted(by_date):
        rs = by_date[date]
        tv = [x["trainPnlPct"] for x in rs if x["trainPnlPct"] is not None]
        ov = [x["originalPnlPct"] for x in rs if x["originalPnlPct"] is not None]
        ta = sum(tv) / len(tv) if tv else None
        oa = sum(ov) / len(ov) if ov else None
        daily.append({
            "date": date, "dateLabel": f"{date[:4]}-{date[4:6]}-{date[6:8]}",
            "count": len(rs),
            "trainPnlPct": _round(ta, 2), "originalPnlPct": _round(oa, 2),
            "diffPct": _round((ta - oa) if (ta is not None and oa is not None) else None, 2),
        })
    train_comp = compound_daily_returns(rows, "trainPnlPct")
    orig_comp = compound_daily_returns(rows, "originalPnlPct")
    return {
        "ok": True, "rows": rows, "daily": daily,
        "summary": {
            "count": len(rows),
            "trainTotalPnlPct": _round(train_comp, 2),
            "originalTotalPnlPct": _round(orig_comp, 2),
            "diffPct": _round((train_comp - orig_comp) if (train_comp is not None and orig_comp is not None) else None, 2),
            "trainAvgPnlPct": _round(train_avg, 2),
            "originalAvgPnlPct": _round(orig_avg, 2),
            "trainWinRate": _round(tw / len(train_vals) * 100, 1) if train_vals else None,
            "originalWinRate": _round(ow / len(orig_vals) * 100, 1) if orig_vals else None,
            "compoundMode": True,
        },
    }
