#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""从通达信「问小达」网页导出「流通市值>1亿 / 主板非ST / 显示概念 / 显示流通股本」→ AIData/INFO/SZ100.xlsx。

用途：为 UPDATE_STOCK_CODES 提供最新股票池（代码|名称|流通股本），是每日更新的第一步。

复用 tools/tdx_top_export.py 的 Edge/Playwright 逻辑（接管普通模式 Edge 调试端口 9333，
登录态保存在 .edge-profile），差异只在查询串与后处理：
  1) 导出的 xlsx 前两行为标题行（第 1 行列标题、第 2 行日期行），数据从第 3 行开始；
  2) 不删除任何股票（银行股保留）；
  3) 数据区按「股票代码」升序排序，前两行标题原样保留；
  4) 覆盖写入 AIData/INFO/SZ100.xlsx（先写临时文件再原子替换；失败不删旧文件）。
浏览器保证在 finally 中关闭：只关自己启动的 .edge-profile Edge 与导出标签页，不影响用户其它窗口。

用法：
    python tools/tdx_sz100_export.py --dry-run          # 只打印计划
    python tools/tdx_sz100_export.py                    # 导出 + 后处理 → AIData/INFO/SZ100.xlsx
    python tools/tdx_sz100_export.py --dest D:/tmp/SZ100.xlsx
    python tools/tdx_sz100_export.py --keep-download     # 保留下载的原始 xlsx

退出码：0 成功；2 页面未出现数据表/需要登录；3 下载/校验失败；4 后处理失败。
调试产物：失败时把页面快照与按钮清单写到 .tools/debug/。
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import os
import sys
import time
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")
TOOLS_PYLIB = os.path.join(ROOT, ".tools", "pylib")
TMP_ROOT = os.path.join(ROOT, ".tools", "tmp")
DEBUG_DIR = os.path.join(ROOT, ".tools", "debug")
EDGE_PROFILE = os.path.join(ROOT, ".edge-profile")
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
CDP_URL = "http://127.0.0.1:9333"
CDP_WAIT = 25

DEST_DEFAULT = os.path.join(ROOT, "AIData", "INFO", "SZ100.xlsx")
SZ100_MSG = "流通市值大于1亿，主板非ST，显示所属概念，显示流通股本"
URL_TMPL = "https://wenda.tdx.com.cn/site/wenda/stock_index.html?message={msg}"

# Playwright 临时产物统一指向工作区（与 tdx_top_export 一致，规避系统 %TEMP% 限制）
for _var in ("TEMP", "TMP", "TMPDIR"):
    os.environ[_var] = TMP_ROOT
os.makedirs(TMP_ROOT, exist_ok=True)


def log(text: str) -> None:
    print(text, flush=True)


def _load_module(name: str, path: str):
    spec = importlib.util.spec_from_file_location(f"_sz100_{name}", path)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _export_tool():
    """tools/tdx_top_export.py —— 复用其 Playwright 页面操作函数。"""
    return _load_module("tdx_top_export", os.path.join(TOOLS, "tdx_top_export.py"))


def query_url() -> str:
    return URL_TMPL.format(msg=urllib.parse.quote(SZ100_MSG))


# ---------------------------------------------------------------- Edge 启动/关闭
def _cdp_alive() -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen(CDP_URL + "/json/version", timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


def ensure_browser() -> tuple[bool, str]:
    """确保普通模式 Edge 以调试端口 9333 运行（站点只对普通浏览器放行登录态）。"""
    if _cdp_alive():
        return True, "调试端口已在线"
    if not os.path.exists(EDGE):
        return False, f"找不到 Edge：{EDGE}"
    subprocess_run = __import__("subprocess").Popen
    subprocess_run([
        EDGE,
        "--remote-debugging-port=9333",
        "--remote-allow-origins=*",
        f"--user-data-dir={EDGE_PROFILE}",
        "--no-first-run",
        "--no-default-browser-check",
        query_url(),
    ])
    deadline = time.time() + CDP_WAIT
    while time.time() < deadline:
        if _cdp_alive():
            return True, "已启动普通模式 Edge"
        time.sleep(1)
    return False, "Edge 调试端口未就绪"


def close_browser() -> str:
    """关闭导出用的专用 Edge（只杀 --user-data-dir=.edge-profile 的进程）。"""
    try:
        import subprocess
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


# ---------------------------------------------------------------- 导出
def _find_downloaded(out_dir: str, since: float) -> str | None:
    """在 out_dir / 用户 Downloads 中找最近生成的 xlsx（save_as 失败时的兜底）。"""
    TE = _export_tool()
    path = TE._newest_xlsx(out_dir, since)
    if path:
        return path
    for extra in (os.path.expanduser("~/Downloads"),):
        if os.path.isdir(extra):
            path = TE._newest_xlsx(extra, since)
            if path:
                return path
    return None


def export_xlsx(out_dir: str, login_wait: int = 300, timeout: int = 90) -> str:
    """打开查询页 → 等待数据表 → 点导出 → 等待下载 → 返回原始 xlsx 路径。

    浏览器生命周期：connect_over_cdp 只操作自己新开的标签页，结束时在 finally 里
    page.close()（不影响用户其它 Edge 窗口）；专用 Edge 进程由 run_export 负责关闭。
    """
    TE = _export_tool()
    TE._ensure_playwright()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(f"未找到 playwright：{exc}") from exc

    os.makedirs(out_dir, exist_ok=True)
    downloads: list = []
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP_URL)
        ctx = browser.contexts[0]
        page = ctx.new_page()  # 自己开新标签页，避免动用户已有标签
        try:
            def on_download(d) -> None:
                downloads.append(d)
                log(f"[下载] 浏览器触发下载：{d.suggested_filename}")

            page.on("download", on_download)
            ctx.on("page", lambda pg: pg.on("download", on_download))
            try:
                page.evaluate("() => { try { localStorage.removeItem('currentMode'); } catch (e) {} }")
            except Exception:
                pass

            url = query_url()
            deadline = time.time() + max(login_wait, timeout)
            table_ok = False
            while time.time() < deadline:
                log(f"[打开] {url}")
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=60000)
                except Exception as exc:
                    log(f"[提示] 打开页面失败：{type(exc).__name__}: {exc}")
                    continue
                if TE._page_has_table(page) or TE._wait_table(page, 10):
                    table_ok = True
                    break
                log("[等待] 数据表未出现：若窗口显示未登录，请登录；脚本会自动重试直到出现数据")
                time.sleep(4)
            if not table_ok:
                TE._dump_debug(page, "sz100-no-table")
                raise RuntimeError("页面未出现数据表（可能未登录/查询串不正确）")

            log("[数据] 数据表已加载")
            started = time.time()
            if not TE._click_export(page):
                TE._dump_debug(page, "sz100-no-export-button")
                raise RuntimeError("未找到“导出数据”按钮")
            TE._handle_export_popover(page)

            # 等待下载并落盘：save_as 失败时重试，仍失败则扫描下载目录兜底
            path: str | None = None
            wait_deadline = time.time() + 150
            while time.time() < wait_deadline:
                if downloads:
                    d = downloads[-1]
                    target = os.path.join(out_dir, d.suggested_filename)
                    for _attempt in range(10):
                        try:
                            d.save_as(target)
                            if os.path.exists(target) and os.path.getsize(target) > 0:
                                path = target
                                break
                        except Exception as exc:
                            log(f"[下载] 保存失败，重试：{type(exc).__name__}: {exc}")
                        time.sleep(1)
                    if path:
                        break
                time.sleep(1)
            if path is None:
                path = _find_downloaded(out_dir, started)
            if not path or not os.path.exists(path):
                TE._dump_debug(page, "sz100-no-download")
                raise RuntimeError("导出后没有找到下载的 xlsx 文件")
            log(f"[下载] 文件：{path}  ({os.path.getsize(path)} 字节)")
            return path
        finally:
            # attach 模式只关自己开的标签页，不关用户其它 Edge 窗口
            try:
                if not page.is_closed():
                    page.close()
                    log("[浏览器] 已关闭导出标签页")
            except Exception:
                pass


# ---------------------------------------------------------------- 后处理
def _header_index(header: list[str], *keywords: str) -> int | None:
    for kw in keywords:
        for idx, name in enumerate(header):
            if kw in name:
                return idx
    return None


def _to_float(value) -> float:
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return float("nan")


def _find_header_row(rows: list) -> int | None:
    """导出的 xlsx 第 1 行是列标题、第 2 行是日期标题行，数据从第 3 行开始。

    返回「含股票代码的列标题行」下标（通常 0）；找不到返回 None。
    """
    for idx in range(min(3, len(rows))):
        cells = [str(c) for c in (rows[idx] or []) if c is not None]
        if any("股票代码" in c for c in cells):
            return idx
    return None


def _is_data_row(row: list, code_idx: int) -> bool:
    """数据行判定：股票代码列为 6 位数字（数字部分 ≥6 位）。"""
    if code_idx >= len(row) or row[code_idx] is None:
        return False
    digits = "".join(ch for ch in str(row[code_idx]) if ch.isdigit())
    return len(digits) >= 6


def postprocess(src: str, dest: str) -> dict:
    """按股票代码升序 → 原子覆盖 dest；返回统计信息。

    保留前两行（列标题 + 日期标题行）原样；不删除任何股票（银行股也保留）；
    排序只作用于第 3 行起的数据区。
    """
    from openpyxl import Workbook, load_workbook

    wb = load_workbook(src)
    try:
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        sheet_title = ws.title
    finally:
        wb.close()
    if not rows:
        raise RuntimeError("下载的 xlsx 为空")
    header_idx = _find_header_row(rows)
    if header_idx is None:
        raise RuntimeError(f"前 3 行里找不到含「股票代码」的列标题行：{rows[:2]}")
    header = [str(c) if c is not None else "" for c in (rows[header_idx] or [])]
    head_rows = [list(r) for r in rows[: header_idx + 1]]
    code_idx = _header_index(header, "股票代码")
    name_idx = _header_index(header, "股票简称", "股票名称", "名称")
    mv_idx = _header_index(header, "流通市值")
    float_idx = _header_index(header, "流通股本")
    industry_idx = _header_index(header, "所属行业", "行业")
    if code_idx is None or name_idx is None or mv_idx is None:
        raise RuntimeError(f"表头缺少必要列（股票代码/名称/流通市值）：{header}")
    if float_idx is None:
        raise RuntimeError(f"表头缺少「流通股本」列（UPDATE_STOCK_CODES 需要）：{header}")

    data_start = header_idx + 1
    # 前两行都是标题行（第 1 行列标题、第 2 行日期行）：跳过所有非数据行（代码列不是 6 位数字的行）
    while data_start < len(rows) and not _is_data_row(rows[data_start], code_idx):
        data_start += 1
    head_rows = [list(r) for r in rows[:data_start]]
    data = [list(r) for r in rows[data_start:]
            if any(c is not None and str(c).strip() != "" for c in r) and _is_data_row(r, code_idx)]
    total_before = len(data)

    def code_key(row: list) -> tuple[int, str]:
        """按纯数字股票代码升序；非 6 位数字的放最后。"""
        raw = str(row[code_idx]).strip() if code_idx < len(row) and row[code_idx] is not None else ""
        digits = "".join(ch for ch in raw if ch.isdigit())
        if len(digits) >= 6:
            return (0, digits[-6:])
        return (1, raw)

    before_top5 = [(str(r[code_idx]), str(r[name_idx]), r[mv_idx]) for r in data[:5]]
    data.sort(key=code_key)
    after_top5 = [(str(r[code_idx]), str(r[name_idx]), r[mv_idx]) for r in data[:5]]

    out_wb = Workbook()
    out_ws = out_wb.active
    out_ws.title = sheet_title
    for row in head_rows:  # 前两行（列标题 + 日期标题行）原样保留
        out_ws.append(row)
    for row in data:       # 数据区从第 3 行开始（不删股票，按代码升序）
        out_ws.append(row)
    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    tmp = dest + ".tmp"
    out_wb.save(tmp)
    out_wb.close()
    try:
        os.replace(tmp, dest)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise

    return {
        "ok": True,
        "source": src,
        "dest": os.path.abspath(dest),
        "sheet": sheet_title,
        "columns": len(header),
        "total_before": total_before,
        "total": len(data),
        "before_top5": before_top5,
        "after_top5": after_top5,
        "mv_column": header[mv_idx],
        "float_column": header[float_idx],
    }


def run_export(dest: str = DEST_DEFAULT, keep_download: bool = False) -> dict:
    """完整流程：启动 Edge → 导出 → 后处理 → 覆盖 SZ100.xlsx；返回结果 dict（失败抛异常）。

    浏览器保证在 finally 中关闭：只关本工具自己启动的 .edge-profile Edge 与导出标签页。
    """
    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(TMP_ROOT, f"sz100_{stamp}")
    ok, note = ensure_browser()
    if not ok:
        raise RuntimeError(f"浏览器未就绪：{note}")
    launched = note == "已启动普通模式 Edge"
    log(f"[浏览器] {note}")
    try:
        src = export_xlsx(out_dir)
        ok2, detail = _validate_sz100(src)
        if not ok2:
            raise RuntimeError(f"下载文件校验失败：{detail}")
        log(f"[校验] 通过：{detail}")
        result = postprocess(src, dest)
        log(f"[后处理] 排序前前5：{result['before_top5']}")
        log(f"[后处理] 排序后前5：{result['after_top5']}")
        log(f"[完成] 已覆盖 {result['dest']}（{result['total']} 行数据 / {result['columns']} 列，前两行标题保留）")
        if not keep_download and os.path.exists(src):
            try:
                os.remove(src)
            except OSError:
                pass
        return result
    finally:
        if launched:
            log(f"[浏览器] {close_browser()}")
        else:
            log("[浏览器] 复用了已有调试端口，仅关闭导出标签页")


def _validate_sz100(path: str) -> tuple[bool, str]:
    from openpyxl import load_workbook

    try:
        wb = load_workbook(path)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        wb.close()
    except Exception as exc:
        return False, f"打不开 xlsx：{exc}"
    if not rows:
        return False, "xlsx 为空"
    header_idx = _find_header_row(rows)
    if header_idx is None:
        return False, f"前 3 行找不到含“股票代码”的列标题行：{rows[:2]}"
    header = [str(c or "") for c in (rows[header_idx] or [])]
    code_idx = _header_index(header, "股票代码")
    if code_idx is None:
        return False, f"表头缺少“股票代码”：{header[:8]}"
    data_start = header_idx + 1
    while data_start < len(rows) and not _is_data_row(rows[data_start], code_idx):
        data_start += 1
    codes = [str(r[code_idx]).strip() for r in rows[data_start:]
             if len(r) > code_idx and r[code_idx] is not None]
    codes = [c for c in codes if c]
    if not codes:
        return False, "没有股票代码数据行"
    if not all(c[:6].isdigit() for c in codes):
        return False, f"股票代码列存在非 6 位数字：{codes[:3]}"
    return True, f"{len(codes)} 行数据（前 {data_start} 行标题原样保留），{len(header)} 列，示例 {codes[:3]}"


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="导出通达信股票池 → AIData/INFO/SZ100.xlsx（保留前两行标题/不删股票/按代码升序）")
    parser.add_argument("--date", default=dt.date.today().isoformat(), help="仅用于日志（导出内容与日期无关）")
    parser.add_argument("--out", default="", help="下载目录（默认 .tools/tmp/sz100_<时间>）")
    parser.add_argument("--dest", default=DEST_DEFAULT, help="目标文件，默认 AIData/INFO/SZ100.xlsx")
    parser.add_argument("--login-wait", type=int, default=300, help="等待登录/数据表的秒数")
    parser.add_argument("--timeout", type=int, default=90, help="等待数据表的秒数")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不启动浏览器")
    parser.add_argument("--keep-download", action="store_true", help="保留下载的原始 xlsx")
    args = parser.parse_args(argv)

    log(f"[参数] 日期={args.date}，查询串={SZ100_MSG}")
    log(f"[参数] URL={query_url()}")
    log(f"[参数] 目标={os.path.abspath(args.dest)}")
    if args.dry_run:
        log("[dry-run] 将：启动/接管 Edge → 导出查询页 xlsx → 保留前两行标题（数据从第3行起）"
            " → 不删股票 → 按股票代码升序 → 原子覆盖目标文件；浏览器用完自动关闭")
        log("[dry-run] 未启动浏览器、未修改任何文件")
        return 0

    try:
        result = run_export(dest=os.path.abspath(args.dest), keep_download=args.keep_download)
    except Exception as exc:
        print(f"[失败] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3
    log(f"[汇总] SZ100 已更新：{result['total']} 行数据（银行股保留、按股票代码升序、"
        f"前两行标题保留，列数 {result['columns']}）→ {result['dest']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
