r"""把某月策略选股全部股票写入同花顺 ===TEST=== 板块，并重启同花顺。

- 读 AIData/STRATEGY/TPO_M5/YYYYMM* 全部行，按代码去重（保留首次出现顺序）。
- 以当前目标 XML（不存在则模板）为基底，只替换 TEST Block，保留 T/T-1 原内容。
- 写 C:\同花顺远航版\bin\users\狗蛋儿家的金\blockstockV3.xml，备份 .bak。
- 复用外部 THS 启动器重启（关闭 hexinlauncher/hexin/happ/hxdaemonprocess 后启动 hexinlauncher.exe）。
"""
import os
import re
import subprocess
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STRATEGY_DIR = os.path.join(ROOT, "AIData", "STRATEGY", "TPO_M5")
TEMPLATE = os.path.join(ROOT, "AIData", "THS", "blockstockV3.xml")
TARGET_DIR = os.environ.get("THS_TARGET_DIR", r"C:\同花顺远航版\bin\users\狗蛋儿家的金")
TARGET = os.path.join(TARGET_DIR, "blockstockV3.xml")
LAUNCHER = r"C:\同花顺远航版\bin\hexinlauncher.exe"
THS_PROCESSES = ["hexinlauncher.exe", "hexin.exe", "happ.exe", "hxdaemonprocess.exe"]


def month_codes(month):
    month = str(month or "").strip()
    if not re.fullmatch(r"\d{6}", month):
        raise ValueError("month 需为 YYYYMM")
    seen = set()
    codes = []
    if not os.path.isdir(STRATEGY_DIR):
        raise ValueError(f"策略目录不存在: {STRATEGY_DIR}")
    for name in sorted(os.listdir(STRATEGY_DIR)):
        if not name.startswith(month) or len(name) != 8 or not name.isdigit():
            continue
        fp = os.path.join(STRATEGY_DIR, name)
        try:
            text = open(fp, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for line in text.splitlines():
            parts = line.strip().split("|")
            if not parts:
                continue
            code = parts[0].strip().upper()
            if len(code) < 9 or code[6] not in ".-":
                # 也允许 600000.SH / 000001.SZ / 830000.BJ
                pass
            if not re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", code):
                continue
            if code not in seen:
                seen.add(code)
                codes.append(code)
    return codes


def _security_line(code):
    pure, suffix = code.split(".")
    market = {"SH": "USHA", "SZ": "USZA", "BJ": "USBJ"}.get(suffix, "USHA")
    return f'    <security market="{market}" code="{pure}" />'


def build_xml(month, codes):
    base_path = TARGET if os.path.isfile(TARGET) else TEMPLATE
    if not os.path.isfile(base_path):
        raise ValueError(f"同花顺模板/目标不存在: {base_path}")
    raw = open(base_path, encoding="utf-8", newline="").read()
    block_lines = [_security_line(c) for c in codes]
    block = '  <Block name="TEST" id="35" IsNameChanged="true">'
    if block_lines:
        block += "\n" + "\n".join(block_lines) + "\n  </Block>"
    else:
        block += "\n  </Block>"
    pat = re.compile(r'[ \t]*<Block\s+name="TEST"[^>]*/>|[ \t]*<Block\s+name="TEST"[^>]*>.*?</Block>', re.S)
    if pat.search(raw):
        raw = pat.sub(block, raw, count=1)
    else:
        raw = re.sub(r"(</hevo\s*>)", block + r"\n\1", raw, count=1)
    # 删掉模板占位行
    raw = re.sub(r"^[ \t]*===TEST===[ \t]*\r?\n?", "", raw, flags=re.M)
    return raw


def _restart_ths():
    log = []
    for name in THS_PROCESSES:
        try:
            r = subprocess.run(["taskkill", "/F", "/T", "/IM", name],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=15)
            if r.returncode == 0:
                log.append(f"killed {name}")
        except BaseException as exc:  # noqa: BLE001
            log.append(f"{name}: {type(exc).__name__}")
    if not os.path.isfile(LAUNCHER):
        return False, "；".join(log + [f"启动器不存在: {LAUNCHER}"])
    try:
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen([LAUNCHER], cwd=os.path.dirname(LAUNCHER),
                         close_fds=True, creationflags=flags)
        log.append("started hexinlauncher.exe")
        time.sleep(1.5)
        return True, "；".join(log)
    except BaseException as exc:  # noqa: BLE001
        return False, "；".join(log + [f"启动失败: {type(exc).__name__}: {exc}"])


def add_month_to_test(month, restart=True):
    codes = month_codes(month)
    raw = build_xml(month, codes)
    if not os.path.isdir(TARGET_DIR):
        raise ValueError(f"同花顺目标目录不存在: {TARGET_DIR}")
    os.makedirs(TARGET_DIR, exist_ok=True)
    if os.path.isfile(TARGET):
        try:
            open(TARGET + ".bak", "w", encoding="utf-8", newline="").write(
                open(TARGET, encoding="utf-8", newline="").read())
        except OSError:
            pass
    with open(TARGET, "w", encoding="utf-8", newline="") as f:
        f.write(raw)
    restarted = False
    restart_detail = "未重启（restart=false）"
    if restart:
        restarted, restart_detail = _restart_ths()
    return {
        "ok": True,
        "month": month,
        "count": len(codes),
        "codes": codes[:20],
        "target": TARGET,
        "restarted": bool(restarted),
        "restartDetail": restart_detail,
    }
