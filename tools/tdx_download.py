#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""自动执行通达信「盘后数据下载」（替代手工点击 选项→盘后数据下载）。

原理（已实测）：
  1. 客户端内部功能串 http://www.treeid/ID_DOWNLOAD 可通过 tq.exec_to_tdx() 打开“盘后数据下载”对话框；
  2. 对话框是标准 Win32 对话框（class #32770），内部按钮/复选框/日期控件都是真实子控件，
     可通过 EnumChildWindows + GetDlgCtrlID 定位、BM_CLICK/BM_GETCHECK/DTM_SETSYSTEMTIME 操作；
  3. 页签是自绘的，用相对对话框的坐标点击切换。

用法：
    python tools/tdx_download.py --date 2026-11-03 --periods 1d,5m
    python tools/tdx_download.py --dry-run              # 只打开对话框打印控件状态，不下载
    python tools/tdx_download.py --periods 5m --timeout 1800
    python tools/tdx_download.py --force                # 本地已最新也重下

退出码：0 成功/本地已最新；1 参数/环境错误；2 打开对话框失败；3 下载失败或超时。
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import datetime as dt
import os
import struct
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TDX_PLUGIN = os.environ.get("TDX_PLUGIN_PATH", r"C:\new_tdx64\PYPlugins\user")
TDX_ROOT = os.path.dirname(os.path.dirname(TDX_PLUGIN))
VIPDOC = os.path.join(TDX_ROOT, "vipdoc")
SAMPLES = ("600000.SH", "000001.SZ")

user32 = ctypes.windll.user32

# 64 位下必须显式声明指针参数，否则 SendMessageW 的 lParam（SYSTEMTIME 指针）会被截断成 32 位
user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
user32.SendMessageW.restype = ctypes.c_ssize_t
user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
user32.PostMessageW.restype = ctypes.c_ssize_t
user32.GetDlgItem.argtypes = [ctypes.c_void_p, ctypes.c_int]
user32.GetDlgItem.restype = ctypes.c_void_p
user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(wt.RECT)]
user32.GetWindowRect.restype = wt.BOOL
user32.GetWindowTextW.argtypes = [ctypes.c_void_p, wt.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetClassNameW.argtypes = [ctypes.c_void_p, wt.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.GetDlgCtrlID.argtypes = [ctypes.c_void_p]
user32.GetDlgCtrlID.restype = ctypes.c_int
user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
user32.SetForegroundWindow.restype = wt.BOOL
user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
user32.IsWindowVisible.restype = wt.BOOL
WM_CLOSE = 0x0010
BM_CLICK = 0x00F5
BM_GETCHECK = 0x00F0
DTM_SETSYSTEMTIME = 0x1002
GDT_VALID = 0
DLG_TITLE = "盘后数据下载"
TAB_OFFSETS = {"1d": (50, 35), "5m": (140, 35)}


class SYSTEMTIME(ctypes.Structure):
    _fields_ = [("wYear", wt.WORD), ("wMonth", wt.WORD), ("wDayOfWeek", wt.WORD),
                ("wDay", wt.WORD), ("wHour", wt.WORD), ("wMinute", wt.WORD),
                ("wSecond", wt.WORD), ("wMilliseconds", wt.WORD)]


def log(text: str) -> None:
    print(text, flush=True)


def enum_windows(pid: int) -> list[dict]:
    out: list[dict] = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def _cb(hwnd, _lp):
        proc_id = wt.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(proc_id))
        if proc_id.value == pid and user32.IsWindowVisible(hwnd):
            out.append({
                "hwnd": int(hwnd),
                "title": _wtext(hwnd),
                "class": _wclass(hwnd),
            })
        return True

    user32.EnumWindows(_cb, 0)
    return out


def visible_children(parent: int) -> list[dict]:
    out: list[dict] = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def _cb(hwnd, _lp):
        if user32.IsWindowVisible(hwnd):
            r = wt.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            out.append({
                "hwnd": int(hwnd),
                "text": _wtext(hwnd),
                "class": _wclass(hwnd),
                "id": int(user32.GetDlgCtrlID(hwnd)),
                "x": r.left,
                "y": r.top,
            })
        return True

    user32.EnumChildWindows(wt.HWND(parent), _cb, 0)
    return out


def _wtext(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(wt.HWND(hwnd), buf, 512)
    return buf.value


def _wclass(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(128)
    user32.GetClassNameW(wt.HWND(hwnd), buf, 128)
    return buf.value


def find_child(parent: int, *, text=None, text_prefix=None, cls=None, index: int = 0):
    matches = []
    for c in visible_children(parent):
        if text is not None and c["text"] != text:
            continue
        if text_prefix is not None and not c["text"].startswith(text_prefix):
            continue
        if cls is not None and c["class"] != cls:
            continue
        matches.append(c)
    if len(matches) <= index:
        return None
    return matches[index]


def is_checked(hwnd: int) -> bool:
    return bool(hwnd) and int(user32.SendMessageW(wt.HWND(hwnd), BM_GETCHECK, 0, 0)) == 1


def click_hwnd(hwnd: int) -> None:
    user32.SendMessageW(wt.HWND(hwnd), BM_CLICK, 0, 0)
    time.sleep(0.2)


def set_date(hwnd: int, day: dt.date) -> None:
    st = SYSTEMTIME(day.year, day.month, 0, day.day, 0, 0, 0, 0)
    user32.SendMessageW(wt.HWND(hwnd), DTM_SETSYSTEMTIME, GDT_VALID, ctypes.addressof(st))


def rect(hwnd: int) -> tuple[int, int, int, int]:
    r = wt.RECT()
    user32.GetWindowRect(wt.HWND(hwnd), ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def click_at(x: int, y: int) -> None:
    user32.SetCursorPos(x, y)
    time.sleep(0.1)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.05)
    user32.mouse_event(0x0004, 0, 0, 0, 0)


def click_tab(dialog: int, period: str) -> None:
    left, top, _r, _b = rect(dialog)
    dx, dy = TAB_OFFSETS[period]
    user32.SetForegroundWindow(wt.HWND(dialog))
    time.sleep(0.2)
    click_at(left + dx, top + dy)
    time.sleep(0.5)


def find_tdx_pid() -> int | None:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq TdxW.exe", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True, encoding="gbk", errors="replace")
    for line in (out.stdout or "").splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) >= 2 and parts[0].lower() == "tdxw.exe":
            try:
                return int(parts[1])
            except ValueError:
                continue
    return None


def find_dialog(pid: int, timeout: float = 15.0) -> int | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        for win in enum_windows(pid):
            if win["title"] == DLG_TITLE and win["class"] == "#32770":
                return win["hwnd"]
        time.sleep(0.3)
    return None


def close_extra_popups(pid: int) -> None:
    keywords = ("广告", "活动", "推广", "公告", "提示", "消息", "升级")
    for win in enum_windows(pid):
        if win["class"] != "#32770" or win["title"] == DLG_TITLE:
            continue
        if any(k in win["title"] for k in keywords):
            log(f"  [弹窗] 关闭：{win['title']}")
            user32.PostMessageW(wt.HWND(win["hwnd"]), WM_CLOSE, 0, 0)


def _local_path(code: str, period: str) -> str:
    market = "sh" if code.upper().endswith(".SH") else "sz"
    number = code.split(".")[0]
    if period == "1d":
        return os.path.join(VIPDOC, market, "lday", f"{market}{number}.day")
    return os.path.join(VIPDOC, market, "fzline", f"{market}{number}.lc5")


def last_date(code: str, period: str) -> str | None:
    path = _local_path(code, period)
    if not os.path.exists(path) or os.path.getsize(path) < 32:
        return None
    with open(path, "rb") as fh:
        fh.seek(-32, os.SEEK_END)
        raw = fh.read(32)
    if period == "1d":
        return str(struct.unpack("<I", raw[:4])[0])
    date_raw, _ = struct.unpack("<HH", raw[:4])
    year = date_raw // 2048 + 2004
    rest = date_raw % 2048
    return f"{year:04d}{rest // 100:02d}{rest % 100:02d}"


def verify(day: dt.date, periods: list[str]) -> tuple[bool, list[str]]:
    problems: list[str] = []
    key = day.strftime("%Y%m%d")
    for code in SAMPLES:
        for period in periods:
            got = last_date(code, period)
            if got is None:
                problems.append(f"{code} {period}: 无本地文件")
            elif got != key:
                problems.append(f"{code} {period}: 最新 {got} != {key}")
    return not problems, problems


def open_dialog() -> tuple[int | None, int | None]:
    sys.path.insert(0, TDX_PLUGIN)
    from tqcenter import tq

    tq.initialize(os.path.abspath(__file__))
    res = tq.exec_to_tdx(url="http://www.treeid/ID_DOWNLOAD")
    log(f"[打开] exec_to_tdx -> {res}")
    pid = find_tdx_pid()
    if pid is None:
        log("[错误] 找不到 TdxW.exe 进程")
        return None, None
    dialog = find_dialog(pid)
    if dialog is None:
        log("[错误] 未等到“盘后数据下载”对话框")
        return None, pid
    log(f"[打开] 对话框已就绪（{dialog}）")
    return dialog, pid


def _checkbox(dialog: int, text: str):
    return find_child(dialog, text=text)


def _all_a_share(dialog: int):
    return find_child(dialog, text_prefix="下载所有A股类品种")


def _dates(dialog: int) -> list[dict]:
    return [c for c in visible_children(dialog) if c["class"] == "SysDateTimePick32"]


def _progress(dialog: int) -> tuple[int, int]:
    pb = find_child(dialog, cls="msctls_progress32")
    if not pb:
        return -1, -1
    pos = int(user32.SendMessageW(wt.HWND(pb["hwnd"]), 0x0408, 0, 0))          # PBM_GETPOS
    hi = int(user32.SendMessageW(wt.HWND(pb["hwnd"]), 0x0407, 1, 0)) >> 16    # PBM_GETRANGE max
    return pos, hi


def run_period(dialog: int, period: str, day: dt.date, timeout: float, pid: int) -> bool:
    label = "日线" if period == "1d" else "5分钟线"
    click_tab(dialog, period)
    log(f"[{label}] 页签已切换")

    dates = sorted(_dates(dialog), key=lambda c: c["x"])
    if len(dates) >= 2:
        set_date(dates[0]["hwnd"], day)
        set_date(dates[-1]["hwnd"], day)
        time.sleep(0.3)

    target = _checkbox(dialog, "日线和实时行情数据") if period == "1d" else _checkbox(dialog, "5分钟线数据")
    if target:
        if not is_checked(target["hwnd"]):
            click_hwnd(target["hwnd"])
        log(f"[{label}] 数据项：{'已勾选' if is_checked(target['hwnd']) else '勾选失败'}")

    all_btn = _all_a_share(dialog)
    if all_btn:
        if not is_checked(all_btn["hwnd"]):
            click_hwnd(all_btn["hwnd"])
        log(f"[{label}] 范围：{'全部A股已勾选' if is_checked(all_btn['hwnd']) else '全部A股勾选失败'}")

    start_btn = find_child(dialog, text="开始下载")
    if not start_btn:
        log(f"[{label}] [错误] 未找到“开始下载”按钮")
        return False

    started = time.time()
    before = {}
    for code in SAMPLES:
        path = _local_path(code, period)
        before[path] = os.path.getmtime(path) if os.path.exists(path) else 0

    click_hwnd(start_btn["hwnd"])
    log(f"[{label}] 已点击“开始下载”，等待下载完成（超时 {int(timeout)}s）...")

    deadline = started + timeout
    last_report = 0.0
    while time.time() < deadline:
        texts = " ".join(c["text"] for c in visible_children(dialog))
        if any(k in texts for k in ("下载失败", "行情断开", "请先连接")):
            log(f"[{label}] [失败] 客户端提示：{texts[:200]}")
            return False
        if any(k in texts for k in ("下载完毕", "下载完成")):
            log(f"[{label}] [完成] 客户端提示下载完毕")
            return True
        rewritten = [p for p, mt in before.items()
                     if os.path.exists(p) and os.path.getmtime(p) > mt + 0.5]
        if rewritten:
            log(f"[{label}] [完成] 本地文件已重写：{os.path.basename(rewritten[0])} 等")
            return True
        pos, hi = _progress(dialog)
        if hi > 0 and pos >= hi:
            log(f"[{label}] [完成] 进度条到达 100%")
            return True
        close_extra_popups(pid)
        if time.time() - last_report > 15:
            last_report = time.time()
            log(f"[{label}] 下载中... 进度 {pos}/{hi if hi > 0 else '?'}，已等 {int(time.time() - started)}s")
        time.sleep(1.0)
    log(f"[{label}] [超时] {int(timeout)}s 内未检测到完成")
    return False


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="自动执行通达信盘后数据下载")
    parser.add_argument("--date", default=dt.date.today().isoformat(), help="目标交易日 YYYY-MM-DD")
    parser.add_argument("--periods", default="1d,5m", help="周期，逗号分隔：1d / 5m")
    parser.add_argument("--timeout", type=float, default=1800, help="每个周期等待完成的秒数")
    parser.add_argument("--dry-run", action="store_true", help="只打开对话框打印控件状态")
    parser.add_argument("--force", action="store_true", help="本地已最新也重下")
    args = parser.parse_args(argv)

    try:
        day = dt.date.fromisoformat(args.date)
    except ValueError:
        log(f"[错误] 日期格式应为 YYYY-MM-DD：{args.date}")
        return 1
    periods = [p.strip() for p in args.periods.split(",") if p.strip()]
    for p in periods:
        if p not in ("1d", "5m"):
            log(f"[错误] 不支持的周期：{p}")
            return 1

    pid = find_tdx_pid()
    if pid is None:
        log("[错误] 通达信客户端未运行（TdxW.exe）")
        return 1
    ok, problems = verify(day, periods)
    if ok and not args.force and not args.dry_run:
        log(f"[跳过] 本地数据已是 {day.isoformat()}（样本校验通过）")
        return 0
    log(f"[校验] 下载前：{'最新' if ok else '; '.join(problems)}")

    dialog, pid = open_dialog()
    if dialog is None:
        return 2
    results: list[bool] = []
    try:
        if args.dry_run:
            for period in periods:
                click_tab(dialog, period)
                dates = sorted(_dates(dialog), key=lambda c: c["x"])
                items = []
                for c in visible_children(dialog):
                    if c["class"] == "Button" and c["text"]:
                        items.append(f"{c['text']}={is_checked(c['hwnd'])}")
                log(f"[预览] {period} 页控件：{'; '.join(items[:8])}")
                if dates:
                    log(f"[预览] 日期：{_wtext(dates[0]['hwnd'])} ~ {_wtext(dates[-1]['hwnd'])}")
            log("[预览] dry-run 结束（未下载）")
            return 0

        for period in periods:
            results.append(run_period(dialog, period, day, args.timeout, pid))
    finally:
        try:
            user32.SetForegroundWindow(wt.HWND(dialog))
            time.sleep(0.2)
            close_btn = find_child(dialog, text="关闭")
            if close_btn:
                click_hwnd(close_btn["hwnd"])
            time.sleep(0.5)
            if find_dialog(pid, timeout=1.0) is not None:
                user32.PostMessageW(wt.HWND(dialog), WM_CLOSE, 0, 0)
        except Exception:
            pass
        try:
            close_extra_popups(pid)
        except Exception:
            pass

    ok_after, problems_after = verify(day, periods)
    log(f"[校验] 下载后：{'本地已更新到 ' + day.isoformat() if ok_after else '仍未更新：' + '; '.join(problems_after)}")
    if all(results) and ok_after:
        log("[完成] 通达信盘后数据下载成功")
        return 0
    log("[失败] 通达信盘后数据下载未成功")
    return 3


if __name__ == "__main__":
    sys.exit(main())
