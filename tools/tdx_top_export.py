#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""从通达信「问小达」网页导出指定交易日的主板涨停股 xlsx。

用途：盘后自动下载 https://wenda.tdx.com.cn/site/wenda/stock_index.html?message=主板，YYYY年M月DD日涨停所有股
      的「导出数据」结果（xlsx），供 AIData/TOP_ORIGIN 使用。

首次使用：会弹出 Edge 窗口，请在该窗口里登录通达信账号（登录态保存在 .edge-profile，之后无需再登录）。
之后每天可复用该登录态（也可用 --headless 静默运行）。

用法：
    python tools/tdx_top_export.py --date 2026-11-03                  # 默认下载到用户 Downloads
    python tools/tdx_top_export.py --date 2026-11-03 --out "C:\\MarcoAI\\.downloads"
    python tools/tdx_top_export.py --date 2026-11-03 --headless       # 已登录后静默
    python tools/tdx_top_export.py --check-playwright                 # 只检查环境

退出码：0 成功；1 参数错误；2 需要登录/登录超时；3 页面未出现数据表；4 导出失败；5 下载文件校验失败。
调试产物：失败时把页面快照与按钮清单写到 .tools/debug/。
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILE_DIR = os.path.join(ROOT, ".edge-profile")
TOOLS_PYLIB = os.path.join(ROOT, ".tools", "pylib")
DEBUG_DIR = os.path.join(ROOT, ".tools", "debug")
_TMP_DIR = os.path.join(ROOT, ".tools", "tmp")

# Playwright 默认把临时产物写到系统 %TEMP%，本机沙箱下该目录不可建目录（EPERM）；
# 统一把 TEMP/TMP/TMPDIR 指到工作区内，脚本与浏览器子进程都用这里。
os.makedirs(_TMP_DIR, exist_ok=True)
for _var in ("TEMP", "TMP", "TMPDIR"):
    os.environ[_var] = _TMP_DIR

URL_TMPL = "https://wenda.tdx.com.cn/site/wenda/stock_index.html?message={msg}"
MSG_TMPL = "主板，{y}年{m}月{d}日涨停所有股"


def _ensure_playwright() -> None:
    if TOOLS_PYLIB not in sys.path:
        sys.path.insert(0, TOOLS_PYLIB)


def _log(text: str) -> None:
    print(text, flush=True)


def _msg_variants(day: dt.date) -> list[str]:
    """站点对「日」可能补零也可能不补，按文件名规律给几种候选，逐个尝试。"""
    variants = [
        MSG_TMPL.format(y=day.year, m=day.month, d=f"{day.day:02d}"),
        MSG_TMPL.format(y=day.year, m=day.month, d=day.day),
        MSG_TMPL.format(y=day.year, m=f"{day.month:02d}", d=f"{day.day:02d}"),
    ]
    out: list[str] = []
    for v in variants:
        if v not in out:
            out.append(v)
    return out


def _logged_in(page) -> bool:
    try:
        return bool(page.evaluate("() => !!(localStorage.getItem('TDXID') || localStorage.getItem('ZH'))"))
    except Exception:
        return False


def _wait_login(page, timeout_s: int) -> bool:
    _log(f"[登录] 请在弹出的浏览器窗口里完成登录（最长等待 {timeout_s} 秒）...")
    deadline = time.time() + timeout_s
    nxt = time.time() + 20
    while time.time() < deadline:
        if _logged_in(page):
            _log("[登录] 已检测到登录态")
            return True
        if time.time() >= nxt:
            nxt = time.time() + 20
            _log("[登录] 仍在等待登录...")
        time.sleep(2)
    return False


def _page_has_table(page) -> bool:
    try:
        text = page.inner_text("body")
    except Exception:
        return False
    return ("股票代码" in text) or ("序号" in text and "涨停" in text)


def _wait_table(page, timeout_s: int) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if _page_has_table(page):
            return True
        time.sleep(2)
    return False


def _dump_debug(page, tag: str) -> None:
    os.makedirs(DEBUG_DIR, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    html_path = os.path.join(DEBUG_DIR, f"{tag}-{ts}.html")
    try:
        with open(html_path, "w", encoding="utf-8", errors="replace") as f:
            f.write(page.content())
        _log(f"[调试] 页面快照：{html_path}")
    except Exception as exc:
        _log(f"[调试] 保存页面失败：{exc}")
    try:
        buttons = page.evaluate(
            """() => Array.from(document.querySelectorAll('button,a,span,div,i,td'))
                  .map(el => (el.innerText || el.textContent || '').trim())
                  .filter(t => t && t.length <= 20)
                  .slice(0, 120)"""
        )
        _log(f"[调试] 可点击文本：{buttons[:60]}")
    except Exception as exc:
        _log(f"[调试] 枚举按钮失败：{exc}")


def _handle_export_popover(page) -> bool:
    """点击“导数据”后站点可能弹出浮层让选导出格式，点浮层里的“导出/Excel/下载”。"""
    time.sleep(1.5)
    try:
        menus = page.evaluate(
            """() => Array.from(document.querySelectorAll('.el-popover, .el-dropdown-menu, .el-menu, [role=menu], .el-select-dropdown'))
                 .filter(el => el.offsetParent !== null)
                 .map(el => (el.innerText || '').trim().slice(0, 200))
                 .filter(t => t)"""
        )
    except Exception:
        menus = []
    _log(f"[导出] 浮层内容：{menus or '无'}")
    for menu in menus:
        if not any(kw in menu for kw in ("导出", "Excel", "excel", "下载", "xlsx", "XLSX")):
            continue
        for kw in ("导出", "Excel", "excel", "下载", "xlsx", "XLSX"):
            if kw not in menu:
                continue
            try:
                item = page.get_by_text(kw, exact=False).last
                if item.count() > 0:
                    item.click(timeout=8000)
                    _log(f"[导出] 浮层内点击：{kw}")
                    return True
            except Exception:
                continue
    return False


def _click_export(page) -> bool:
    """点击页面上的“导数据”按钮（真实文字是“导数据”，类名 tdx-btn-exportdata）。"""
    candidates = [
        ".tdx-btn-exportdata",
        "[class*='exportdata']",
        "button:has-text('导数据')",
        "button:has-text('导出')",
    ]
    for selector in candidates:
        try:
            loc = page.locator(selector).first
            if loc.count() > 0:
                loc.click(timeout=8000)
                _log(f"[导出] 已点击：{selector}")
                return True
        except Exception:
            continue
    for text in ("导数据", "导出数据", "导出"):
        try:
            loc = page.get_by_text(text, exact=False).first
            if loc.count() > 0:
                loc.click(timeout=8000)
                _log(f"[导出] 已点击文本：{text}")
                return True
        except Exception:
            continue
    return False


def _newest_xlsx(directory: str, since_ts: float) -> str | None:
    candidates = []
    for pattern in ("*.xlsx", "*.xls"):
        for path in glob.glob(os.path.join(directory, pattern)):
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            if mtime >= since_ts - 2:
                candidates.append((mtime, path))
    return max(candidates)[1] if candidates else None


def _validate_xlsx(path: str) -> tuple[bool, str]:
    try:
        from openpyxl import load_workbook

        wb = load_workbook(path)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        wb.close()
    except Exception as exc:
        return False, f"打不开 xlsx：{exc}"
    if not rows:
        return False, "xlsx 为空"
    header = [str(c or "") for c in rows[0]]
    if "股票代码" not in header:
        return False, f"表头缺少“股票代码”：{header[:6]}"
    idx = header.index("股票代码")
    codes = [str(r[idx]).strip() for r in rows[1:] if len(r) > idx and r[idx] is not None]
    codes = [c for c in codes if c]
    if not codes:
        return False, "没有股票代码数据行"
    if not all(c[:6].isdigit() for c in codes):
        return False, f"股票代码列存在非 6 位数字：{codes[:3]}"
    return True, f"{len(rows) - 1} 行，{len(header)} 列，示例 {codes[:3]}"


def _load_table(page, day: dt.date, timeout_s: int, login_wait: int) -> str | None:
    """反复加载查询页直到出现数据表（登录态由浏览器 cookie 维持，不依赖 localStorage 键名）。

    返回命中的查询串；超时返回 None。
    """
    variants = _msg_variants(day)
    deadline = time.time() + max(login_wait, timeout_s)
    last_notice = 0.0
    while time.time() < deadline:
        for msg in variants:
            url = URL_TMPL.format(msg=msg)
            _log(f"[打开] {url}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
            except Exception as exc:
                _log(f"[提示] 打开页面失败：{type(exc).__name__}: {exc}")
                continue
            time.sleep(3)
            if _page_has_table(page):
                return msg
            if _wait_table(page, 8):
                return msg
        if time.time() - last_notice > 20:
            last_notice = time.time()
            _log("[等待] 数据表未出现：若窗口显示未登录，请登录；脚本会自动重试直到出现数据")
        time.sleep(4)
    return None


def _export(day: dt.date, out_dir: str, login_wait: int, timeout: int, headless: bool, attach: bool = False) -> int:
    _ensure_playwright()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        _log(f"[错误] 未找到 playwright：{exc}")
        return 5

    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(PROFILE_DIR, exist_ok=True)
    downloads: list = []

    with sync_playwright() as p:
        if attach:
            # 接管一个“普通模式”启动的 Edge（只有 --remote-debugging-port，无自动化标记），
            # 页面里 navigator.webdriver 为 false，站点不会拦截登录。
            browser = p.chromium.connect_over_cdp("http://127.0.0.1:9333")
            ctx = browser.contexts[0]
            wenda_pages = [pg for pg in ctx.pages if "wenda.tdx.com.cn" in (pg.url or "")]
            page = wenda_pages[0] if wenda_pages else (ctx.pages[0] if ctx.pages else ctx.new_page())
        else:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=PROFILE_DIR,
                channel="msedge",
                headless=headless,
                accept_downloads=True,
                downloads_path=out_dir,
                viewport={"width": 1440, "height": 900},
                args=["--no-first-run", "--no-default-browser-check", "--disable-blink-features=AutomationControlled"],
            )
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:

            def on_download(d) -> None:
                downloads.append(d)
                _log(f"[下载] 浏览器触发下载：{d.suggested_filename}")

            page.on("download", on_download)
            ctx.on("page", lambda pg: pg.on("download", on_download))

            if attach:
                # 站点曾在 localStorage 写 currentMode=3.0 后自动跳转 v3 页面，这里清掉避免导航被改写
                try:
                    page.evaluate("() => { try { localStorage.removeItem('currentMode'); } catch (e) {} }")
                except Exception:
                    pass

            used_msg = _load_table(page, day, timeout, login_wait)
            if not used_msg:
                _dump_debug(page, "no-table")
                _log(f"[错误] 页面未出现数据表（{day}）：可能未登录、查询串不正确或当日无数据")
                return 2

            _log(f"[数据] 数据表已加载，查询串：{used_msg}")
            started = time.time()
            if not _click_export(page):
                _dump_debug(page, "no-export-button")
                _log("[错误] 未找到“导出数据”按钮")
                return 4
            _handle_export_popover(page)

            path: str | None = None
            deadline = time.time() + 120
            while time.time() < deadline:
                if downloads:
                    d = downloads[-1]
                    path = os.path.join(out_dir, d.suggested_filename)
                    try:
                        d.save_as(path)
                    except Exception:
                        path = _newest_xlsx(out_dir, started)
                    break
                time.sleep(1)

            if path is None:
                path = _newest_xlsx(out_dir, started)

            if not path or not os.path.exists(path):
                _dump_debug(page, "no-download")
                _log("[错误] 导出后没有找到下载的 xlsx 文件")
                return 4

            _log(f"[下载] 文件：{path}  ({os.path.getsize(path)} 字节)")
            ok, detail = _validate_xlsx(path)
            _log(f"[校验] {'通过' if ok else '失败'}：{detail}")
            if not ok:
                return 5
            _log(f"[完成] 已获取 {day.isoformat()} 的涨停数据：{path}")
            return 0
        finally:
            if not attach:
                try:
                    ctx.close()
                except Exception:
                    pass


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="从通达信问小达导出主板涨停股 xlsx")
    parser.add_argument("--date", default=dt.date.today().isoformat(), help="交易日 YYYY-MM-DD，默认今天")
    parser.add_argument("--out", default=os.path.join(os.path.expanduser("~"), "Downloads"), help="下载目录，默认用户 Downloads")
    parser.add_argument("--login-wait", type=int, default=600, help="等待人工登录的秒数，默认 600")
    parser.add_argument("--timeout", type=int, default=90, help="等待数据表的秒数，默认 90")
    parser.add_argument("--headless", action="store_true", help="静默运行（已登录时可用）")
    parser.add_argument("--attach", action="store_true", help="接管普通模式 Edge（127.0.0.1:9333 调试端口）")
    parser.add_argument("--check-playwright", action="store_true", help="检查 playwright 是否可用")
    args = parser.parse_args(argv)

    _ensure_playwright()
    if args.check_playwright:
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = p.chromium.launch(channel="msedge", headless=True)
                _log(f"[检查] Playwright 可用，Edge 版本：{browser.version}")
                browser.close()
            return 0
        except Exception as exc:
            _log(f"[检查] 不可用：{type(exc).__name__}: {exc}")
            return 1

    try:
        day = dt.date.fromisoformat(args.date)
    except ValueError:
        _log(f"[错误] 日期格式应为 YYYY-MM-DD：{args.date}")
        return 1

    return _export(day, os.path.abspath(args.out), args.login_wait, args.timeout, headless=args.headless, attach=args.attach)


if __name__ == "__main__":
    sys.exit(main())
