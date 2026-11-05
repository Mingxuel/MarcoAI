#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""MarcoAI 目录结构查看器。

在项目根 C:\\MarcoAI 下随时运行，快速回答“这个项目有哪些目录/文件”。

用法示例:
    python tools/print_tree.py                      # 默认：根目录下 3 层目录 + 文件数/体积
    python tools/print_tree.py AICode -d 5 --files  # 看 AICode 5 层并列出文件名
    python tools/print_tree.py AIData -d 1          # 只看数据目录总览
    python tools/print_tree.py --pattern "*.py"     # 只显示 py 文件（需配合 --files）
    python tools/print_tree.py -a --files           # 连 __pycache__/.git 等也显示

参数:
    PATH              起点路径（默认项目根，即本脚本上一级目录）
    -d, --depth N     显示层数，1 = 只显示起点下一层（默认 3）
    --files           列出文件名（默认只显示目录与文件统计）
    --pattern GLOB    只列出匹配的文件名，可重复：--pattern "*.py" --pattern "*.md"
    -a, --all         不跳过 __pycache__/.git/.venv/build/dist 等目录
    --max N           每个目录最多显示 N 项（默认 30），其余折叠为总数
    --sort size       同级按体积降序（默认按名称）
    --no-sizes        不显示体积统计
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import sys

# 默认跳过的目录（体积大且无信息量的构建/缓存产物）
SKIP_DIRS = {
    "__pycache__", ".git", ".venv", "venv", "node_modules",
    "build", "dist", ".idea", ".mypy_cache", ".pytest_cache", ".vs",
}

_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ROOT = os.path.dirname(_HERE)


def _setup_stdout() -> None:
    """被管道捕获时强制 UTF-8，避免 Windows 控制台编码导致输出乱码。"""
    try:
        sys.stdout.reconfigure(errors="replace")
        if not sys.stdout.isatty():
            sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def _fmt_size(size: int) -> str:
    if size < 1024:
        return f"{size}B"
    value = float(size)
    for unit in ("KB", "MB", "GB", "TB"):
        value /= 1024.0
        if value < 1024.0 or unit == "TB":
            return f"{value:.1f}{unit}"
    return f"{value:.1f}TB"


def _walk_stats(path: str, skip: bool) -> tuple[int, int]:
    """递归统计目录下的文件数与总字节数（不进入被跳过的目录、不跟随符号链接）。"""
    total_files = 0
    total_size = 0
    stack = [path]
    while stack:
        current = stack.pop()
        try:
            entries = os.scandir(current)
        except OSError:
            continue
        with entries:
            for entry in entries:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        if skip and entry.name in SKIP_DIRS:
                            continue
                        stack.append(entry.path)
                    elif entry.is_file(follow_symlinks=False):
                        total_files += 1
                        try:
                            total_size += entry.stat(follow_symlinks=False).st_size
                        except OSError:
                            pass
                except OSError:
                    continue
    return total_files, total_size


def _dir_label(entry: os.DirEntry, args, stats_cache: dict) -> str:
    if entry.is_symlink():
        return f"{entry.name}/ -> {os.readlink(entry.path) if hasattr(os, 'readlink') else '?'}  [符号链接，未展开]"
    cache_key = entry.path
    if cache_key not in stats_cache:
        stats_cache[cache_key] = _walk_stats(entry.path, skip=not args.all)
    file_count, total_size = stats_cache[cache_key]
    if file_count == 0:
        return f"{entry.name}/  [空目录]"
    parts = [f"{file_count} files"]
    if not args.no_sizes:
        parts.append(_fmt_size(total_size))
    return f"{entry.name}/  [{', '.join(parts)}]"


def _file_label(entry: os.DirEntry, args) -> str:
    if entry.is_symlink():
        return f"{entry.name}  [符号链接]"
    size = ""
    if not args.no_sizes:
        try:
            size = f"  ({_fmt_size(entry.stat(follow_symlinks=False).st_size)})"
        except OSError:
            size = ""
    return f"{entry.name}{size}"


def _matches(name: str, patterns: list[str] | None) -> bool:
    if not patterns:
        return True
    return any(fnmatch.fnmatch(name.lower(), pattern.lower()) for pattern in patterns)


def _iter_children(path: str, args) -> list[os.DirEntry]:
    try:
        entries = list(os.scandir(path))
    except OSError as exc:
        return [exc]  # type: ignore[list-item]
    dirs = [e for e in entries if e.is_dir(follow_symlinks=False) and (args.all or e.name not in SKIP_DIRS)]
    files = [e for e in entries if e.is_file(follow_symlinks=False) and _matches(e.name, args.pattern)]
    dirs.sort(key=lambda e: e.name.lower())
    files.sort(key=lambda e: e.name.lower())
    if args.sort == "size":
        def _size(entry: os.DirEntry) -> int:
            try:
                return entry.stat(follow_symlinks=False).st_size
            except OSError:
                return 0
        files.sort(key=_size, reverse=True)
    return dirs + files


def _render(path: str, depth: int, prefix: str, args, root_level: bool, stats_cache: dict) -> list[str]:
    """递归渲染：返回若干行文本。depth 从 1 开始计。"""
    lines: list[str] = []
    children = _iter_children(path, args)
    if children and isinstance(children[0], OSError):
        lines.append(prefix + f"[无法读取: {children[0].strerror}]")
        return lines

    entries = children
    shown = entries[: args.max]
    hidden = len(entries) - len(shown)
    total = len(entries)

    for index, entry in enumerate(shown):
        is_last = (index == len(shown) - 1) and hidden == 0
        branch = "`-- " if is_last else "|-- "
        child_prefix = prefix + ("    " if is_last else "|   ")

        if entry.is_dir(follow_symlinks=False):
            lines.append(prefix + branch + _dir_label(entry, args, stats_cache))
            if depth < args.depth:
                lines.extend(_render(entry.path, depth + 1, child_prefix, args, False, stats_cache))
        else:
            if args.files or root_level:
                lines.append(prefix + branch + _file_label(entry, args))

    if hidden > 0:
        lines.append(prefix + "`-- ... 其余 " + str(hidden) + " 项未显示（共 " + str(total) +
                     " 项；用 --max / -d / --files 调整）")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="MarcoAI 目录结构查看器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("path", nargs="?", default=DEFAULT_ROOT, help="起点路径（默认项目根）")
    parser.add_argument("-d", "--depth", type=int, default=3, help="显示层数，默认 3（1 = 只看起点下一层）")
    parser.add_argument("--files", action="store_true", help="列出文件名（默认只显示目录与统计）")
    parser.add_argument("--pattern", action="append", default=[], help="只显示匹配的文件名，可重复，如 --pattern \"*.py\"")
    parser.add_argument("-a", "--all", action="store_true", help="不跳过 __pycache__/.git/build/dist 等")
    parser.add_argument("--max", type=int, default=30, help="每个目录最多显示 N 项，默认 30")
    parser.add_argument("--sort", choices=("name", "size"), default="name", help="同级排序方式，默认 name")
    parser.add_argument("--no-sizes", action="store_true", help="不显示体积")
    args = parser.parse_args(argv)
    args.depth = max(1, args.depth)
    args.max = max(1, args.max)

    _setup_stdout()

    target = os.path.abspath(args.path)
    if not os.path.exists(target):
        print(f"路径不存在: {target}")
        return 1
    if os.path.isfile(target):
        print(target)
        return 0

    stats_cache: dict[str, tuple[int, int]] = {}
    file_count, total_size = _walk_stats(target, skip=not args.all)
    header = f"{target}  [{file_count} files"
    if not args.no_sizes:
        header += f", {_fmt_size(total_size)}"
    header += "]"
    print(header)
    for line in _render(target, 1, "", args, True, stats_cache):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
