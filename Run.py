"""
Run.py —— 主交互菜单

运行：
    cd e:/MarcoAI
    python Run.py

功能：
    1. 更新数据   —— 运行完整数据更新管线（交易日历/股票代码/日线/涨停/策略/目标池）
    2. 更新5M数据 —— 下载 5 分钟级原始行情（2026 起，需通达信联网）
    3. 显示 UI    —— 生成策略看板并在浏览器中打开
    4. QMT 自动交易 —— 买入 / 卖出监控 / 常驻 watch
    5. 上传 Gitee  —— 提交改动并推送到 Gitee 仓库（remote: origin）
    6. 上传 GitHub —— 提交改动并推送到 GitHub 仓库（remote: github）
    7. 更新同花顺 —— 选策略后写入同花顺板块（自动关闭/重启同花顺生效）
    0. 退出
执行完任一项后自动回到主菜单。
"""

import datetime
import os
import subprocess
import sys

# 项目根（Run.py 所在目录）加入 sys.path，保证 AICode.* 可被导入
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# AICode 子目录加入 sys.path，保证 AITrading 裸包（from AITrading import ...）可被导入
_AICODE = os.path.join(_ROOT, "AICode")
if _AICODE not in sys.path:
    sys.path.insert(0, _AICODE)

# 强制 UTF-8 输出，避免 Windows 控制台中文乱码
try:
    getattr(sys.stdout, "reconfigure", lambda *a, **k: None)(encoding="utf-8")
    getattr(sys.stderr, "reconfigure", lambda *a, **k: None)(encoding="utf-8")
except Exception:
    pass

from AICode.MarcoAPI.Update.Update1D import UPDATE_ALL
from AICode.MarcoAPI.Update.SZ2005M import UPDATE_5M_ORIGIN
from AICode.MarcoAPI.Update.Path import PATH_AIDATA
from AICode.MarcoAPI.StrategyUI import GENERATE_STRATEGY_UI, CMD_UPDATE_THS, _list_strategies
from AICode.AITrading.Structure.callbacks import watch as qmt_watch
from AICode.AITrading import commands as CMD


# 终端颜色（非 TTY 环境自动降级为空，避免乱码）
_USE_COLOR = sys.stdout.isatty()
C = "\033[96m" if _USE_COLOR else ""   # cyan
G = "\033[92m" if _USE_COLOR else ""   # green
Y = "\033[93m" if _USE_COLOR else ""   # yellow
B = "\033[1m"  if _USE_COLOR else ""   # bold
R = "\033[0m"  if _USE_COLOR else ""   # reset


def _do_update():
    UPDATE_ALL()


def _safe_rmtree(path: str):
    """逐文件删除目录（规避实盘机批量删除保护），递归处理子目录。"""
    import os
    if not os.path.isdir(path):
        return
    for name in os.listdir(path):
        p = os.path.join(path, name)
        try:
            if os.path.isdir(p):
                _safe_rmtree(p)
                os.rmdir(p)
            else:
                os.remove(p)
        except OSError:
            pass
    try:
        os.rmdir(path)
    except OSError:
        pass


def _cleanup_5m_old_dirs():
    """删除 5M 更新时 _rotate_dir 留下的 5M.old_* 残留目录（单文件删除，规避批量删除保护）。"""
    import os
    aidata = PATH_AIDATA()
    removed = 0
    for name in os.listdir(aidata):
        if name.startswith("5M") and ".old_" in name:
            p = os.path.join(aidata, name)
            if os.path.isdir(p):
                _safe_rmtree(p)
                removed += 1
                print(f"    已清理残留目录: {name}")
    if removed == 0:
        print("    无 5M 残留目录")
    return removed


def _do_update_5m():
    print(f"  {C}开始更新 5M 数据（2026 起，需通达信联网）...{R}")
    try:
        # 抑制内部详细输出，仅打印摘要
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            summary = UPDATE_5M_ORIGIN()
        if summary:
            print(f"  {summary}")
    except BaseException as exc:
        print(f"!!!!! UPDATE_5M FAILED: {type(exc).__name__}: {exc}")
    # 清理 _rotate_dir 留下的 5M.old_* 残留目录
    try:
        _cleanup_5m_old_dirs()
    except BaseException as exc:
        print(f"!!!!! CLEANUP 5M RESIDUAL FAILED: {type(exc).__name__}: {exc}")
    print("5M DATA UPDATE COMPLETED")


def _do_ui():
    GENERATE_STRATEGY_UI()


def _do_qmt():
    """启动 QMT 自动交易（常驻 watch：按时间窗自动触发买卖）。Ctrl+C 退出。"""
    print(f"  {Y}即将启动 QMT 自动交易（常驻），按 Ctrl+C 退出。{R}")
    # 脚本启动时（无论盘前还是盘中）预筛当日买入候选：全市场日线预热、买入池读取、
    # T-4/T-3/T-2 预筛等重型 I/O 在此一次性完成，尾盘 decide_buy 只做 T-1 实时快判。
    try:
        CMD.prepare_buy_candidates()
    except Exception as e:
        print(f"  {Y}[警告] 买入候选预筛失败，尾盘将降级为全量判定：{e}{R}")
    qmt_watch()


def _git(*args, capture=True):
    """在项目根执行 git 命令，返回 (返回码, 输出)。

    capture=True  用于查询类命令（status/remote/branch），捕获输出供程序判断；
    capture=False 用于 commit/push，输出直接打到终端，便于看到进度与凭据提示。
    """
    try:
        p = subprocess.run(
            ["git", *args],
            cwd=_ROOT,
            capture_output=capture,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        return 127, "未找到 git 命令，请先安装 Git 并将其加入 PATH。"
    if capture:
        return p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()
    return p.returncode, ""


def _current_branch():
    """取当前分支名；非 git 仓库时返回 None。"""
    code, out = _git("rev-parse", "--abbrev-ref", "HEAD")
    return out if code == 0 else None


def _git_push(remote):
    """提交改动并推送到指定 remote（remote 名称：gitee / github）。

    流程：确认仓库与 remote → 有改动则 add+commit（说明可自定义，回车用默认时间戳）
          → push 到 remote 当前分支（上游未设置时自动带 -u 重试）。
    """
    branch = _current_branch()
    if branch is None:
        print(f"  {Y}当前目录不是 git 仓库（或未初始化），无法上传。{R}")
        return

    code, url = _git("remote", "get-url", remote)
    if code != 0:
        print(f"  {Y}未配置 remote「{remote}」，请先执行："
              f"git remote add {remote} <仓库地址>{R}")
        return
    print(f"  {C}目标：{remote} → {url}（分支 {branch}）{R}")

    # —— 有改动则先提交 ——
    _, status = _git("status", "--porcelain")
    if status:
        lines = status.splitlines()
        print(f"  待提交改动（共 {len(lines)} 项）：")
        for line in lines[:20]:
            print(f"    {line}")
        if len(lines) > 20:
            print(f"    ... 其余 {len(lines) - 20} 项已省略")
        msg = input("  提交说明（回车使用默认时间戳）→ ").strip()
        if not msg:
            msg = "chore: 自动提交 " + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        code, out = _git("add", "-A")
        if code != 0:
            print(f"  {Y}git add 失败：{out}{R}")
            return
        code, _ = _git("commit", "-m", msg, capture=False)
        if code != 0:
            print(f"  {Y}git commit 失败（可能无改动或钩子拦截），已中止推送。{R}")
            return
        print(f"  {G}✓ 已提交：{msg}{R}")
    else:
        print(f"  {Y}工作区无改动，直接推送已有提交。{R}")

    # —— 推送 ——
    print(f"  正在推送到 {remote} ...")
    code, out = _git("push", remote, branch)
    if code != 0 and ("no upstream" in out.lower() or "set-upstream" in out.lower()):
        # 首次推送：本地分支未关联上游，带 -u 重试
        code, out = _git("push", "-u", remote, branch)
    if code != 0:
        print(f"  {Y}推送失败：{out or '（详见上方 git 输出）'}{R}")
        return
    print(f"  {G}✓ 已推送到 {remote}（分支 {branch}）{R}")


def _do_gitee():
    """菜单 5：提交并推送到 Gitee（实际 remote 名为 origin）。"""
    _git_push("origin")


def _do_github():
    """菜单 6：提交并推送到 GitHub。"""
    _git_push("github")


def _do_ths():
    """菜单 7：更新同花顺板块（子菜单选择策略）。

    列出 AIData/Strategy 下的全部策略，用户选一个后调用 CMD_UPDATE_THS：
    若同花顺在运行会先自动关闭再写入、写完自动重启，使板块立即生效。
    """
    try:
        strategies = _list_strategies()
    except Exception as e:
        print(f"  {Y}读取策略列表失败：{e}{R}")
        return
    if not strategies:
        print(f"  {Y}没有可用策略（AIData/Strategy 下无数据）。{R}")
        return
    while True:
        print(f"\n  {C}{B}── 选择要更新到同花顺板块的策略 ──{R}")
        for i, s in enumerate(strategies, 1):
            print(f"  {G}{i}{R}  {s}")
        print(f"  {Y}0{R}  {B}返回主菜单{R}")
        sel = input(f"  {C}请选择策略 → {R}").strip()
        if sel == "0":
            return
        if not sel.isdigit() or not (1 <= int(sel) <= len(strategies)):
            print(f"  {Y}无效选择，请输入 1 ~ {len(strategies)} 或 0。{R}")
            continue
        strategy = strategies[int(sel) - 1]
        print(f"  {C}正在更新同花顺板块（策略：{strategy}）...{R}")
        try:
            result = CMD_UPDATE_THS(strategy)
        except BaseException as exc:
            print(f"  {Y}!!!!! 更新同花顺失败：{type(exc).__name__}: {exc}{R}")
            result = None
        if result:
            print(f"  {result}")
        print(f"  {G}── 更新完成，可继续选择其它策略或输入 0 返回 ──{R}")


def _banner():
    print()
    print(f"{C}{B}╔══════════════════════════════════════════╗{R}")
    print(f"{C}{B}║            MarcoAI 量化数据终端           ║{R}")
    print(f"{C}{B}╚══════════════════════════════════════════╝{R}")
    print()


def _menu_loop():
    while True:
        _banner()
        print(f"  {G}1{R}  {B}更新数据{R}    同步交易日历 / 日线 / 涨停 / 策略 / 目标池")
        print(f"  {G}2{R}  {B}更新5M数据{R}  下载 5 分钟级原始行情（2026 起）")
        print(f"  {G}3{R}  {B}显示看板{R}    生成并打开策略 UI")
        print(f"  {G}4{R}  {B}QMT 自动交易{R} 买入 / 卖出监控 / 常驻 watch")
        print(f"  {G}5{R}  {B}上传 Gitee{R}    提交改动并推送到 Gitee 仓库")
        print(f"  {G}6{R}  {B}上传 GitHub{R}   提交改动并推送到 GitHub 仓库")
        print(f"  {G}7{R}  {B}更新同花顺{R}    按策略把股票写入同花顺板块（自动关闭/重启生效）")
        print(f"  {Y}0{R}  {B}退出{R}")
        print()
        choice = input(f"  {C}请选择 → {R}").strip()
        if choice == "1":
            _do_update()
        elif choice == "2":
            _do_update_5m()
        elif choice == "3":
            _do_ui()
        elif choice == "4":
            _do_qmt()
        elif choice == "5":
            _do_gitee()
            input("\n  按回车返回主菜单...")
        elif choice == "6":
            _do_github()
            input("\n  按回车返回主菜单...")
        elif choice == "7":
            _do_ths()
        elif choice in ("0", "q", "Q", "exit", "quit"):
            print(f"\n  {Y}已退出。{R}\n")
            break
        else:
            print(f"  {Y}无效选择，请输入 1 / 2 / 3 / 4 / 5 / 6 / 7 / 0。{R}")


def main():
    # 命令行参数直接启动 QMT 自动化（常驻 watch）：python Run.py qmt
    args = sys.argv[1:]
    if args and args[0] == "qmt":
        # 脚本启动时预筛当日买入候选（同上，覆盖命令行直接启动场景）
        try:
            CMD.prepare_buy_candidates()
        except Exception as e:
            print(f"{Y}[警告] 买入候选预筛失败，尾盘将降级为全量判定：{e}{R}")
        qmt_watch()
        return
    _menu_loop()


if __name__ == "__main__":
    main()
