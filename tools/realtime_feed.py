"""实时看盘数据源（tqcenter 实时快照轮询 + 买卖信号）。

设计要点：
- 只用通达信 tqcenter 快照（`get_market_snapshot`），不用 subscribe_hq（实测无推送）；
  后台线程每 ~2 秒轮询一次，API 只读线程维护的最新状态，不阻塞其他接口。
- 候选股 = 最新 STRATEGY 日期首行（T-0）+ picks 的 tpoWindow.T / TM1；picks 尚未预热时
  自动重试，另用「最新两天 STRATEGY 首行」兜底。
- 环境：T-1 日线 MA60（成长端 7 个宽基中 ≥4 在 MA60 上 → 好），由 AIData/INDEX_5M 收盘价聚合日线计算；
  盘中宽度 = 成长端 7 个当前价 > 昨收的个数。
- 持仓：dashboard/holdings.json（用户可编辑；POST 由服务端原子写回）。
- 只做行情 + 判断，不接 miniQMT、不下单。
"""
from __future__ import annotations

import bisect
import calendar
import copy
import datetime as _dt
import json
import os
import re
import struct
import sys
import threading
import time
import traceback

CODE_RE = re.compile(r"^[0-9]{6}\.(SH|SZ|BJ)$")

GROWTH_INDEXES = [
    ("399673.SZ", "创业板50"),
    ("399006.SZ", "创业板指"),
    ("000688.SH", "科创50"),
    ("399001.SZ", "深证成指"),
    ("000300.SH", "沪深300"),
    ("000852.SH", "中证1000"),
    ("000905.SH", "中证500"),
]
ENV_INDEXES = [("000300.SH", "沪深300"), ("399006.SZ", "创业板指"), ("399986.SZ", "中证银行")]
WIDTH_INDEXES = [("000300.SH", "沪深300"), ("399006.SZ", "创业板指")]
WIDTH_THRESHOLD = 2
EXTRA_INDEXES = [
    ("000001.SH", "上证指数"),
    ("399986.SZ", "中证银行"),
    ("000015.SH", "红利指数"),
]
ALL_INDEXES = GROWTH_INDEXES + EXTRA_INDEXES
INDEX_NAMES = {c: n for c, n in ALL_INDEXES}


# ---------------------------------------------------------------- utils
def _ensure_code(code):
    code = str(code or "").strip().upper()
    return code if CODE_RE.match(code) else None


def _f(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x:  # NaN
        return None
    return x


def _read_text(path):
    raw = open(path, "rb").read()
    for enc in ("utf-8", "gbk", "gb2312", "latin-1"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="ignore")


def market_state(dt=None):
    """返回 (marketState, label)。marketState 仅 盘中/收盘/休市。"""
    dt = dt or _dt.datetime.now()
    if dt.weekday() >= 5:
        return "休市", "周末休市"
    t = dt.time()
    if t < _dt.time(9, 15):
        return "休市", "未开盘"
    if t < _dt.time(9, 30):
        return "休市", "集合竞价"
    if t <= _dt.time(11, 30):
        return "盘中", "上午盘"
    if t < _dt.time(13, 0):
        return "休市", "午间休市"
    if t <= _dt.time(15, 0):
        return "盘中", "下午盘"
    return "收盘", "已收盘（EOD 冻结）"


def _pct(a, b):
    if a is None or b in (None, 0):
        return None
    return round((a - b) / b * 100, 2)


def compute_buy_signal(quote, env_good, breadth):
    """候选股买入信号（严格按任务规则）。quote 为 None 时返回数据缺失。"""
    if not quote or quote.get("now") is None or quote.get("lastClose") is None:
        return {"score": None, "signal": "数据缺失", "reason": "无实时快照", "limitUp": False}
    now, last, op, avg = quote.get("now"), quote.get("lastClose"), quote.get("open"), quote.get("avg")
    score = 0
    parts = []
    if last and now > last:
        score += 1
        parts.append("现价>昨收")
    if op and now > op:
        score += 1
        parts.append("现价>开盘")
    if avg and now > avg:
        score += 1
        parts.append("现价>均价")
    if env_good:
        score += 1
        parts.append("T-1环境好")
    if breadth is not None and breadth >= 4:
        score += 1
        parts.append(f"宽度{breadth}/7")
    zaf = _pct(now, last) if last else None
    limit_up = zaf is not None and zaf >= 9.5
    if last and avg and now < last and now < avg:
        signal = "回避"
        reason = "现价低于昨收且低于均价"
    elif score >= 5 and op and avg and now > op and now > avg:
        signal = "可买（强）"
        reason = "；".join(parts) + f"；score={score}"
    elif score == 4:
        signal = "观察"
        reason = "；".join(parts) + "；score=4"
    else:
        signal = "不买"
        reason = "；".join(parts) + f"；score={score}" if parts else f"score={score}"
    if limit_up:
        reason = "已涨停（打板谨慎）；" + reason
    return {"score": score, "signal": signal, "reason": reason, "limitUp": limit_up, "zaf": zaf}


def _limit_up_price(code, last_close):
    """按板块估算涨停价（主板 10% / 创业板科创板 20% / 北交所 30%）。"""
    last_close = _f(last_close)
    if not last_close or last_close <= 0:
        return None
    c = str(code or "").upper()
    if c.startswith(("300", "301", "688")):
        pct = 0.20
    elif c.startswith(("8", "4", "92")):
        pct = 0.30
    else:
        pct = 0.10
    return round(last_close * (1 + pct) + 1e-9, 2)


def bplus_action(env_t1, breadth, now_dt=None, breadth_1000=None, env_score=None):
    """S6 四状态：score≥2 持有；score==1 看 10:00 宽度（300+创指都红）；score==0 10:00卖。"""
    now_dt = now_dt or _dt.datetime.now()
    if env_score is None:
        return "环境不可用（回退满仓·持有到14:55）", "hold"
    if env_score >= 2:
        return "持有到14:55（涨停/止损优先）", "hold"
    if env_score == 0:
        return "10:00卖出（S0 环境 0/3）", "bplus-sell"
    b = breadth_1000 if breadth_1000 is not None else breadth
    if now_dt.time() < _dt.time(10, 0):
        return f"10:00待判（S1，宽度 {b if b is not None else '—'}/2）", "bplus-pending"
    if b is not None and b >= 2:
        return f"持有到14:55（S1 宽度 {b}/2）", "bplus-hold"
    return f"10:00卖出（S1 宽度 {b if b is not None else '—'}/2 <2）", "bplus-sell"


def compute_sell_signal(holding, quote, env_good, breadth, now_dt=None, breadth_1000=None, env_score=None):
    """B+ 执行口径卖出信号：涨停价卖 / 止损卖 / 10:00卖出 / 待定 / 持有到14:55。
    原「弱势卖」降级为 note 参考字段。"""
    now_dt = now_dt or _dt.datetime.now()
    if not quote or quote.get("now") is None:
        return {"signal": "数据缺失", "reason": "无实时快照", "note": None, "pnlPct": None}
    now, op, avg, last = quote.get("now"), quote.get("open"), quote.get("avg"), quote.get("lastClose")
    cost = _f(holding.get("cost"))
    pnl = _pct(now, cost) if cost else None
    env_label = "好" if env_good else "差"
    b1000 = breadth_1000 if breadth_1000 is not None else breadth
    weak = bool(op and avg and last and now < op and now < avg and now < last)
    note = "现价<开盘/均价/昨收（弱势参考）" if weak else None

    # 1) 涨停价卖（优先）
    limit_price = _limit_up_price(holding.get("code"), last)
    if limit_price is not None and now >= limit_price - 0.005:
        return {
            "signal": "涨停价卖", "reason": f"已触及涨停价 {limit_price:.2f}（优先卖出）",
            "note": note, "pnlPct": pnl, "limitUpPrice": limit_price,
            "env": env_label, "breadth": breadth, "breadth1000": b1000,
        }
    # 2) -5% 止损（最高优先级）
    if cost and now <= cost * 0.95:
        return {
            "signal": "止损卖", "reason": f"现价 {now:.2f} ≤ 成本×0.95（{cost * 0.95:.2f}）→ 止损卖（-5% 优先）",
            "note": note, "pnlPct": pnl, "env": env_label, "breadth": breadth, "breadth1000": b1000,
        }
    # 3) B+ 环境/10:00 宽度
    text, typ = bplus_action(env_label, breadth, now_dt, breadth_1000, env_score)
    if typ == "bplus-pending":
        text = f"待定（10:00 看宽度，当前 {breadth}/7）"
    if typ == "bplus-sell":
        reason = f"T-1环境差；10:00 宽度 {b1000}/7 ≤3 → 10:00卖出"
    elif typ == "bplus-hold":
        if env_good:
            reason = "T-1环境好 → 持有到14:55（涨停/止损优先）"
        else:
            reason = f"T-1环境差但 10:00 宽度 {b1000}/7 ≥4 → 持有到14:55（涨停/止损优先）"
    elif typ == "hold":
        reason = "T-1环境好 → 持有到14:55（涨停/止损优先）"
    else:
        reason = f"T-1环境差；当前宽度 {breadth}/7；10:00 前待判，10:00 再看宽度"
    return {
        "signal": text, "reason": reason, "note": note, "pnlPct": pnl,
        "env": env_label, "breadth": breadth, "breadth1000": b1000,
    }

# ---------------------------------------------------------------- 实时 K 线（v2）
def _display_ts(dt):
    """本地挂钟时间 → 秒（前端按 UTC 渲染，与主看板时间口径一致）。"""
    return calendar.timegm((dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, 0, 0, 0))


def _fmt_ymd(d):
    d = str(d or '').replace('-', '')
    return d[:4] + '-' + d[4:6] + '-' + d[6:8] if len(d) == 8 else str(d or '')


def _vipdoc_dir():
    base = os.environ.get('TDX_VIPDOC', '')
    if base and os.path.isdir(base):
        return base
    for cand in (r'C:/new_tdx64/vipdoc', r'D:/new_tdx/vipdoc', r'D:/new_tdx_mock/vipdoc'):
        if os.path.isdir(cand):
            return cand
    try:
        from AICode.MarcoAPI.Update.Path import PATH_TDX  # type: ignore
        tdx = PATH_TDX().replace('\\', '/')
        cand = tdx.split('/PYPlugins')[0] + '/vipdoc'
        if os.path.isdir(cand):
            return cand
    except BaseException:
        pass
    return r'C:/new_tdx64/vipdoc'


def _lc5_path(code):
    code = str(code or '').upper()
    mkt = 'sh' if code.endswith('.SH') else ('sz' if code.endswith('.SZ') else 'bj')
    return os.path.join(_vipdoc_dir(), mkt, 'fzline', f'{mkt}{code[:6]}.lc5')


def _parse_lc5(path):
    """通达信 .lc5（32 字节/根）：date(u16), minute(u16), OHLC(f32*4), amount(f32), volume(u32), reserved(u32)。"""
    raw = open(path, 'rb').read()
    out = []
    for i in range(len(raw) // 32):
        rec = raw[i * 32:(i + 1) * 32]
        try:
            date, minute, op, hi, lo, cl, amount, vol, _reserved = struct.unpack('<HHfffffII', rec)
            year = date // 2048 + 2004
            rem = date % 2048
            month, day = rem // 100, rem % 100
            hh, mm = divmod(minute, 60)
            dt = _dt.datetime(year, month, day, hh, mm)
        except (struct.error, ValueError):
            continue
        if op <= 0 or cl <= 0:
            continue
        out.append({
            'time': _display_ts(dt), 'open': float(op), 'high': float(hi),
            'low': float(lo), 'close': float(cl), 'volume': float(vol),
        })
    out.sort(key=lambda b: b['time'])
    return out


def _lday_path(code):
    code = str(code or "").upper()
    mkt = 'sh' if code.endswith('.SH') else ('sz' if code.endswith('.SZ') else 'bj')
    return os.path.join(_vipdoc_dir(), mkt, 'lday', f'{mkt}{code[:6]}.lday')


def _parse_lday_daily(path):
    """vipdoc lday 原始日线：[(YYYY-MM-DD, close), ...]（价格以分为单位）。"""
    out = []
    try:
        raw = open(path, 'rb').read()
    except OSError:
        return out
    for i in range(len(raw) // 32):
        try:
            date, op, hi, lo, cl, _amount, _vol, _r = struct.unpack('<IIIIIfII', raw[i * 32:(i + 1) * 32])
            year, rem = date // 10000, date % 10000
            month, day = rem // 100, rem % 100
            if not (1990 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31) or op <= 0 or cl <= 0:
                continue
            out.append((f'{year:04d}-{month:02d}-{day:02d}', cl / 100.0))
        except struct.error:
            continue
    out.sort(key=lambda x: x[0])
    return out


def _raw_daily_closes(code):
    """原始价日线收盘：优先由该股 5m 按日聚合最后一根 close（与蜡烛同口径）；不足再回退 lday。"""
    by_day = {}
    try:
        bars = _parse_lc5(_lc5_path(code))
        for b in bars:
            d = _dt.datetime.utcfromtimestamp(b['time']).strftime('%Y-%m-%d')
            by_day[d] = b['close']
    except BaseException:
        by_day = {}
    lc = sorted(by_day.items())
    if len(lc) >= 60:
        return lc
    lday = _parse_lday_daily(_lday_path(code))
    return lday if len(lday) > len(lc) else lc


def _parse_aidata_5m(path):
    text = _read_text(path)
    out = []
    for line in text.splitlines():
        parts = line.split('|')
        if len(parts) < 6:
            continue
        try:
            dt = _dt.datetime.strptime(parts[0].strip()[:19], '%Y-%m-%d %H:%M:%S')
            op, hi, lo, cl = float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])
            vol = float(parts[5])
        except ValueError:
            continue
        out.append({'time': _display_ts(dt), 'open': op, 'high': hi, 'low': lo,
                    'close': cl, 'volume': vol})
    out.sort(key=lambda b: b['time'])
    return out


def _parse_1d_daily(path):
    text = _read_text(path)
    out = []
    for line in text.splitlines():
        parts = line.split('|')
        if len(parts) < 5:
            continue
        d = parts[0].strip()[:8]
        try:
            close = float(parts[4])
        except ValueError:
            continue
        if len(d) == 8 and close > 0:
            out.append((d[:4] + '-' + d[4:6] + '-' + d[6:8], close))
    out.sort(key=lambda x: x[0])
    return out


def load_realtime_kline(code, root, data_dir, days=10):
    """实时看盘 5m K 线：优先 TDX vipdoc/*.lc5，缺文件回退 AIData/5M；日线 MA 取 AIData/1D（截至前一交易日）。"""
    code = str(code or '').upper()
    if not _ensure_code(code):
        return {'ok': False, 'exists': False, 'error': '非法股票代码'}
    days = max(3, min(30, int(days or 10)))
    bars = []
    source = None
    err = None
    try:
        lc5 = _lc5_path(code)
        if os.path.isfile(lc5) and os.path.getsize(lc5) >= 32:
            bars = _parse_lc5(lc5)
            if bars:
                source = 'tdx-lc5'
    except BaseException as exc:  # noqa: BLE001
        err = f'{type(exc).__name__}: {exc}'
    if not bars:
        p5 = os.path.join(data_dir, '5M', code)
        try:
            if os.path.isfile(p5):
                bars = _parse_aidata_5m(p5)
                if bars:
                    source = 'AIData-5M'
        except BaseException as exc:  # noqa: BLE001
            err = f'{type(exc).__name__}: {exc}'
    if not bars:
        return {'ok': False, 'exists': False, 'code': code, 'period': '5m',
                'error': err or '本地无该股 5m 数据（TDX vipdoc 与 AIData/5M 均缺失）',
                'bars': [], 'dailyMa': {}, 'asOf': None}

    dates = sorted({_dt.datetime.utcfromtimestamp(b['time']).strftime('%Y-%m-%d') for b in bars})
    keep = set(dates[-days:])
    bars = [b for b in bars if _dt.datetime.utcfromtimestamp(b['time']).strftime('%Y-%m-%d') in keep]
    dates = [d for d in dates if d in keep]

    # 日线：优先 vipdoc lday/5m 原始价（与 5m 蜡烛同口径）；缺失才回退 AIData/1D
    daily = _raw_daily_closes(code)
    if not daily:
        for sub in ('1D', 'INDEX'):
            p = os.path.join(data_dir, sub, code)
            if os.path.isfile(p):
                daily = _parse_1d_daily(p)
                break
    daily_dates = [d for d, _ in daily]
    daily_closes = [c for _, c in daily]

    periods = [5, 10, 20, 30, 60, 120]
    day_ma = {p: [] for p in periods}
    daily_ref = []
    first_time = {}
    for b in bars:
        d = _dt.datetime.utcfromtimestamp(b['time']).strftime('%Y-%m-%d')
        first_time.setdefault(d, b['time'])
    for d in dates:
        idx = bisect.bisect_left(daily_dates, d) if daily_dates else 0
        vals = {}
        for p in periods:
            if idx >= p:
                vals[p] = round(sum(daily_closes[idx - p:idx]) / p, 3)
                day_ma[p].append({'time': first_time[d], 'value': vals[p]})
        daily_ref.append({'date': d, 'close': daily_closes[idx - 1] if idx > 0 else None,
                          'ma5': vals.get(5), 'ma60': vals.get(60)})

    as_of = dates[-1] if dates else None
    today = _dt.date.today().strftime('%Y-%m-%d')
    return {
        'ok': True, 'exists': True, 'code': code, 'period': '5m', 'source': source,
        'asOf': as_of, 'today': today, 'hasToday': as_of == today,
        'count': len(bars), 'bars': bars,
        'dailyMa': {str(k): v for k, v in day_ma.items()},
        'dailyRef': daily_ref[-5:],
        'error': err,
    }



class RealtimeFeed:
    def __init__(self, root, dashboard_dir, data_dir, get_picks=None, interval=2.0, strategy_name="TPO_M5"):
        self.root = root
        self.strategy_name = strategy_name or "TPO_M5"
        self.dashboard_dir = dashboard_dir
        self.data_dir = data_dir
        self.index5m_dir = os.path.join(data_dir, "INDEX_5M")
        self.strategy_dir = os.path.join(data_dir, "STRATEGY", "TPO_M5")
        self.holdings_path = os.path.join(dashboard_dir, "holdings.json")
        self.get_picks = get_picks or (lambda: None)
        self.interval = max(1.0, float(interval))

        self._lock = threading.Lock()
        self._state = self._empty_state(initializing=True)
        self._stop = threading.Event()
        self._thread = None

        self._tq = None
        self._tq_error = None
        self._tq_retry_at = 0.0
        self._tq_lock = threading.Lock()

        self._candidates = []
        self._candidate_date = None
        self._candidates_at = 0.0
        self._candidates_retry_at = 0.0

        self._env_cache = None
        self._env_at = 0.0

        self._holdings = []
        self._holdings_mtime = -1.0
        self._name_cache = {}
        self._picks = None
        self.next_day_path = os.environ.get("NEXT_DAY_PATH") or os.path.join(data_dir, "NEXT_DAY", "strategy.json")
        self.preclose_path = os.environ.get("PRECLOSE_PATH") or os.path.join(data_dir, "NEXT_DAY", "preclose_strategy.json")
        self._nextday_source = None
        self._nextday_cache = None
        self._nextday_mtime = -1.0
        self._breadth_1000 = {"date": None, "value": None}
        self._error_log_at = 0.0

    # ------------------------------------------------------------ lifecycle
    def start(self):
        if self._thread and self._thread.is_alive():
            return self
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="realtime-feed", daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=3)

    def snapshot(self):
        with self._lock:
            return copy.deepcopy(self._state)

    def get_holdings(self):
        return copy.deepcopy(self._read_holdings())

    def name_for(self, code):
        code = _ensure_code(code)
        if not code:
            return None
        try:
            self._ensure_tq()
            return self._stock_name(code)
        except BaseException:
            return None

    def set_holdings(self, rows):
        cleaned = self._validate_holdings(rows, strict=True)
        os.makedirs(self.dashboard_dir, exist_ok=True)
        tmp = self.holdings_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cleaned, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.holdings_path)
        with self._lock:
            self._holdings = cleaned
            self._holdings_mtime = os.path.getmtime(self.holdings_path) if os.path.exists(self.holdings_path) else 0
        return copy.deepcopy(cleaned)

    # ------------------------------------------------------------ tqcenter
    def _ensure_tq(self):
        if self._tq is not None:
            return True
        if time.time() < self._tq_retry_at:
            return False
        try:
            tdx_path = ""
            try:
                sys.path.insert(0, self.root)
                from AICode.MarcoAPI.Update.Path import PATH_TDX  # type: ignore
                tdx_path = PATH_TDX()
            except BaseException:
                tdx_path = os.environ.get("TDX_PLUGIN_PATH", "")
            if not tdx_path:
                tdx_path = os.environ.get("TDX_PLUGIN_PATH", r"C:/new_tdx64/PYPlugins/user")
            if tdx_path and tdx_path not in sys.path:
                sys.path.append(tdx_path)
            from tqcenter import tq  # type: ignore
            tq.initialize(__file__)
            self._tq = tq
            self._tq_error = None
            print("[realtime] tqcenter 已连接")
            return True
        except BaseException as exc:  # noqa: BLE001
            self._tq = None
            self._tq_error = f"{type(exc).__name__}: {exc}"
            self._tq_retry_at = time.time() + 30
            self._log(f"tqcenter 初始化失败（30s 重试）: {self._tq_error}")
            return False

    def _snapshot(self, code):
        tq = self._tq
        if tq is None:
            raise RuntimeError(self._tq_error or "tqcenter 未连接")
        with self._tq_lock:
            d = tq.get_market_snapshot(stock_code=code)
        if not isinstance(d, dict) or not d:
            raise RuntimeError("空快照")
        if str(d.get("ErrorId", "0")) != "0":
            raise RuntimeError(d.get("Error") or "快照 ErrorId!=0")
        now = _f(d.get("Now"))
        last = _f(d.get("LastClose"))
        if now is None or last is None or now <= 0:
            raise RuntimeError("快照无有效现价")
        q = {
            "code": code,
            "now": now,
            "lastClose": last,
            "open": _f(d.get("Open")),
            "max": _f(d.get("Max")),
            "min": _f(d.get("Min")),
            "avg": _f(d.get("Average")),
            "volume": _f(d.get("Volume")),
            "amount": _f(d.get("Amount")),
            "zangsu": _f(d.get("Zangsu")),
            "bid1": _f((d.get("Buyp") or [None])[0]) if isinstance(d.get("Buyp"), list) else _f(d.get("Buyp")),
            "ask1": _f((d.get("Sellp") or [None])[0]) if isinstance(d.get("Sellp"), list) else _f(d.get("Sellp")),
        }
        q["zaf"] = _pct(now, last)
        return q

    def _stock_name(self, code):
        if code in self._name_cache:
            return self._name_cache[code]
        name = None
        if self._tq is not None:
            try:
                with self._tq_lock:
                    info = self._tq.get_stock_info(stock_code=code)
                if isinstance(info, dict):
                    name = info.get("Name") or None
            except BaseException:
                name = None
        if name:
            self._name_cache[code] = name
        return name

    # ------------------------------------------------------------ data/candidates
    def _dates(self):
        try:
            return sorted([n for n in os.listdir(self.strategy_dir) if n.isdigit() and len(n) == 8], reverse=True)
        except OSError:
            return []

    def _first_strategy_row(self, date):
        try:
            text = _read_text(os.path.join(self.strategy_dir, date))
        except OSError:
            return None
        for line in text.splitlines():
            parts = line.split("|")
            if len(parts) >= 2 and _ensure_code(parts[0]):
                return parts[0].strip().upper(), (parts[1] or "").strip()
        return None

    def _refresh_candidates(self, force=False):
        now = time.time()
        if not force and self._candidates and (now - self._candidates_at) < 60:
            return
        if not force and now < self._candidates_retry_at:
            return
        dates = self._dates()
        latest = dates[0] if dates else None
        picks = None
        try:
            picks = self.get_picks()
        except BaseException as exc:  # noqa: BLE001
            self._log(f"候选/ picks 读取失败: {type(exc).__name__}: {exc}")
            picks = None
        out = []
        seen = set()

        def add(code, name, source):
            code = _ensure_code(code)
            if not code or code in seen:
                return
            seen.add(code)
            out.append({"code": code, "name": (name or "").strip(), "source": source})

        if latest:
            row = self._first_strategy_row(latest)
            if row:
                add(row[0], row[1], "T-0")
        self._picks = picks
        tw = (picks or {}).get("tpoWindow") or {}
        for r in tw.get("T") or []:
            if isinstance(r, (list, tuple)) and len(r) >= 2:
                add(r[0], r[1], "T")
        for r in tw.get("TM1") or []:
            if isinstance(r, (list, tuple)) and len(r) >= 2:
                add(r[0], r[1], "T-1")
        # picks 尚未预热（无 T/T-1）时兜底：读最新两个 STRATEGY 日期首行
        if not any(c["source"] in ("T", "T-1") for c in out) and len(dates) >= 2:
            row = self._first_strategy_row(dates[1])
            if row:
                add(row[0], row[1], "T-1")
        if out:
            self._candidates = out
            self._candidate_date = latest
            self._candidates_at = now
            self._candidates_retry_at = 0
        else:
            self._candidates_retry_at = now + 30

    # ------------------------------------------------------------ env
    def _daily_closes(self, code):
        path = os.path.join(self.index5m_dir, code)
        try:
            text = _read_text(path)
        except OSError:
            return []
        daily = {}
        for line in text.splitlines():
            parts = line.split("|")
            if len(parts) < 5:
                continue
            day = parts[0][:10]
            close = _f(parts[4])
            if day and close is not None:
                daily[day] = close
        return [(d, daily[d]) for d in sorted(daily)]

    def _refresh_env(self, force=False):
        now = time.time()
        if not force and self._env_cache and (now - self._env_at) < 300:
            return
        env_indexes = [("000300.SH", "沪深300"), ("399006.SZ", "创业板指"), ("399986.SZ", "中证银行")]
        details = []
        flags = {}
        t1_date = None
        valid = True
        for code, name in env_indexes:
            closes = self._daily_closes(code)
            if len(closes) < 61:
                details.append({"code": code, "name": name, "ok": False})
                valid = False
                continue
            ma60 = sum(c for _d, c in closes[-61:-1]) / 60.0
            day, last = closes[-1]
            t1_date = t1_date or day
            is_above = last > ma60
            flags[code] = is_above
            details.append({
                "code": code, "name": name, "ok": True, "date": day,
                "close": round(last, 2), "ma60": round(ma60, 2), "above": is_above,
            })
        if valid and len(flags) == 3:
            score = int(bool(flags.get("000300.SH"))) + int(bool(flags.get("399006.SZ"))) + int(not bool(flags.get("399986.SZ")))
            sell_rule = "持有到14:55" if score >= 2 else ("10:00看300+创指宽度" if score == 1 else "10:00卖出")
            self._env_cache = {
                "t1": ("好" if score >= 2 else "差"),
                "score": score, "state": f"S{score}",
                "above": sum(1 for x in details if x.get("above")),
                "total": 3, "date": t1_date, "details": details, "mode": "s6",
                "rule": "S6：沪深300上+1、创业板指上+1、中证银行≤MA60+1",
                "sellRule": sell_rule,
            }
        else:
            self._env_cache = {
                "t1": None, "score": None, "state": "不可用",
                "above": None, "total": 3, "date": t1_date,
                "details": details, "mode": "s6",
                "rule": "S6 三指数数据不足 → 环境不可用（回退满仓·14:55）",
                "sellRule": "回退满仓·持有到14:55",
            }
        self._env_at = now

    # ------------------------------------------------------------ holdings
    def _validate_holdings(self, rows, strict=False):
        out = []
        if not isinstance(rows, (list, tuple)):
            raise ValueError("holdings 需为数组")
        for r in rows[:100]:
            if not isinstance(r, dict):
                if strict:
                    raise ValueError("holdings 每项需为对象 {code,cost,qty}")
                continue
            code = _ensure_code(r.get("code"))
            if not code:
                if strict:
                    raise ValueError(f"非法股票代码：{r.get('code')}")
                continue
            item = {"code": code}
            cost = _f(r.get("cost"))
            qty = _f(r.get("qty"))
            if cost is not None:
                item["cost"] = round(cost, 4)
            if qty is not None:
                item["qty"] = int(qty) if float(qty).is_integer() else qty
            name = (r.get("name") or "").strip()
            if name:
                item["name"] = name
            out.append(item)
        return out

    def _read_holdings(self):
        path = self.holdings_path
        if not os.path.exists(path):
            self._holdings = []
            self._holdings_mtime = -1.0
            return self._holdings
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return self._holdings
        if mtime == self._holdings_mtime:
            return self._holdings
        try:
            raw = _read_text(path)
            data = json.loads(raw) if raw.strip() else []
            self._holdings = self._validate_holdings(data)
            self._holdings_mtime = mtime
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self._log(f"holdings.json 解析失败（按空处理）: {type(exc).__name__}: {exc}")
            self._holdings = []
            self._holdings_mtime = mtime
        return self._holdings

    # ------------------------------------------------------------ poll / state
    def _empty_state(self, initializing=False):
        st, label = market_state()
        return {
            "ok": True,
            "initializing": bool(initializing),
            "time": _dt.datetime.now().isoformat(timespec="seconds"),
            "marketState": st,
            "marketLabel": label,
            "source": "tqcenter",
            "interval": self.interval,
            "env": {"t1": None, "t1Label": "数据缺失", "breadth": None, "breadthTotal": 3,
                    "label": "初始化中", "above": None, "date": None},
            "indices": [],
            "candidates": [],
            "holdings": [],
            "strategy": None,
            "nextDay": {"available": False, "reason": "初始化中", "sellPlan": {"mode": "B+", "rule": "差环境10:00看3指数宽度≥2抗/≤1卖", "stop": -0.05}},
            "holdingsToday": [],
            "candidatesTomorrow": [],
            "closedYesterday": [],
            "error": None,
            "tq": {"ready": False, "error": None},
        }


    # ------------------------------------------------------------ NEXT_DAY artifact
    def _load_next_day(self):
        """读 AIData/NEXT_DAY/strategy.json（每日更新产出）；过期/缺失时返回 available=False。"""
        now = _dt.datetime.now()
        force_pre = os.environ.get("PRECLOSE_FORCE_WINDOW") == "1"
        in_window = force_pre or (_dt.time(14, 45) <= now.time() < _dt.time(15, 50))
        pre_exists = os.path.isfile(self.preclose_path)
        use_pre = bool(in_window and pre_exists)
        source = "preclose" if use_pre else "formal"
        path = self.preclose_path if use_pre else self.next_day_path
        try:
            mtime = os.path.getmtime(path) if os.path.isfile(path) else -1.0
        except OSError:
            mtime = -1.0
        today = _dt.date.today()
        nxt = today + _dt.timedelta(days=1)
        while nxt.weekday() >= 5:
            nxt += _dt.timedelta(days=1)
        base = {
            "available": False, "reason": None, "generatedAt": None,
            "buyDate": None, "buyDateLabel": None,
            "forTradeDate": None, "forTradeDateLabel": None,
            "firstPick": None, "buyList": [], "candidates": [], "env": None,
            "file": path, "today": today.strftime("%Y-%m-%d"),
            "nextTradeDate": nxt.strftime("%Y-%m-%d"),
            "source": source, "preclose": source == "preclose",
            "precloseActive": source == "preclose",
            "label": "14:45 预生成（尾盘买入用）" if source == "preclose" else "每日更新正式名单",
        }
        if mtime < 0:
            base["reason"] = "名单未生成（等每日更新）"
            return base
        if self._nextday_cache is not None and mtime == self._nextday_mtime \
                and self._nextday_source == source:
            return self._nextday_cache
        try:
            raw = json.loads(_read_text(path))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            base["reason"] = f"名单解析失败（{type(exc).__name__}）"
            self._nextday_cache = base
            self._nextday_mtime = mtime
            return base
        if not isinstance(raw, dict):
            base["reason"] = "名单格式错误（非对象）"
            self._nextday_cache = base
            self._nextday_mtime = mtime
            return base

        def ymd(v):
            t = str(v or "").replace("-", "").strip()
            return t if len(t) == 8 and t.isdigit() else None

        buy_date = ymd(raw.get("buyDate"))
        ft = ymd(raw.get("forTradeDate"))
        today_s = today.strftime("%Y%m%d")
        next_s = nxt.strftime("%Y%m%d")
        buy_list = []
        for it in raw.get("buyList") or []:
            if not isinstance(it, dict):
                continue
            code = _ensure_code(it.get("code"))
            if not code:
                continue
            buy_list.append({
                "code": code,
                "name": (it.get("name") or "").strip(),
                "buyPrice": _f(it.get("buyPrice")),
                "marketValue": _f(it.get("marketValue")),
                "ma5Pred": bool(it.get("ma5Pred")),
            })
        candidates = []
        for it in raw.get("candidates") or []:
            if not isinstance(it, dict):
                continue
            code = _ensure_code(it.get("code"))
            if not code:
                continue
            candidates.append({"code": code, "name": (it.get("name") or "").strip(),
                               "source": (it.get("source") or "下一交易日预选").strip()})
        first = raw.get("firstPick")
        first_pick = None
        if isinstance(first, dict) and _ensure_code(first.get("code")):
            first_pick = {
                "code": _ensure_code(first.get("code")),
                "name": (first.get("name") or "").strip(),
                "buyPrice": _f(first.get("buyPrice")),
                "marketValue": _f(first.get("marketValue")),
            }
        elif buy_list:
            first_pick = {k: buy_list[0].get(k) for k in ("code", "name", "buyPrice", "marketValue")}

        empty = not buy_list
        available = bool(ft) and ft in (today_s, next_s)
        reason = None
        if not ft:
            reason = "名单缺少 forTradeDate"
        elif ft < today_s:
            reason = f"名单已过期（forTradeDate={ft}）"
        elif ft not in (today_s, next_s):
            reason = f"名单日期不是今日/下一交易日（forTradeDate={ft}）"
        elif empty:
            reason = "下个交易日无首选/空仓（TPO 名单为空）"

        env_art = raw.get("env") if isinstance(raw.get("env"), dict) else None
        result = {
            "available": available,
            "empty": empty,
            "emptyLabel": "下个交易日无首选/空仓" if empty else None,
            "reason": reason,
            "generatedAt": raw.get("generatedAt"),
            "buyDate": buy_date,
            "buyDateLabel": _fmt_ymd(buy_date) if buy_date else today.strftime("%Y-%m-%d"),
            "forTradeDate": ft,
            "forTradeDateLabel": _fmt_ymd(ft) if ft else nxt.strftime("%Y-%m-%d"),
            "firstPick": first_pick,
            "buyList": buy_list,
            "candidates": candidates,
            "env": env_art,
            "file": path,
            "today": today.strftime("%Y-%m-%d"),
            "nextTradeDate": nxt.strftime("%Y-%m-%d"),
            "strategy": raw.get("strategy") or self.strategy_name,
            "source": source,
            "preclose": source == "preclose",
            "precloseActive": source == "preclose",
            "label": "14:45 预生成（尾盘买入用）" if source == "preclose" else "每日更新正式名单",
            "precloseExpired": bool(source == "formal" and pre_exists and not in_window),
        }
        self._nextday_cache = result
        self._nextday_mtime = mtime
        self._nextday_source = source
        return result


    def _breadth_1000_value(self, now_dt, breadth):
        """10:00 宽度缓存：当日首次到达 10:00 时记录成长端红盘宽度；未到 10:00 返回 None。"""
        if breadth is None:
            return None
        if now_dt.time() < _dt.time(10, 0):
            return None
        today = now_dt.strftime("%Y%m%d")
        if self._breadth_1000.get("date") != today or self._breadth_1000.get("value") is None:
            self._breadth_1000 = {"date": today, "value": breadth}
        return self._breadth_1000["value"]

    def _poll_once(self):
        now_dt = _dt.datetime.now()
        st, label = market_state(now_dt)
        self._refresh_env()
        self._refresh_candidates()
        holdings_in = list(self._read_holdings())
        next_day = self._load_next_day()
        env = copy.deepcopy(self._env_cache) if self._env_cache else {}

        tq_ready = self._ensure_tq()
        quotes = {}
        errors = {}
        if tq_ready:
            codes = [c for c, _ in ALL_INDEXES]
            codes += [c["code"] for c in self._candidates]
            codes += [x.get("code") for x in (next_day.get("buyList") or [])]
            codes += [x.get("code") for x in (next_day.get("candidates") or [])]
            if next_day.get("firstPick"):
                codes.append(next_day["firstPick"].get("code"))
            codes += [h["code"] for h in holdings_in]
            seen = set()
            for code in codes:
                if code in seen:
                    continue
                seen.add(code)
                try:
                    quotes[code] = self._snapshot(code)
                except BaseException as exc:  # noqa: BLE001
                    errors[code] = f"{type(exc).__name__}: {exc}"

        # 10:00 红盘宽度：S6 只用沪深300+创业板指（不含银行）
        width_details = []
        breadth = None
        for code, name in WIDTH_INDEXES:
            q = quotes.get(code) or {}
            closes = self._daily_closes(code)
            prev_daily = closes[-1][1] if closes else None
            nowp = q.get("now")
            red = bool(nowp and prev_daily and nowp > prev_daily)
            width_details.append({"code": code, "name": name, "now": nowp,
                                  "prevDailyClose": round(prev_daily, 2) if prev_daily else None,
                                  "red": red})
        if all(x["now"] is not None and x["prevDailyClose"] is not None for x in width_details):
            breadth = sum(1 for x in width_details if x["red"])
        breadth_1000 = self._breadth_1000_value(now_dt, breadth)
        env_score = env.get("score")
        env_good = (env_score is not None and env_score >= 2)

        indices = []
        for code, name in ALL_INDEXES:
            q = quotes.get(code) or {}
            indices.append({
                "code": code, "name": name,
                "now": q.get("now"), "lastClose": q.get("lastClose"),
                "zaf": q.get("zaf"), "avg": q.get("avg"),
                "growth": code in dict(GROWTH_INDEXES),
            })

        candidates = []
        for c in self._candidates:
            q = quotes.get(c["code"])
            sig = compute_buy_signal(q, env_good, breadth)
            candidates.append({
                "code": c["code"], "name": c["name"],
                "source": c["source"],
                "now": q.get("now") if q else None,
                "lastClose": q.get("lastClose") if q else None,
                "zaf": q.get("zaf") if q else None,
                "open": q.get("open") if q else None,
                "avg": q.get("avg") if q else None,
                "zangsu": q.get("zangsu") if q else None,
                "score": sig.get("score"),
                "signal": sig["signal"],
                "reason": sig["reason"],
                "limitUp": sig.get("limitUp", False),
                "missing": q is None,
            })

        holdings_out = []
        for h in holdings_in:
            q = quotes.get(h["code"])
            sig = compute_sell_signal(h, q, env_good, breadth, now_dt, breadth_1000, env_score)
            name = h.get("name") or self._stock_name(h["code"]) or ""
            holdings_out.append({
                "code": h["code"], "name": name,
                "cost": h.get("cost"), "qty": h.get("qty"),
                "now": q.get("now") if q else None,
                "lastClose": q.get("lastClose") if q else None,
                "zaf": q.get("zaf") if q else None,
                "avg": q.get("avg") if q else None,
                "open": q.get("open") if q else None,
                "pnlPct": sig.get("pnlPct"),
                "signal": sig["signal"],
                "reason": sig["reason"],
                "sellNote": sig.get("note"),
                "missing": q is None,
            })

        env_state = {
            "t1": env.get("t1"),
            "t1Label": ("T-1环境 好" if env.get("t1") == "好" else ("T-1环境 差" if env.get("t1") == "差" else "T-1环境 数据缺失")),
            "above": env.get("above"),
            "total": env.get("total"),
            "date": env.get("date"),
            "breadth": breadth,
            "breadthTotal": 3,
            "widthDetails": width_details,
            "details": env.get("details") or [],
            "label": (f"T-1环境 {env.get('state') or '—'} · 盘中宽度 {breadth if breadth is not None else '—'}/2"),
        }
        error = None
        if not tq_ready:
            error = self._tq_error or "tqcenter 未连接"
        elif not quotes:
            error = "实时快照无有效数据（tqcenter 可能未连通达信）"
        elif errors and len(quotes) == 0:
            error = next(iter(errors.values()))

        # ---------- v2：当日策略 / 今日持仓(T) / 明日预选(T-1) / 昨日已了结(T-0) ----------
        def _cand_row(c):
            q = quotes.get(c["code"])
            sig = compute_buy_signal(q, env_good, breadth)
            return {
                "code": c["code"], "name": c["name"], "source": c["source"],
                "now": q.get("now") if q else None,
                "lastClose": q.get("lastClose") if q else None,
                "zaf": q.get("zaf") if q else None,
                "open": q.get("open") if q else None,
                "avg": q.get("avg") if q else None,
                "zangsu": q.get("zangsu") if q else None,
                "score": sig.get("score"), "signal": sig["signal"],
                "reason": sig["reason"], "limitUp": sig.get("limitUp", False),
                "missing": q is None,
            }

        # next_day 已在本次轮询开头加载（用于补充报价代码）
        # 环境以实时三指数计算为准；artifact 的旧 7 指数 env 仅在新计算不可用时兜底
        if isinstance(next_day.get("sellPlan"), dict):
            next_day["sellPlan"]["rule"] = "差环境 10:00 看 3 指数宽度（≥2 抗/≤1 卖）；-5%止损；涨停价优先"
        strategy_env = env
        if strategy_env.get("t1") not in ("好", "差") and next_day.get("available") \
                and isinstance(next_day.get("env"), dict) \
                and next_day["env"].get("t1") in ("好", "差"):
            strategy_env = next_day["env"]
        if next_day.get("available") and strategy_env.get("details"):
            next_day["env"] = strategy_env
        env_good_now = strategy_env.get("t1") == "好"
        env_score_now = strategy_env.get("score")

        holdings_today = []
        candidates_tomorrow = []
        if next_day.get("available"):
            fp = next_day.get("firstPick") or {}
            fp_code = fp.get("code")
            for item in next_day.get("buyList") or []:
                code = item["code"]
                q = quotes.get(code)
                cost = item.get("buyPrice")
                if cost is None and q:
                    cost = q.get("lastClose")
                sell = compute_sell_signal({"code": code, "cost": cost}, q,
                                           env_good_now, breadth, now_dt, breadth_1000, env_score_now)
                holdings_today.append({
                    "code": code, "name": item.get("name") or self._stock_name(code) or "",
                    "source": "NEXT_DAY", "buyPrice": cost, "cost": cost,
                    "marketValue": item.get("marketValue"), "ma5Pred": item.get("ma5Pred"),
                    "firstPick": bool(fp_code and code == fp_code),
                    "now": q.get("now") if q else None,
                    "lastClose": q.get("lastClose") if q else None,
                    "zaf": q.get("zaf") if q else None,
                    "open": q.get("open") if q else None,
                    "avg": q.get("avg") if q else None,
                    "pnlPct": sell.get("pnlPct"),
                    "sellSignal": sell.get("signal"),
                    "sellReason": sell.get("reason"),
                    "sellNote": sell.get("note"),
                    "missing": q is None,
                })
            for item in next_day.get("candidates") or []:
                q = quotes.get(item["code"])
                sig = compute_buy_signal(q, env_good_now, breadth)
                candidates_tomorrow.append({
                    "code": item["code"], "name": item.get("name") or self._stock_name(item["code"]) or "",
                    "source": item.get("source") or "下一交易日预选",
                    "now": q.get("now") if q else None,
                    "lastClose": q.get("lastClose") if q else None,
                    "zaf": q.get("zaf") if q else None,
                    "open": q.get("open") if q else None,
                    "avg": q.get("avg") if q else None,
                    "zangsu": q.get("zangsu") if q else None,
                    "score": sig.get("score"), "signal": sig["signal"],
                    "reason": sig["reason"], "limitUp": sig.get("limitUp", False),
                    "missing": q is None,
                })
        else:
            for c in self._candidates:
                if c["source"] == "T":
                    row = _cand_row(c)
                    cost = row["lastClose"]
                    sell = compute_sell_signal({"code": c["code"], "cost": cost},
                                               quotes.get(c["code"]), env_good, breadth, now_dt, breadth_1000, env_score)
                    row["cost"] = cost
                    row["pnlPct"] = sell.get("pnlPct")
                    row["sellSignal"] = sell.get("signal")
                    row["sellReason"] = sell.get("reason")
                    row["sellNote"] = sell.get("note")
                    row["firstPick"] = False
                    holdings_today.append(row)
                if c["source"] == "T-1":
                    candidates_tomorrow.append(_cand_row(c))

        file_date = self._candidate_date
        closed_yesterday = []
        rows = ((self._picks or {}).get("picks") or {}).get(file_date) or []
        if rows:
            for r in rows:
                if not isinstance(r, dict):
                    continue
                closed_yesterday.append({
                    "code": r.get("code"), "name": r.get("name") or "",
                    "date": file_date, "chg": r.get("chg"),
                    "sellChg5m": r.get("sell_chg_5m"),
                    "mcap": r.get("mcap"),
                })
        elif file_date:
            try:
                text = _read_text(os.path.join(self.strategy_dir, file_date))
                for line in text.splitlines():
                    parts = line.split("|")
                    if len(parts) < 11 or not _ensure_code(parts[0]):
                        continue
                    close = _f(parts[7]); pre = _f(parts[10]); market = _f(parts[2])
                    closed_yesterday.append({
                        "code": parts[0].strip().upper(), "name": (parts[1] or "").strip(),
                        "date": file_date,
                        "chg": round((close - pre) / pre * 100, 2) if close and pre else None,
                        "sellChg5m": None,
                        "mcap": round(market / 1e8, 2) if market else None,
                    })
            except OSError:
                pass

        action_text, action_type = bplus_action(strategy_env.get("t1"), breadth, now_dt, breadth_1000, strategy_env.get("score"))
        if next_day.get("available") and next_day.get("empty"):
            action_text, action_type = "下个交易日空仓（无首选）", "empty"
        next_day["sellPlan"] = {
            "mode": "B+",
            "env": strategy_env.get("t1"),
            "rule": "S6：score≥2持有；score=1看300+创指宽度≥2抗/≤1卖；score0 10:00卖；-5%止损；涨停价优先",
            "stop": -0.05,
            "breadth1000": breadth_1000,
            "actionText": action_text,
            "actionType": action_type,
        }

        def _next_weekday(d):
            n = d + _dt.timedelta(days=1)
            while n.weekday() >= 5:
                n += _dt.timedelta(days=1)
            return n

        today_date = now_dt.date()
        strategy = {
            "name": next_day.get("strategy") or self.strategy_name,
            "fileDate": file_date,
            "fileDateLabel": _fmt_ymd(file_date),
            "tDateLabel": today_date.strftime("%Y-%m-%d"),
            "t1DateLabel": _next_weekday(today_date).strftime("%Y-%m-%d"),
            "t0DateLabel": _fmt_ymd(file_date),
            "nextDayAvailable": bool(next_day.get("available")),
            "nextDaySource": next_day.get("source"),
            "nextDayLabel": next_day.get("label"),
            "nextDayReason": next_day.get("reason"),
            "buyDateLabel": next_day.get("buyDateLabel"),
            "forTradeDateLabel": next_day.get("forTradeDateLabel"),
            "firstPick": next_day.get("firstPick"),
            "env": {
                "t1": strategy_env.get("t1"), "above": strategy_env.get("above"),
                "total": strategy_env.get("total"), "date": strategy_env.get("date"),
                "mode": strategy_env.get("mode") or "s6",
                "rule": strategy_env.get("rule") or "S6 三指数评分",
                "score": strategy_env.get("score"),
                "state": strategy_env.get("state"),
                "sellRule": strategy_env.get("sellRule"),
                "details": strategy_env.get("details") or [],
            },
            "breadth": breadth,
            "breadthTotal": 2,
            "widthDetails": width_details,
            "envScore": env.get("score"),
            "envState": env.get("state"),
            "sellRule": env.get("sellRule"),
            "actionText": action_text,
            "actionType": action_type,
            "sellPlan": next_day["sellPlan"],
            "ruleText": "B+ 卖法：-5% 止损优先；涨停价优先卖出；好环境持有到 14:55；差环境 10:00 看 3 指数红盘宽度（≥2 抗到 14:55 / ≤1 10:00 卖出）（规则摘要，非投资建议）",
        }

        # ---------- 实时最该买（参考评分，不下单） ----------
        pool, seen = [], set()

        def _add_pool(code, name):
            code = _ensure_code(code)
            if code and code not in seen:
                seen.add(code)
                pool.append((code, name or ""))

        for item in next_day.get("buyList") or []:
            _add_pool(item.get("code"), item.get("name"))
        for item in next_day.get("candidates") or []:
            _add_pool(item.get("code"), item.get("name"))
        for item in holdings_today:
            _add_pool(item.get("code"), item.get("name"))
        for item in candidates_tomorrow:
            _add_pool(item.get("code"), item.get("name"))
        for c in self._candidates:
            _add_pool(c.get("code"), c.get("name"))
        top_picks = []
        for code, name in pool:
            q = quotes.get(code)
            if not q or q.get("now") is None:
                continue
            now_p, last_p, op, avg = q.get("now"), q.get("lastClose"), q.get("open"), q.get("avg")
            if now_p and last_p and avg and now_p < last_p and now_p < avg:
                continue
            zaf = q.get("zaf") if q.get("zaf") is not None else (
                (now_p / last_p - 1) * 100 if (now_p and last_p) else 0)
            r_open = (now_p / op - 1) * 100 if (now_p and op) else 0
            r_avg = (now_p / avg - 1) * 100 if (now_p and avg) else 0
            zangsu = q.get("zangsu") or 0
            score = 0.45 * zaf + 0.25 * r_open + 0.20 * r_avg + 0.10 * zangsu
            reason = (f"涨幅{zaf:+.2f}%×45% + 现价/开盘{r_open:+.2f}%×25% + "
                      f"现价/均价{r_avg:+.2f}%×20% + 涨速{zangsu:+.2f}×10%")
            top_picks.append({
                "code": code, "name": name, "now": now_p, "zaf": round(zaf, 2),
                "score": round(score, 3), "reason": reason,
            })
        top_picks.sort(key=lambda x: (-x["score"], x["code"]))
        top_picks = top_picks[:3]
        top_pick_now = top_picks[0] if top_picks else None

        return {
            "ok": True,
            "initializing": False,
            "time": now_dt.isoformat(timespec="seconds"),
            "marketState": st,
            "marketLabel": label,
            "source": "tqcenter",
            "interval": self.interval,
            "env": env_state,
            "indices": indices,
            "candidates": candidates,
            "holdings": holdings_out,
            "strategy": strategy,
            "nextDay": next_day,
            "topPicks": top_picks,
            "topPickNow": top_pick_now,
            "holdingsToday": holdings_today,
            "candidatesTomorrow": candidates_tomorrow,
            "closedYesterday": closed_yesterday,
            "candidateDate": self._candidate_date,
            "error": error,
            "tq": {"ready": bool(tq_ready), "error": self._tq_error},
            "quoteErrors": errors if errors else None,
        }

    def _loop(self):
        while not self._stop.is_set():
            started = time.time()
            try:
                state = self._poll_once()
                with self._lock:
                    self._state = state
            except BaseException as exc:  # noqa: BLE001
                self._log(f"轮询异常: {type(exc).__name__}: {exc}")
                traceback.print_exc()
                with self._lock:
                    st = copy.deepcopy(self._state)
                    st["ok"] = False
                    st["time"] = _dt.datetime.now().isoformat(timespec="seconds")
                    st["error"] = f"{type(exc).__name__}: {exc}"
                    self._state = st
            elapsed = time.time() - started
            self._stop.wait(max(0.2, self.interval - elapsed))

    def _log(self, msg):
        if time.time() - self._error_log_at < 10:
            return
        self._error_log_at = time.time()
        print(f"[realtime] {msg}")
