#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""下一交易日 TPO_M5 名单生成器（供新 UI「实时看盘」读取）。

用途：每日盘后（T-1 = 今日，数据已更新）计算 T-0 = 下一交易日 的 TPO_M5 名单，
即「今晚尾盘买入、下个交易日卖出」的股票，写入 AIData/NEXT_DAY/strategy.json。

选股条件与 SZ200Strategy 的 TPO_M5 完全一致（T-0 视角）：
  T-3：涨停 is_top=1 且首板 lian_ban=1 且放量 is_volume_up=1
  T-2：上涨 is_up=1 且放量 is_volume_up=1 且未涨停 is_top=0
  T-1：涨跌幅 ratio<=3.0 且缩量 is_volume_down=1 且 close>ma5
  流通市值 = T-2 收盘价 × 流通股本，须在 [200 亿, 1300 亿]
  MA5 预测：T-1 close >= (T-1×2 + T-2 + T-3 + T-4)/5（不满足的顺延，全部不满足则空仓）
  按流通市值倒序，首个满足 MA5 预测者 = 首选（实际只买首选）

数据源（只读，不写 AIData 其它目录）：
  AIData/TRADING_DATES        交易日历（YYYYMMDD/行）
  AIData/1D/<code>            加工日线 25 列，列 4=close,8=is_top,10=ratio,11=is_up,
                              15=is_volume_up,16=is_volume_down,17=ma5,23=lian_ban
  AIData/STOCK_CODES_ALL      代码|名称|流通股本
  AIData/INDEX_5M/<code>      指数/宽基 5m（按日收盘聚合算成长端 7 宽基日线 MA60）
  口径与 tools/realtime_feed.py 的 _refresh_env 一致（≥4 在 MA60 上 → 好）。

输出：AIData/NEXT_DAY/strategy.json（UTF-8，原子写），字段：
  generatedAt / buyDate(T-1) / forTradeDate(T-0) / strategy / env / firstPick / buyList / candidates

用法：
  python tools/next_day_strategy.py                    # 默认 T-1=今天
  python tools/next_day_strategy.py --buy-date 20261103
  python tools/next_day_strategy.py --dry-run          # 只打印计划
  python tools/next_day_strategy.py --verbose          # 打印诊断

退出码：0 成功；2 交易日历/历史数据不足；3 数据读取/写入失败。
"""

from __future__ import annotations

import argparse
import bisect
import datetime as dt
import json
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AIDATA = os.path.join(ROOT, "AIData")
DIR_1D = os.path.join(AIDATA, "1D")
DIR_INDEX_5M = os.path.join(AIDATA, "INDEX_5M")
OUT_DIR = os.path.join(AIDATA, "NEXT_DAY")
OUT_FILE = os.path.join(OUT_DIR, "strategy.json")

TDX_PLUGIN = os.environ.get("TDX_PLUGIN_PATH", r"C:\new_tdx64\PYPlugins\user")

STRATEGY = "TPO_M5"
MAX_RATIO = 3.0
MARKET_MIN = 2e10          # 200 亿
MARKET_MAX = 1.3e11        # 1300 亿

# 成长端 7 宽基（与 tools/realtime_feed.py 的 GROWTH_INDEXES 保持一致）
GROWTH_INDEXES = [
    ("399673.SZ", "创业板50"),
    ("399006.SZ", "创业板指"),
    ("000688.SH", "科创50"),
    ("399001.SZ", "深证成指"),
    ("000300.SH", "沪深300"),
    ("000852.SH", "中证1000"),
    ("000905.SH", "中证500"),
]

# 1D 加工日线列号（见 SZ2001D._PARSE_DATA_1D）
_C_CLOSE, _C_IS_TOP, _C_RATIO = 4, 8, 10
_C_IS_UP, _C_VOL_UP, _C_VOL_DOWN = 11, 15, 16
_C_MA5, _C_LIAN_BAN = 17, 23

_log_enabled = True


def log(text: str) -> None:
    if _log_enabled:
        print(text, flush=True)


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
        return fh.read()


def _to_int(value: str) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def load_trading_dates() -> list[str]:
    path = os.path.join(AIDATA, "TRADING_DATES")
    dates = [line.strip() for line in _read_text(path).splitlines() if line.strip()]
    dates = sorted(d for d in dates if len(d) == 8 and d.isdigit())
    if not dates:
        raise RuntimeError("AIData/TRADING_DATES 为空")
    return dates


def build_window(buy_date: str, dates: list[str]) -> tuple[list[str], int]:
    """返回 (交易日列表含 buy_date, buy_date 下标)；T-4 不足时抛错。

    本地交易日历可能尚未含今日（日历只到上一交易日），此时把 buy_date 按序插入；
    buy_date 已由 daily_update 的交易日校验确认是交易日。
    """
    if buy_date not in dates:
        bisect.insort(dates, buy_date)
    pos = dates.index(buy_date)
    if pos < 3:
        raise RuntimeError(f"{buy_date} 之前不足 3 个交易日，无法计算 T-2/T-3/T-4")
    return dates, pos


def next_trading_day(buy_date: str, dates: list[str]) -> tuple[str, bool]:
    """buy_date 的下一交易日；返回 (YYYYMMDD, approx)。

    优先本地日历；否则现场问通达信 tq.get_trading_dates；再不行用「下一工作日」兜底并标 approx。
    """
    future = [d for d in dates if d > buy_date]
    if future:
        return future[0], False

    api = _next_trading_day_via_tq(buy_date)
    if api:
        return api, False

    day = dt.datetime.strptime(buy_date, "%Y%m%d").date() + dt.timedelta(days=1)
    while day.weekday() >= 5:
        day += dt.timedelta(days=1)
    return day.strftime("%Y%m%d"), True


def _next_trading_day_via_tq(buy_date: str) -> str | None:
    """向常驻通达信询问 buy_date 之后的交易日；失败返回 None（不抛异常）。"""
    try:
        if TDX_PLUGIN not in sys.path:
            sys.path.append(TDX_PLUGIN)
        from tqcenter import tq

        end = (dt.datetime.strptime(buy_date, "%Y%m%d") + dt.timedelta(days=45)).strftime("%Y%m%d")
        tq.initialize(os.path.abspath(__file__))
        try:
            res = tq.get_trading_dates(market="SH", start_time=buy_date, end_time=end, count=-1)
        finally:
            try:
                tq.close()
            except Exception:
                pass
        values = res.values() if isinstance(res, dict) else res
        normalized = []
        for item in values or []:
            text = str(item).replace("-", "").replace("/", "").strip()
            if len(text) >= 8 and text[:8].isdigit():
                normalized.append(text[:8])
        future = sorted({d for d in normalized if d > buy_date})
        if future:
            return future[0]
    except Exception as exc:  # 通达信不可用/日历接口异常 → 交给兜底
        log(f"[warn] 通达信日历不可用，下一交易日回退工作日推算：{type(exc).__name__}: {exc}")
    return None


def load_stock_codes() -> list[tuple[str, str, int]]:
    """返回 [(代码, 名称, 流通股本)]，与 SZ200Strategy 用 GET_STOCK_INFO 的口径一致。"""
    path = os.path.join(AIDATA, "STOCK_CODES_ALL")
    rows: list[tuple[str, str, int]] = []
    for line in _read_text(path).splitlines():
        if not line:
            continue
        parts = line.split("|")
        if len(parts) < 3:
            continue
        code = parts[0].strip()
        name = parts[1].strip() if len(parts) > 1 else ""
        try:
            float_share = int(float(parts[2]))
        except (TypeError, ValueError):
            float_share = 0
        rows.append((code, name, float_share))
    return rows


def load_days(code: str, targets: set[str]) -> dict[str, list[str]]:
    """读 AIData/1D/<code>，只保留 targets 里的交易日行；文件缺失返回空 dict。"""
    path = os.path.join(DIR_1D, code)
    if not os.path.exists(path):
        return {}
    out: dict[str, list[str]] = {}
    with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
        for line in fh:
            if not line:
                continue
            day = line[:8]
            if day not in targets:
                continue
            parts = line.strip().split("|")
            if len(parts) <= _C_LIAN_BAN:
                continue
            out[day] = parts
    return out


def _market_value(parts: list[str], float_share: int) -> float:
    return float_share * float(parts[_C_CLOSE])


def _daily_index_closes(code: str) -> list[tuple[str, float]]:
    """指数日线：vipdoc lday *.day 原始日线；缺失回退 INDEX_5M 聚合日线。"""
    mkt = "sh" if code.upper().endswith(".SH") else "sz"
    base = os.path.join(os.environ.get("TDX_VIPDOC", r"C:/new_tdx64/vipdoc"), mkt, "lday", mkt + code[:6])
    for ext in (".day", ".lday"):
        fp = base + ext
        if not os.path.isfile(fp):
            continue
        try:
            raw = open(fp, "rb").read()
        except OSError:
            continue
        out = {}
        for i in range(len(raw) // 32):
            try:
                date, _op, _hi, _lo, cl, _amt, _vol, _r = struct.unpack("<IIIIIfII", raw[i * 32:(i + 1) * 32])
            except struct.error:
                continue
            y, rem = date // 10000, date % 10000
            mo, da = rem // 100, rem % 100
            if 1990 <= y <= 2100 and 1 <= mo <= 12 and 1 <= da <= 31 and cl > 0:
                out[f"{y}{mo:02d}{da:02d}"] = cl / 100.0
        if out:
            return [(d, out[d]) for d in sorted(out)]
    # 回退 INDEX_5M 聚合
    path = os.path.join(DIR_INDEX_5M, code)
    daily: dict[str, float] = {}
    try:
        for line in _read_text(path).splitlines():
            parts = line.split("|")
            if len(parts) < 5:
                continue
            day = parts[0][:10].replace("-", "")
            try:
                daily[day] = float(parts[4])
            except ValueError:
                continue
    except OSError:
        return []
    return [(d, daily[d]) for d in sorted(daily)]


def compute_env(buy_date: str) -> dict:
    """新 B+ 环境（3 指数）：沪深300 上、创业板指 上、中证银行 下 → 好。"""
    env_indexes = [("000300.SH", "沪深300"), ("399006.SZ", "创业板指"), ("399986.SZ", "中证银行")]
    details = []
    flags = {}
    env_date = None
    valid = True
    for code, name in env_indexes:
        closes = [(d, c) for d, c in _daily_index_closes(code) if d <= buy_date]
        if not closes:
            details.append({"code": code, "name": name, "ok": False})
            valid = False
            continue
        if len(closes) < 61:
            details.append({"code": code, "name": name, "ok": False})
            valid = False
            continue
        ma60 = sum(c for _d, c in closes[-61:-1]) / 60.0
        day, last = closes[-1]
        env_date = env_date or day
        above = last > ma60
        flags[code] = above
        details.append({"code": code, "name": name, "ok": True, "date": day,
                        "close": round(last, 2), "ma60": round(ma60, 2), "above": bool(above)})
    if valid and len(flags) == 3:
        score = int(bool(flags.get("000300.SH"))) + int(bool(flags.get("399006.SZ"))) + int(not bool(flags.get("399986.SZ")))
        sell_rule = "持有到14:55" if score >= 2 else ("10:00看300+创指宽度" if score == 1 else "10:00卖出")
        return {"t1": "好" if score >= 2 else "差", "score": score, "state": f"S{score}",
                "sellRule": sell_rule, "above": sum(1 for x in details if x.get("above")),
                "total": 3, "date": env_date, "mode": "s6",
                "rule": "S6：沪深300上+1、创业板指上+1、中证银行≤MA60+1", "details": details}
    return {"t1": None, "score": None, "state": "不可用", "sellRule": "回退满仓·持有到14:55",
            "above": None, "total": 3, "date": env_date, "mode": "s6",
            "rule": "S6 三指数数据不足 → 环境不可用", "details": details}


def generate(buy_date: str) -> dict:
    dates = load_trading_dates()
    dates, pos = build_window(buy_date, dates)
    t1 = buy_date
    t2 = dates[pos - 1]              # T-2 = 买入日前一交易日
    t3 = dates[pos - 2]              # T-3 = 买入日前两交易日
    t4 = dates[pos - 3]              # T-4 = 买入日前三交易日
    targets = {t1, t2, t3, t4}
    for_trade_date, approx = next_trading_day(buy_date, dates)
    log(f"[1/4] T-1={t1} T-2={t2} T-3={t3} T-4={t4} → T-0={for_trade_date}"
        + ("（下一工作日近似）" if approx else ""))

    stocks = load_stock_codes()
    log(f"[2/4] 股票池 {len(stocks)} 只，读取 1D ...")
    picks_all: list[dict] = []          # 满足 TPO 全部形态+市值条件
    picks_pred: list[dict] = []         # 其中同时满足 MA5 预测
    candidates: list[dict] = []        # 后日 T-0 预选（T-3→T-2 窗口，depth=2）
    for code, name, float_share in stocks:
        if float_share <= 0:
            continue
        recs = load_days(code, targets)
        r1, r2, r3, r4 = recs.get(t1), recs.get(t2), recs.get(t3), recs.get(t4)
        if r1 is None or r2 is None or r3 is None or r4 is None:
            continue
        # T-3：首板放量涨停
        if _to_int(r3[_C_IS_TOP]) != 1 or _to_int(r3[_C_LIAN_BAN]) != 1 or _to_int(r3[_C_VOL_UP]) != 1:
            continue
        # T-2：放量上涨未涨停
        if _to_int(r2[_C_IS_UP]) != 1 or _to_int(r2[_C_VOL_UP]) != 1 or _to_int(r2[_C_IS_TOP]) != 0:
            continue
        # T-1：涨跌幅 <= 3%、缩量、收盘站上 MA5
        if float(r1[_C_RATIO]) > MAX_RATIO:
            continue
        if _to_int(r1[_C_VOL_DOWN]) != 1:
            continue
        close1 = float(r1[_C_CLOSE])
        if close1 <= float(r1[_C_MA5]):
            continue
        # 流通市值（T-2 收盘 × 流通股本）∈ [200 亿, 1300 亿]
        market_value = _market_value(r2, float_share)
        if market_value < MARKET_MIN or market_value > MARKET_MAX:
            continue
        # MA5 预测（T-0 卖出日）：(T-1×2 + T-2 + T-3 + T-4)/5
        pred_ma5 = (close1 * 2.0 + float(r2[_C_CLOSE]) + float(r3[_C_CLOSE]) + float(r4[_C_CLOSE])) / 5.0
        ma5_pred = close1 >= pred_ma5
        item = {
            "code": code,
            "name": name,
            "buyPrice": close1,
            "marketValue": round(market_value, 2),
            "ma5Pred": ma5_pred,
        }
        picks_all.append(item)
        if ma5_pred:
            picks_pred.append(dict(item))

        # 「后日 T-0 预选」：T-2 首板放量涨停、T-1 放量上涨未涨停，市值用 T-1 收盘（同 GET_STRATEGY_TPO_WINDOW depth=2）
        if _to_int(r2[_C_IS_TOP]) == 1 and _to_int(r2[_C_LIAN_BAN]) == 1 and _to_int(r2[_C_VOL_UP]) == 1 \
                and _to_int(r1[_C_IS_UP]) == 1 and _to_int(r1[_C_VOL_UP]) == 1 and _to_int(r1[_C_IS_TOP]) == 0:
            mv_today = _market_value(r1, float_share)
            if MARKET_MIN <= mv_today <= MARKET_MAX:
                candidates.append({"code": code, "name": name, "source": "T-1预选", "_mv": mv_today})

    picks_all.sort(key=lambda x: x["marketValue"], reverse=True)
    picks_pred.sort(key=lambda x: x["marketValue"], reverse=True)
    candidates.sort(key=lambda x: x["_mv"], reverse=True)
    candidates = [{"code": c["code"], "name": c["name"], "source": c["source"]} for c in candidates]
    log(f"[3/4] TPO 形态+市值候选 {len(picks_all)} 只，其中 MA5 预测通过 {len(picks_pred)} 只")

    chosen = picks_pred[0] if picks_pred else None
    if chosen is not None:
        first_pick = {k: chosen[k] for k in ("code", "name", "buyPrice", "marketValue")}
        # 与 SZ200Strategy 一致：满足 MA5 预测的首选置顶（回测取首行），其余仍按市值倒序
        if picks_all and picks_all[0]["code"] != chosen["code"]:
            picks_all = [chosen] + [x for x in picks_all if x["code"] != chosen["code"]]
    else:
        first_pick = None

    result = {
        "generatedAt": dt.datetime.now().isoformat(timespec="seconds"),
        "buyDate": t1,
        "forTradeDate": for_trade_date,
        "approx": approx,
        "strategy": STRATEGY,
        "env": compute_env(t1),
        "firstPick": first_pick,
        "buyList": picks_all,
        "candidates": candidates,
    }
    log(f"[4/4] 首选={first_pick['code'] + ' ' + first_pick['name'] if first_pick else '空仓'}，"
        f"buyList={len(picks_all)} 只，candidates={len(candidates)} 只")
    return result


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="下一交易日 TPO_M5 名单生成器")
    parser.add_argument("--buy-date", default=dt.date.today().strftime("%Y%m%d"),
                        help="T-1 买入日（默认今天，数据须已更新）")
    parser.add_argument("--out", default=OUT_FILE, help="输出 json 路径")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不写文件")
    parser.add_argument("--verbose", action="store_true", help="打印诊断日志")
    args = parser.parse_args(argv)

    global _log_enabled
    _log_enabled = args.verbose or args.dry_run

    buy_date = args.buy_date.replace("-", "").strip()
    if len(buy_date) != 8 or not buy_date.isdigit():
        print(f"[错误] --buy-date 需为 YYYYMMDD：{args.buy_date}")
        return 2

    try:
        if args.dry_run:
            dates = load_trading_dates()
            dates, _pos = build_window(buy_date, dates)
            nxt, approx = next_trading_day(buy_date, dates)
            print(f"[dry-run] T-1={buy_date}，将生成 forTradeDate={nxt}"
                  + ("（下一工作日近似）" if approx else "") + f" 的 {STRATEGY} 名单 → {args.out}")
            try:
                env = compute_env(buy_date)
                print(f"[dry-run] 环境：{env['t1']}（above={env['above']}/{env['total']}，日期 {env['date']}）")
            except Exception as exc:
                print(f"[dry-run] 环境计算跳过：{type(exc).__name__}: {exc}")
            return 0

        result = generate(buy_date)
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        tmp = args.out + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, args.out)
        summary = {
            "ok": True,
            "buyDate": result["buyDate"],
            "forTradeDate": result["forTradeDate"],
            "approx": result["approx"],
            "firstPick": result["firstPick"],
            "buyListCount": len(result["buyList"]),
            "candidatesCount": len(result["candidates"]),
            "env": result["env"],
            "out": os.path.abspath(args.out),
        }
        print("NEXT_DAY_JSON " + json.dumps(summary, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(f"[失败] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
