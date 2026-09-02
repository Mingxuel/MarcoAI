"""兼容 tqdm 接口的单行进度条，强制用 \\r 原地刷新（无论输出是否为 TTY）。

背景：数据更新在网页端通过子进程把 stdout/stderr 重定向到日志文件（非 TTY），
tqdm 在非 TTY 下不会用 \\r 原地刷新，而是每步写一行，导致网页日志里进度条逐行累积
（即"每更新一行"）。本实现始终写 `\\r` + 定宽行 + flush，使日志文件中的进度序列
可被 StrategyService._strip_carriage 压缩为单行进度。命令行 TTY 下同样单行刷新。

接口对齐 tqdm：支持 total/desc/ncols/disable 构造参数，以及 set_postfix/update/close，
因此调用处只需把 `from tqdm import tqdm` 换成 `from .progress import ProgressBar as tqdm`。
"""


import sys


class ProgressBar:
    def __init__(self, total, desc="", ncols=90, disable=False, file=None):
        self.total = total
        self.desc = desc
        self.ncols = ncols
        self.file = file if file is not None else sys.stderr
        self.n = 0
        self._postfix = {}

    def set_postfix(self, refresh=None, **kwargs):
        # tqdm 的 refresh 参数无意义，忽略；其余键值作为后缀显示
        self._postfix = kwargs

    def update(self, n=1):
        self.n += n
        pct = (self.n * 100 // self.total) if self.total else 100
        extra = " ".join(f"{k}={v}" for k, v in self._postfix.items())
        body = f"{self.desc}: {pct:3d}%|{self.n}/{self.total}| {extra}".rstrip()
        line = ("\r" + body).ljust(self.ncols)
        try:
            self.file.write(line[: self.ncols])
            self.file.flush()
        except Exception:
            pass

    def close(self):
        try:
            self.file.write("\n")
            self.file.flush()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False
