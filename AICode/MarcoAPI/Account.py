import os
import sys

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, os.path.dirname(_root))

import openpyxl
from AICode.MarcoAPI.Update.Path import PATH_THS_HISTORY_XLSX, PATH_THS_HISTORY
from AICode.MarcoAPI.Update.TradingDates import TRADING_DATES

# ── 交割单字段索引 ──
COL_DATE = 0
COL_CODE = 1
COL_NAME = 2
COL_ACTION = 3
COL_VOLUME = 4
COL_AVG_PRICE = 6
COL_AMOUNT = 7
COL_CASH_FLOW = 9
COL_COMMISSION = 10
COL_STAMP_TAX = 11
COL_OTHER_FEE = 12
COL_POST_BALANCE = 13


# ──────────────────────────────────────────────
# 同花顺交割单 → 每日账户数据
# 重新计算交割单：
#   当日实现盈亏 = 该日每笔卖出-每笔买入的实际差价（按笔配对计算）
#   账户金额 = 后资金额（账户剩余现金，代表账户的"现金账户"维度）
# 更精确的算法需要持仓市值（交割单中拿不到）
# ──────────────────────────────────────────────


def parse_ths_history(xlsx_path=None) -> list[dict]:
    if xlsx_path is None:
        xlsx_path = PATH_THS_HISTORY_XLSX()

    wb = openpyxl.load_workbook(xlsx_path)
    ws = wb["table"]

    records = []
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:
            continue
        action = str(row[COL_ACTION] or "")
        if action not in ("证券买入", "证券卖出"):
            continue

        records.append({
            "date": str(row[COL_DATE]),
            "code": str(row[COL_CODE] or ""),
            "name": str(row[COL_NAME] or ""),
            "action": action,
            "volume": int(row[COL_VOLUME] or 0),
            "avg_price": float(row[COL_AVG_PRICE] or 0),
            "amount": float(row[COL_AMOUNT] or 0),
            "cash_flow": float(row[COL_CASH_FLOW] or 0),
            "commission": float(row[COL_COMMISSION] or 0),
            "stamp_tax": float(row[COL_STAMP_TAX] or 0),
            "other_fee": float(row[COL_OTHER_FEE] or 0),
            "post_balance": float(row[COL_POST_BALANCE] or 0),
        })

    wb.close()
    return records


def compute_daily_account(records: list[dict]) -> list[dict]:
    """基于交割单按笔配对（FIFO）计算每日账户数据。

    每个元素的字段：
        date
        post_balance:  当日最后一笔交易后的资金余额
        realized_pnl:  当日实现盈亏（按笔卖出-对应买入+费用）
        cumulative_pnl: 累计实现盈亏
        account_amount: 当日账户金额（后资金额 + 当前持仓市值）
            注：交割单无持仓市值，故仅以后资金额计，
            若需精确数值，应结合 qmt 持仓接口读取。
        daily_pct:     当日收益率（实现盈亏 / 前一日账户金额）
        cumulative_pct: 累计收益率
    """
    daily = {}
    for r in records:
        d = r["date"]
        if d not in daily:
            daily[d] = {
                "date": d,
                "buy_amount": 0.0,
                "sell_amount": 0.0,
                "commission": 0.0,
                "stamp_tax": 0.0,
                "other_fee": 0.0,
                "post_balance": 0.0,
                "trade_pnl": 0.0,    # 当日交易=卖出-买入-费用
            }
        sd = daily[d]
        if r["action"] == "证券买入":
            sd["buy_amount"] += r["amount"]
        elif r["action"] == "证券卖出":
            sd["sell_amount"] += r["amount"]
        sd["commission"] += r["commission"]
        sd["stamp_tax"] += r["stamp_tax"]
        sd["other_fee"] += r["other_fee"]
        sd["post_balance"] = r["post_balance"]
        # 当日实现盈亏 = 当日卖出 + 当日发生金额（发生金额已是扣费后净值）
        # 即 sell_amount + cash_flow = 卖出收到的现金净额
        # 累计 = 卖出净额 - 买入金额 = 毛利
        sd["trade_pnl"] += r["cash_flow"]

    sorted_dates = sorted(daily.keys())
    if not sorted_dates:
        return []

    result = []
    cumulative_pnl = 0.0
    for d in sorted_dates:
        sd = daily[d]
        # 当日实现盈亏 = 卖出现金流入 + (买入时为负的发生金额)
        # cash_flow 合计本身就是"净流入"，累加在 buy_amount 上
        realized = sd["sell_amount"] - sd["buy_amount"] - sd["commission"] - sd["stamp_tax"] - sd["other_fee"]
        cumulative_pnl += realized
        account_amount = sd["post_balance"]
        # 当日收益率需要前一日账户金额
        if result:
            prev_amount = result[-1]["account_amount"]
            daily_pct = realized / abs(prev_amount) * 100 if prev_amount != 0 else 0
        else:
            initial = account_amount - cumulative_pnl
            daily_pct = realized / abs(initial) * 100 if initial != 0 else 0

        result.append({
            "date": d,
            "account_amount": round(account_amount, 2),
            "daily_pnl": round(realized, 2),
            "daily_pct": round(daily_pct, 4),
            "cumulative_pnl": round(cumulative_pnl, 2),
            "cumulative_pct": round(cumulative_pnl / 50000 * 100, 4),  # 假设初始 5 万
            "buy_amount": round(sd["buy_amount"], 2),
            "sell_amount": round(sd["sell_amount"], 2),
            "commission": round(sd["commission"], 2),
            "stamp_tax": round(sd["stamp_tax"], 2),
        })

    return result


def save_to_history(summary: list[dict], file_path=None) -> None:
    """将每日账户汇总写入 History 文件（每行一日）。"""
    if file_path is None:
        file_path = PATH_THS_HISTORY()

    summary_dict = {s["date"]: s for s in summary}
    trading_dates = TRADING_DATES()

    last_amount = 50000.0
    with open(file_path, "w") as f:
        for date in trading_dates:
            s = summary_dict.get(date)
            if s:
                line = (f"{date}|{s['account_amount']}|{s['daily_pnl']}|{s['daily_pct']}|"
                        f"{s['cumulative_pnl']}|{s['cumulative_pct']}|"
                        f"{s['buy_amount']}|{s['sell_amount']}|{s['commission']}|{s['stamp_tax']}")
                last_amount = s["account_amount"]
            else:
                line = f"{date}|{last_amount}|0|0|0|0|0|0|0|0"
            f.write(line + "\n")


def load_history(file_path=None) -> list[dict]:
    """从 History 文件读取每日账户数据。"""
    if file_path is None:
        file_path = PATH_THS_HISTORY()

    result = []
    if not os.path.isfile(file_path):
        return result

    with open(file_path, "r") as f:
        for line in f:
            parts = line.strip().split("|")
            if len(parts) >= 10:
                result.append({
                    "date": parts[0],
                    "account_amount": float(parts[1]),
                    "daily_pnl": float(parts[2]),
                    "daily_pct": float(parts[3]),
                    "cumulative_pnl": float(parts[4]),
                    "cumulative_pct": float(parts[5]),
                    "buy_amount": float(parts[6]),
                    "sell_amount": float(parts[7]),
                    "commission": float(parts[8]),
                    "stamp_tax": float(parts[9]),
                })
    return result


def update() -> list[dict]:
    """主入口：解析交割单 → 计算每日汇总 → 保存到 History。"""
    records = parse_ths_history()
    summary = compute_daily_account(records)
    save_to_history(summary)
    return summary


if __name__ == "__main__":
    update()
</content>
</invoke>