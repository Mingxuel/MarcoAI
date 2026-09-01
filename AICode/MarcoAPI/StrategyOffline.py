# -*- coding: utf-8 -*-
"""
离线看板生成器（不修改 StrategyUI.py）

功能：
    把 StrategyDashboard.html 依赖的两个 CDN 脚本（chart.js / lightweight-charts）
    替换为项目内自带的本地文件（UI/lib/），生成一个完全离线、双击即开的
    StrategyDashboard_Offline.html，无需联网、无需 pip 安装任何第三方库。

两种运行环境都能用：
    1) 开发机（已装 tqcenter/pandas 等）：直接调用 StrategyUI 聚合+渲染，再本地化。
    2) 新设备（仅靠已有数据 + 本文件 + UI/lib/）：读取已生成的 StrategyDashboard.html，
       仅做文本替换，零依赖。若 StrategyUI 因缺少依赖无法 import，自动退化为此模式。

用法：
    python -m AICode.MarcoAPI.StrategyOffline
"""

import os
import sys

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, os.path.dirname(_root))

UI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "UI")
SRC_HTML = os.path.join(UI_DIR, "StrategyDashboard.html")
OUT_HTML = os.path.join(UI_DIR, "StrategyDashboard_Offline.html")
LIB_DIR = os.path.join(UI_DIR, "lib")

# (原 CDN 引用, 本地相对路径) —— 与 StrategyUI._render_html 中的两行精确对应
CDN_REPLACEMENTS = [
    (
        '<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>',
        '<script src="lib/chart.umd.min.js"></script>',
    ),
    (
        '<script src="https://unpkg.com/lightweight-charts@5.0.8/dist/lightweight-charts.standalone.production.js"></script>',
        '<script src="lib/lightweight-charts.standalone.production.js"></script>',
    ),
    # 移除 google fonts 的在线 link，避免离线时浏览器尝试联网（字体回退为系统默认）
    (
        '<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@900&display=swap" rel="stylesheet">\n',
        '',
    ),
]

# 离线看板无后端 HTTP 服务，把 fetch('/api/...') 这类调用替换为安全的 no-op，
# 避免用户点击"更新/命令"按钮时抛出未捕获错误（看板展示本身不依赖这些调用）。
_FETCH_SHIM = (
    "<script>function OFFLINE_FETCH(){return Promise.resolve({ok:false,json:async()=>({})});}"
    "window.OFFLINE_FETCH=OFFLINE_FETCH;</script>\n"
)


def _ensure_lib() -> bool:
    """检查本地 JS 库是否齐全。"""
    needed = ["chart.umd.min.js", "lightweight-charts.standalone.production.js"]
    return all(os.path.isfile(os.path.join(LIB_DIR, f)) for f in needed)


def _get_source_html() -> str | None:
    """尝试生成或读取源 HTML。优先调用 StrategyUI 重新生成；失败则读已有文件。"""
    # 尝试调用 StrategyUI 聚合+渲染（需要完整依赖环境）
    try:
        from AICode.MarcoAPI.StrategyUI import GENERATE_STRATEGY_UI
        path = GENERATE_STRATEGY_UI(open_browser=False)
        if path and os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
    except Exception as e:
        print(f"STRATEGY_OFFLINE: 无法调用 StrategyUI 重新生成（{type(e).__name__}），尝试读取已有 HTML")

    # 退化：读取已生成的 StrategyDashboard.html
    if os.path.isfile(SRC_HTML):
        with open(SRC_HTML, "r", encoding="utf-8") as f:
            return f.read()
    return None


def _localize(html: str) -> str:
    for cdn, local in CDN_REPLACEMENTS:
        html = html.replace(cdn, local)
    # 屏蔽所有 fetch( 调用，离线环境无后端服务
    html = html.replace("fetch(", "OFFLINE_FETCH(")
    banner = "<!-- 离线版：JS 库已本地化（UI/lib/），无需联网，双击即可打开 -->\n"
    return banner + _FETCH_SHIM + html


def main() -> str:
    if not _ensure_lib():
        raise SystemExit(
            "STRATEGY_OFFLINE: 缺少本地 JS 库，请确认 UI/lib/ 下存在 "
            "chart.umd.min.js 与 lightweight-charts.standalone.production.js"
        )
    html = _get_source_html()
    if not html:
        raise SystemExit(
            "STRATEGY_OFFLINE: 未找到源 HTML。请先在可运行 StrategyUI 的环境生成 "
            "StrategyDashboard.html，或在该环境直接运行本脚本。"
        )
    out = _localize(html)
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(out)
    print(f"STRATEGY_OFFLINE: 离线看板已生成 -> {OUT_HTML}")
    return OUT_HTML


if __name__ == "__main__":
    main()
