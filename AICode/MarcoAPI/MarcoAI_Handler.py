# -*- coding: utf-8 -*-
"""
MarcoAI 自定义协议命令处理器 (marcoai://)
========================================
当网页通过 `location.href = "marcoai://run?cmd=UPDATE_THS&strategy=TPO_3"` 触发时，
Windows 会唤起本程序，解析 URL 中的参数并执行对应的 Python 命令，然后用消息框显示结果。

用法（注册协议后）:
    marcoai://run?cmd=UPDATE_DATA
    marcoai://run?cmd=UPDATE_THS&strategy=TPO_3
    marcoai://run?cmd=GIT_SYNC

本程序不依赖本地 HTTP 服务，因此网页直接双击打开（file://）也能触发命令。
"""

import os
import re
import sys
import urllib.parse
import subprocess

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# git 工作目录 = 项目根（MarcoAI_Handler.py 位于 AICode/MarcoAPI/，往上三级为项目根）
GIT_REPO_DIR = _ROOT
GIT_COMMIT_MSG = "Updated"


def GIT_SYNC() -> str:
    """git 同步：git add . -> git commit -m "Updated" -> git push"""
    steps = [
        ("git add .", ["git", "add", "."]),
        (f'git commit -m "{GIT_COMMIT_MSG}"', ["git", "commit", "-m", GIT_COMMIT_MSG]),
        ("git push", ["git", "push"]),
    ]
    logs = []
    for label, cmd in steps:
        logs.append(f"$ {label}")
        try:
            r = subprocess.run(cmd, cwd=GIT_REPO_DIR, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=120)
        except subprocess.TimeoutExpired:
            logs.append("  [超时]")
            return "\n".join(logs)
        out = (r.stdout or "").strip()
        err = (r.stderr or "").strip()
        if out:
            logs.append(out)
        if err:
            logs.append(err)
        if r.returncode != 0:
            logs.append(f"  [失败，返回码 {r.returncode}]")
            return "\n".join(logs)
    logs.append("git 同步完成")
    return "\n".join(logs)


# 命令 -> 可执行函数映射（延迟导入，避免未使用时报错）
def _run_cmd(cmd: str, strategy: str, step: str = "") -> str:
    if cmd == "UPDATE_DATA":
        from AICode.MarcoAPI.StrategyUI import CMD_UPDATE_DATA
        return CMD_UPDATE_DATA()
    if cmd == "UPDATE_THS":
        if not strategy:
            return "未指定策略"
        from AICode.MarcoAPI.StrategyUI import CMD_UPDATE_THS
        return CMD_UPDATE_THS(strategy)
    if cmd == "GIT_SYNC":
        return GIT_SYNC()
    if cmd == "RUN_STEP":
        if not step:
            return "未指定 step"
        from AICode.MarcoAPI.StrategyUI import CMD_RUN_STEP
        return CMD_RUN_STEP(step)
    return f"未知命令: {cmd}"


def _show_result(title: str, text: str):
    """用 tkinter 消息框显示命令执行结果"""
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        messagebox.showinfo(title, text)
        root.destroy()
    except Exception:
        # 无 GUI 环境下退化为打印
        print(text)


def main(argv):
    """argv[1] 是传入的完整 URL，如 marcoai://run?cmd=UPDATE_THS&strategy=TPO_3"""
    url = argv[1] if len(argv) > 1 else "marcoai://run?cmd=?"
    parsed = urllib.parse.urlparse(url)
    params = dict(urllib.parse.parse_qsl(parsed.query))
    cmd = params.get("cmd", "")
    strategy = params.get("strategy", "")
    step = params.get("step", "")

    try:
        output = _run_cmd(cmd, strategy, step)
        text = f"命令: {cmd}\n策略: {strategy or '-'}\n\n{output}"
    except Exception as exc:
        text = f"命令: {cmd}\n策略: {strategy or '-'}\n\n执行失败: {exc}"

    # 追加到运行日志
    log_dir = os.path.join(_ROOT, "AIData", "run.log")
    try:
        with open(log_dir, "a", encoding="utf-8") as f:
            f.write(f"[{cmd}] {strategy or '-'}: {text}\n")
    except Exception:
        pass

    _show_result("MarcoAI 命令结果", text)


if __name__ == "__main__":
    main(sys.argv)
