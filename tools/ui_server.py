#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""新 UI 服务（dashboard_server.py）重启工具，供 Run.py 与 tools/daily_update.py 共用。

功能：
  - 找出正在运行的 dashboard_server.py 进程并结束（wmic/CIM 双保险，只匹配 dashboard_server）；
  - 后台重启 dashboard_server.py（--port 8765），等待 /api/meta 返回 200；
  - 返回 {"ok": bool, "pid": int|None, "oldPids": [...], "note"/"error": str}。

用法：
    python tools/ui_server.py                # 重启 8765
    python tools/ui_server.py --port 8765
    python tools/ui_server.py --dry-run      # 只打印计划
    python tools/ui_server.py --stop         # 只停止，不重启

退出码：0 成功；1 失败。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DASHBOARD_SCRIPT = os.path.join(ROOT, "tools", "dashboard_server.py")
DEFAULT_PORT = 8765
WAIT_READY_S = 40


def log(text: str) -> None:
    print(text, flush=True)


def find_dashboard_pids() -> list[int]:
    """找出正在运行的 dashboard_server.py 进程 PID（wmic/CIM 双保险）。"""
    pids: list[int] = []
    try:
        out = subprocess.run(
            ["wmic", "process", "where", "name='python.exe'", "get", "processid,commandline"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
        ).stdout or ""
        for line in out.splitlines():
            if "dashboard_server" in line:
                for tok in reversed(line.replace("\r", " ").split()):
                    if tok.isdigit():
                        pids.append(int(tok))
                        break
    except Exception:
        pass
    if not pids:
        try:
            ps = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                 "Where-Object { $_.CommandLine -like '*dashboard_server*' } | "
                 "ForEach-Object { $_.ProcessId }"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
            ).stdout or ""
            pids = [int(x) for x in ps.split() if x.strip().isdigit()]
        except Exception:
            pass
    return sorted(set(pids))


def stop_dashboard() -> list[int]:
    """结束所有 dashboard_server 进程，返回被停止的 PID 列表。"""
    pids = find_dashboard_pids()
    for pid in pids:
        try:
            subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                           capture_output=True, timeout=20)
        except Exception:
            pass
    return pids


def _meta_ready(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/meta", timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


def restart_dashboard(port: int = DEFAULT_PORT, dry_run: bool = False,
                      wait_ready_s: int = WAIT_READY_S) -> dict:
    """重启新 UI 服务：停旧进程 → 后台起 dashboard_server → 等 /api/meta 200。

    返回 {"ok", "pid", "oldPids", "note"} 或 {"ok": False, "error", ...}。
    """
    if dry_run:
        return {"ok": True, "pid": None, "oldPids": [],
                "note": f"将重启新 UI 服务（http://127.0.0.1:{port}）"}
    if not os.path.exists(DASHBOARD_SCRIPT):
        return {"ok": False, "pid": None, "oldPids": [],
                "error": f"找不到 {DASHBOARD_SCRIPT}"}

    old_pids = stop_dashboard()
    log(f"[UI] 已停止旧服务进程 {old_pids or '（未发现）'}")
    time.sleep(1.5)
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
        proc = subprocess.Popen(
            [sys.executable, DASHBOARD_SCRIPT, "--port", str(port)], cwd=ROOT,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
            creationflags=flags, close_fds=True,
        )
    except Exception as exc:
        return {"ok": False, "pid": None, "oldPids": old_pids,
                "error": f"启动失败：{type(exc).__name__}: {exc}"}

    deadline = time.time() + wait_ready_s
    while time.time() < deadline:
        if _meta_ready(port):
            log(f"[UI] 新 UI 服务已就绪（PID {proc.pid}）")
            return {"ok": True, "pid": proc.pid, "oldPids": old_pids,
                    "note": "新 UI 服务已重启并就绪"}
        time.sleep(1.0)
    return {"ok": False, "pid": proc.pid, "oldPids": old_pids,
            "error": f"新 UI 服务启动后 {wait_ready_s} 秒内未就绪，请检查 logs/dashboard_server.log"}


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="重启新 UI 服务（dashboard_server）")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="端口，默认 8765")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不执行")
    parser.add_argument("--stop", action="store_true", help="只停止当前服务，不重启")
    args = parser.parse_args(argv)

    if args.dry_run:
        print(f"[dry-run] 将重启新 UI 服务（http://127.0.0.1:{args.port}）")
        return 0
    if args.stop:
        pids = stop_dashboard()
        print(f"[UI] 已停止旧服务进程 {pids or '（未发现）'}")
        return 0
    result = restart_dashboard(port=args.port)
    if result.get("ok"):
        print(f"[完成] {result.get('note')}（PID {result.get('pid')}）")
        return 0
    print(f"[失败] {result.get('error')}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
