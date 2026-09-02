"""
策略看板本地服务（快捷命令后端）
=============================
用 Python 标准库 http.server 起一个本地 HTTP 服务，同时：
    - GET  /                     返回 StrategyDashboard.html（策略看板）
    - POST /api/cmd              执行侧边栏快捷命令（更新数据 / 更新同花顺板块）
       请求体: {"cmd": "UPDATE_DATA" | "UPDATE_THS", "strategy": "TPO_3"}
       返回体: {"ok": true, "output": "...", "running": false}

用法:
    python AICode/MarcoAPI/StrategyService.py           # 默认端口 8765
    python AICode/MarcoAPI/StrategyService.py --port 9000

启动后在浏览器打开 http://localhost:8765/ 即可使用。
"""

import argparse
import contextlib
import io
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, os.path.dirname(_root))

from AICode.MarcoAPI.StrategyUI import (
    CMD_UPDATE_DATA, CMD_UPDATE_THS,
    GENERATE_STRATEGY_UI, _list_strategies,
)
from AICode.MarcoAPI.Update.Update1D import UPDATE_ALL

HOST = "127.0.0.1"
PORT = 8765

# ---- 异步数据更新（独立进程，避免 QMT tq 后台线程限制） ----
_update_running = False
_update_done = False
_update_proc = None
_update_lock = threading.Lock()
_update_log_file = os.path.join(_root, "..", "AIData", "update.log")
_update_log_file = os.path.abspath(_update_log_file)


def _run_update_background():
    """启动 Update1D.py 独立进程执行数据更新，stdout/stderr 实时写入日志文件"""
    global _update_running, _update_done, _update_proc
    os.makedirs(os.path.dirname(_update_log_file), exist_ok=True)
    # 运行 Update1D.py 脚本（其 __main__ 调用 UPDATE_ALL 并 print 步骤日志）
    update_py = os.path.join("AICode", "MarcoAPI", "Update", "Update1D.py")
    with open(_update_log_file, "w", encoding="utf-8") as f:
        # 强制子进程以 UTF-8 输出，避免 Windows 默认 GBK 编码导致日志乱码
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        _update_proc = subprocess.Popen(
            [sys.executable, "-u", update_py],
            cwd=GIT_REPO_DIR,
            stdout=f,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env=env,
        )


def _wait_update_proc():
    """等待子进程结束，更新 done 状态"""
    global _update_running, _update_done, _update_proc
    try:
        if _update_proc:
            _update_proc.wait()
    finally:
        with _update_lock:
            _update_running = False
            _update_done = True


def _strip_carriage(log: str) -> str:
    """把进度条的 \\r 原地刷新序列压缩为单行进度：遇到裸 \\r 时删除上一个 \\n 之后的未定稿内容，
    只保留最后一帧。先归一 CRLF（行尾的 \\r\\n 来自 close()/print 的 \\n），避免行尾 \\r 误删上一行。
    这样写入文件的进度序列在网页 <pre> 里可被渲染成单行进度。"""
    log = log.replace("\r\n", "\n")  # CRLF 归一为 LF（行结束，非覆盖信号）
    out: list[str] = []
    for ch in log:
        if ch == "\r":
            s = "".join(out)
            idx = s.rfind("\n")
            out = [s[: idx + 1]] if idx >= 0 else []
        else:
            out.append(ch)
    return "".join(out)


def _simplify_update_log(log: str) -> str:
    """精简更新日志：只保留失败行（!!!!!）与最后一个进度条行（当前步骤进度），
    使前端进度条可单行实时刷新。"""
    log = _strip_carriage(log)
    fail_lines: list[str] = []
    last_progress = ""
    for ln in log.split("\n"):
        s = ln.strip()
        if not s:
            continue
        if s.startswith("!!!!!"):
            fail_lines.append(ln)
        else:
            last_progress = ln
    lines = fail_lines[:]
    if last_progress:
        lines.append(last_progress)
    return "\n".join(lines)


def _update_status() -> dict:
    global _update_running, _update_done
    # 读取日志文件（二进制读，保留 \r，避免文本模式 universal-newline 把 \r 转成 \n）
    log = ""
    try:
        if os.path.isfile(_update_log_file):
            with open(_update_log_file, "rb") as _f:
                log = _f.read().decode("utf-8", errors="replace")
    except Exception:
        pass
    log = _simplify_update_log(log)
    with _update_lock:
        return {"ok": True, "running": _update_running, "done": _update_done, "log": log}

# git 工作目录 = 项目根（StrategyService.py 位于 AICode/MarcoAPI/，其上两级为项目根）
GIT_REPO_DIR = os.path.dirname(_root)  # 项目根（_root=AICode）
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

# 生成策略看板 HTML 文本（用于 GET / 返回）
def _dashboard_html() -> str:
    out = GENERATE_STRATEGY_UI(open_browser=False)
    if not out:
        return "<html><body><h1>无策略数据</h1></body></html>"
    with open(out, "r", encoding="utf-8") as f:
        return f.read()


class StrategyHandler(BaseHTTPRequestHandler):
    """策略看板 HTTP 请求处理器"""

    def log_message(self, fmt, *args):  # 精简控制台日志
        print("[%s] %s" % (self.address_string(), fmt % args))

    # ---- CORS ----
    def _send_headers(self, status=200, ctype="application/json; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _send_json(self, data: dict, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self._send_headers(status)
        self.wfile.write(body)

    # ---- 预检 ----
    def do_OPTIONS(self):
        self._send_headers(204)

    # ---- 页面 ----
    def do_GET(self):
        if self.path in ("/", "/StrategyDashboard.html", "/index.html"):
            html = _dashboard_html().encode("utf-8")
            self._send_headers(200, "text/html; charset=utf-8")
            self.wfile.write(html)
        elif self.path == "/api/update_log":
            self._send_json(_update_status())
        else:
            self._send_json({"ok": False, "error": f"未找到 {self.path}"}, 404)

    # ---- 命令 ----
    def do_POST(self):
        if self.path != "/api/cmd":
            self._send_json({"ok": False, "error": f"未找到 {self.path}"}, 404)
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception as exc:
            self._send_json({"ok": False, "error": f"请求体解析失败: {exc}"}, 400)
            return

        cmd = payload.get("cmd", "")
        strategy = payload.get("strategy") or ""

        if cmd == "UPDATE_DATA":
            global _update_running, _update_done, _update_proc
            if _update_running:
                self._send_json({"ok": True, "output": "数据正在更新中，请稍候...", "running": True})
                return
            # 重置状态并启动独立更新进程（子进程主线程跑 UPDATE_ALL，避免 QMT tq 线程限制）
            with _update_lock:
                _update_running = True
                _update_done = False
                _update_proc = None
            _run_update_background()
            threading.Thread(target=_wait_update_proc, daemon=True).start()
            self._send_json({"ok": True, "output": "开始更新数据，进度请查看下方日志...", "running": True})
            return

        if cmd == "UPDATE_THS":
            if not strategy:
                self._send_json({"ok": False, "error": "未指定策略"}, 400)
                return
            try:
                output = CMD_UPDATE_THS(strategy)
                self._send_json({"ok": True, "output": output, "running": False})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc), "running": False}, 500)
            return

        if cmd == "GIT_SYNC":
            try:
                output = GIT_SYNC()
                self._send_json({"ok": True, "output": output, "running": False})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc), "running": False}, 500)
            return

        # 未知命令：返回可用命令列表
        self._send_json({
            "ok": False,
            "error": f"未知命令: {cmd}",
            "available": ["UPDATE_DATA", "UPDATE_THS", "GIT_SYNC"],
            "strategies": _list_strategies(),
        }, 400)


def main():
    parser = argparse.ArgumentParser(description="策略看板本地服务")
    parser.add_argument("--host", default=HOST, help="监听地址，默认 127.0.0.1")
    parser.add_argument("--port", type=int, default=PORT, help="监听端口，默认 8765")
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), StrategyHandler)
    print(f"策略看板服务已启动: http://{args.host}:{args.port}/")
    print("按 Ctrl+C 停止")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")
        server.shutdown()


if __name__ == "__main__":
    main()
