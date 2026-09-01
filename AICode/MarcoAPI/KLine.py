import json
import os
import webbrowser
import pandas as pd

MA_COLORS = {5: '#FFFFFF', 10: '#FFFF00', 20: '#FFA500',
             30: '#00FF00', 60: '#1E90FF', 120: '#FF69B4'}

# 信号类型 → 颜色 / 显示名
SIGNAL_STYLE = {
    'panic_bottom':    {'color': '#FF5722', 'label': '恐慌底'},
    'breadth_thrust':  {'color': '#4CAF50', 'label': '广度拐点'},
    'ma_golden_cross': {'color': '#FFC107', 'label': 'MA金叉'},
    'breadth_divergence': {'color': '#9C27B0', 'label': '广度背离'},
}


def _norm_date(val):
    """将 yyyyMMdd 转为 yyyy-MM-dd，其他格式不动。"""
    s = str(val)
    if len(s) == 8 and s.isdigit():
        return f'{s[:4]}-{s[4:6]}-{s[6:8]}'
    return s


def _hp_filter(series, lam=100.0):
    """Hodrick-Prescott 滤波器：从时间序列中提取平滑趋势分量。

    Args:
        series: 输入序列（list of float）。
        lam: 平滑参数，越大趋势越平滑（日线默认 100）。

    Returns:
        (trend, cycle) — 趋势分量和周期/残差分量。均为 list[float]。
    """
    import numpy as np
    n = len(series)
    if n < 4:
        return list(series), [0.0] * n
    y = np.array(series, dtype=float)
    I = np.eye(n)
    D = np.zeros((n - 2, n))
    for i in range(n - 2):
        D[i, i] = 1.0
        D[i, i + 1] = -2.0
        D[i, i + 2] = 1.0
    trend = np.linalg.solve(I + lam * D.T @ D, y)
    return trend.tolist(), (y - trend).tolist()


def _top_trend_segments(trend, times):
    """将 HP 趋势按斜率正负拆分为上升段与下降段数据。

    Args:
        trend: HP 趋势值列表。
        times: 对应的时间戳列表（与 trend 等长）。

    Returns:
        (up_segments, dn_segments):
          up_segments — list[{'time':..., 'value':...}], 上升段连续数据；
          dn_segments — list[{'time':..., 'value':...}], 下降段连续数据。
        转折点同时出现在两个列表中以保证线段衔接。
    """
    up_seg, dn_seg = [], []
    n = len(trend)
    if n == 0:
        return up_seg, dn_seg

    up_seg.append({'time': times[0], 'value': round(trend[0], 1)})
    for i in range(1, n):
        t = times[i]
        v = round(trend[i], 1)
        is_up = trend[i] >= trend[i - 1]
        if is_up:
            # 由降转升 → 把上一个点也加入上升段，保证线条连续
            if dn_seg and dn_seg[-1]['time'] == times[i - 1]:
                up_seg.append({'time': times[i - 1], 'value': round(trend[i - 1], 1)})
            up_seg.append({'time': t, 'value': v})
        else:
            if up_seg and up_seg[-1]['time'] == times[i - 1]:
                dn_seg.append({'time': times[i - 1], 'value': round(trend[i - 1], 1)})
            dn_seg.append({'time': t, 'value': v})
    return up_seg, dn_seg


def _hp_trend_markers(trend, times):
    """检测 HP 趋势的局部极值点，标记最佳入场（谷底）和出场（山峰）点。

    Args:
        trend: HP 趋势值列表。
        times: 对应的时间戳列表。

    Returns:
        markers: list[{time, position, color, shape, text}]
    """
    markers = []
    n = len(trend)
    if n < 3:
        return markers
    for i in range(n):
        is_local_min = False
        is_local_max = False
        if i == 0:
            if n > 1:
                if trend[0] < trend[1]:
                    is_local_min = True
                elif trend[0] > trend[1]:
                    is_local_max = True
        elif i == n - 1:
            if trend[-1] < trend[-2]:
                is_local_min = True
            elif trend[-1] > trend[-2]:
                is_local_max = True
        else:
            if trend[i] < trend[i - 1] and trend[i] < trend[i + 1]:
                is_local_min = True
            elif trend[i] > trend[i - 1] and trend[i] > trend[i + 1]:
                is_local_max = True
        if is_local_min:
            markers.append({'time': times[i], 'position': 'belowBar',
                            'color': '#4CAF50', 'shape': 'arrowUp', 'text': '入场'})
        elif is_local_max:
            markers.append({'time': times[i], 'position': 'aboveBar',
                            'color': '#EF5350', 'shape': 'arrowDown', 'text': '出场'})
    return markers


def _downsample(df, keep_bars=3000, intraday=False):
    """降采样：保留最近 keep_bars 根，更早的数据聚合为粗粒度 OHLC。"""
    if len(df) <= keep_bars:
        return df

    recent = df.iloc[-keep_bars:].copy()
    old = df.iloc[:-keep_bars].copy()

    # 统一日期格式：仅对 yyyyMMdd 做转换
    recent['date'] = recent['date'].apply(_norm_date)

    if intraday:
        # 5M → 日线
        old['_dt'] = old['date'].str.slice(0, 10)
        grouped = old.groupby('_dt', sort=False).agg(
            open=('open', 'first'),
            high=('high', 'max'),
            low=('low', 'min'),
            close=('close', 'last'),
            volume=('volume', 'sum'),
            amount=('amount', 'sum'),
        ).reset_index().rename(columns={'_dt': 'date'})
        if len(grouped) > 0 and len(grouped['date'].iloc[0]) == 8:
            grouped['date'] = grouped['date'].apply(_norm_date)
    else:
        # 1D → 周线
        old['date'] = pd.to_datetime(old['date'], format='%Y%m%d')
        grouped = old.resample('W', on='date').agg(
            open=('open', 'first'),
            high=('high', 'max'),
            low=('low', 'min'),
            close=('close', 'last'),
            volume=('volume', 'sum'),
            amount=('amount', 'sum'),
        ).dropna().reset_index()
        grouped['date'] = grouped['date'].dt.strftime('%Y-%m-%d')

    return pd.concat([grouped, recent], ignore_index=True)


def _build_html(title, candle_data, volume_data, ma_series, intraday=False):
    """生成 TradingView Lightweight Charts 自包含 HTML。"""
    candle_json = json.dumps(candle_data)
    volume_json = json.dumps(volume_data)

    ma_js = ''
    for period, pts in ma_series.items():
        color = MA_COLORS.get(period, '#CCCCCC')
        ma_js += f'''
        const ma{period}Series = chart.addLineSeries({{
            color: '{color}', lineWidth: 1.5,
            priceLineVisible: false, lastValueVisible: false,
        }});
        ma{period}Series.setData({json.dumps(pts)});'''

    time_visible = 'true' if intraday else 'false'

    return f'''<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>{title}</title>
<style>
  * {{ margin:0; padding:0; }}
  html, body, #chart {{ width:100%; height:100vh; background:#131722; }}
</style>
<script src="lc.min.js"></script>
</head>
<body>
<div id="chart"></div>
<script>
const chart = LightweightCharts.createChart(document.getElementById('chart'), {{
    layout: {{
        background: {{ type: LightweightCharts.ColorType.Solid, color: '#131722' }},
        textColor: '#d1d4dc',
    }},
    grid: {{
        vertLines: {{ color: '#2b2b43' }},
        horzLines: {{ color: '#2b2b43' }},
    }},
    crosshair: {{ mode: LightweightCharts.CrosshairMode.Normal }},
    timeScale: {{
        borderColor: '#485c7b',
        timeVisible: {time_visible},
        secondsVisible: false,
    }},
    rightPriceScale: {{ borderColor: '#485c7b' }},
}});

const candleSeries = chart.addCandlestickSeries({{
    upColor: '#ef5350', downColor: '#00BCD4',
    borderUpColor: '#ef5350', borderDownColor: '#00BCD4',
    wickUpColor: '#ef5350', wickDownColor: '#00BCD4',
}});
candleSeries.setData({candle_json});

const volumeSeries = chart.addHistogramSeries({{
    priceFormat: {{ type: 'volume' }},
    priceScaleId: 'volume',
}});
volumeSeries.setData({volume_json});
chart.priceScale('volume').applyOptions({{
    scaleMargins: {{ top: 0.85, bottom: 0 }},
}});

{ma_js}

chart.timeScale().fitContent();

window.addEventListener('resize', () => {{
    chart.applyOptions({{ width: window.innerWidth, height: window.innerHeight }});
}});
</script>
</body>
</html>'''


def SHOW_K_LINE(file, title=None, ma_periods=None, intraday=False, downsample_bars=3000):
    """读取数据文件并显示 TradingView K 线图。

    Args:
        file: 以｜分隔的 OHLCV 数据文件路径，第一列为时间。
        title: 图表标题（默认取文件名）。
        ma_periods: 均线周期列表，默认 [5,10,20,30,60,120]。
        intraday: 是否日内数据（如 5M）。
        downsample_bars: 超过此条数时对旧数据降采样。
    """
    if title is None:
        title = str(file)
    if ma_periods is None:
        ma_periods = [5, 10, 20, 30, 60, 120]

    df = pd.read_csv(file, sep='|', header=None,
                     names=['date', 'open', 'high', 'low', 'close', 'volume', 'amount'],
                     dtype={'date': str})

    # 降采样
    df = _downsample(df, keep_bars=downsample_bars, intraday=intraday)

    # 统一日期格式（保护未降采样的场景）
    if len(df) > 0 and len(str(df['date'].iloc[0])) == 8:
        df['date'] = df['date'].apply(_norm_date)

    # ── 准备 OHLC / Volume 数据 ──
    times = []
    candle_data = []
    volume_data = []
    for _, row in df.iterrows():
        if intraday:
            # 日内数据用 UNIX 时间戳
            dt = pd.Timestamp(row['date'])
            t = int(dt.timestamp())
        else:
            # 日线用 YYYY-MM-DD 字符串
            t = row['date'][:10]
        times.append(t)
        candle_data.append({
            'time': t,
            'open': round(row['open'], 2),
            'high': round(row['high'], 2),
            'low': round(row['low'], 2),
            'close': round(row['close'], 2),
        })
        color = '#ef5350' if row['close'] >= row['open'] else '#00BCD4'
        volume_data.append({
            'time': t,
            'value': round(row['volume'], 2),
            'color': color,
        })

    # ── 均线数据 ──
    ma_series = {}
    for period in ma_periods:
        ma = df['close'].rolling(window=period).mean()
        pts = []
        for i, row in df.iterrows():
            v = ma.iloc[i]
            if not pd.isna(v):
                pts.append({
                    'time': times[i],
                    'value': round(v, 2),
                })
        ma_series[period] = pts

    # ── 生成 HTML ──
    html = _build_html(title, candle_data, volume_data, ma_series, intraday=intraday)

    fname = os.path.basename(str(file)) + '.html'
    output = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'UI', fname)
    with open(output, 'w', encoding='utf-8') as f:
        f.write(html)
    webbrowser.open(output)


def _build_signal_html(title, candle_data, volume_data, ma_series, signals, intraday=False):
    """生成带入场信号标记的 HTML，信号显示在最底部。"""
    candle_json = json.dumps(candle_data)
    volume_json = json.dumps(volume_data)

    # 信号标记：K线下方箭头
    markers = []
    for s in signals:
        markers.append({
            'time': s['time'],
            'position': 'belowBar',
            'color': s['color'],
            'shape': 'arrowUp',
            'text': s['short'],
        })
    markers_json = json.dumps(markers)

    # 信号底部指示条（柱状图）
    sig_bars = []
    for s in signals:
        sig_bars.append({'time': s['time'], 'value': 1, 'color': s['color']})
    sig_bars_json = json.dumps(sig_bars)

    # 信号类型图例
    types_used = set(s['type'] for s in signals)
    legend_items = ''.join(
        f'<span style="display:inline-flex;align-items:center;gap:4px;margin-right:10px;">'
        f'<span style="width:10px;height:10px;border-radius:2px;background:{SIGNAL_STYLE.get(t, {}).get("color", "#FFFFFF")};"></span>'
        f'<span style="font-size:11px;">{SIGNAL_STYLE.get(t, {"label": t})["label"]}</span></span>'
        for t in sorted(types_used)
    )

    ma_js = ''
    for period, pts in ma_series.items():
        color = MA_COLORS.get(period, '#CCCCCC')
        ma_js += f'''
        const ma{period}Series = chart.addLineSeries({{
            color: '{color}', lineWidth: 1.5,
            priceLineVisible: false, lastValueVisible: false,
        }});
        ma{period}Series.setData({json.dumps(pts)});'''

    time_visible = 'true' if intraday else 'false'

    return f'''<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>{title}</title>
<style>
  * {{ margin:0; padding:0; }}
  html, body, #chart {{ width:100%; height:100vh; background:#131722; }}
</style>
<script src="lc.min.js"></script>
</head>
<body>
<div id="legend" style="position:absolute;top:10px;left:10px;z-index:10;background:rgba(19,23,34,0.85);border:1px solid #485c7b;border-radius:6px;padding:6px 12px;display:flex;align-items:center;gap:4px;flex-wrap:wrap;">
  <span style="color:#d1d4dc;font-size:11px;font-weight:bold;margin-right:6px;">信号:</span>
  {legend_items}
</div>
<div id="chart"></div>
<script>
const chart = LightweightCharts.createChart(document.getElementById('chart'), {{
    layout: {{
        background: {{ type: LightweightCharts.ColorType.Solid, color: '#131722' }},
        textColor: '#d1d4dc',
    }},
    grid: {{
        vertLines: {{ color: '#2b2b43' }},
        horzLines: {{ color: '#2b2b43' }},
    }},
    crosshair: {{ mode: LightweightCharts.CrosshairMode.Normal }},
    timeScale: {{
        borderColor: '#485c7b',
        timeVisible: {time_visible},
        secondsVisible: false,
    }},
    rightPriceScale: {{ borderColor: '#485c7b' }},
}});

const candleSeries = chart.addCandlestickSeries({{
    upColor: '#ef5350', downColor: '#00BCD4',
    borderUpColor: '#ef5350', borderDownColor: '#00BCD4',
    wickUpColor: '#ef5350', wickDownColor: '#00BCD4',
}});
candleSeries.setData({candle_json});
candleSeries.setMarkers({markers_json});

const volumeSeries = chart.addHistogramSeries({{
    priceFormat: {{ type: 'volume' }},
    priceScaleId: 'volume',
}});
volumeSeries.setData({volume_json});
chart.priceScale('volume').applyOptions({{
    scaleMargins: {{ top: 0.80, bottom: 0.08 }},
}});

// ── 信号指示条（最底部） ──
const signalSeries = chart.addHistogramSeries({{
    priceFormat: {{ type: 'volume' }},
    priceScaleId: 'signals',
}});
signalSeries.setData({sig_bars_json});
chart.priceScale('signals').applyOptions({{
    scaleMargins: {{ top: 0.94, bottom: 0 }},
    borderVisible: false,
}});

{ma_js}

chart.timeScale().fitContent();

window.addEventListener('resize', () => {{
    chart.applyOptions({{ width: window.innerWidth, height: window.innerHeight }});
}});
</script>
</body>
</html>'''


def SHOW_K_LINE_WITH_SIGNALS(kl_file, sig_file, title=None, intraday=False, downsample_bars=3000):
    """读取K线 + 信号数据，在图中叠加标记。

    Args:
        kl_file: OHLCV 数据文件路径。
        sig_file: 信号数据文件，格式: date|type|direction|price|description
        title: 图表标题。
        intraday: 是否日内数据。
        downsample_bars: 降采样阈值。
    """
    if title is None:
        title = str(kl_file)

    # ── 读取 K 线 ──
    df = pd.read_csv(kl_file, sep='|', header=None,
                     names=['date', 'open', 'high', 'low', 'close', 'volume', 'amount'],
                     dtype={'date': str})
    df = _downsample(df, keep_bars=downsample_bars, intraday=intraday)
    if len(df) > 0 and len(str(df['date'].iloc[0])) == 8:
        df['date'] = df['date'].apply(_norm_date)

    times = []
    candle_data = []
    volume_data = []
    for _, row in df.iterrows():
        if intraday:
            dt = pd.Timestamp(row['date'])
            t = int(dt.timestamp())
        else:
            t = row['date'][:10]
        times.append(t)
        candle_data.append({
            'time': t,
            'open': round(row['open'], 2),
            'high': round(row['high'], 2),
            'low': round(row['low'], 2),
            'close': round(row['close'], 2),
        })
        color = '#ef5350' if row['close'] >= row['open'] else '#00BCD4'
        volume_data.append({
            'time': t,
            'value': round(row['volume'], 2),
            'color': color,
        })

    # ── 均线 ──
    ma_series = {}
    for period in [5, 10, 20, 30, 60, 120]:
        ma = df['close'].rolling(window=period).mean()
        pts = []
        for i, row in df.iterrows():
            v = ma.iloc[i]
            if not pd.isna(v):
                pts.append({'time': times[i], 'value': round(v, 2)})
        ma_series[period] = pts

    # ── 读取信号 ──
    signals = []
    time_set = set(times)
    try:
        with open(sig_file, 'r') as f:
            for line in f:
                parts = line.strip().split('|')
                if len(parts) < 5:
                    continue
                raw_date = parts[0]
                sig_type = parts[1]
                desc = parts[4]
                if intraday:
                    # 5M：将 datetime 字符串转为 UNIX 时间戳
                    sig_time = int(pd.Timestamp(raw_date).timestamp())
                else:
                    # 日线
                    sig_time = _norm_date(raw_date) if len(raw_date) == 8 and raw_date.isdigit() else raw_date[:10]
                if sig_time in time_set:
                    color = SIGNAL_STYLE.get(sig_type, {}).get('color', '#FFFFFF')
                    label = SIGNAL_STYLE.get(sig_type, {}).get('label', sig_type)
                    signals.append({
                        'time': sig_time,
                        'type': sig_type,
                        'color': color,
                        'short': label,
                        'description': desc,
                    })
    except FileNotFoundError:
        print(f'[警告] 信号文件未找到: {sig_file}')

    print(f'[信号] 图表中叠加 {len(signals)} 个信号标记')

    # ── 生成 HTML ──
    html = _build_signal_html(title, candle_data, volume_data, ma_series, signals, intraday=intraday)

    fname = os.path.basename(str(kl_file)) + '_with_signals.html'
    output = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'UI', fname)
    with open(output, 'w', encoding='utf-8') as f:
        f.write(html)
    webbrowser.open(output)


_WIN_MA_COLORS = ['#FFD700', '#FF69B4', '#00FF00', '#1E90FF', '#FFFFFF']
_WIN_MA_LABELS = ['MA1', 'MA2', 'MA3', 'MA4', 'MA5']





def SHOW_WIN_COUNT(file, title=None, ma_periods=None, intraday=False, top_dir=None):
    """读取涨跌家数数据文件并显示柱状图 + 可配置均线 + TOP 数据。

    数据格式：date|up|flat|down|total

    Args:
        file: 涨跌家数数据文件路径。
        title: 图表标题。
        ma_periods: 均线周期列表，默认 [5, 10, 20, 0, 0]。
        intraday: 是否日内数据（如 5M）。
        top_dir: TOP 数据目录，每日期一份文件（文件名 YYYYMMDD），底部显示 TOP 数量柱状图。
    """
    if title is None:
        title = str(file)
    if ma_periods is None:
        ma_periods = [5, 10, 20, 0, 0]

    df = pd.read_csv(file, sep='|', header=None,
                     names=['date', 'up', 'flat', 'down', 'total'],
                     dtype={'date': str})

    if len(df) > 0 and len(str(df['date'].iloc[0])) == 8:
        df['date'] = df['date'].apply(_norm_date)

    times = []
    time_set = set()
    up_bars = []
    down_bars = []
    for _, row in df.iterrows():
        if intraday:
            dt = pd.Timestamp(row['date'])
            t = int(dt.timestamp())
        else:
            t = row['date'][:10]
        times.append(t)
        time_set.add(t)
        u = int(row['up'])
        d = int(row['down'])
        if u > 0:
            up_bars.append({'time': t, 'value': u, 'color': '#ef5350'})
        if d > 0:
            down_bars.append({'time': t, 'value': -d, 'color': '#00BCD4'})

    up_json = json.dumps(up_bars)
    down_json = json.dumps(down_bars)
    times_json = json.dumps(times)
    ups_json = json.dumps([int(r['up']) for _, r in df.iterrows()])
    downs_json = json.dumps([int(r['down']) for _, r in df.iterrows()])

    # ── 读取 TOP 数据 ──
    top_bars = []
    top_vals = []
    if top_dir and os.path.isdir(top_dir):
        top_cache = {}
        for fname in os.listdir(top_dir):
            fpath = os.path.join(top_dir, fname)
            if os.path.isfile(fpath):
                with open(fpath, 'r') as f:
                    top_cache[fname] = sum(1 for _ in f if _.strip())
        for _, row in df.iterrows():
            raw_date = row['date']
            if intraday:
                # 5M: "2026-02-09 09:35:00" → "20260209"
                top_key = raw_date[:4] + raw_date[5:7] + raw_date[8:10]
            else:
                top_key = raw_date[:4] + raw_date[5:7] + raw_date[8:10]
            count = top_cache.get(top_key, 0)
            top_vals.append(count)
            t = None
            if intraday:
                dt = pd.Timestamp(raw_date)
                t = int(dt.timestamp())
            else:
                t = raw_date[:10]
            if count > 0 and t in time_set:
                top_bars.append({'time': t, 'value': count, 'color': '#FFD700'})
        print(f'[TOP] 共加载 {len(top_cache)} 个交易日 TOP 数据')
    top_json = json.dumps(top_bars)
    tops_json = json.dumps(top_vals)

    time_visible = 'true' if intraday else 'false'

    # ── 预计算 MA 控制栏 HTML（避免 f-string 嵌套，Python 3.11 不支持） ──
    ma_controls = ''.join(
        '<div style="display:flex;align-items:center;gap:2px;">'
        f'<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:{_WIN_MA_COLORS[i]};"></span>'
        f'<span style="color:#d1d4dc;font-size:11px;margin-right:2px;">{_WIN_MA_LABELS[i]}</span>'
        f'<input id="ma{i+1}" type="number" value="{ma_periods[i] if i < len(ma_periods) else 0}" min="0" max="500" '
        f'style="width:36px;background:#2b2b43;color:#d1d4dc;border:1px solid #485c7b;border-radius:3px;text-align:center;font-size:11px;padding:1px 2px;" placeholder="0"></div>'
        for i in range(5)
    )

    # ── HP 滤波器：TOP 趋势分解 + 入场/出场标记 ──
    top_trend_up = []
    top_trend_dn = []
    markers = []
    if top_vals:
        trend, _ = _hp_filter(top_vals, lam=100.0)
        top_trend_up, top_trend_dn = _top_trend_segments(trend, times)
        markers = _hp_trend_markers(trend, times)
        print(f'[HP] TOP 趋势：上升 {len(top_trend_up)} 点，下降 {len(top_trend_dn)} 点，'
              f'标记 {len(markers)} 个极值点')
    top_trend_up_json = json.dumps(top_trend_up)
    top_trend_dn_json = json.dumps(top_trend_dn)
    markers_json = json.dumps(markers)

    signal_js = ''
    sig_scale_js = ''

    html = f'''<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>{title}</title>
<style>
  * {{ margin:0; padding:0; }}
  html, body, #chart {{ width:100%; height:100vh; background:#131722; }}
</style>
<script src="lc.min.js"></script>
</head>
<body style="position:relative;">
<div id="controls" style="position:absolute;top:12px;left:12px;z-index:10;display:flex;gap:6px;background:rgba(19,23,34,0.9);padding:6px 10px;border-radius:6px;border:1px solid #485c7b;align-items:center;">
  {ma_controls}
</div>
<div id="legend" style="position:absolute;top:48px;left:12px;z-index:10;display:flex;gap:8px;background:rgba(19,23,34,0.9);padding:4px 8px;border-radius:6px;border:1px solid #485c7b;align-items:center;flex-wrap:wrap;">
  <span style="display:flex;align-items:center;gap:4px;"><span style="width:10px;height:10px;border-radius:2px;background:#ef5350;"></span><span style="color:#d1d4dc;font-size:11px;">上涨</span></span>
  <span style="display:flex;align-items:center;gap:4px;"><span style="width:10px;height:10px;border-radius:2px;background:#00BCD4;"></span><span style="color:#d1d4dc;font-size:11px;">下跌</span></span>
  <span style="display:flex;align-items:center;gap:4px;"><span style="width:10px;height:10px;border-radius:2px;background:#FFD700;"></span><span style="color:#d1d4dc;font-size:11px;">TOP池</span></span>
  <span style="display:flex;align-items:center;gap:4px;"><span style="width:10px;height:10px;border-radius:2px;background:#26a69a;"></span><span style="color:#d1d4dc;font-size:11px;">HP上升趋势</span></span>
  <span style="display:flex;align-items:center;gap:4px;"><span style="width:10px;height:10px;border-radius:2px;background:#ef5350;"></span><span style="color:#d1d4dc;font-size:11px;">HP下降趋势</span></span>
  <span style="display:flex;align-items:center;gap:4px;"><span style="width:10px;height:10px;border-radius:2px;background:#4CAF50;"></span><span style="color:#d1d4dc;font-size:11px;">▲ 入场</span></span>
  <span style="display:flex;align-items:center;gap:4px;"><span style="width:10px;height:10px;border-radius:2px;background:#EF5350;"></span><span style="color:#d1d4dc;font-size:11px;">▼ 出场</span></span>
</div>
<div id="chart"></div>
<script>
const times = {times_json};
const upVals = {ups_json};
const downVals = {downs_json};
const cols = {json.dumps(_WIN_MA_COLORS)};
const labels = {json.dumps(_WIN_MA_LABELS)};

const chart = LightweightCharts.createChart(document.getElementById('chart'), {{
    layout: {{
        background: {{ type: LightweightCharts.ColorType.Solid, color: '#131722' }},
        textColor: '#d1d4dc',
    }},
    grid: {{ vertLines: {{ color: '#2b2b43' }}, horzLines: {{ color: '#2b2b43' }} }},
    crosshair: {{ mode: LightweightCharts.CrosshairMode.Normal }},
    timeScale: {{ borderColor: '#485c7b', timeVisible: {time_visible}, secondsVisible: false }},
    rightPriceScale: {{ borderColor: '#485c7b', visible: false }},
}});

// ── 第一步: 添加所有数据序列（创建 Panel） ──

// 1/4: 上涨均线 Panel（占位序列）
const _upMaPH = chart.addLineSeries({{ color: 'transparent', priceScaleId: 'up-ma', priceLineVisible: false, lastValueVisible: false }});
_upMaPH.setData([{{time: times[0], value: 0}}]);

// 2/4: 上涨+下跌柱状图（合并到同一 Panel，上涨向上、下跌向下）
const upSeries = chart.addHistogramSeries({{
    color: '#ef5350', title: '上涨',
    priceFormat: {{ type: 'volume' }},
    priceScaleId: 'bar',
}});
upSeries.setData({up_json});
const downSeries = chart.addHistogramSeries({{
    color: '#00BCD4', title: '下跌',
    priceFormat: {{ type: 'volume' }},
    priceScaleId: 'bar',
}});
downSeries.setData({down_json});

// 3/4: HP 趋势线 Panel（独立面板，与 TOP 上下相邻）
const _hpPH = chart.addLineSeries({{ color: 'transparent', priceScaleId: 'hp-trend', priceLineVisible: false, lastValueVisible: false }});
_hpPH.setData([{{time: times[0], value: 0}}]);

// HP 趋势：上升段（绿色）
const hpTrendUp = chart.addLineSeries({{
    color: '#26a69a', lineWidth: 2,
    title: 'HP Trend ↑',
    priceScaleId: 'hp-trend',
    priceLineVisible: false,
    lastValueVisible: false,
}});
hpTrendUp.setData({top_trend_up_json});

// HP 趋势：下降段（红色）
const hpTrendDn = chart.addLineSeries({{
    color: '#ef5350', lineWidth: 2,
    title: 'HP Trend ↓',
    priceScaleId: 'hp-trend',
    priceLineVisible: false,
    lastValueVisible: false,
}});
hpTrendDn.setData({top_trend_dn_json});

// 入场（绿↑）/ 出场（红↓）标记
hpTrendUp.setMarkers({markers_json});

// 4/4: TOP 池数量柱状图（独立面板，与 HP 趋势上下相邻）
const topSeries = chart.addHistogramSeries({{
    color: '#FFD700', title: 'TOP',
    priceFormat: {{ type: 'volume' }},
    priceScaleId: 'top',
}});
topSeries.setData({top_json});

// ── 第二步: 配置所有 Panel 垂直位置（4 面板，各占 1/4） ──
chart.priceScale('up-ma').applyOptions({{
    scaleMargins: {{ top: 0, bottom: 0.75 }},
    borderColor: '#485c7b',
    textColor: '#d1d4dc',
}});
chart.priceScale('bar').applyOptions({{
    scaleMargins: {{ top: 0.25, bottom: 0.5 }},
    borderColor: '#485c7b',
    textColor: '#d1d4dc',
}});
chart.priceScale('hp-trend').applyOptions({{
    scaleMargins: {{ top: 0.5, bottom: 0.25 }},
    borderColor: '#485c7b',
    textColor: '#d1d4dc',
}});
chart.priceScale('top').applyOptions({{
    scaleMargins: {{ top: 0.75, bottom: 0 }},
    borderColor: '#485c7b',
    textColor: '#d1d4dc',
}});

let upMaSeries = [];

function calcMA(arr, period) {{
    if (period < 2) return [];
    const result = [];
    for (let i = 0; i < arr.length; i++) {{
        if (i + 1 < period) continue;
        let sum = 0;
        for (let j = i - period + 1; j <= i; j++) sum += arr[j];
        result.push({{time: times[i], value: Math.round((sum / period) * 10) / 10}});
    }}
    return result;
}}

function updateMA() {{
    upMaSeries.forEach(s => chart.removeSeries(s));
    upMaSeries = [];

    for (let i = 1; i <= 5; i++) {{
        const period = parseInt(document.getElementById('ma' + i).value);
        if (isNaN(period) || period < 2) continue;
        const upMA = calcMA(upVals, period);

        // 1/4 上涨均线
        if (upMA.length > 0) {{
            const s = chart.addLineSeries({{
                color: cols[i-1], lineWidth: 1.5,
                title: labels[i-1] + ' Up',
                priceScaleId: 'up-ma',
                priceLineVisible: false,
                lastValueVisible: true,
            }});
            s.setData(upMA);
            upMaSeries.push(s);
        }}
    }}
}}

// 输入框变化时重新计算
for (let i = 1; i <= 5; i++) {{
    document.getElementById('ma' + i).addEventListener('change', updateMA);
    document.getElementById('ma' + i).addEventListener('input', updateMA);
}}

updateMA();
chart.timeScale().fitContent();
window.addEventListener('resize', () => chart.applyOptions({{width: window.innerWidth, height: window.innerHeight}}));
</script>
</body>
</html>'''


    fname = os.path.basename(str(file)) + '.win_count.html'
    output = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'UI', fname)
    with open(output, 'w', encoding='utf-8') as f:
        f.write(html)
    webbrowser.open(output)
