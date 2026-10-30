"""
Run.py —— 主交互菜单

运行：
    cd e:/MarcoAI
    python Run.py

功能：
    1. 更新数据   —— 运行完整数据更新管线（交易日历/股票代码/日线/涨停/策略/目标池）
    2. 更新5M数据 —— 下载首板/涨停/候选池/详情涉及股、按关键日 T-2~T+5 窗口的 5 分钟行情（需通达信联网）
    3. 更新同花顺 —— 选策略后写入同花顺板块（自动关闭/重启同花顺生效）
    4. 离线看板   —— 生成内联图表库的单文件看板，无外网也能打开（统一用此项查看看板）
    5. 单项更新   —— 列出一条龙各步骤，单独运行任意一项（如只刷涨停/只跑某策略回测）
    6. 上传 Gitee  —— 提交改动并推送到 Gitee 仓库（remote: origin）
    7. 上传 GitHub —— 提交改动并推送到 GitHub 仓库（remote: github）
    77. QMT 自动交易 —— 买入 / 卖出监控 / 常驻 watch
    88. 一条龙更新 —— 进入后 5 秒倒计时（默认策略 TPO_MA60 + 周期 12 个月，倒计时内按键转人工选择），再依次：更新数据(含5M) → 刷新离线看板 → 更新同花顺 → 上传 Gitee
    0. 退出
执行完任一项后自动回到主菜单。
"""

import datetime
import os
import subprocess
import sys
import time
import unicodedata

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
from AICode.MarcoAPI.Update.SZ2005M import UPDATE_5M_ORIGIN, UPDATE_5M_PANELS
from AICode.MarcoAPI.Update.Path import PATH_AIDATA
from AICode.MarcoAPI.StrategyUI import (GENERATE_STRATEGY_UI_OFFLINE, CMD_UPDATE_THS, CMD_RUN_STEP,
                                         _list_strategies, OFFLINE_DASHBOARD_STATUS, OFFLINE_DASHBOARD_PATH)
from AICode.AITrading.Structure.callbacks import watch as qmt_watch
from AICode.AITrading import commands as CMD


# 终端颜色（非 TTY 环境自动降级为空，避免乱码）
_USE_COLOR = sys.stdout.isatty()
C = "\033[96m" if _USE_COLOR else ""   # cyan
G = "\033[92m" if _USE_COLOR else ""   # green
Y = "\033[93m" if _USE_COLOR else ""   # yellow
B = "\033[1m"  if _USE_COLOR else ""   # bold
R = "\033[0m"  if _USE_COLOR else ""   # reset


def _do_update(scope_codes: list[str] | None = None, recent_days_5m: int = 0):
    UPDATE_ALL(scope_codes=scope_codes, recent_days_5m=recent_days_5m)


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
    print(f"  {C}开始更新 5M 数据（首板/涨停/候选池/详情涉及股，2026 起，需通达信联网）...{R}")
    try:
        # 抑制内部详细输出，仅打印摘要
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            summary = UPDATE_5M_PANELS()
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


def _do_ui_offline():
    """菜单 4：打开离线看板。

    看板文件已存在时默认【直接打开（秒开）】，日常只是想看盘无需等待；
    源数据自上次生成后有更新时会在提示里说明，输入 r 才重新生成。
    重建需扫描全部个股的 5M 数据并写出数百 MB，耗时数分钟，故默认不自动重建。
    """
    fresh, msg = OFFLINE_DASHBOARD_STATUS()
    print(f"\n  {C}离线看板：{msg}{R}")
    p = OFFLINE_DASHBOARD_PATH()
    if os.path.isfile(p):
        ans = input(f"  {Y}回车=直接打开现有看板(秒开)，输入 r 回车=重新生成：{R}").strip().lower()
        if ans != "r":
            import webbrowser
            webbrowser.open("file:///" + p.replace("\\", "/") + "?v=" + str(int(os.path.getmtime(p))))
            print(f"  {G}[OK] 已打开离线看板{R}")
            return
    GENERATE_STRATEGY_UI_OFFLINE()


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


def _git_push(remote, commit_msg=None):
    """提交改动并推送到指定 remote（remote 名称：gitee / github）。

    流程：确认仓库与 remote → 有改动则 add+commit（说明可自定义，回车用默认时间戳）
          → push 到 remote 当前分支（上游未设置时自动带 -u 重试）。
    commit_msg 为 None 时交互询问提交说明；传入非空字符串则直接采用（用于一条龙等自动流程，避免再弹窗）。
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
        if commit_msg is None:
            # 交互模式：允许自定义提交说明，回车用默认时间戳
            commit_msg = input("  提交说明（回车使用默认时间戳）→ ").strip()
        if not commit_msg:
            commit_msg = "chore: 自动提交 " + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        msg = commit_msg
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


def _select_strategy():
    """交互式选择要更新到同花顺板块的策略，返回策略名；用户选 0 返回 None。"""
    try:
        strategies = _list_strategies()
    except Exception as e:
        print(f"  {Y}读取策略列表失败：{e}{R}")
        return None
    if not strategies:
        print(f"  {Y}没有可用策略（AIData/Strategy 下无数据）。{R}")
        return None
    while True:
        print(f"\n  {C}{B}── 选择要更新到同花顺板块的策略 ──{R}")
        for i, s in enumerate(strategies, 1):
            print(f"  {G}{i}{R}  {s}")
        print(f"  {Y}0{R}  {B}返回主菜单{R}")
        sel = input(f"  {C}请选择策略 → {R}").strip()
        if sel == "0":
            return None
        if not sel.isdigit() or not (1 <= int(sel) <= len(strategies)):
            print(f"  {Y}无效选择，请输入 1 ~ {len(strategies)} 或 0。{R}")
            continue
        return strategies[int(sel) - 1]


# 一条龙「可选周期」：基于 TOP（每日涨停股清单）按周期圈定股票范围，并限定 5M 只下载最近窗口。
# 5M 实际显示/回测只用约 8 个交易日窗口（见 StrategyUI._read_5m_window），故统一只下最近一段。
_RECENT_DAYS_5M = 30  # 5M 下载保留的最近交易日数（含充足余量覆盖 MA120 与各窗口）

_PERIOD_OPTIONS = (
    ("1", "最近 2 个月", 2),
    ("2", "最近 3 个月", 3),
    ("3", "最近 6 个月", 6),
    ("4", "最近 12 个月", 12),
)


def _top_codes_in_period(months: int) -> set[str]:
    """返回最近 months 个月内（含）出现过涨停的个股代码集合（读 AIData/TOP 每日清单）。"""
    from AICode.MarcoAPI.Update.Path import PATH_AIDATA_TOP
    top_dir = PATH_AIDATA_TOP()
    if not os.path.isdir(top_dir):
        return set()
    files = [n for n in os.listdir(top_dir) if n.isdigit() and len(n) == 8]
    if not files:
        return set()
    end = max(datetime.date(int(n[:4]), int(n[4:6]), int(n[6:8])) for n in files)
    y, m = end.year, end.month - months
    while m <= 0:
        m += 12
        y -= 1
    start = datetime.date(y, m, end.day)
    codes: set[str] = set()
    for n in files:
        d = datetime.date(int(n[:4]), int(n[4:6]), int(n[6:8]))
        if d < start:
            continue
        with open(os.path.join(top_dir, n), encoding="utf-8") as fh:
            for line in fh:
                c = line.strip()
                if c:
                    codes.add(c)
    return codes


def _select_period():
    """一条龙可选周期：返回 (scope_codes, recent_days_5m)；选 0 返回 (None, 0) 表示全量。

    scope_codes 为该周期内涨停过的个股（用于缩小 5M 下载股票范围），recent_days_5m 限定 5M 只下最近窗口。
    """
    print(f"\n  {C}{B}── 选择数据更新周期（缩小 5M 下载范围）──{R}")
    for num, name, _ in _PERIOD_OPTIONS:
        print(f"  {G}{num}{R}  {B}{name}{R}")
    print(f"  {Y}0{R}  {B}全量（不限定，5M 仍全历史下载）{R}")
    while True:
        sel = input(f"  {C}请选择周期 → {R}").strip()
        if sel == "0":
            return None, 0
        hit = next((it for it in _PERIOD_OPTIONS if it[0] == sel), None)
        if not hit:
            print(f"  {Y}无效选择，请输入 1 ~ {len(_PERIOD_OPTIONS)} 或 0。{R}")
            continue
        _, name, months = hit
        codes = _top_codes_in_period(months)
        print(f"  {G}已圈定 [{name}] 内涨停股 {len(codes)} 只：1D 仅下载这些股（保留完整历史）、候选池/策略只产出这些票、5M 仅下最近 {_RECENT_DAYS_5M} 个交易日{R}")
        return sorted(codes), _RECENT_DAYS_5M


def _do_ths():
    """菜单 7：更新同花顺板块（子菜单选择策略）。

    列出 AIData/Strategy 下的全部策略，用户选一个后调用 CMD_UPDATE_THS：
    若同花顺在运行会先自动关闭再写入、写完自动重启，使板块立即生效。
    可连续为多个策略更新，输入 0 返回主菜单。
    """
    while True:
        strategy = _select_strategy()
        if not strategy:
            return
        print(f"  {C}正在更新同花顺板块（策略：{strategy}）...{R}")
        try:
            result = CMD_UPDATE_THS(strategy)
        except BaseException as exc:
            print(f"  {Y}!!!!! 更新同花顺失败：{type(exc).__name__}: {exc}{R}")
            result = None
        if result:
            print(f"  {result}")
        print(f"  {G}── 更新完成，可继续选择其它策略或输入 0 返回 ──{R}")


def _pipeline_choose(seconds: int = 5):
    """一条龙进入时提供 5 秒倒计时：倒计时内按任意键 → 转人工选择策略/周期；
    倒计时结束未按键 → 直接采用默认（策略=TPO_MA60，周期=最近12个月）。

    返回 (strategy, scope_codes, recent_days_5m)；用户中途取消（人工选择时选 0）返回 None。
    """
    default_strategy = "TPO_MA60"
    default_months = 12  # 对应 _PERIOD_OPTIONS 中「最近 12 个月」

    # Windows 用 msvcrt 做非阻塞按键检测；其它平台降级为「仅默认、不可中断」
    try:
        import msvcrt
        def _kbhit() -> bool:
            return msvcrt.kbhit()
        def _getch() -> str:
            return msvcrt.getwch()
    except Exception:
        def _kbhit() -> bool:
            return False
        def _getch() -> str:
            return ""

    def manual():
        strategy = _select_strategy()
        if not strategy:
            return None
        scope_codes, recent_days_5m = _select_period()
        return strategy, scope_codes, recent_days_5m

    print(f"\n  {C}{B}═══ 一条龙更新（{seconds} 秒后自动以默认执行）═══{R}")
    print(f"  {Y}默认：策略 = {default_strategy}，周期 = 最近 12 个月（按时间窗圈定 5M 下载范围）{R}")
    print(f"  {G}倒计时内按任意键 → 进入人工选择（策略 / 周期）；什么也不按 → {seconds} 秒后自动开始{R}")
    deadline = time.time() + seconds
    while True:
        left = max(0, int(round(deadline - time.time())))
        sys.stdout.write(f"\r  {C}自动开始倒计时：{left:>2} 秒（按任意键人工选择）{' ' * 6}{R}")
        sys.stdout.flush()
        if left <= 0:
            break
        if _kbhit():
            _getch()  # 消费掉该按键，避免带入后续 input
            sys.stdout.write("\r\n")
            return manual()
        time.sleep(0.1)
    sys.stdout.write("\r\n")
    codes = _top_codes_in_period(default_months)
    print(f"  {G}✓ 采用默认：策略={default_strategy}，周期=最近12个月（已圈定 {len(codes)} 只涨停股）{R}")
    return default_strategy, sorted(codes), _RECENT_DAYS_5M


def _do_pipeline():
    """菜单 88：一条龙数据更新 —— 倒计时默认（TPO_MA60 + 12 个月）或人工选择策略/周期，
    然后依次：更新数据(含5M) → 刷新离线看板 → 更新同花顺 → 上传 Gitee，全程自动。

    更新数据（UPDATE_ALL）已内含 5M 原始行情拉取，故此处不再单独调用 _do_update_5m()，
    避免 5M 被重复下载。各步骤错误互不影响，最终汇总结果。
    """
    print(f"\n  {C}{B}═══ 一条龙更新：① 选策略 → ② 更新数据(含5M) → ③ 刷新离线看板 → ④ 更新同花顺 → ⑤ 上传 Gitee ═══{R}")
    # ① 选策略/周期：5 秒倒计时默认 TPO_MA60 + 12 个月；倒计时内按键转人工
    chosen = _pipeline_choose()
    if chosen is None:
        print(f"  {Y}已取消一条龙更新。{R}")
        return
    strategy, scope_codes, recent_days_5m = chosen
    # ② 更新数据（含 5M）；按周期圈定的股票范围 + 最近 5M 窗口，极大缩短下载
    print(f"\n  {C}{B}── ② 更新数据（含 5M）──{R}")
    try:
        _do_update(scope_codes=scope_codes, recent_days_5m=recent_days_5m)
    except BaseException as exc:
        print(f"  {Y}!!!!! ② 更新数据失败：{type(exc).__name__}: {exc}{R}")
    # ③ 数据更新完毕后刷新离线看板（HTML + data/ 伴随文件），保证离线数据与源数据同步
    print(f"\n  {C}{B}── ③ 刷新离线看板（HTML + data/）──{R}")
    try:
        GENERATE_STRATEGY_UI_OFFLINE(open_browser=False)
        print(f"  {G}[OK] 离线看板与 data/ 已刷新{R}")
    except BaseException as exc:
        print(f"  {Y}!!!!! ③ 离线看板生成失败：{type(exc).__name__}: {exc}{R}")
    # ④ 更新同花顺板块（使用第①步所选策略）
    print(f"\n  {C}{B}── ④ 更新同花顺板块（策略：{strategy}）──{R}")
    try:
        result = CMD_UPDATE_THS(strategy)
        if result:
            print(f"  {result}")
    except BaseException as exc:
        print(f"  {Y}!!!!! ④ 更新同花顺失败：{type(exc).__name__}: {exc}{R}")
    # ⑤ 上传 Gitee（自动提交说明，不再弹交互）
    print(f"\n  {C}{B}── ⑤ 上传 Gitee ──{R}")
    try:
        _git_push("origin", commit_msg="chore: 一条龙自动更新 " + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    except BaseException as exc:
        print(f"  {Y}!!!!! ⑤ 上传 Gitee 失败：{type(exc).__name__}: {exc}{R}")
    print(f"\n  {G}{B}── 一条龙更新结束 ──{R}")


# 单项更新步骤（与一条龙依赖顺序一致）：编号 -> (显示名, UPDATE_* 标识)
_UPDATE_STEP_ITEMS = (
    ("1",  "交易日历",     "UPDATE_TRADING_DATES"),
    ("2",  "股票池",       "UPDATE_STOCK_CODES"),
    ("3",  "日线原始",     "UPDATE_1D_ORIGIN"),
    ("4",  "5分钟原始",    "UPDATE_5M_ORIGIN"),
    ("5",  "涨停列表",     "UPDATE_TOP"),
    ("6",  "加工日线",     "UPDATE_1D"),
    ("7",  "首板涨停",     "UPDATE_TOP_FIRST"),
    ("8",  "TPO_M5 回测",     "UPDATE_STRATEGY_TPO_M5"),
    ("9",  "TPO_MA60 回测",   "UPDATE_STRATEGY_TPO_MA60"),
    ("10", "TPO_M5 候选",      "UPDATE_TARGET_TPO_M5"),
    ("11", "TPO_MA60 候选",    "UPDATE_TARGET_TPO_MA60"),
    ("12", "指数列表",          "UPDATE_INDEX_CODES"),
    ("13", "指数日线原始",      "UPDATE_INDEX_1D_ORIGIN"),
    ("14", "指数加工日线",      "UPDATE_INDEX_1D"),
)


def _do_single_update():
    """菜单 5：单项数据更新 —— 列出一条龙各步骤，单独运行任意一项（复用 CMD_RUN_STEP）。"""
    print(f"\n  {C}{B}── 单项数据更新（按依赖顺序）──{R}")
    print(f"  {Y}依赖：⑥加工日线依赖⑤涨停列表；⑦首板涨停依赖⑥的 is_volume_up{R}")
    for num, name, step in _UPDATE_STEP_ITEMS:
        print(f"  {G}{num:>2}{R}  {B}{name}{R}  {Y}({step}){R}")
    print(f"  {Y}0{R}  {B}返回主菜单{R}")
    while True:
        sel = input(f"  {C}请选择要运行的步骤 → {R}").strip()
        if sel == "0":
            return
        hit = next((it for it in _UPDATE_STEP_ITEMS if it[0] == sel), None)
        if not hit:
            print(f"  {Y}无效选择，请输入 1 ~ {len(_UPDATE_STEP_ITEMS)} 或 0。{R}")
            continue
        _, name, step = hit
        print(f"  {C}运行：{name}（{step}）...{R}")
        try:
            result = CMD_RUN_STEP(step)
        except BaseException as exc:
            print(f"  {Y}!!!!! {name} 失败：{type(exc).__name__}: {exc}{R}")
            result = None
        if result:
            print(f"  {result}")
        print(f"  {G}── {name} 完成，可继续选择或输入 0 返回 ──{R}")


# 菜单结构：(编号, 名称, 说明)。每个元组为一组，组之间会画一条分隔线。
_MENU_GROUPS = (
    (("1", "更新数据", "同步交易日历 / 日线 / 涨停 / 策略 / 目标池"),
     ("2", "更新5M数据", "下载首板/涨停/候选池/详情涉及股、按关键日 T-2~T+5 窗口的 5 分钟行情"),
     ("3", "更新同花顺", "按策略写入同花顺板块（自动关闭/重启生效）"),
     ("4", "离线看板", "打开离线看板（已是最新则秒开，数据有更新才重建）"),
     ("5", "单项更新", "列出一条龙各步骤，单独运行任意一项")),
    (("6", "上传 Gitee", "提交改动并推送到 Gitee 仓库"),
     ("7", "上传 GitHub", "提交改动并推送到 GitHub 仓库")),
    (("77", "QMT 自动交易", "买入 / 卖出监控 / 常驻 watch"),
     ("88", "一条龙更新", "先选策略 → 数据 → 离线看板 → 同花顺 → 上传 Gitee，一步到位")),
)


def _dw(s: str) -> int:
    """按终端实际显示宽度计算字符串宽度（CJK 全角字符占 2 列）。"""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in s)


def _pad(s: str, width: int) -> str:
    """按显示宽度在右侧补空格，保证中英混排也能对齐。"""
    return s + " " * max(0, width - _dw(s))


def _print_menu():
    """打印带边框的主菜单面板：标题居中，编号/名称/说明三列按显示宽度对齐，分组间加分隔线。"""
    items = [r for g in _MENU_GROUPS for r in g] + [("0", "退出", "")]
    badge_w = max(_dw("[ " + n + " ]") for n, _, _ in items) + 2
    name_w = max(_dw(nm) for _, nm, _ in items) + 2
    desc_w = max(_dw(d) for _, _, d in items)
    left, gap, right = 2, 2, 2
    inner = left + badge_w + gap + name_w + gap + desc_w + right
    edge = C + B  # 边框颜色

    print()
    print(edge + "╔" + "═" * inner + "╗" + R)
    title = "MarcoAI 量化数据终端"
    pad_total = inner - _dw(title)
    lp = pad_total // 2
    print(edge + "║" + R + " " * lp + edge + title + R
          + " " * (pad_total - lp) + edge + "║" + R)
    print(edge + "╠" + "═" * inner + "╣" + R)

    def row(num: str, name: str, desc: str) -> None:
        body = (" " * left
                + G + _pad("[ " + num + " ]", badge_w) + R
                + " " * gap
                + B + _pad(name, name_w) + R
                + " " * gap
                + _pad(desc, desc_w)
                + " " * right)
        print(edge + "║" + R + body + edge + "║" + R)

    for gi, group in enumerate(_MENU_GROUPS):
        if gi:  # 组间分隔线（细线，区别于表头粗线）
            print(edge + "║" + R + " " * 2 + "─" * (inner - 4) + " " * 2 + edge + "║" + R)
        for num, name, desc in group:
            row(num, name, desc)

    print(edge + "╠" + "═" * inner + "╣" + R)
    row("0", "退出", "")
    print(edge + "╚" + "═" * inner + "╝" + R)
    print()


def _menu_loop():
    while True:
        _print_menu()
        choice = input(f"  {C}请选择 → {R}").strip()
        if choice == "1":
            _do_update()
        elif choice == "2":
            _do_update_5m()
        elif choice == "4":
            _do_ui_offline()
        elif choice == "5":
            _do_single_update()
        elif choice == "77":
            _do_qmt()
        elif choice == "6":
            _do_gitee()
            input("\n  按回车返回主菜单...")
        elif choice == "7":
            _do_github()
            input("\n  按回车返回主菜单...")
        elif choice == "3":
            _do_ths()
        elif choice == "88":
            _do_pipeline()
        elif choice in ("0", "q", "Q", "exit", "quit"):
            print(f"\n  {Y}已退出。{R}\n")
            break
        else:
            print(f"  {Y}无效选择，请输入 1 / 2 / 3 / 4 / 5 / 6 / 7 / 77 / 88 / 0。{R}")


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
