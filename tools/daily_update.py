#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""每日盘后更新总控（供「每日更新大师」小美在交易日 15:50 后执行）。

顺序：
  0. 交易日校验（非交易日直接跳过）
  1. 网页导出当日涨停股 xlsx → AIData/TOP_ORIGIN（内容相同则跳过；不同则先备份 .bak 再覆盖）
  2. 通达信本地数据：默认【跳过检测】（数据由用户手动「盘后数据下载」）；
     需要自动检测/尝试刷新时加 --with-tdx（校验 1d/5m 是否到当日，不新鲜则 NEEDS_MANUAL）。
  3. 指数/宽基 5m 全量导出 → AIData/INDEX_5M（回测用；失败只告警）。
  4. 一条龙更新（复用 Run.py 的现有逻辑）：UPDATE_ALL(最近12个月涨停股口径)。
     同花顺板块默认【自动更新】（--no-ths 可跳过）；Gitee 默认不上传（--with-git）。
  5. 生成下一交易日 TPO_M5 名单 → AIData/NEXT_DAY/strategy.json（供新 UI「实时看盘」读取；失败不阻断）。
  6. 重启新 UI 服务（dashboard_server，8765）。

用法：
    python tools/daily_update.py --dry-run           # 只体检，不动数据
    python tools/daily_update.py                     # 正式执行（同花顺自动、Gitee 跳过）
    python tools/daily_update.py --with-tdx          # 顺便自动检测/刷新通达信本地数据
    python tools/daily_update.py --no-ths            # 不同花顺
    python tools/daily_update.py --with-git          # 需要时上传 Gitee

结果：控制台摘要 + logs/daily_update_<时间>.json（机器可读）+ 同名 .log（全过程输出）。
退出码：0 成功/非交易日跳过；2 通达信数据未就绪需人工；3 网页导出失败；4 一条龙失败。
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AIDATA = os.path.join(ROOT, "AIData")
TOP_ORIGIN = os.path.join(AIDATA, "TOP_ORIGIN")
LOGS = os.path.join(ROOT, "logs")
DOWNLOADS = os.path.join(os.path.expanduser("~"), "Downloads")

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
EDGE_PROFILE = os.path.join(ROOT, ".edge-profile")
CDP_URL = "http://127.0.0.1:9333"
CDP_WAIT = 25

TDX_PLUGIN = os.environ.get("TDX_PLUGIN_PATH", r"C:\new_tdx64\PYPlugins\user")
TDX_VIPDOC = os.path.join(os.path.dirname(os.path.dirname(TDX_PLUGIN)), "vipdoc")
TDX_SAMPLES = ("600000.SH", "000001.SZ")

TOOLS = os.path.join(ROOT, "tools")
_log_file = None


def log(text: str) -> None:
    print(text, flush=True)
    if _log_file:
        try:
            _log_file.write(text + "\n")
            _log_file.flush()
        except Exception:
            pass


def _load_tool(name: str):
    path = os.path.join(TOOLS, name + ".py")
    spec = importlib.util.spec_from_file_location(f"_tool_{name}", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _xlsx_name(day: dt.date) -> str:
    return f"主板，{day.year}年{day.month}月{day.day:02d}日涨停所有股.xlsx"


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------- 步骤 0：交易日 ----------------
def _trading_day_via_tq(key: str) -> bool | None:
    """本地交易日历文件可能只更新到上一次运行；用常驻的通达信日历现场确认。"""
    try:
        sys.path.insert(0, TDX_PLUGIN)
        from tqcenter import tq

        tq.initialize(os.path.abspath(__file__))
        dates = tq.get_trading_dates(market="SH", start_time=key, end_time=key, count=-1)
        try:
            tq.close()
        except Exception:
            pass
        values = dates.values() if isinstance(dates, dict) else dates
        normalized = set()
        for item in values or []:
            text = str(item).replace("-", "").strip()
            if len(text) >= 8:
                normalized.add(text[:8])
        if key in normalized:
            return True
        if normalized:
            return False
        return None
    except Exception:
        return None


def check_trading_day(day: dt.date) -> tuple[bool | None, str]:
    path = os.path.join(AIDATA, "TRADING_DATES")
    if not os.path.exists(path):
        return False, "AIData/TRADING_DATES 不存在"
    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        dates = {line.strip() for line in fh if line.strip()}
    key = day.strftime("%Y%m%d")
    latest = max(dates) if dates else "?"
    if key in dates:
        return True, f"{key} 在交易日历中"

    api = _trading_day_via_tq(key)
    if api is True:
        return True, f"{key} 经通达信日历确认是交易日（本地文件未含）"
    if api is False:
        return False, f"{key} 经通达信日历确认非交易日"
    if day.weekday() >= 5:
        return False, f"{key} 是周末"
    return None, f"{key} 不在本地交易日历（最新 {latest}），通达信日历暂未返回；先试导出以确认是否交易日"


# ---------------- 步骤 1：网页导出 + 归档 ----------------
def _cdp_alive() -> bool:
    try:
        with urllib.request.urlopen(CDP_URL + "/json/version", timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


def ensure_browser(day: dt.date) -> tuple[bool, str]:
    if _cdp_alive():
        return True, "调试端口已在线"
    if not os.path.exists(EDGE):
        return False, f"找不到 Edge：{EDGE}"
    msg = _xlsx_name(day).replace(".xlsx", "")
    url = f"https://wenda.tdx.com.cn/site/wenda/stock_index.html?message={urllib.parse.quote(msg)}"
    subprocess.Popen([
        EDGE,
        "--remote-debugging-port=9333",
        "--remote-allow-origins=*",
        f"--user-data-dir={EDGE_PROFILE}",
        "--no-first-run",
        "--no-default-browser-check",
        url,
    ])
    deadline = time.time() + CDP_WAIT
    while time.time() < deadline:
        if _cdp_alive():
            return True, "已启动普通模式 Edge"
        time.sleep(1)
    return False, "Edge 调试端口未就绪"


def close_browser() -> str:
    """关闭网页导出用的专用 Edge（只杀 --user-data-dir=.edge-profile 的进程，不动用户日常 Edge）。"""
    try:
        script = (
            "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" -ErrorAction SilentlyContinue | "
            "Where-Object { $_.CommandLine -like '*\\.edge-profile*' } | "
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
        )
        subprocess.run(["powershell", "-NoProfile", "-Command", script],
                       capture_output=True, text=True, timeout=60)
        time.sleep(1)
        return "导出用浏览器已关闭"
    except Exception as exc:
        return f"关闭浏览器失败：{type(exc).__name__}"


def verify_download(source: str, day: dt.date) -> tuple[bool, str]:
    """按固定文件名 + 工作表名日期双重确认下载的是目标日期的数据。"""
    expected = _xlsx_name(day)
    actual = os.path.basename(source)
    if actual != expected:
        return False, f"文件名不符：{actual}（期望 {expected}）"
    try:
        from openpyxl import load_workbook

        wb = load_workbook(source)
        sheet = wb.sheetnames[0] if wb.sheetnames else ""
        wb.close()
    except Exception as exc:
        return False, f"打开 xlsx 失败：{type(exc).__name__}: {exc}"
    key = day.strftime("%Y%m%d")
    if key not in sheet:
        return False, f"工作表名不含日期 {key}：{sheet}"
    return True, f"文件名与工作表日期校验通过（{sheet}）"


def step_export(day: dt.date, dry_run: bool) -> dict:
    name = _xlsx_name(day)
    source = os.path.join(DOWNLOADS, name)
    target = os.path.join(TOP_ORIGIN, name)
    os.makedirs(TOP_ORIGIN, exist_ok=True)

    if dry_run:
        exists = os.path.exists(source)
        return {"step": "export", "ok": True, "dry_run": True,
                "note": f"将导出 {name}；Downloads 现有={'是' if exists else '否'}；"
                        f"TOP_ORIGIN 现有={'是' if os.path.exists(target) else '否'}；"
                        f"导出后按固定文件名+工作表日期校验"}

    ok, note = ensure_browser(day)
    if not ok:
        return {"step": "export", "ok": False, "error": note}
    log(f"[1/6] 浏览器：{note}")

    tool = _load_tool("tdx_top_export")
    try:
        code = tool._export(day, DOWNLOADS, login_wait=180, timeout=60, headless=False, attach=True)
    finally:
        close_note = close_browser()
        log(f"[1/6] {close_note}")

    if code != 0:
        return {"step": "export", "ok": False, "error": f"导出脚本退出码 {code}", "browser": close_note}
    if not os.path.exists(source):
        return {"step": "export", "ok": False, "error": "下载文件未找到", "browser": close_note}

    verify_ok, verify_note = verify_download(source, day)
    log(f"[1/6] {verify_note}")
    if not verify_ok:
        return {"step": "export", "ok": False, "error": verify_note, "browser": close_note}

    if os.path.exists(target):
        if _sha256(source) == _sha256(target):
            os.remove(source)
            return {"step": "export", "ok": True, "note": "TOP_ORIGIN 已存在同内容文件，跳过",
                    "path": target, "browser": close_note, "verify": verify_note}
        backup = target + ".bak"
        shutil.copy2(target, backup)
        log(f"[1/6] 已备份旧文件 → {os.path.basename(backup)}")
        os.remove(target)
    shutil.move(source, target)
    return {"step": "export", "ok": True, "path": target, "sha256": _sha256(target),
            "browser": close_note, "verify": verify_note}


# ---------------- 步骤 2：通达信本地数据 ----------------
def _tdx_last_date(code: str, period: str) -> str | None:
    tool = _load_tool("tdx_refresh")
    path = tool._local_file(code, period)
    last = tool._last_date(path, period)
    return None if last in (None, "无文件", "解析失败") else last


def tdx_is_fresh(day: dt.date) -> tuple[bool, list[str]]:
    want_day = day.strftime("%Y-%m-%d")
    problems: list[str] = []
    for code in TDX_SAMPLES:
        for period in ("1d", "5m"):
            last = _tdx_last_date(code, period)
            if last is None:
                problems.append(f"{code} {period}: 无本地数据")
                continue
            normalized = last
            if period == "1d" and len(last) == 8 and last.isdigit():
                normalized = f"{last[:4]}-{last[4:6]}-{last[6:]}"
            if normalized[:10] != want_day:
                problems.append(f"{code} {period}: 本地最新 {last}，未到 {want_day}")
    return not problems, problems


def step_tdx(day: dt.date, skip: bool, dry_run: bool) -> dict:
    fresh, problems = tdx_is_fresh(day)
    if dry_run:
        if skip:
            return {"step": "tdx", "ok": True, "dry_run": True, "skipped": True,
                    "fresh": fresh, "problems": problems,
                    "note": "默认跳过自动刷新（仍校验是否当日最新：不新鲜会提示手动盘后下载）"}
        return {"step": "tdx", "ok": True, "dry_run": True, "fresh": fresh, "problems": problems}
    if skip:
        if not fresh:
            log("[2/6] 通达信本地数据不是当日最新：请先手动执行「盘后数据下载」")
            return {"step": "tdx", "ok": False, "needs_manual": True, "problems": problems,
                    "error": "通达信本地数据未到当日，请手动执行：选项 → 盘后数据下载（勾选日线+5分钟），然后重跑"}
        log("[2/6] 通达信数据已就绪（用户手动下载），跳过自动刷新")
        return {"step": "tdx", "ok": True, "skipped": True, "fresh": True}
    if fresh:
        return {"step": "tdx", "ok": True, "note": "本地数据已是当日最新"}

    # 先尝试官方代码接口（实测可能无效，仍保留尝试并如实校验）
    log("[2/6] 本地数据未就绪，尝试 tqcenter.refresh_kline ...")
    try:
        subprocess.run(
            [sys.executable, os.path.join(TOOLS, "tdx_refresh.py"),
             "--codes", ",".join(TDX_SAMPLES), "--periods", "1d,5m"],
            cwd=ROOT, timeout=300, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
    except Exception as exc:
        log(f"[2/6] refresh_kline 调用异常：{type(exc).__name__}: {exc}")

    fresh, problems = tdx_is_fresh(day)
    if fresh:
        return {"step": "tdx", "ok": True, "note": "refresh_kline 后本地数据已就绪"}
    return {
        "step": "tdx", "ok": False, "needs_manual": True,
        "error": "通达信本地数据仍不是当日最新，请手动执行：选项 → 盘后数据下载（勾选日线+5分钟）",
        "problems": problems,
    }


# ---------------- 步骤 3：指数/宽基 5m 全量 ----------------
def step_index_5m(dry_run: bool) -> dict:
    """把指数/宽基/相关 ETF 的 5m 全量从通达信本地导出到 AIData/INDEX_5M（回测用）。"""
    if dry_run:
        return {"step": "index_5m", "ok": True, "dry_run": True,
                "note": "将把 AIData/INDEX_5M_CODES 里的指数/宽基/ETF 5m 全量导出（当前 17 个）"}
    log("[3/6] 导出指数/宽基 5m 全量 → AIData/INDEX_5M ...")
    try:
        proc = subprocess.run(
            [sys.executable, os.path.join(TOOLS, "export_index_5m.py")],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
        )
    except Exception as exc:
        return {"step": "index_5m", "ok": False, "error": f"{type(exc).__name__}: {exc}"}
    tail = (proc.stdout or "").strip().splitlines()[-1:] or [""]
    if proc.returncode != 0:
        return {"step": "index_5m", "ok": False, "error": (proc.stderr or proc.stdout or "")[-500:]}
    log(f"[3/6] {tail[0]}")
    return {"step": "index_5m", "ok": True, "note": tail[0]}


# ---------------- 步骤 4：一条龙 ----------------
def step_pipeline(day: dt.date, months: int, with_ths: bool, with_git: bool, dry_run: bool) -> dict:
    if dry_run:
        try:
            sys.path.insert(0, ROOT)
            import Run as R  # noqa: F401
            scope = R._top_codes_in_period(months)
            result = {"step": "pipeline", "ok": True, "dry_run": True,
                      "note": f"将更新：scope 股票 {len(scope)} 只，5M 最近 {R._RECENT_DAYS_5M} 个交易日；"
                              f"同花顺={'开' if with_ths else '关'}，Gitee={'开' if with_git else '关'}"}
            return result
        except Exception as exc:
            return {"step": "pipeline", "ok": False, "dry_run": True, "error": f"{type(exc).__name__}: {exc}"}

    log(f"[4/6] 一条龙更新开始（scope=近{months}个月涨停股，含 5M 窗口下载）...")
    started = time.time()
    sys.path.insert(0, ROOT)
    import Run as R

    scope = sorted(R._top_codes_in_period(months))
    log(f"[4/6] 圈定股票 {len(scope)} 只")
    R._do_update(scope_codes=scope, recent_days_5m=R._RECENT_DAYS_5M)
    log(f"[4/6] 数据更新完成（{time.time() - started:.0f}s）")

    if with_ths:
        try:
            res = R.CMD_UPDATE_THS("TPO_M5")
            log(f"[4/6] 同花顺板块：{res}")
        except Exception as exc:
            log(f"[4/6] 同花顺板块失败（不阻断）：{type(exc).__name__}: {exc}")
    else:
        log("[4/6] 同花顺已跳过（--no-ths）")

    if with_git:
        try:
            R._git_push("origin", commit_msg="chore: 每日自动更新 " + dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            log("[4/6] 已上传 Gitee")
        except Exception as exc:
            log(f"[4/6] Gitee 上传失败（不阻断）：{type(exc).__name__}: {exc}")
    else:
        log("[4/6] Gitee 已暂时屏蔽（仓库约 1.9GB 超出配额；需要上传时加 --with-git）")

    return {"step": "pipeline", "ok": True, "duration_s": round(time.time() - started, 1)}


# ---------------- 步骤 5：下一交易日策略 ----------------
def step_next_day(day: dt.date, dry_run: bool) -> dict:
    """生成下一交易日 TPO_M5 名单 → AIData/NEXT_DAY/strategy.json（供新 UI 实时看盘）。

    子进程调用 tools/next_day_strategy.py；失败不阻断主流程，只在 summary 里标记。
    """
    out = os.path.join(AIDATA, "NEXT_DAY", "strategy.json")
    if dry_run:
        note = "将生成下一交易日 TPO_M5 名单（forTradeDate=下一交易日）→ AIData/NEXT_DAY/strategy.json"
        log("[5/6] " + note)
        return {"step": "next_day", "ok": True, "dry_run": True, "note": note}
    log("[5/6] 生成下一交易日 TPO_M5 名单 ...")
    try:
        proc = subprocess.run(
            [sys.executable, os.path.join(TOOLS, "next_day_strategy.py"),
             "--buy-date", day.strftime("%Y%m%d")],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
        )
    except Exception as exc:
        return {"step": "next_day", "ok": False, "error": f"{type(exc).__name__}: {exc}"}

    payload: dict | None = None
    for line in reversed((proc.stdout or "").strip().splitlines()):
        if line.startswith("NEXT_DAY_JSON "):
            try:
                payload = json.loads(line[len("NEXT_DAY_JSON "):])
            except json.JSONDecodeError:
                payload = None
            break
    if proc.returncode != 0 or not payload or not payload.get("ok"):
        detail = ((proc.stderr or "") + (proc.stdout or "")).strip()[-500:]
        return {"step": "next_day", "ok": False,
                "error": f"生成器退出码 {proc.returncode}：{detail}"}

    pick = payload.get("firstPick") or {}
    log(f"[5/6] 已生成：forTradeDate={payload.get('forTradeDate')}，"
        f"首选={pick.get('code', '空仓')} {pick.get('name', '')}，buyList={payload.get('buyListCount')} 只")
    return {"step": "next_day", "ok": True,
            "forTradeDate": payload.get("forTradeDate"),
            "firstPick": payload.get("firstPick"),
            "buyListCount": payload.get("buyListCount"),
            "candidatesCount": payload.get("candidatesCount"),
            "env": payload.get("env"),
            "out": payload.get("out", out)}


# ---------------- 步骤 6：重启新 UI 服务 ----------------
def step_restart_dashboard(dry_run: bool) -> dict:
    """数据更新完成后重启新 UI 服务（dashboard_server）；复用 tools/ui_server.py 的 restart_dashboard。

    返回 {"step": "restart_ui", "ok": bool, "pid": int|None, ...}（失败不阻断主流程）。
    """
    if dry_run:
        return {"step": "restart_ui", "ok": True, "dry_run": True,
                "note": "将重启新 UI 服务（http://127.0.0.1:8765）"}
    log("[6/6] 重启新 UI 服务（dashboard_server）...")
    tool = _load_tool("ui_server")
    result = tool.restart_dashboard(port=8765)
    old = result.get("oldPids") or []
    if old:
        log(f"[6/6] 已停止旧服务进程 {old}")
    if result.get("ok"):
        log(f"[6/6] 新 UI 服务已就绪（PID {result.get('pid')}）")
        return {"step": "restart_ui", "ok": True, "pid": result.get("pid"),
                "note": "新 UI 服务已重启并就绪"}
    return {"step": "restart_ui", "ok": False, "pid": result.get("pid"),
            "error": result.get("error", "重启失败")}


# ---------------- 主流程 ----------------
def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="每日盘后更新总控")
    parser.add_argument("--date", default=dt.date.today().isoformat(), help="交易日 YYYY-MM-DD，默认今天")
    parser.add_argument("--dry-run", action="store_true", help="只体检，不动数据")
    parser.add_argument("--skip-tdx", action="store_true", help="（已废弃：默认就跳过通达信检测）")
    parser.add_argument("--skip-export", action="store_true", help="跳过网页导出归档")
    parser.add_argument("--skip-pipeline", action="store_true", help="跳过一条龙更新")
    parser.add_argument("--months", type=int, default=12, help="一条龙周期（月），默认 12")
    parser.add_argument("--with-tdx", action="store_true",
                        help="自动检测/尝试刷新通达信本地数据（默认跳过：数据由用户手动盘后下载）")
    parser.add_argument("--no-ths", action="store_true", help="不自动更新同花顺（默认自动更新）")
    parser.add_argument("--with-ths", action="store_true", help="（已废弃：默认就自动更新同花顺）")
    parser.add_argument("--with-git", action="store_true",
                        help="上传 Gitee（默认关闭：仓库约 1.9GB 超出配额，暂时屏蔽）")
    parser.add_argument("--no-git", action="store_true", help="（已废弃：默认就不上传 Gitee）")
    args = parser.parse_args(argv)

    try:
        day = dt.date.fromisoformat(args.date)
    except ValueError:
        print(f"[错误] 日期格式应为 YYYY-MM-DD：{args.date}")
        return 1

    os.makedirs(LOGS, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    global _log_file
    _log_file = open(os.path.join(LOGS, f"daily_update_{stamp}.log"), "w", encoding="utf-8")

    summary: dict = {"date": day.isoformat(), "dry_run": args.dry_run,
                     "started": dt.datetime.now().isoformat(timespec="seconds"), "steps": []}
    try:
        trading, note = check_trading_day(day)
        log(f"[0/6] 交易日校验：{note}")
        if trading is False:
            summary["skipped"] = "非交易日"
            summary["ok"] = True
        else:
            if trading is None:
                summary["trading_day_unverified"] = True
            if not args.skip_export:
                export = step_export(day, args.dry_run)
                summary["steps"].append(export)
                if not export.get("ok"):
                    if trading is None:
                        summary["skipped"] = "疑似非交易日（导出无数据表）"
                        summary["ok"] = True
                        return 0
                    raise RuntimeError("网页导出失败：" + str(export.get("error")))
            else:
                summary["steps"].append({"step": "export", "skipped": True})

            tdx = step_tdx(day, not args.with_tdx, args.dry_run)
            summary["steps"].append(tdx)
            if not tdx.get("ok"):
                summary["ok"] = False
                summary["exit_code"] = 2
                return 2

            # 指数/宽基 5m 全量导出（回测用；失败只告警，不阻断主流程）
            idx5 = step_index_5m(args.dry_run)
            summary["steps"].append(idx5)
            if not idx5.get("ok"):
                log("[警告] 指数 5m 全量导出失败（不阻断）：" + str(idx5.get("error")))

            if not args.skip_pipeline:
                pipe = step_pipeline(day, args.months, not args.no_ths, args.with_git, args.dry_run)
                summary["steps"].append(pipe)
                if not pipe.get("ok"):
                    raise RuntimeError("一条龙失败：" + str(pipe.get("error")))
            else:
                summary["steps"].append({"step": "pipeline", "skipped": True})

            # 步骤 5：生成下一交易日策略（失败不阻断，只在 summary 里标记）
            next_day = step_next_day(day, args.dry_run)
            summary["steps"].append(next_day)
            if not next_day.get("ok"):
                summary.setdefault("warnings", []).append(
                    "下一交易日策略生成失败：" + str(next_day.get("error")))

            # 步骤 6：重启新 UI 服务，避免页面读取启动时的旧缓存
            ui = step_restart_dashboard(args.dry_run)
            summary["steps"].append(ui)
            if not ui.get("ok"):
                summary.setdefault("warnings", []).append(
                    "新 UI 服务重启失败：" + str(ui.get("error")))

            summary["ok"] = True
        return 0
    except Exception as exc:
        summary["ok"] = False
        summary["exit_code"] = 3
        summary["error"] = f"{type(exc).__name__}: {exc}"
        log(f"[失败] {summary['error']}")
        return 3
    finally:
        summary["finished"] = dt.datetime.now().isoformat(timespec="seconds")
        result_path = os.path.join(LOGS, f"daily_update_{stamp}.json")
        with open(result_path, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, ensure_ascii=False, indent=2)
        log("SUMMARY_JSON " + json.dumps(summary, ensure_ascii=False))
        if _log_file:
            _log_file.close()


if __name__ == "__main__":
    sys.exit(main())
