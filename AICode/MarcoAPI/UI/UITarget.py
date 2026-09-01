import json
import os
import sys
import webbrowser

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, os.path.dirname(_root))
from AICode.MarcoAPI.Update.Path import PATH_AIDATA_TARGET_31, PATH_AIDATA_1D_WIN_COUNT, PATH_AIDATA_TARGET_31_RATIO, PATH_AIDATA_TARGET_311_RATIO, PATH_AIDATA_TARGET_HISTORY_RATIO, PATH_AIDATA_TARGET_TOP_1_RATIO, PATH_AIDATA_TARGET_TOP_11_RATIO, PATH_AIDATA_TOP, PATH_AIDATA_TOPPED, PATH_AIDATA_BOTTOM, PATH_AIDATA_1D_MOTION_COUNT, PATH_AIDATA_MOTION, PATH_AIDATA_1D_PRICE
from AICode.MarcoAPI.Update.DataAligned import READ_ALIGNED_LINES


def SHOW_TARGET_1D():
    """三列可视化：D行日期轴(垂直)+十字虚线+悬浮窗+滚动条+联动拖拽。"""
    target_dir = PATH_AIDATA_TARGET_31()
    if not os.path.isdir(target_dir):
        print('[SHOW] 目标数据目录不存在')
        return

    fnames = sorted(os.listdir(target_dir), reverse=True)
    latest = None
    stocks = []
    for fname in fnames:
        fpath = os.path.join(target_dir, fname)
        if not os.path.isfile(fpath):
            continue
        with open(fpath, 'r') as f:
            cur = []
            for line in f:
                parts = line.strip().split('|')
                if len(parts) >= 8:
                    cur.append({
                        'code': parts[0],
                        'open': parts[1],
                        'high': parts[2],
                        'low': parts[3],
                        'close': parts[4],
                        'volume': parts[5],
                        'amount': parts[6],
                        'pre_close': parts[7],
                    })
            if cur:
                latest = fname
                stocks = cur
                break

    if not latest:
        print('[SHOW] 无有效数据')
        return

    win_data = []
    win_path = PATH_AIDATA_1D_WIN_COUNT()
    for date, line in READ_ALIGNED_LINES(win_path):
        if line:
            parts = line.split('|')
            win_data.append({
                'date': date,
                'up': int(parts[1]),
                'flat': int(parts[2]),
                'down': int(parts[3]),
                'total': int(parts[4]),
                'amount': float(parts[5]) if len(parts) > 5 else 0.0,
            })
        else:
            win_data.append({
                'date': date,
                'up': 0,
                'flat': 0,
                'down': 0,
                'total': 0,
                'amount': 0.0,
            })

    # ratio 数据（对齐读取，确保与 win_data 行数一致）
    ratio_data = []
    ratio_path = PATH_AIDATA_TARGET_31_RATIO()
    for date, line in READ_ALIGNED_LINES(ratio_path):
        if line:
            parts = line.split('|')
            ratio_data.append({'date': date, 'val': float(parts[1])})
        else:
            ratio_data.append({'date': date, 'val': 0.0})

    # 311_RATIO 数据（对齐读取，第9行）
    ratio311_data = []
    ratio311_path = PATH_AIDATA_TARGET_311_RATIO()
    for date, line in READ_ALIGNED_LINES(ratio311_path):
        if line:
            parts = line.split('|')
            ratio311_data.append({'date': date, 'val': float(parts[1])})
        else:
            ratio311_data.append({'date': date, 'val': 0.0})

    # HISTORY_RATIO 数据（对齐读取，位于 311_RATIO 之后）
    history_data = []
    history_path = PATH_AIDATA_TARGET_HISTORY_RATIO()
    for date, line in READ_ALIGNED_LINES(history_path):
        if line:
            parts = line.split('|')
            history_data.append({'date': date, 'val': float(parts[1])})
        else:
            history_data.append({'date': date, 'val': 0.0})



    # MOTION_COUNT 数据（对齐读取，第7行）
    motion_data = []
    motion_path = PATH_AIDATA_1D_MOTION_COUNT()
    for date, line in READ_ALIGNED_LINES(motion_path):
        if line:
            parts = line.split('|')
            motion_data.append({'date': date, 'up_diff': int(parts[1]), 'amount': float(parts[2])})
        else:
            motion_data.append({'date': date, 'up_diff': 0, 'amount': 0.0})

    # 1D_PRICE 数据（对齐读取，第5.5行均价线）
    price_data = []
    price_path = PATH_AIDATA_1D_PRICE()
    for date, line in READ_ALIGNED_LINES(price_path):
        if line:
            parts = line.split('|')
            price_data.append({'date': date, 'avg_close': float(parts[1]), 'vwap': float(parts[2])})
        else:
            price_data.append({'date': date, 'avg_close': 0.0, 'vwap': 0.0})

    # TOP 数据（对齐读取，第13行）
    top_data = []
    top_dir = PATH_AIDATA_TOP()
    for date, _ in READ_ALIGNED_LINES(win_path):
        fpath = os.path.join(top_dir, date)
        if os.path.isfile(fpath):
            with open(fpath, 'r') as f:
                count = sum(1 for line in f if line.strip())
        else:
            count = 0
        top_data.append({'date': date, 'count': count})

    # BOTTOM 数据（对齐读取，第14行）
    bottom_data = []
    bottom_dir = PATH_AIDATA_BOTTOM()
    for date, _ in READ_ALIGNED_LINES(win_path):
        fpath = os.path.join(bottom_dir, date)
        if os.path.isfile(fpath):
            with open(fpath, 'r') as f:
                count = sum(1 for line in f if line.strip())
        else:
            count = 0
        bottom_data.append({'date': date, 'count': count})

    # TOPPED 数据（对齐读取）
    topped_data = []
    topped_dir = PATH_AIDATA_TOPPED()
    for date, _ in READ_ALIGNED_LINES(win_path):
        fpath = os.path.join(topped_dir, date)
        if os.path.isfile(fpath):
            with open(fpath, 'r') as f:
                count = sum(1 for line in f if line.strip())
        else:
            count = 0
        topped_data.append({'date': date, 'count': count})

    # 封板率数据（TOP / (TOPPED + TOP) * 100，无触板则为0%）
    seal_data = []
    for i in range(len(top_data)):
        top_count = top_data[i]['count']
        topped_count = topped_data[i]['count']
        total = top_count + topped_count
        rate = round(top_count / total * 100, 1) if total > 0 else 0.0
        seal_data.append({'date': top_data[i]['date'], 'rate': rate})

    # 计算列宽：与D行日期标签总宽一致(10px/条)
    col_chart_w = max(3000, len(win_data) * 11)

    # 8×8 颜色矩阵
    colors_64 = [
        '#ff0000','#ff4500','#ff8c00','#ffd700','#ffff00','#adff2f','#00ff00','#00ff7f',
        '#00ffff','#00bfff','#1e90ff','#0000ff','#8a2be2','#9400d3','#ff00ff','#ff1493',
        '#dc143c','#b22222','#8b0000','#cd5c5c','#f08080','#ff6347','#ff6600','#f4a460',
        '#b8860b','#bdb76b','#808000','#9acd32','#32cd32','#228b22','#006400','#008080',
        '#20b2aa','#00ced1','#5f9ea0','#4682b4','#4169e1','#483d8b','#4b0082','#8b008b',
        '#9932cc','#da70d6','#dda0dd','#ff69b4','#db7093','#ffc0cb','#a52a2a','#d2691e',
        '#cd853f','#8fbc8f','#2e8b57','#556b2f','#808080','#c0c0c0','#ffffff','#696969',
        '#a9a9a9','#2f4f4f','#000000','#bc8f8f','#6495ed','#e9967a','#f5a623','#00e5ff'
    ]
    color_opts_8x8 = ''.join(f'<span style="background:{c}" data-color="{c}"></span>' for c in colors_64)

    # 基于 31_RATIO 构建真实价格 K线（起始价格100，open=昨日close，close=今日close，无影线）
    def build_ohlc(ratio_list):
        ohlc = []
        price = 100.0
        for i, d in enumerate(ratio_list):
            val = d['val']
            if i > 0:
                price = ohlc[i - 1]['close']
            open_price = price
            close = round(price * (1 + val / 100), 4)
            ohlc.append({'date': f"{d['date'][:4]}-{d['date'][4:6]}-{d['date'][6:8]}", 'open': open_price, 'high': close, 'low': close, 'close': close})
        return ohlc

    ohlc_data = build_ohlc(ratio_data)
    ohlc311_data = build_ohlc(ratio311_data)
    ohlc_history_data = build_ohlc(history_data)

    data_json = json.dumps(stocks, ensure_ascii=False)
    win_json = json.dumps(win_data, ensure_ascii=False)
    ratio_json = json.dumps(ratio_data, ensure_ascii=False)
    ratio311_json = json.dumps(ratio311_data, ensure_ascii=False)
    history_json = json.dumps(history_data, ensure_ascii=False)
    ohlc_json = json.dumps(ohlc_data, ensure_ascii=False)
    ohlc311_json = json.dumps(ohlc311_data, ensure_ascii=False)
    ohlc_history_json = json.dumps(ohlc_history_data, ensure_ascii=False)
    # 构建成交额 K线（用成交额每日变化率，与昨日成交额的百分比）
    amount_ohlc = []
    amt_price = 100.0
    for i, d in enumerate(win_data):
        if i == 0:
            amt_pct = 0.0
        else:
            prev_amt = win_data[i - 1]['amount']
            cur_amt = d['amount']
            amt_pct = ((cur_amt - prev_amt) / prev_amt * 100) if prev_amt != 0 else 0.0
        if i > 0:
            amt_price = amount_ohlc[i - 1]['close']
        open_price = amt_price
        close = round(amt_price * (1 + amt_pct / 100), 4)
        amount_ohlc.append({
            'date': f"{d['date'][:4]}-{d['date'][4:6]}-{d['date'][6:8]}",
            'open': open_price,
            'high': close,
            'low': close,
            'close': close,
        })

    amount_ohlc_json = json.dumps(amount_ohlc, ensure_ascii=False)
    top_json = json.dumps(top_data, ensure_ascii=False)
    bottom_json = json.dumps(bottom_data, ensure_ascii=False)
    topped_json = json.dumps(topped_data, ensure_ascii=False)
    seal_json = json.dumps(seal_data, ensure_ascii=False)
    motion_json = json.dumps(motion_data, ensure_ascii=False)
    price_json = json.dumps(price_data, ensure_ascii=False)

    html = f'''<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Target 1D</title>
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@900&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
<script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  html, body {{ height:100%; background:#131722; color:#d1d4dc; font-family:'Segoe UI',sans-serif; }}
  body {{ padding:10px 20px 20px 0; }}

  html, body {{ height:100%; overflow:hidden; }}
  #scroll-wrap {{ overflow:auto; width:100%; height:calc(100vh - 30px); overscroll-behavior-x:none; touch-action:pan-y; }}
  #scroll-wrap::-webkit-scrollbar {{ display:none; }}
  #scroll-wrap {{ -ms-overflow-style:none; scrollbar-width:none; }}

  table {{ table-layout:fixed; width:{col_chart_w + 460}px; border-collapse:collapse; }}
  td {{ padding:8px 10px; border-bottom:1px solid #2b2b43; vertical-align:middle; background:#131722; }}
  .col-idx {{ position:sticky; left:0; z-index:3; width:240px; text-align:center; color:#ffffff; font-size:200px; font-weight:900; line-height:1; }}
  .col-chart {{ width:{col_chart_w}px; position:relative; }}
  .col-param {{ position:sticky; right:0; z-index:3; width:220px; padding-left:20px; }}

  /* D 行 - 冻结在顶部 */
  .row-date {{ position:sticky; top:0; z-index:4; }}
  .row-date td {{ padding:0 0 10px; background:#131722; }}
  .row-date .data-area {{ display:flex; align-items:stretch; height:80px; padding:0 10px 0 5px; }}
  .row-date .data-area {{ display:flex; align-items:stretch; height:80px; }}
  .date-axis {{ position:relative; height:100%; }}
  .date-axis .dl {{ position:absolute; top:0; bottom:0; writing-mode:vertical-rl; text-orientation:upright; font-size:8px; color:#d1d4dc; text-align:center; border-left:1px solid #5a5f7a; display:flex; align-items:center; justify-content:center; }}
  .date-axis .dl.hl {{ background:#ffffff15; font-weight:bold; color:#ffffff; }}

  /* 图表容器 */
  .chart-box {{ position:relative; user-select:none; margin:0; cursor:crosshair; }}


  .chart-label .tag {{ font-size:10px; padding:2px 8px; border-radius:10px; font-weight:normal; }}
  .chart-label .tag.blue {{ background:#2962ff22; color:#2962ff; border:1px solid #2962ff44; }}
  .chart-label .tag.green {{ background:#26a69a22; color:#26a69a; border:1px solid #26a69a44; }}
  .chart-label .tag.red {{ background:#ef535022; color:#ef5350; border:1px solid #ef535044; }}

  .param-group {{ display:flex; flex-direction:column; gap:4px; }}
  .param-row {{ display:flex; align-items:center; gap:6px; }}
  .param-row label {{ font-size:11px; color:#787b86; min-width:48px; text-align:right; }}
  .param-row input {{ flex:1; min-width:40px; padding:4px 6px; border:1px solid #2b2b43; background:#1e222d; color:#d1d4dc; font-size:11px; border-radius:4px; outline:none; }}
  .param-row input:focus {{ border-color:#2962ff; }}
  .param-row input[type="checkbox"] {{ flex:unset; min-width:unset; width:16px; height:16px; }}
  .param-divider {{ height:1px; background:#2b2b43; margin:4px 0; }}
  .color-picker {{ position:relative; }}
  .color-swatch {{ width:22px; height:22px; border:1px solid #2b2b43; border-radius:3px; cursor:pointer; flex-shrink:0; }}
  .color-grid {{ position:fixed; z-index:31; display:none; grid-template-columns:repeat(8,18px); gap:1px; background:#1e222d; padding:3px; border:1px solid #2b2b43; border-radius:4px; }}
  .color-grid.show {{ display:grid; }}
  .color-grid span {{ width:18px; height:18px; cursor:pointer; border-radius:2px; border:1px solid transparent; }}
  .color-grid span:hover {{ border-color:#fff; }}
  .param-row input.height-input {{ min-width:60px; }}

  /* 十字虚线 */
  #cross-v {{ position:fixed; top:0; bottom:0; width:0; border-left:1px dashed #787b8666; z-index:10; pointer-events:none; display:none; }}

  /* 统一悬浮窗 */
  #custom-tooltip {{ position:fixed; z-index:30; background:#1e222d; border:1px solid #2b2b43; border-radius:6px; padding:8px 12px; font-size:12px; line-height:1.8; pointer-events:none; display:none; box-shadow:0 4px 12px rgba(0,0,0,0.4); }}
  #custom-tooltip .tt-date {{ font-size:13px; font-weight:700; color:#fff; margin-bottom:4px; text-align:center; }}
  #custom-tooltip .tt-row {{ display:flex; justify-content:space-between; gap:20px; }}
  #custom-tooltip .tt-label {{ color:#787b86; }}
  #custom-tooltip .tt-value {{ color:#d1d4dc; font-weight:600; text-align:right; }}
  #custom-tooltip .tt-up {{ color:#ef5350; }}
  #custom-tooltip .tt-dn {{ color:#00e5ff; }}
  #custom-tooltip .tt-sep {{ border-bottom:1px solid #2b2b43; margin:4px 0; }}

  .up {{ color:#ef5350; }} .dn {{ color:#00e5ff; }}
  .empty {{ color:#485c7b; font-size:14px; padding:40px; text-align:center; }}
</style>
</head>
<body>

<div id="cross-v"></div>
<div id="custom-tooltip"></div>
<div class="color-grid" id="global-color-grid">{color_opts_8x8}</div>
<div id="scroll-wrap">
  <table>
    <tbody>
      <!-- 日期轴（冻结） -->
      <tr class="row-date">
        <td class="col-idx" style="font-family:'Orbitron',sans-serif;font-size:40px;line-height:80px;">100,000</td>
        <td>
          <div class="data-area">
            <div class="date-axis-wrap">
              <div class="date-axis" id="date-axis"></div>
            </div>
          </div>
        </td>
        <td class="col-param"></td>
      </tr>
      <!-- 第2行：上升均线 -->
      <tr>
        <td class="col-idx" style="padding:0;"><div style="font-size:13px;font-weight:normal;color:#d1d4dc;line-height:1.2;"><span style="font-size:10px;background:#2962ff22;color:#2962ff;border:1px solid #2962ff44;padding:1px 6px;border-radius:8px;">MA</span></div><div style="font-family:'Orbitron',sans-serif;font-size:48px;font-weight:900;line-height:1;">MA</div></td>
        <td style="padding:0 5px 0 0;">
          <div class="chart-box" style="height:120px;">
            <canvas id="c-ma"></canvas>
          </div>
        </td>
        <td class="col-param">
          <div class="param-group">
            <div class="param-row"><label>MA1</label><input class="ma-period" type="number" value="5" min="0" data-ma="0"><div class="color-picker"><div class="color-swatch ma-swatch" data-ma="0" style="background:#f5a623"></div></div></div>
            <div class="param-row"><label>MA2</label><input class="ma-period" type="number" value="10" min="0" data-ma="1"><div class="color-picker"><div class="color-swatch ma-swatch" data-ma="1" style="background:#1e90ff"></div></div></div>
            <div class="param-row"><label>MA3</label><input class="ma-period" type="number" value="0" min="0" data-ma="2"><div class="color-picker"><div class="color-swatch ma-swatch" data-ma="2" style="background:#808080"></div></div></div>
            <div class="param-row"><label>数据线</label><input type="checkbox" class="ma-line-toggle" checked></div>
            <div class="param-row"><label>高度</label><input class="height-input" type="number" value="180" min="60" step="10" data-target="c-ma"></div>
          </div>
        </td>
      </tr>
      <!-- 第3行：每日上涨个数 -->
      <tr>
        <td class="col-idx" style="padding:0;border-bottom:none;"><div style="font-size:13px;font-weight:normal;color:#d1d4dc;line-height:1.2;"><span style="font-size:10px;background:#ef535022;color:#ef5350;border:1px solid #ef535044;padding:1px 6px;border-radius:8px;">WIN</span></div><div style="font-family:'Orbitron',sans-serif;font-size:48px;font-weight:900;line-height:1;">UP</div></td>
        <td style="padding:0;border-bottom:none;line-height:0;">
          <div class="chart-box" style="height:270px;">
            <canvas id="c-up"></canvas>
          </div>
        </td>
        <td class="col-param" style="border-bottom:none;"></td>
      </tr>
      <!-- 第4行：下跌柱状图 -->
      <tr>
        <td class="col-idx" style="padding:0;border-top:none;"><div style="font-size:13px;font-weight:normal;color:#d1d4dc;line-height:1.2;"><span style="font-size:10px;background:#00e5ff22;color:#00e5ff;border:1px solid #00e5ff44;padding:1px 6px;border-radius:8px;">LOSE</span></div><div style="font-family:'Orbitron',sans-serif;font-size:48px;font-weight:900;line-height:1;">DOWN</div></td>
        <td style="padding:0;border-top:none;line-height:0;">
          <div class="chart-box" style="height:270px;">
            <canvas id="c-dn"></canvas>
          </div>
        </td>
        <td class="col-param" style="padding:0;border-top:none;"></td>
      </tr>
      <!-- 第6行：居中包络通道（居中窗口 + 自适应末端预测） -->
      <tr>
        <td class="col-idx" style="padding:0;"><div style="font-size:13px;font-weight:normal;color:#d1d4dc;line-height:1.2;"><span style="font-size:10px;background:#ffd74022;color:#ffd740;border:1px solid #ffd74044;padding:1px 6px;border-radius:8px;">ENV</span></div><div style="font-family:'Orbitron',sans-serif;font-size:36px;font-weight:900;line-height:1;">包络<br>通道</div></td>
        <td style="padding:0 5px 0 0;">
          <div class="chart-box" style="height:200px;">
            <canvas id="c-amount-ma"></canvas>
          </div>
        </td>
        <td class="col-param">
          <div class="param-group">
            <div class="param-row"><label>窗口</label><input class="env-window" type="number" value="20" min="2" step="1"></div>
            <div class="param-row"><label>平滑</label><input class="env-smooth" type="number" value="0.25" min="0.01" max="1" step="0.05"></div>
            <div class="param-divider"></div>
            <div class="param-row"><label>波峰色</label><div class="color-picker"><div class="color-swatch env-peak-swatch" style="background:#ef5350"></div></div></div>
            <div class="param-row"><label>波谷色</label><div class="color-picker"><div class="color-swatch env-valley-swatch" style="background:#00e5ff"></div></div></div>
            <div class="param-row"><label>成交额</label><input type="checkbox" class="env-raw-toggle" checked></div>
            <div class="param-row"><label>高度</label><input class="height-input" type="number" value="200" min="60" step="10" data-target="c-amount-ma"></div>
          </div>
        </td>
      </tr>
      <!-- 第7行：成交额柱状图 -->
      <tr>
        <td class="col-idx" style="padding:0;border-bottom:none;"><div style="font-size:13px;font-weight:normal;color:#d1d4dc;line-height:1.2;"><span style="font-size:10px;background:#ffd74022;color:#ffd740;border:1px solid #ffd74044;padding:1px 6px;border-radius:8px;">AMOUNT</span></div><div style="font-family:'Orbitron',sans-serif;font-size:48px;font-weight:900;line-height:1;">成交额</div></td>
        <td style="padding:0;border-bottom:none;line-height:0;">
          <div class="chart-box" style="height:180px;">
            <canvas id="c-amount-raw"></canvas>
          </div>
        </td>
        <td class="col-param" style="border-bottom:none;"></td>
      </tr>
      <!-- 第8行：31_RATIO -->
      <tr>
        <td class="col-idx"><div style="font-size:13px;font-weight:normal;color:#d1d4dc;line-height:1.2;"><span style="font-size:10px;background:#ff8c0022;color:#ff8c00;border:1px solid #ff8c0044;padding:1px 6px;border-radius:8px;">D-DAY</span></div><div style="font-family:'Orbitron',sans-serif;font-size:48px;font-weight:900;line-height:1.1;">31<br>RATIO</div></td>
        <td style="padding:10px 0;">
          <div class="chart-box" style="height:180px;">
            <canvas id="c-ratio"></canvas>
          </div>
        </td>
        <td class="col-param">
          <div class="param-group">
            <div class="param-row"><label>线颜色</label><div class="color-picker"><div class="color-swatch ratio-swatch ratio-line-swatch" style="background:#26a69a"></div></div></div>
            <div class="param-row"><label>上升色</label><div class="color-picker"><div class="color-swatch ratio-swatch ratio-up-swatch" style="background:#ef5350"></div></div></div>
            <div class="param-row"><label>下降色</label><div class="color-picker"><div class="color-swatch ratio-swatch ratio-dn-swatch" style="background:#00e5ff"></div></div></div>
            <div class="param-row"><label>高度</label><input class="height-input" type="number" value="180" min="60" step="10" data-target="c-ratio"></div>
          </div>
        </td>
      </tr>
      <!-- 第8.5行：31 RATIO K线（lightweight-charts），包含均线 -->
      <tr>
        <td class="col-idx"><div style="font-size:13px;font-weight:normal;color:#d1d4dc;line-height:1.2;"><span style="font-size:10px;background:#ff8c0022;color:#ff8c00;border:1px solid #ff8c0044;padding:1px 6px;border-radius:8px;">D-DAY</span></div><div style="font-family:'Orbitron',sans-serif;font-size:40px;font-weight:900;line-height:1.1;">31<br>KLINE</div></td>
        <td style="padding:10px 0;">
          <div class="chart-box" style="height:500px;position:relative;">
            <div id="c-ohlc" style="width:100%;height:100%;"></div>
          </div>
        </td>
        <td class="col-param">
          <div class="param-group">
            <div class="param-row"><label>MA1</label><input class="ohlc-ma-period" type="number" value="5" min="0" data-ma="0" data-ohlc="31"><div class="color-picker"><div class="color-swatch ohlc-ma-swatch" data-ma="0" style="background:#f5a623"></div></div></div>
            <div class="param-row"><label>MA2</label><input class="ohlc-ma-period" type="number" value="10" min="0" data-ma="1" data-ohlc="31"><div class="color-picker"><div class="color-swatch ohlc-ma-swatch" data-ma="1" style="background:#1e90ff"></div></div></div>
            <div class="param-row"><label>MA3</label><input class="ohlc-ma-period" type="number" value="0" min="0" data-ma="2" data-ohlc="31"><div class="color-picker"><div class="color-swatch ohlc-ma-swatch" data-ma="2" style="background:#808080"></div></div></div>
            <div class="param-row"><label>高度</label><input class="height-input" type="number" value="500" min="60" step="10" data-target="c-ohlc"></div>
          </div>
        </td>
      </tr>
      <!-- 第9行：311_RATIO -->
      <tr>
        <td class="col-idx"><div style="font-size:13px;font-weight:normal;color:#d1d4dc;line-height:1.2;"><span style="font-size:10px;background:#7c4dff22;color:#7c4dff;border:1px solid #7c4dff44;padding:1px 6px;border-radius:8px;">D-DAY + 1</span></div><div style="font-family:'Orbitron',sans-serif;font-size:48px;font-weight:900;line-height:1.1;">311<br>RATIO</div></td>
        <td style="padding:10px 0;">
          <div class="chart-box" style="height:180px;">
            <canvas id="c-ratio311"></canvas>
          </div>
        </td>
        <td class="col-param">
          <div class="param-group">
            <div class="param-row"><label>线颜色</label><div class="color-picker"><div class="color-swatch ratio-swatch ratio-line-swatch" style="background:#26a69a"></div></div></div>
            <div class="param-row"><label>上升色</label><div class="color-picker"><div class="color-swatch ratio-swatch ratio-up-swatch" style="background:#ef5350"></div></div></div>
            <div class="param-row"><label>下降色</label><div class="color-picker"><div class="color-swatch ratio-swatch ratio-dn-swatch" style="background:#00e5ff"></div></div></div>
            <div class="param-row"><label>高度</label><input class="height-input" type="number" value="180" min="60" step="10" data-target="c-ratio311"></div>
          </div>
        </td>
      </tr>
      <!-- 第9.5行：311 RATIO K线（lightweight-charts），包含均线 -->
      <tr>
        <td class="col-idx"><div style="font-size:13px;font-weight:normal;color:#d1d4dc;line-height:1.2;"><span style="font-size:10px;background:#7c4dff22;color:#7c4dff;border:1px solid #7c4dff44;padding:1px 6px;border-radius:8px;">D-DAY + 1</span></div><div style="font-family:'Orbitron',sans-serif;font-size:40px;font-weight:900;line-height:1.1;">311<br>KLINE</div></td>
        <td style="padding:10px 0;">
          <div class="chart-box" style="height:500px;position:relative;">
            <div id="c-ohlc311" style="width:100%;height:100%;"></div>
          </div>
        </td>
        <td class="col-param">
          <div class="param-group">
            <div class="param-row"><label>MA1</label><input class="ohlc-ma-period" type="number" value="5" min="0" data-ma="0" data-ohlc="311"><div class="color-picker"><div class="color-swatch ohlc-ma-swatch" data-ma="0" style="background:#f5a623"></div></div></div>
            <div class="param-row"><label>MA2</label><input class="ohlc-ma-period" type="number" value="10" min="0" data-ma="1" data-ohlc="311"><div class="color-picker"><div class="color-swatch ohlc-ma-swatch" data-ma="1" style="background:#1e90ff"></div></div></div>
            <div class="param-row"><label>MA3</label><input class="ohlc-ma-period" type="number" value="0" min="0" data-ma="2" data-ohlc="311"><div class="color-picker"><div class="color-swatch ohlc-ma-swatch" data-ma="2" style="background:#808080"></div></div></div>
            <div class="param-row"><label>高度</label><input class="height-input" type="number" value="500" min="60" step="10" data-target="c-ohlc311"></div>
          </div>
        </td>
      </tr>
      <!-- 第10行：HISTORY_RATIO -->
      <tr>
        <td class="col-idx"><div style="font-size:13px;font-weight:normal;color:#d1d4dc;line-height:1.2;"><span style="font-size:10px;background:#e040fb22;color:#e040fb;border:1px solid #e040fb44;padding:1px 6px;border-radius:8px;">HISTORY</span></div><div style="font-family:'Orbitron',sans-serif;font-size:36px;font-weight:900;line-height:1.1;">HISTORY<br>RATIO</div></td>
        <td style="padding:10px 0;">
          <div class="chart-box" style="height:180px;">
            <canvas id="c-history"></canvas>
          </div>
        </td>
        <td class="col-param">
          <div class="param-group">
            <div class="param-row"><label>线颜色</label><div class="color-picker"><div class="color-swatch ratio-swatch ratio-line-swatch" style="background:#26a69a"></div></div></div>
            <div class="param-row"><label>上升色</label><div class="color-picker"><div class="color-swatch ratio-swatch ratio-up-swatch" style="background:#ef5350"></div></div></div>
            <div class="param-row"><label>下降色</label><div class="color-picker"><div class="color-swatch ratio-swatch ratio-dn-swatch" style="background:#00e5ff"></div></div></div>
            <div class="param-row"><label>高度</label><input class="height-input" type="number" value="180" min="60" step="10" data-target="c-history"></div>
          </div>
        </td>
      </tr>
      <!-- 第10.5行：HISTORY RATIO K线（lightweight-charts），包含均线 -->
      <tr>
        <td class="col-idx"><div style="font-size:13px;font-weight:normal;color:#d1d4dc;line-height:1.2;"><span style="font-size:10px;background:#e040fb22;color:#e040fb;border:1px solid #e040fb44;padding:1px 6px;border-radius:8px;">HISTORY</span></div><div style="font-family:'Orbitron',sans-serif;font-size:36px;font-weight:900;line-height:1.1;">HISTORY<br>KLINE</div></td>
        <td style="padding:10px 0;">
          <div class="chart-box" style="height:500px;position:relative;">
            <div id="c-ohlc-history" style="width:100%;height:100%;"></div>
          </div>
        </td>
        <td class="col-param">
          <div class="param-group">
            <div class="param-row"><label>MA1</label><input class="ohlc-ma-period" type="number" value="5" min="0" data-ma="0" data-ohlc="history"><div class="color-picker"><div class="color-swatch ohlc-ma-swatch" data-ma="0" style="background:#f5a623"></div></div></div>
            <div class="param-row"><label>MA2</label><input class="ohlc-ma-period" type="number" value="10" min="0" data-ma="1" data-ohlc="history"><div class="color-picker"><div class="color-swatch ohlc-ma-swatch" data-ma="1" style="background:#1e90ff"></div></div></div>
            <div class="param-row"><label>MA3</label><input class="ohlc-ma-period" type="number" value="0" min="0" data-ma="2" data-ohlc="history"><div class="color-picker"><div class="color-swatch ohlc-ma-swatch" data-ma="2" style="background:#808080"></div></div></div>
            <div class="param-row"><label>高度</label><input class="height-input" type="number" value="500" min="60" step="10" data-target="c-ohlc-history"></div>
          </div>
        </td>
      </tr>
      <!-- 第11行：成交额 KLINE（lightweight-charts + 均线） -->
      <tr>
        <td class="col-idx"><div style="font-size:13px;font-weight:normal;color:#d1d4dc;line-height:1.2;"><span style="font-size:10px;background:#ffd74022;color:#ffd740;border:1px solid #ffd74044;padding:1px 6px;border-radius:8px;">AMOUNT</span></div><div style="font-family:'Orbitron',sans-serif;font-size:36px;font-weight:900;line-height:1.1;">成交额<br>KLINE</div></td>
        <td style="padding:10px 0;">
          <div class="chart-box" style="height:500px;position:relative;">
            <div id="c-ohlc-amount" style="width:100%;height:100%;"></div>
          </div>
        </td>
        <td class="col-param">
          <div class="param-group">
            <div class="param-row"><label>MA1</label><input class="ohlc-ma-period" type="number" value="5" min="0" data-ma="0" data-ohlc="amount"><div class="color-picker"><div class="color-swatch ohlc-ma-swatch" data-ma="0" style="background:#f5a623"></div></div></div>
            <div class="param-row"><label>MA2</label><input class="ohlc-ma-period" type="number" value="10" min="0" data-ma="1" data-ohlc="amount"><div class="color-picker"><div class="color-swatch ohlc-ma-swatch" data-ma="1" style="background:#1e90ff"></div></div></div>
            <div class="param-row"><label>MA3</label><input class="ohlc-ma-period" type="number" value="0" min="0" data-ma="2" data-ohlc="amount"><div class="color-picker"><div class="color-swatch ohlc-ma-swatch" data-ma="2" style="background:#808080"></div></div></div>
            <div class="param-row"><label>高度</label><input class="height-input" type="number" value="500" min="60" step="10" data-target="c-ohlc-amount"></div>
          </div>
        </td>
      </tr>
      <!-- 第12行：封板率 TOP/(TOPPED+TOP)*100 -->
      <tr>
        <td class="col-idx" style="padding:0;"><div style="font-size:13px;font-weight:normal;color:#d1d4dc;line-height:1.2;"><span style="font-size:10px;background:#ffd74022;color:#ffd740;border:1px solid #ffd74044;padding:1px 6px;border-radius:8px;">SEAL</span></div><div style="font-family:'Orbitron',sans-serif;font-size:40px;font-weight:900;line-height:1;">封板率</div></td>
        <td style="padding:0;line-height:0;">
          <div class="chart-box" style="height:120px;">
            <canvas id="c-seal"></canvas>
          </div>
        </td>
        <td class="col-param"></td>
      </tr>
      <!-- 第13行：TOPPED数量 -->
      <tr>
        <td class="col-idx" style="padding:0;"><div style="font-size:13px;font-weight:normal;color:#d1d4dc;line-height:1.2;"><span style="font-size:10px;background:#26a69a22;color:#26a69a;border:1px solid #26a69a44;padding:1px 6px;border-radius:8px;">TOPPED</span></div><div style="font-family:'Orbitron',sans-serif;font-size:48px;font-weight:900;line-height:1;">TOPPED</div></td>
        <td style="padding:0;line-height:0;">
          <div class="chart-box" style="height:120px;">
            <canvas id="c-topped"></canvas>
          </div>
        </td>
        <td class="col-param"></td>
      </tr>
      <!-- 第14行：TOP数量 -->
      <tr>
        <td class="col-idx" style="padding:0;"><div style="font-size:13px;font-weight:normal;color:#d1d4dc;line-height:1.2;"><span style="font-size:10px;background:#7c4dff22;color:#7c4dff;border:1px solid #7c4dff44;padding:1px 6px;border-radius:8px;">TOP</span></div><div style="font-family:'Orbitron',sans-serif;font-size:48px;font-weight:900;line-height:1;">TOP</div></td>
        <td style="padding:0;line-height:0;">
          <div class="chart-box" style="height:120px;">
            <canvas id="c-top"></canvas>
          </div>
        </td>
        <td class="col-param"></td>
      </tr>
      <!-- 第15行：BOTTOM数量 -->
      <tr>
        <td class="col-idx" style="padding:0;"><div style="font-size:13px;font-weight:normal;color:#d1d4dc;line-height:1.2;"><span style="font-size:10px;background:#ff910022;color:#ff9100;border:1px solid #ff910044;padding:1px 6px;border-radius:8px;">BOT</span></div><div style="font-family:'Orbitron',sans-serif;font-size:48px;font-weight:900;line-height:1;">BOT</div></td>
        <td style="padding:0;line-height:0;">
          <div class="chart-box" style="height:120px;">
            <canvas id="c-bottom"></canvas>
          </div>
        </td>
        <td class="col-param"></td>
      </tr>

      <!-- 4 行空白（高度 200px） -->
      <tr style="height:200px;"><td class="col-idx"></td><td></td><td class="col-param"></td></tr>
      <tr style="height:200px;"><td class="col-idx"></td><td></td><td class="col-param"></td></tr>
      <tr style="height:200px;"><td class="col-idx"></td><td></td><td class="col-param"></td></tr>
      <tr style="height:200px;"><td class="col-idx"></td><td></td><td class="col-param"></td></tr>
    </tbody>
  </table>
</div>

<script>
const stocks = {data_json};
const winData = {win_json};
const ratioData = {ratio_json};
const ratio311Data = {ratio311_json};
const historyData = {history_json};
const ohlcData = {ohlc_json};
const ohlc311Data = {ohlc311_json};
const ohlcHistoryData = {ohlc_history_json};
const amountOhlcData = {amount_ohlc_json};
const topData = {top_json};
const bottomData = {bottom_json};
const toppedData = {topped_json};
const sealData = {seal_json};
const motionData = {motion_json};
const priceData = {price_json};
let charts = [];

/* ---- 鼠标中键拖动 ---- */
const wrap = document.getElementById('scroll-wrap');
const crossV = document.getElementById('cross-v');
let dragging = false, sx = 0, ss = 0;

document.addEventListener('mousedown', e => {{
  if (e.button !== 1 || !e.target.closest('#scroll-wrap')) return;
  e.preventDefault();
  dragging = true;
  sx = e.clientX;
  ss = wrap.scrollLeft;
  wrap.style.cursor = 'grabbing';
}});

document.addEventListener('mousemove', e => {{
  if (dragging) {{
    wrap.scrollLeft = ss - (e.clientX - sx);
  }} else if (e.target.closest('#scroll-wrap')) {{
    crossV.style.display = 'block';
    crossV.style.left = e.clientX + 'px';
    // 联动所有图表高亮
    syncAllChartsHover(e);
  }} else {{
    crossV.style.display = 'none';
    clearAllHovers();
  }}
}});

document.addEventListener('mouseup', e => {{
  if (e.button === 1 && dragging) {{
    dragging = false;
    wrap.style.cursor = '';
  }}
  crossV.style.display = 'none';
  clearAllHovers();
}});

wrap.addEventListener('mouseleave', () => {{ crossV.style.display = 'none'; clearAllHovers(); }});

// 阻止中键点击默认的自动滚动行为
document.addEventListener('auxclick', e => {{ if (e.button === 1) e.preventDefault(); }});

// 联动所有图表hover
function syncAllChartsHover(e) {{
  const refChart = charts.find(c => c.canvas && c.canvas.id === 'c-up');
  if (!refChart) return;
  const rect = refChart.canvas.getBoundingClientRect();
  const mouseX = e.clientX - rect.left;
  // 通过 X 轴刻度反查数据索引
  const xScale = refChart.scales.x;
  if (!xScale) return;
  const idx = xScale.getValueForPixel(mouseX);
  if (idx == null || idx < 0 || idx >= winData.length) return;
  const dataIdx = Math.round(idx);

  charts.forEach(ch => {{
    if (!ch || !ch.canvas) return;
    if (ch.isLW) {{
      // lightweight-charts: 使用时间和价格设置 crosshair
      const ohlc = ch.ohlcData[dataIdx];
      if (ohlc) {{
        ch.chart.setCrosshairPosition(ohlc.close, ohlc.date, ch.series);
      }}
      return;
    }}
    const activeElements = [];
    for (let d = 0; d < ch.data.datasets.length; d++) {{
      const m = ch.getDatasetMeta(d);
      if (m && m.data && m.data[dataIdx]) {{
        activeElements.push({{ datasetIndex:d, index:dataIdx }});
      }}
    }}
    ch.setActiveElements(activeElements);
    ch.update('none');
  }});

  // D行日期高亮
  const dateLabels = document.querySelectorAll('#date-axis .dl');
  dateLabels.forEach((el, i) => {{ el.classList.toggle('hl', i === dataIdx); }});

  // 统一悬浮窗内容
  const d = winData[dataIdx];
  const r = ratioData[dataIdx];
  const r311 = ratio311Data[dataIdx];
  const m = motionData[dataIdx];
  const tt = document.getElementById('custom-tooltip');
  const upPct = d.total > 0 ? (d.up / d.total * 100).toFixed(1) : '0.0';
  const dnPct = d.total > 0 ? (d.down / d.total * 100).toFixed(1) : '0.0';

  // 计算成交额 MA5/MA10 及金叉/死叉估算
  const amtVals = winData.map(w => w.amount / 1e8);
  const curMA5 = dataIdx >= 4 ? amtVals.slice(dataIdx-4, dataIdx+1).reduce((a,b) => a+b, 0) / 5 : null;
  const curMA10 = dataIdx >= 9 ? amtVals.slice(dataIdx-9, dataIdx+1).reduce((a,b) => a+b, 0) / 10 : null;
  let crossEstimate = '';
  if (curMA5 !== null && curMA10 !== null) {{
    const sum4 = amtVals[dataIdx - 4] + amtVals[dataIdx - 3] + amtVals[dataIdx - 2] + amtVals[dataIdx - 1];
    const sum9 = amtVals.slice(dataIdx - 9, dataIdx).reduce((a,b) => a+b, 0);
    // 新MA5 = (sum4+x)/5, 新MA10 = (sum9+x)/10
    // 金叉: (sum4+x)/5 > (sum9+x)/10  =>  x > sum9 - 2*sum4
    const threshold = sum9 - 2 * sum4;
    if (curMA5 <= curMA10) {{
      if (threshold > amtVals[dataIdx]) {{
        crossEstimate = '<div class="tt-row"><span class="tt-label">金叉需增量</span><span class="tt-value tt-up">+' + (threshold - amtVals[dataIdx]).toFixed(2) + '亿</span></div>';
      }} else {{
        crossEstimate = '<div class="tt-row"><span class="tt-label">金叉</span><span class="tt-value tt-up">✓ 已满足</span></div>';
      }}
    }} else {{
      if (threshold < amtVals[dataIdx]) {{
        crossEstimate = '<div class="tt-row"><span class="tt-label">死叉需减量</span><span class="tt-value tt-dn">-' + (amtVals[dataIdx] - threshold).toFixed(2) + '亿</span></div>';
      }} else {{
        crossEstimate = '<div class="tt-row"><span class="tt-label">死叉</span><span class="tt-value tt-dn">✓ 已满足</span></div>';
      }}
    }}
  }}

  tt.innerHTML =
    '<div class="tt-date">' + d.date + '</div>' +
    '<div class="tt-sep"></div>' +
    '<div class="tt-row"><span class="tt-label">上涨</span><span class="tt-value tt-up">' + d.up + ' <span style="font-weight:400;color:#787b86;font-size:11px">(' + upPct + '%)</span></span></div>' +
    '<div class="tt-row"><span class="tt-label">下跌</span><span class="tt-value tt-dn">' + d.down + ' <span style="font-weight:400;color:#787b86;font-size:11px">(' + dnPct + '%)</span></span></div>' +
    '<div class="tt-row"><span class="tt-label">平盘</span><span class="tt-value">' + d.flat + '</span></div>' +
    '<div class="tt-row"><span class="tt-label">总数</span><span class="tt-value">' + d.total + '</span></div>' +
    '<div class="tt-row"><span class="tt-label">总成交额</span><span class="tt-value">' + (d.amount / 1e8).toFixed(2) + '亿</span></div>' +
    '<div class="tt-row"><span class="tt-label">MA5</span><span class="tt-value">' + (curMA5 !== null ? curMA5.toFixed(2) : '-') + '亿</span></div>' +
    '<div class="tt-row"><span class="tt-label">MA10</span><span class="tt-value">' + (curMA10 !== null ? curMA10.toFixed(2) : '-') + '亿</span></div>' +
    (crossEstimate) +
    '<div class="tt-row"><span class="tt-label">均价</span><span class="tt-value">' + priceData[dataIdx].avg_close.toFixed(2) + '</span></div>' +
    '<div class="tt-sep"></div>' +
    '<div class="tt-row"><span class="tt-label">31_RATIO</span><span class="tt-value ' + (r.val >= 0 ? 'tt-up' : 'tt-dn') + '">' + (r.val >= 0 ? '+' : '') + r.val.toFixed(2) + '%</span></div>' +
    '<div class="tt-sep"></div>' +
    '<div class="tt-row"><span class="tt-label">311_RATIO</span><span class="tt-value ' + (r311.val >= 0 ? 'tt-up' : 'tt-dn') + '">' + (r311.val >= 0 ? '+' : '') + r311.val.toFixed(2) + '%</span></div>' +
    '<div class="tt-row"><span class="tt-label">HISTORY</span><span class="tt-value ' + (historyData[dataIdx].val >= 0 ? 'tt-up' : 'tt-dn') + '">' + (historyData[dataIdx].val >= 0 ? '+' : '') + historyData[dataIdx].val.toFixed(2) + '%</span></div>' +
    '<div class="tt-sep"></div>' +
    '<div class="tt-row"><span class="tt-label">封板率</span><span class="tt-value ' + (sealData[dataIdx].rate >= 60 ? 'tt-up' : sealData[dataIdx].rate >= 20 ? '' : 'tt-dn') + '">' + sealData[dataIdx].rate.toFixed(1) + '%</span></div>' +
    '<div class="tt-sep"></div>' +
    '<div class="tt-row"><span class="tt-label">TOP数</span><span class="tt-value">' + topData[dataIdx].count + '</span></div>' +
    '<div class="tt-row"><span class="tt-label">TOPPED数</span><span class="tt-value">' + toppedData[dataIdx].count + '</span></div>' +
    '<div class="tt-row"><span class="tt-label">BOTTOM数</span><span class="tt-value">' + bottomData[dataIdx].count + '</span></div>';
  tt.style.display = 'block';
  // 定位在鼠标附近，自动保持在视窗内
  let tx = e.clientX + 16;
  let ty = e.clientY + 16;
  const tw = tt.offsetWidth;
  const th = tt.offsetHeight;
  if (tx + tw > window.innerWidth - 10) tx = e.clientX - tw - 16;
  if (ty + th > window.innerHeight - 10) ty = e.clientY - th - 16;
  if (tx < 10) tx = 10;
  if (ty < 10) ty = 10;
  tt.style.left = tx + 'px';
  tt.style.top = ty + 'px';
}}

function clearAllHovers() {{
  charts.forEach(ch => {{
    if (!ch) return;
    if (ch.isLW) {{
      ch.chart.setCrosshairPosition(null, null, ch.series);
      return;
    }}
    ch.setActiveElements([]);
    if (ch.tooltip) ch.tooltip.setActiveElements([], {{ x:0, y:0 }});
    ch.update('none');
  }});
  document.querySelectorAll('#date-axis .dl.hl').forEach(el => el.classList.remove('hl'));
}}

/* ---- 高度参数变化时重绘 ---- */
document.addEventListener('input', e => {{
  const input = e.target.closest('.height-input');
  if (!input) return;
  const targetId = input.dataset.target;
  const h = parseInt(input.value) || 120;
  const row = input.closest('tr');
  if (!row) return;
  const box = row.querySelector('.chart-box');
  const canvas = document.getElementById(targetId);
  if (!box || !canvas) return;
  box.style.height = h + 'px';
  const ch = charts.find(c => c.canvas === canvas);
  if (ch) {{
    if (ch.resize) ch.resize();
  }}
}});

/* ---- MA 配置变化时重绘 ---- */
function rebuildMAChart() {{
  const ch = charts.find(c => c.canvas && c.canvas.id === 'c-ma');
  if (!ch) return;
  const upVals = winData.map(d => d.up);
  const showLine = document.querySelector('.ma-line-toggle').checked;
  const datasets = [];
  if (showLine) {{
    datasets.push({{ label:'UP', data:upVals, borderColor:'#26a69a', backgroundColor:'rgba(38,166,154,0.08)', fill:true, tension:0.3, pointRadius:0, pointHoverRadius:4, borderWidth:1.5 }});
  }}
  for (let maIdx = 0; maIdx < 3; maIdx++) {{
    const periodInput = document.querySelector('.ma-period[data-ma="'+maIdx+'"]');
    const swatch = document.querySelector('.ma-swatch[data-ma="'+maIdx+'"]');
    if (!periodInput || !swatch) continue;
    const period = parseInt(periodInput.value) || 0;
    const color = swatch.dataset.color || swatch.style.background;
    if (period <= 0) continue;
    const maData = upVals.map((v,i) => i<period-1 ? null : +(upVals.slice(i-period+1,i+1).reduce((a,b)=>a+b,0)/period).toFixed(2));
    datasets.push({{ label:'MA'+period, data:maData, borderColor:color, borderDash:[3,2], fill:false, tension:0.3, pointRadius:0, pointHoverRadius:6, pointHoverBackgroundColor:'#ffffff', borderWidth:1 }});
  }}
  ch.data.datasets = datasets;
  ch.update();
}}

/* ---- 居中包络通道：居中窗口 + 自适应末端预测 ---- */
function computeBand(data, windowSize, smoothAlpha) {{
  const n = data.length;
  const half = Math.floor(windowSize / 2);
  const rawUpper = new Array(n).fill(null);
  const rawLower = new Array(n).fill(null);

  // 居中窗口极值：历史数据用居中（无滞后），右侧末端用回溯（预测）
  for (let i = 0; i < n; i++) {{
    if (data[i] === null || data[i] === undefined) continue;
    const isRightTail = i + half >= n - 1;
    const left = Math.max(0, i - half);
    const right = isRightTail ? i : Math.min(n - 1, i + half);
    let maxV = -Infinity, minV = Infinity;
    for (let j = left; j <= right; j++) {{
      if (data[j] === null || data[j] === undefined) continue;
      if (data[j] > maxV) maxV = data[j];
      if (data[j] < minV) minV = data[j];
    }}
    rawUpper[i] = maxV > -Infinity ? maxV : null;
    rawLower[i] = minV < Infinity ? minV : null;
  }}

  // 轻量平滑（消除阶梯感）
  const peakLine = new Array(n).fill(null);
  const valleyLine = new Array(n).fill(null);
  for (let i = 0; i < n; i++) {{
    if (rawUpper[i] === null) continue;
    if (i === 0 || peakLine[i - 1] === null) {{
      peakLine[i] = rawUpper[i];
      valleyLine[i] = rawLower[i];
    }} else {{
      peakLine[i] = smoothAlpha * rawUpper[i] + (1 - smoothAlpha) * peakLine[i - 1];
      valleyLine[i] = smoothAlpha * rawLower[i] + (1 - smoothAlpha) * valleyLine[i - 1];
    }}
  }}

  // 确保波峰 > 波谷
  for (let i = 0; i < n; i++) {{
    if (peakLine[i] !== null && valleyLine[i] !== null && peakLine[i] < valleyLine[i]) {{
      const mid = (peakLine[i] + valleyLine[i]) / 2;
      const halfRange = Math.abs(peakLine[i] - valleyLine[i]) / 2;
      peakLine[i] = mid + halfRange;
      valleyLine[i] = mid - halfRange;
    }}
  }}

  // 当前预测值（右侧末端包络值即为预测）
  const currentPeak = peakLine[n - 1] || 0;
  const currentValley = valleyLine[n - 1] || 0;
  const currentAmount = data[n - 1] || 0;
  const rangePct = currentPeak - currentValley > 0.01
    ? ((currentAmount - currentValley) / (currentPeak - currentValley) * 100).toFixed(1)
    : '50.0';

  return {{ peakLine, valleyLine, currentPeak, currentValley, currentAmount, rangePct }};
}}

function rebuildPredictionChart() {{
  const ch = charts.find(c => c.canvas && c.canvas.id === 'c-amount-ma');
  if (!ch) return;
  const amtVals = winData.map(d => d.amount / 1e8);
  const windowSize = parseInt(document.querySelector('.env-window').value) || 20;
  const smoothAlpha = parseFloat(document.querySelector('.env-smooth').value) || 0.15;
  const showRaw = document.querySelector('.env-raw-toggle').checked;
  const peakSwatch = document.querySelector('.env-peak-swatch');
  const valleySwatch = document.querySelector('.env-valley-swatch');
  const peakColor = (peakSwatch && peakSwatch.dataset.color) || '#ef5350';
  const valleyColor = (valleySwatch && valleySwatch.dataset.color) || '#00e5ff';

  const {{ peakLine, valleyLine, currentPeak, currentValley, currentAmount, rangePct }} = computeBand(amtVals, windowSize, smoothAlpha);

  // 成交额按通道位置着色
  const amtColors = amtVals.map((v, i) => {{
    if (v === null || v === undefined) return '#ffd740';
    const p = peakLine[i], vl = valleyLine[i];
    if (p === null || vl === null) return '#ffd740';
    if (v < vl) return '#26a69a';
    if (v > p) return '#ef5350';
    return '#ffd740';
  }});

  const datasets = [];

  // ① 包络区间填充（峰→谷）
  datasets.push({{
    label: '包络区间', data: peakLine,
    borderColor: 'transparent', backgroundColor: 'rgba(255,215,64,0.06)',
    fill: '+1', pointRadius: 0, pointHoverRadius: 0, borderWidth: 0,
  }});

  // ② 波谷包络线
  datasets.push({{
    label: '波谷包络', data: valleyLine,
    borderColor: valleyColor, backgroundColor: 'transparent',
    fill: false, tension: 0,
    pointRadius: 0, pointHoverRadius: 6, pointHoverBackgroundColor: '#ffffff',
    borderWidth: 1.5, borderDash: [4, 3],
  }});

  // ③ 波峰包络线
  datasets.push({{
    label: '波峰包络', data: peakLine,
    borderColor: peakColor, backgroundColor: 'transparent',
    fill: false, tension: 0,
    pointRadius: 0, pointHoverRadius: 6, pointHoverBackgroundColor: '#ffffff',
    borderWidth: 1.5, borderDash: [4, 3],
  }});

  // ④ 实际成交额
  if (showRaw) {{
    datasets.push({{
      label: '成交额', data: amtVals,
      borderColor: '#ffd740',
      backgroundColor: 'rgba(255,215,64,0.08)',
      fill: true, tension: 0.3,
      pointRadius: 0, pointHoverRadius: 6, pointHoverBackgroundColor: '#ffffff',
      borderWidth: 2,
      segment: {{
        borderColor: ctx => {{
          const i = ctx.p1DataIndex;
          return amtColors[i] || '#ffd740';
        }}
      }}
    }});
  }}

  ch.data.datasets = datasets;
  ch.update();

  // 更新底部预测值信息
  let infoEl = document.getElementById('prediction-info');
  if (!infoEl) {{
    infoEl = document.createElement('div');
    infoEl.id = 'prediction-info';
    infoEl.style.cssText = 'font-size:11px;color:#787b86;margin-top:4px;';
    const paramGroup = document.querySelector('.param-group');
    if (paramGroup) paramGroup.appendChild(infoEl);
  }}
  const pct = parseFloat(rangePct);
  const posColor = pct > 70 ? '#ef5350' : pct < 30 ? '#26a69a' : '#ffd740';
  const statusText = pct > 80 ? '⚠ 超买区' : pct < 20 ? '⚠ 超卖区' : '✓ 合理区间';
  infoEl.innerHTML =
    '<div style="display:flex;justify-content:space-between;gap:8px;">' +
    '<span>波峰 <b style="color:' + peakColor + ';">' + currentPeak.toFixed(2) + '亿</b></span>' +
    '<span>当前 <b style="color:' + posColor + ';">' + currentAmount.toFixed(2) + '亿</b></span>' +
    '<span>波谷 <b style="color:' + valleyColor + ';">' + currentValley.toFixed(2) + '亿</b></span>' +
    '</div>' +
    '<div style="margin-top:2px;text-align:center;font-size:10px;color:' + posColor + ';">' +
    '通道位置: ' + rangePct + '%  ' + statusText +
    '</div>';
}}

function rebuildRatioCharts() {{
  const rc = getRatioColors();
  const upColor = hexToRgba(rc.up, 0.18);
  const dnColor = hexToRgba(rc.dn, 0.18);
  charts.forEach(ch => {{
    if (!ch || !ch.canvas) return;
    const id = ch.canvas.id;
    if (id !== 'c-ratio' && id !== 'c-ratio311') return;
    ch.data.datasets[0].borderColor = rc.line;
    ch.data.datasets[0].fill.above = upColor;
    ch.data.datasets[0].fill.below = dnColor;
    ch.update();
  }});
}}

let activeColorSwatch = null;

// 颜色矩阵点击
document.addEventListener('click', e => {{
  const grid = document.getElementById('global-color-grid');
  // 点击颜色方格
  const span = e.target.closest('.color-grid span');
  if (span) {{
    if (activeColorSwatch) {{
      activeColorSwatch.style.background = span.dataset.color;
      activeColorSwatch.dataset.color = span.dataset.color;
      grid.classList.remove('show');
      if (activeColorSwatch.classList.contains('ratio-swatch')) {{
        rebuildRatioCharts();
      }} else if (activeColorSwatch.classList.contains('ohlc-ma-swatch')) {{
        // 触发 K线 MA 重建
        const evt = new Event('change');
        document.querySelector('.ohlc-ma-period')?.dispatchEvent(evt);
      }} else if (activeColorSwatch.classList.contains('env-peak-swatch') || activeColorSwatch.classList.contains('env-valley-swatch')) {{
        rebuildPredictionChart();
      }} else {{
        rebuildMAChart();
      }}
      activeColorSwatch = null;
    }}
    return;
  }}
  // 点击色块显示/隐藏网格
  const sw = e.target.closest('.ma-swatch, .ratio-swatch, .ohlc-ma-swatch, .env-peak-swatch, .env-valley-swatch');
  if (sw) {{
    if (activeColorSwatch === sw) {{
      grid.classList.remove('show');
      activeColorSwatch = null;
      return;
    }}
    const r = sw.getBoundingClientRect();
    grid.style.top = (r.bottom + 2) + 'px';
    grid.style.right = (window.innerWidth - r.right) + 'px';
    grid.style.left = 'auto';
    grid.classList.add('show');
    activeColorSwatch = sw;
    return;
  }}
  // 点击外部关闭
  if (!e.target.closest('.color-picker')) {{
    grid.classList.remove('show');
    activeColorSwatch = null;
  }}
}});

document.addEventListener('input', e => {{
  if (e.target.closest('.ma-period')) rebuildMAChart();
  if (e.target.closest('.env-window') || e.target.closest('.env-smooth') || e.target.closest('.env-peak-swatch') || e.target.closest('.env-valley-swatch')) rebuildPredictionChart();
}});
document.addEventListener('change', e => {{
  if (e.target.closest('.ma-line-toggle')) rebuildMAChart();
  if (e.target.closest('.env-raw-toggle')) rebuildPredictionChart();
}});

/* ---- 构建 D 行日期轴（1:1 垂直标签） ---- */
function buildDateAxis() {{
  const axis = document.getElementById('date-axis');
  if (!axis || winData.length === 0) return;
  const barW = 11; // 每根柱子宽度 11px
  const totalW = winData.length * barW;
  axis.style.width = totalW + 'px';

  winData.forEach(d => {{
    const el = document.createElement('div');
    el.className = 'dl';
    el.textContent = d.date;
    axis.appendChild(el);
  }});
}}

/* ---- 图表 ---- */
function destroyCharts() {{ charts.forEach(c => c.destroy()); charts = []; }}

function init() {{
  if (stocks.length === 0) {{
    document.querySelector('#scroll-wrap table tbody').innerHTML =
      '<tr><td colspan="3" class="empty">暂无数据</td></tr>';
    return;
  }}
  buildDateAxis();
  setTimeout(() => renderCharts(), 60);
}}

function renderCharts() {{
  const records = stocks.map(s => ({{
    code: s.code,
    close: parseFloat(s.close),
    pre: parseFloat(s.pre_close),
    pct: (parseFloat(s.close)-parseFloat(s.pre_close))/parseFloat(s.pre_close)*100,
  }}));

  const chartWidth = Math.max(3000, winData.length * 11);
  // 统一上下图Y轴范围
  const maxUpVal = Math.max(...winData.map(d => d.up));
  const maxDnVal = Math.max(...winData.map(d => d.down));
  const globalMax = Math.max(maxUpVal, maxDnVal);

  /* ---- 第2行：上升均线（用 UP 数据 + 最多3条MA，默认 5/10/0） ---- */
  const ctx1 = document.getElementById('c-ma');
  if (ctx1 && winData.length > 0) {{
    const upVals = winData.map(d => d.up);
    const datasets = [
      {{ label:'UP', data:upVals, borderColor:'#26a69a', backgroundColor:'rgba(38,166,154,0.08)', fill:true, tension:0.3, pointRadius:0, pointHoverRadius:6, pointHoverBackgroundColor:'#ffffff', borderWidth:1.5 }}
    ];
    for (let maIdx = 0; maIdx < 3; maIdx++) {{
      const periodInput = document.querySelector('.ma-period[data-ma="'+maIdx+'"]');
      const sw = document.querySelector('.ma-swatch[data-ma="'+maIdx+'"]');
      if (!periodInput || !sw) continue;
      const p = parseInt(periodInput.value) || 0;
      const color = sw.style.background;
      if (p <= 0) continue;
      const ma = upVals.map((v,i) => i<p-1 ? null : +(upVals.slice(i-p+1,i+1).reduce((a,b)=>a+b,0)/p).toFixed(2));
      datasets.push({{ label:'MA'+p, data:ma, borderColor:color, borderDash:[3,2], fill:false, tension:0.3, pointRadius:0, pointHoverRadius:6, pointHoverBackgroundColor:'#ffffff', borderWidth:1 }});
    }}
    charts.push(new Chart(ctx1, {{
      type:'line',
      data:{{ labels: winData.map(d => d.date), datasets: datasets }},
      options:{{
        responsive:true, maintainAspectRatio:false,
        plugins:{{ legend:{{ display:false }}, tooltip:{{ enabled:false }} }},
        scales:{{
          x:{{ offset:true, ticks:{{ display:false }}, grid:{{ display:false }} }},
          y:{{ display:false }}
        }}
      }}
    }}));
  }}

  /* ---- 第3行：每日上涨个数 ---- */
  const ctx2 = document.getElementById('c-up');
  if (ctx2 && winData.length > 0) {{
    const upVals = winData.map(d => d.up);
    // 用真实日期作为 labels（供 tooltip 使用），但 X 轴隐藏
    const ch = new Chart(ctx2, {{
      type:'bar',
      data:{{
        labels: winData.map(d => d.date),
        datasets:[{{ label:'上涨个数', data:upVals, backgroundColor:'#ef5350', borderColor:'#b71c1c', hoverBackgroundColor:'#ff8a80', hoverBorderColor:'#ffffff', hoverBorderWidth:2, borderWidth:1, borderRadius:1, barPercentage:0.92, categoryPercentage:1 }}]
      }},
      options:{{
        responsive:true, maintainAspectRatio:false,
        interaction:{{ mode:'index', intersect:false }},
        plugins:{{ legend:{{ display:false }}, tooltip:{{ enabled:false }} }},
        scales:{{
          x:{{ offset:true, ticks:{{ display:false }}, grid:{{ display:false }} }},
          y:{{ display:true, position:'right', ticks:{{ display:false }}, grid:{{ color:'#485c7b55', borderDash:[3,4], lineWidth:1 }}, border:{{ display:false }}, max:globalMax }}
        }}
      }}
    }});
    charts.push(ch);
  }}

  /* ---- 第4行：下跌柱状图（用 winData.down，向下柱子） ---- */
  const ctx3 = document.getElementById('c-dn');
  if (ctx3 && winData.length > 0) {{
    const dnVals = winData.map(d => -d.down);  // 负值，柱子向下
    charts.push(new Chart(ctx3, {{
      type:'bar',
      data:{{
        labels: winData.map(d => d.date),
        datasets:[{{ label:'下跌个数', data:dnVals, backgroundColor:'#00e5ff', borderColor:'#00b8d4', hoverBackgroundColor:'#69f0ae', hoverBorderColor:'#ffffff', hoverBorderWidth:2, borderWidth:1, borderRadius:1, barPercentage:0.92, categoryPercentage:1 }}]
      }},
      options:{{
        responsive:true, maintainAspectRatio:false,
        interaction:{{ mode:'index', intersect:false }},
        plugins:{{ legend:{{ display:false }}, tooltip:{{ enabled:false }} }},
        scales:{{
          x:{{ offset:true, ticks:{{ display:false }}, grid:{{ display:false }} }},
          y:{{ display:true, position:'right', ticks:{{ display:false }}, grid:{{ color:'#485c7b55', borderDash:[3,4], lineWidth:1 }}, border:{{ display:false }} }}
        }}
      }}
    }}));
  }}

  /* ---- 第6行：居中包络通道（居中窗口 + 自适应末端预测） ---- */
  const ctxAmt = document.getElementById('c-amount-ma');
  if (ctxAmt && winData.length > 0) {{
    const amtVals = winData.map(d => d.amount / 1e8);
    const windowSize = parseInt(document.querySelector('.env-window').value) || 20;
    const smoothAlpha = parseFloat(document.querySelector('.env-smooth').value) || 0.15;
    const showRaw = document.querySelector('.env-raw-toggle').checked;
    const peakSwatch = document.querySelector('.env-peak-swatch');
    const valleySwatch = document.querySelector('.env-valley-swatch');
    const peakColor = (peakSwatch && peakSwatch.dataset.color) || '#ef5350';
    const valleyColor = (valleySwatch && valleySwatch.dataset.color) || '#00e5ff';

    const {{ peakLine, valleyLine, currentPeak, currentValley, currentAmount, rangePct }} = computeBand(amtVals, windowSize, smoothAlpha);

    const amtColors = amtVals.map((v, i) => {{
      if (v === null || v === undefined) return '#ffd740';
      const p = peakLine[i], vl = valleyLine[i];
      if (p === null || vl === null) return '#ffd740';
      if (v < vl) return '#26a69a';
      if (v > p) return '#ef5350';
      return '#ffd740';
    }});

    const datasets = [];
    datasets.push({{
      label: '包络区间', data: peakLine,
      borderColor: 'transparent', backgroundColor: 'rgba(255,215,64,0.06)',
      fill: '+1', pointRadius: 0, pointHoverRadius: 0, borderWidth: 0,
    }});
    datasets.push({{
      label: '波谷包络', data: valleyLine,
      borderColor: valleyColor, backgroundColor: 'transparent',
      fill: false, tension: 0,
      pointRadius: 0, pointHoverRadius: 6, pointHoverBackgroundColor: '#ffffff',
      borderWidth: 1.5, borderDash: [4, 3],
    }});
    datasets.push({{
      label: '波峰包络', data: peakLine,
      borderColor: peakColor, backgroundColor: 'transparent',
      fill: false, tension: 0,
      pointRadius: 0, pointHoverRadius: 6, pointHoverBackgroundColor: '#ffffff',
      borderWidth: 1.5, borderDash: [4, 3],
    }});
    if (showRaw) {{
      datasets.push({{
        label: '成交额', data: amtVals,
        borderColor: '#ffd740',
        backgroundColor: 'rgba(255,215,64,0.08)',
        fill: true, tension: 0.3,
        pointRadius: 0, pointHoverRadius: 6, pointHoverBackgroundColor: '#ffffff',
        borderWidth: 2,
        segment: {{
          borderColor: ctx => {{ const i = ctx.p1DataIndex; return amtColors[i] || '#ffd740'; }}
        }}
      }});
    }}

    charts.push(new Chart(ctxAmt, {{
      type: 'line',
      data: {{ labels: winData.map(d => d.date), datasets: datasets }},
      options: {{
        responsive: true, maintainAspectRatio: false,
        plugins: {{ legend: {{ display: false }}, tooltip: {{ enabled: false }} }},
        scales: {{
          x: {{ offset: true, ticks: {{ display: false }}, grid: {{ display: false }} }},
          y: {{ display: false }}
        }}
      }}
    }}));
  }}

  /* ---- 第7行：成交额柱状图（winData.amount，单位亿） ---- */
  const ctxAmtRaw = document.getElementById('c-amount-raw');
  if (ctxAmtRaw && winData.length > 0) {{
    const amtRawVals = winData.map(d => d.amount / 1e8);
    charts.push(new Chart(ctxAmtRaw, {{
      type:'bar',
      data:{{
        labels: winData.map(d => d.date),
        datasets:[{{ label:'总成交额', data:amtRawVals, backgroundColor:'#ffd740', borderColor:'#ffab00', hoverBackgroundColor:'#fff176', hoverBorderColor:'#ffffff', hoverBorderWidth:2, borderWidth:1, borderRadius:1, barPercentage:0.92, categoryPercentage:1 }}]
      }},
      options:{{
        responsive:true, maintainAspectRatio:false,
        interaction:{{ mode:'index', intersect:false }},
        plugins:{{ legend:{{ display:false }}, tooltip:{{ enabled:false }} }},
        scales:{{
          x:{{ offset:true, ticks:{{ display:false }}, grid:{{ display:false }} }},
          y:{{ display:true, position:'right', ticks:{{ display:false, callback:v => v + '亿' }}, grid:{{ color:'#485c7b55', borderDash:[3,4], lineWidth:1 }}, border:{{ display:false }} }}
        }}
      }}
    }}));
  }}

/* ---- 辅助函数：获取ratio颜色配置 ---- */
function getRatioColors() {{
  const ls = document.querySelector('.ratio-line-swatch');
  const us = document.querySelector('.ratio-up-swatch');
  const ds = document.querySelector('.ratio-dn-swatch');
  return {{
    line: (ls && ls.dataset.color) || '#26a69a',
    up: (us && us.dataset.color) || '#ef5350',
    dn: (ds && ds.dataset.color) || '#00e5ff',
  }};
}}
function hexToRgba(hex, alpha) {{
  if (!hex || hex.startsWith('rgba') || hex.startsWith('rgb')) return hex || 'rgba(0,0,0,0.18)';
  const h = hex.replace('#','');
  const r = parseInt(h.substring(0,2),16);
  const g = parseInt(h.substring(2,4),16);
  const b = parseInt(h.substring(4,6),16);
  return `rgba(${{r}},${{g}},${{b}},${{alpha}})`;
}}
function makeRatioChartOptions() {{
  return {{
    responsive:true, maintainAspectRatio:false,
    interaction:{{ mode:'index', intersect:false }},
    plugins:{{ legend:{{ display:false }}, tooltip:{{ enabled:false }} }},
    scales:{{
      x:{{ offset:true, ticks:{{ display:false }}, grid:{{ display:false }} }},
      y:{{ display:true, position:'right', min:-11, max:11,
        ticks:{{ display:false, stepSize:5 }},
        afterBuildTicks: axis => {{ axis.ticks = axis.ticks.filter(t => t.value === -5 || t.value === 5); }},
        grid:{{ color:'#485c7b55', borderDash:[3,4], lineWidth:1 }},
        border:{{ display:false }}
      }}
    }}
  }};
}}

  /* ---- 第8行：31_RATIO（单线 + 上下不同色阴影） ---- */
  const ctx4 = document.getElementById('c-ratio');
  if (ctx4 && ratioData.length > 0) {{
    const vals = ratioData.map(d => d.val);
    const rc = getRatioColors();
    charts.push(new Chart(ctx4, {{
      type:'line',
      data:{{
        labels: ratioData.map(d => d.date),
        datasets:[{{
          label:'RATIO', data:vals,
          borderColor:rc.line,
          fill:{{ target:{{ value:0 }}, above:hexToRgba(rc.up,0.18), below:hexToRgba(rc.dn,0.18) }},
          tension:0.2, pointRadius:0, pointHoverRadius:5, pointHoverBackgroundColor:'#ffffff', borderWidth:1.2
        }}]
      }},
      options: makeRatioChartOptions()
    }}));
  }}


  /* ---- 第8.5行：31_RATIO K线（lightweight-charts） + 均线 ---- */
  function renderOHLC_Kline(containerId, ohlcData, dataAttr) {{
    try {{
    const container = document.getElementById(containerId);
    if (!container || ohlcData.length === 0) return;
    const ohlcChart = LightweightCharts.createChart(container, {{
      width: container.parentElement.clientWidth || chartWidth,
      height: container.parentElement.clientHeight || 500,
      layout: {{ background: {{ type: 'solid', color: 'transparent' }}, textColor: '#787b86' }},
      grid: {{ vertLines: {{ color: '#2b2b43' }}, horzLines: {{ color: '#2b2b43' }} }},
      crosshair: {{ mode: LightweightCharts.CrosshairMode.Normal }},
      rightPriceScale: {{ borderColor: '#2b2b43', visible: false }},
      timeScale: {{ borderColor: '#2b2b43', visible: false, shiftVisibleRangeOnNewBar: false, rightOffset: 0, barSpacing: 8 }},
      handleScroll: false,
      handleScale: false,
    }});
    const candleSeries = ohlcChart.addCandlestickSeries({{
      upColor: '#ef5350', downColor: '#00e5ff', borderUpColor: '#ef5350', borderDownColor: '#00e5ff',
      wickUpColor: '#ef5350', wickDownColor: '#00e5ff',
    }});
    const ohlcFormatted = ohlcData.map(d => ({{
      time: d.date,
      open: d.open,
      high: d.high,
      low: d.low,
      close: d.close,
    }}));
    candleSeries.setData(ohlcFormatted);
    ohlcChart.timeScale().fitContent();
    // 去掉右侧间距，与其它图表右对齐
    ohlcChart.timeScale().scrollToPosition(0, false);
    // 自动适配价格范围
    ohlcChart.priceScale('right').applyOptions({{ autoScale: true }});

    // 计算并添加 MA 均线
    const closeVals = ohlcData.map(d => d.close);
    const maSeries = [];
    function rebuildMA() {{
      maSeries.forEach(s => ohlcChart.removeSeries(s));
      maSeries.length = 0;
      for (let maIdx = 0; maIdx < 3; maIdx++) {{
        const periodInput = document.querySelector('.ohlc-ma-period[data-ma="' + maIdx + '"][data-ohlc="' + dataAttr + '"]');
        const swatch = document.querySelector('.ohlc-ma-swatch[data-ma="' + maIdx + '"]');
        if (!periodInput || !swatch) continue;
        const period = parseInt(periodInput.value) || 0;
        const color = swatch.dataset.color || swatch.style.background;
        if (period <= 0) continue;
        const maData = closeVals.map((v, i) =>
          i < period - 1 ? null : +(closeVals.slice(i - period + 1, i + 1).reduce((a, b) => a + b, 0) / period).toFixed(4)
        );
        const lineData = [];
        for (let i = 0; i < maData.length; i++) {{
          if (maData[i] !== null) {{
            lineData.push({{ time: ohlcData[i].date, value: maData[i] }});
          }}
        }}
        if (lineData.length > 0) {{
          const s = ohlcChart.addLineSeries({{
            color: color,
            lineWidth: 1,
            lastValueVisible: false,
            priceLineVisible: false,
          }});
          s.setData(lineData);
          maSeries.push(s);
        }}
      }}
    }}
    rebuildMA();

    // 将 lightweight-charts 实例包装后加入 charts 数组
    charts.push({{
      canvas: container,
      isLW: true,
      chart: ohlcChart,
      series: candleSeries,
      ohlcData: ohlcData,
      setActiveElements: function(active) {{}},
      update: function() {{}},
      resize: function() {{
        const w = container.parentElement.clientWidth || chartWidth;
        const h = container.parentElement.clientHeight || 500;
        ohlcChart.applyOptions({{ width: w, height: h }});
      }},
    }});

    // 窗口大小变化时自动 resize
    const ro = new ResizeObserver(() => {{
      const w = container.parentElement.clientWidth || chartWidth;
      const h = container.parentElement.clientHeight || 500;
      ohlcChart.applyOptions({{ width: w, height: h }});
    }});
    ro.observe(container.parentElement);

    // MA 参数变化时重绘（只响应自己 data-ohlc 的 input）
    document.querySelectorAll('.ohlc-ma-period[data-ohlc="' + dataAttr + '"]').forEach(input => {{
      input.addEventListener('change', rebuildMA);
      input.addEventListener('input', rebuildMA);
    }});
    }} catch(e) {{
      console.error(containerId + ' K线图表加载失败:', e);
    }}
  }}

  renderOHLC_Kline('c-ohlc', ohlcData, '31');
  renderOHLC_Kline('c-ohlc311', ohlc311Data, '311');
  renderOHLC_Kline('c-ohlc-history', ohlcHistoryData, 'history');

  renderOHLC_Kline('c-ohlc-amount', amountOhlcData, 'amount');


  /* ---- 第9行：311_RATIO（单线 + 上下不同色阴影） ---- */
  const ctx5 = document.getElementById('c-ratio311');
  if (ctx5 && ratio311Data.length > 0) {{
    const vals = ratio311Data.map(d => d.val);
    const rc = getRatioColors();
    charts.push(new Chart(ctx5, {{
      type:'line',
      data:{{
        labels: ratio311Data.map(d => d.date),
        datasets:[{{
          label:'311RATIO', data:vals,
          borderColor:rc.line,
          fill:{{ target:{{ value:0 }}, above:hexToRgba(rc.up,0.18), below:hexToRgba(rc.dn,0.18) }},
          tension:0.2, pointRadius:0, pointHoverRadius:5, pointHoverBackgroundColor:'#ffffff', borderWidth:1.2
        }}]
      }},
      options: makeRatioChartOptions()
    }}));
  }}


  /* ---- 第10行：HISTORY_RATIO（单线 + 上下不同色阴影） ---- */
  const ctxHistory = document.getElementById('c-history');
  if (ctxHistory && historyData.length > 0) {{
    const vals = historyData.map(d => d.val);
    const rc = getRatioColors();
    charts.push(new Chart(ctxHistory, {{
      type:'line',
      data:{{
        labels: historyData.map(d => d.date),
        datasets:[{{
          label:'HISTORY', data:vals,
          borderColor:rc.line,
          fill:{{ target:{{ value:0 }}, above:hexToRgba(rc.up,0.18), below:hexToRgba(rc.dn,0.18) }},
          tension:0.2, pointRadius:0, pointHoverRadius:5, pointHoverBackgroundColor:'#ffffff', borderWidth:1.2
        }}]
      }},
      options: makeRatioChartOptions()
    }}));
  }}



  /* ---- 第12行：封板率柱状图 TOP/(TOPPED+TOP)*100 ---- */
  const ctxSeal = document.getElementById('c-seal');
  if (ctxSeal && sealData.length > 0) {{
    const sealVals = sealData.map(d => d.rate);
    charts.push(new Chart(ctxSeal, {{
      type:'bar',
      data:{{
        labels: winData.map(d => d.date),
        datasets:[{{ label:'封板率%', data:sealVals, backgroundColor:sealVals.map(v => v >= 60 ? '#26a69a' : v >= 40 ? '#ffd740' : v >= 20 ? '#ff8a65' : '#ef5350'), borderColor:'#00897b', hoverBackgroundColor:'#80cbc4', hoverBorderColor:'#ffffff', hoverBorderWidth:2, borderWidth:1, borderRadius:1, barPercentage:0.92, categoryPercentage:1 }}]
      }},
      options:{{
        responsive:true, maintainAspectRatio:false,
        interaction:{{ mode:'index', intersect:false }},
        plugins:{{ legend:{{ display:false }}, tooltip:{{ enabled:false }} }},
        scales:{{
          x:{{ offset:true, ticks:{{ display:false }}, grid:{{ display:false }} }},
          y:{{ display:true, position:'right', min:0, max:100,
            ticks:{{ display:false, stepSize:20 }},
            grid:{{ color:'#485c7b55', borderDash:[3,4], lineWidth:1 }},
            border:{{ display:false }}
          }}
        }}
      }}
    }}));
  }}

  /* ---- 第13行：TOPPED数量柱状图 ---- */
  const ctxTopped = document.getElementById('c-topped');
  if (ctxTopped && toppedData.length > 0) {{
    const toppedVals = toppedData.map(d => d.count);
    charts.push(new Chart(ctxTopped, {{
      type:'bar',
      data:{{
        labels: winData.map(d => d.date),
        datasets:[{{ label:'TOPPED数量', data:toppedVals, backgroundColor:'#26a69a', borderColor:'#00897b', hoverBackgroundColor:'#80cbc4', hoverBorderColor:'#ffffff', hoverBorderWidth:2, borderWidth:1, borderRadius:1, barPercentage:0.92, categoryPercentage:1 }}]
      }},
      options:{{
        responsive:true, maintainAspectRatio:false,
        interaction:{{ mode:'index', intersect:false }},
        plugins:{{ legend:{{ display:false }}, tooltip:{{ enabled:false }} }},
        scales:{{
          x:{{ offset:true, ticks:{{ display:false }}, grid:{{ display:false }} }},
          y:{{ display:true, position:'right', max:50, ticks:{{ display:false }}, grid:{{ color:'#485c7b55', borderDash:[3,4], lineWidth:1 }}, border:{{ display:false }} }}
        }}
      }}
    }}));
  }}

  /* ---- 第14行：TOP数量柱状图 ---- */
  const ctx6 = document.getElementById('c-top');
  if (ctx6 && topData.length > 0) {{
    const topVals = topData.map(d => d.count);
    charts.push(new Chart(ctx6, {{
      type:'bar',
      data:{{
        labels: winData.map(d => d.date),
        datasets:[{{ label:'TOP数量', data:topVals, backgroundColor:'#7c4dff', borderColor:'#651fff', hoverBackgroundColor:'#b388ff', hoverBorderColor:'#ffffff', hoverBorderWidth:2, borderWidth:1, borderRadius:1, barPercentage:0.92, categoryPercentage:1 }}]
      }},
      options:{{
        responsive:true, maintainAspectRatio:false,
        interaction:{{ mode:'index', intersect:false }},
        plugins:{{ legend:{{ display:false }}, tooltip:{{ enabled:false }} }},
        scales:{{
          x:{{ offset:true, ticks:{{ display:false }}, grid:{{ display:false }} }},
          y:{{ display:true, position:'right', max:50, ticks:{{ display:false }}, grid:{{ color:'#485c7b55', borderDash:[3,4], lineWidth:1 }}, border:{{ display:false }} }}
        }}
      }}
    }}));
  }}

  /* ---- 第15行：BOTTOM数量柱状图 ---- */
  const ctx7 = document.getElementById('c-bottom');
  if (ctx7 && bottomData.length > 0) {{
    const botVals = bottomData.map(d => d.count);
    charts.push(new Chart(ctx7, {{
      type:'bar',
      data:{{
        labels: winData.map(d => d.date),
        datasets:[{{ label:'BOTTOM数量', data:botVals, backgroundColor:'#ff9100', borderColor:'#e65100', hoverBackgroundColor:'#ffb74d', hoverBorderColor:'#ffffff', hoverBorderWidth:2, borderWidth:1, borderRadius:1, barPercentage:0.92, categoryPercentage:1 }}]
      }},
      options:{{
        responsive:true, maintainAspectRatio:false,
        interaction:{{ mode:'index', intersect:false }},
        plugins:{{ legend:{{ display:false }}, tooltip:{{ enabled:false }} }},
        scales:{{
          x:{{ offset:true, ticks:{{ display:false }}, grid:{{ display:false }} }},
          y:{{ display:true, position:'right', max:50, ticks:{{ display:false }}, grid:{{ color:'#485c7b55', borderDash:[3,4], lineWidth:1 }}, border:{{ display:false }} }}
        }}
      }}
    }}));
  }}

  // 用 Chart.js 柱子的精确 X 坐标定位 D 行标签
  setTimeout(() => {{
    const ch = charts.find(c => c.canvas && c.canvas.id === 'c-up');
    if (!ch) return;
    const meta = ch.getDatasetMeta(0);
    if (!meta || !meta.data || !meta.data.length) return;
    const axis = document.getElementById('date-axis');
    if (!axis) return;
    const labels = axis.querySelectorAll('.dl');
    if (!labels.length) return;
    // 获取第一个柱子的左边界作为偏移基准
    const firstX = meta.data[0].x;
    const lastX = meta.data[meta.data.length - 1].x;
    // 计算每根柱子的实际间距（Chart.js 可能不等距）
    const gaps = [];
    for (let i = 1; i < meta.data.length; i++) {{
      gaps.push(meta.data[i].x - meta.data[i-1].x);
    }}
    const avgGap = gaps.length > 0 ? Math.round(gaps.reduce((a,b)=>a+b,0)/gaps.length) : 11;
    const totalW = lastX - firstX + avgGap;
    axis.style.width = totalW + 'px';
    axis.style.paddingLeft = firstX + 'px';
    // 用每个柱子的精确 X 坐标定位 label
    labels.forEach((el, i) => {{
      const cx = meta.data[i].x - firstX;
      el.style.left = cx + 'px';
      el.style.width = avgGap + 'px';
      el.style.transform = 'translateX(-50%)';
    }});
  }}, 400);
}}

init();
</script>
</body>
</html>'''

    output = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'target_1d.html')
    with open(output, 'w', encoding='utf-8') as f:
        f.write(html)
    webbrowser.open(output)
    print(f'[SHOW] {latest} ({len(stocks)} stocks, {len(win_data)} days) -> {output}')


def SHOW_5M_MOTION():
    # 5M分时段涨跌家数—表格四行：时间/上涨/下降/成交额，样式参考1D。
    from AICode.MarcoAPI.Update.DataAligned import READ_ALIGNED_LINES
    import json

    motion_path = os.path.join(PATH_AIDATA_MOTION(), "5M_MOTION_COUNT")
    if not os.path.isfile(motion_path):
        print('[SHOW_5M_MOTION] 数据文件不存在')
        return

    data = []
    for date, line in READ_ALIGNED_LINES(motion_path):
        if line:
            parts = line.split('|')
            data.append({
                'date': date,
                'open_up': int(parts[1]), 'open_dn': int(parts[2]),
                'noon_up': int(parts[3]), 'noon_dn': int(parts[4]), 'noon_amt': float(parts[5]),
                'close_up': int(parts[6]), 'close_dn': int(parts[7]), 'close_amt': float(parts[8]),
            })
        else:
            data.append({
                'date': date, 'open_up': 0, 'open_dn': 0,
                'noon_up': 0, 'noon_dn': 0, 'noon_amt': 0.0,
                'close_up': 0, 'close_dn': 0, 'close_amt': 0.0,
            })

    data_json = json.dumps(data, ensure_ascii=False)
    n = len(data)
    col_chart_w = max(3000, n * 32)
    colors_64 = [
        '#ff0000','#ff4500','#ff8c00','#ffd700','#ffff00','#adff2f','#00ff00','#00ff7f',
        '#00ffff','#00bfff','#1e90ff','#0000ff','#8a2be2','#9400d3','#ff00ff','#ff1493',
        '#dc143c','#b22222','#8b0000','#cd5c5c','#f08080','#ff6347','#ff6600','#f4a460',
        '#b8860b','#bdb76b','#808000','#9acd32','#32cd32','#228b22','#006400','#008080',
        '#20b2aa','#00ced1','#5f9ea0','#4682b4','#4169e1','#483d8b','#4b0082','#8b008b',
        '#9932cc','#da70d6','#dda0dd','#ff69b4','#db7093','#ffc0cb','#a52a2a','#d2691e',
        '#cd853f','#8fbc8f','#2e8b57','#556b2f','#808080','#c0c0c0','#ffffff','#696969',
        '#a9a9a9','#2f4f4f','#000000','#bc8f8f','#6495ed','#e9967a','#f5a623','#00e5ff'
    ]
    color_opts = ''.join(f'<span style="background:{c}" data-color="{c}"></span>' for c in colors_64)

    html = f'''<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>5M分时段涨跌家数</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  html, body {{ height:100%; background:#131722; color:#d1d4dc; font-family:'Segoe UI',sans-serif; overflow:hidden; }}
  body {{ padding:10px 20px 20px 0; }}
  #scroll-wrap {{ overflow:auto; width:100%; height:calc(100vh - 30px); overscroll-behavior-x:none; touch-action:pan-y; }}
  #scroll-wrap::-webkit-scrollbar {{ display:none; }}
  #scroll-wrap {{ -ms-overflow-style:none; scrollbar-width:none; }}
  table {{ table-layout:fixed; width:{col_chart_w + 460}px; border-collapse:collapse; }}
  td {{ padding:8px 10px; border-bottom:1px solid #2b2b43; vertical-align:middle; background:#131722; }}
  .col-idx {{ position:sticky; left:0; z-index:3; width:240px; text-align:center; color:#ffffff; font-size:200px; font-weight:900; line-height:1; }}
  .col-chart {{ width:{col_chart_w}px; position:relative; }}
  .col-param {{ position:sticky; right:0; z-index:3; width:220px; padding-left:20px; }}
  .row-date {{ position:sticky; top:0; z-index:4; }}
  .row-date td {{ padding:0 0 10px; background:#131722; }}
  .row-date .data-area {{ display:flex; align-items:stretch; height:80px; padding:0 10px 0 5px; }}
  .date-axis {{ position:relative; height:100%; }}
  .date-axis .dl {{ position:absolute; top:0; bottom:0; writing-mode:vertical-rl; text-orientation:upright; font-size:8px; color:#d1d4dc; text-align:center; border-left:1px solid #5a5f7a; display:flex; align-items:center; justify-content:center; }}
  .date-axis .dl.hl {{ background:#ffffff15; font-weight:bold; color:#ffffff; }}
  .chart-box {{ position:relative; user-select:none; margin:0; cursor:crosshair; }}
  .param-group {{ display:flex; flex-direction:column; gap:4px; }}
  .param-row {{ display:flex; align-items:center; gap:6px; }}
  .param-row label {{ font-size:11px; color:#787b86; min-width:48px; text-align:right; }}
  .param-row input {{ flex:1; min-width:40px; padding:4px 6px; border:1px solid #2b2b43; background:#1e222d; color:#d1d4dc; font-size:11px; border-radius:4px; outline:none; }}
  .param-row input:focus {{ border-color:#2962ff; }}
  .param-row input.height-input {{ min-width:60px; }}
  .color-picker {{ position:relative; }}
  .color-swatch {{ width:22px; height:22px; border:1px solid #2b2b43; border-radius:3px; cursor:pointer; flex-shrink:0; }}
  .color-grid {{ position:fixed; z-index:31; display:none; grid-template-columns:repeat(8,18px); gap:1px; background:#1e222d; padding:3px; border:1px solid #2b2b43; border-radius:4px; }}
  .color-grid.show {{ display:grid; }}
  .color-grid span {{ width:18px; height:18px; cursor:pointer; border-radius:2px; border:1px solid transparent; }}
  .color-grid span:hover {{ border-color:#fff; }}
  #cross-v {{ position:fixed; top:0; bottom:0; width:0; border-left:1px dashed #787b8666; z-index:10; pointer-events:none; display:none; }}
  #custom-tooltip {{ position:fixed; z-index:30; background:#1e222d; border:1px solid #2b2b43; border-radius:6px; padding:8px 12px; font-size:12px; line-height:1.8; pointer-events:none; display:none; box-shadow:0 4px 12px rgba(0,0,0,0.4); }}
  #custom-tooltip .tt-date {{ font-size:13px; font-weight:700; color:#fff; margin-bottom:4px; text-align:center; }}
  #custom-tooltip .tt-row {{ display:flex; justify-content:space-between; gap:20px; }}
  #custom-tooltip .tt-label {{ color:#787b86; }}
  #custom-tooltip .tt-value {{ color:#d1d4dc; font-weight:600; text-align:right; }}
  #custom-tooltip .tt-up {{ color:#26a69a; }}
  #custom-tooltip .tt-dn {{ color:#ef5350; }}
  #custom-tooltip .tt-sep {{ border-bottom:1px solid #2b2b43; margin:4px 0; }}
</style>
</head>
<body>

<div id="cross-v"></div>
<div id="custom-tooltip"></div>
<div class="color-grid" id="global-color-grid">{color_opts}</div>
<div id="scroll-wrap">
  <table>
    <tbody>
      <!-- 第1行：日期轴（冻结） -->
      <tr class="row-date">
        <td class="col-idx" style="font-family:'Orbitron',sans-serif;font-size:40px;line-height:80px;">5M</td>
        <td>
          <div class="data-area">
            <div class="date-axis" id="date-axis"></div>
          </div>
        </td>
        <td class="col-param"></td>
      </tr>
      <!-- 第2行：上涨—开盘/中午/下午的上涨个数 -->
      <tr>
        <td class="col-idx" style="padding:0;"><div style="font-size:13px;font-weight:normal;color:#d1d4dc;line-height:1.2;"><span style="font-size:10px;background:#FFA72622;color:#FFA726;border:1px solid #FFA72644;padding:1px 6px;border-radius:8px;">UP</span></div><div style="font-family:'Orbitron',sans-serif;font-size:48px;font-weight:900;line-height:1;">上涨</div></td>
        <td style="padding:0;border-bottom:none;line-height:0;">
          <div class="chart-box" style="height:270px;">
            <canvas id="c-up-5m"></canvas>
          </div>
        </td>
        <td class="col-param" style="border-bottom:none;">
          <div class="param-group">
            <div class="param-row"><label>高度</label><input class="height-input" type="number" value="270" min="60" step="10" data-target="c-up-5m"></div>
          </div>
        </td>
      </tr>
      <!-- 第3行：下降—开盘/中午/下午的下降个数（负值向下） -->
      <tr>
        <td class="col-idx" style="padding:0;border-top:none;"><div style="font-size:13px;font-weight:normal;color:#d1d4dc;line-height:1.2;"><span style="font-size:10px;background:#00e5ff22;color:#00e5ff;border:1px solid #00e5ff44;padding:1px 6px;border-radius:8px;">DOWN</span></div><div style="font-family:'Orbitron',sans-serif;font-size:48px;font-weight:900;line-height:1;">下降</div></td>
        <td style="padding:0;border-top:none;line-height:0;">
          <div class="chart-box" style="height:270px;">
            <canvas id="c-dn-5m"></canvas>
          </div>
        </td>
        <td class="col-param" style="padding:0;border-top:none;">
          <div class="param-group">
            <div class="param-row"><label>高度</label><input class="height-input" type="number" value="270" min="60" step="10" data-target="c-dn-5m"></div>
          </div>
        </td>
      </tr>
      <!-- 第4行：成交额—中午/下午 -->
      <tr>
        <td class="col-idx" style="padding:0;border-bottom:none;"><div style="font-size:13px;font-weight:normal;color:#d1d4dc;line-height:1.2;"><span style="font-size:10px;background:#ffd74022;color:#ffd740;border:1px solid #ffd74044;padding:1px 6px;border-radius:8px;">AMT</span></div><div style="font-family:'Orbitron',sans-serif;font-size:48px;font-weight:900;line-height:1;">成交额</div></td>
        <td style="padding:0;border-bottom:none;line-height:0;">
          <div class="chart-box" style="height:200px;">
            <canvas id="c-amt-5m"></canvas>
          </div>
        </td>
        <td class="col-param" style="border-bottom:none;">
          <div class="param-group">
            <div class="param-row"><label>高度</label><input class="height-input" type="number" value="200" min="60" step="10" data-target="c-amt-5m"></div>
          </div>
        </td>
      </tr>
      <tr style="height:200px;"><td class="col-idx"></td><td></td><td class="col-param"></td></tr>
      <tr style="height:200px;"><td class="col-idx"></td><td></td><td class="col-param"></td></tr>
    </tbody>
  </table>
</div>

<script>
const raw = {data_json};
const dates = raw.map(d=>d.date);
const upOpen = raw.map(d=>d.open_up);
const upNoon = raw.map(d=>d.noon_up);
const upClose = raw.map(d=>d.close_up);
const dnOpen = raw.map(d=>-d.open_dn);
const dnNoon = raw.map(d=>-d.noon_dn);
const dnClose = raw.map(d=>-d.close_dn);
const amtNoon = raw.map(d=>+(d.noon_amt/1e8).toFixed(2));
const amtClose = raw.map(d=>+(d.close_amt/1e8).toFixed(2));
const maxUp = Math.max(...upOpen,...upNoon,...upClose,1);
const maxDn = Math.max(...raw.map(d=>d.open_dn),...raw.map(d=>d.noon_dn),...raw.map(d=>d.close_dn),1);
const maxAmt = Math.max(...amtNoon,...amtClose,1);
const wrap = document.getElementById('scroll-wrap');
const crossV = document.getElementById('cross-v');
const tt = document.getElementById('custom-tooltip');
const grid = document.getElementById('global-color-grid');
let charts = [];
let dragging = false, sx = 0, ss = 0;

document.addEventListener('mousedown', e => {{
  if (e.button !== 1 || !e.target.closest('#scroll-wrap')) return;
  e.preventDefault(); dragging = true; sx = e.clientX; ss = wrap.scrollLeft;
  wrap.style.cursor = 'grabbing';
}});
document.addEventListener('mousemove', e => {{
  if (dragging) {{
    wrap.scrollLeft = ss - (e.clientX - sx);
  }} else if (e.target.closest('#scroll-wrap')) {{
    crossV.style.display = 'block'; crossV.style.left = e.clientX + 'px';
    syncAllHover(e);
  }} else {{
    crossV.style.display = 'none'; clearAllHovers();
  }}
}});
document.addEventListener('mouseup', e => {{
  if (e.button === 1 && dragging) {{ dragging = false; wrap.style.cursor = ''; }}
  crossV.style.display = 'none'; clearAllHovers();
}});
wrap.addEventListener('mouseleave', () => {{ crossV.style.display = 'none'; clearAllHovers(); }});
document.addEventListener('auxclick', e => {{ if (e.button === 1) e.preventDefault(); }});

function syncAllHover(e) {{
  const ref = charts.find(c => c.canvas && c.canvas.id === 'c-up-5m');
  if (!ref) return;
  const xScale = ref.scales.x;
  if (!xScale) return;
  const idx = Math.round(xScale.getValueForPixel(e.clientX - ref.canvas.getBoundingClientRect().left));
  if (idx == null || idx < 0 || idx >= dates.length) return;
  charts.forEach(ch => {{
    if (!ch || !ch.canvas) return;
    const active = [];
    for (let d = 0; d < ch.data.datasets.length; d++) {{
      const m = ch.getDatasetMeta(d);
      if (m && m.data && m.data[idx]) active.push({{ datasetIndex:d, index:idx }});
    }}
    ch.setActiveElements(active); ch.update('none');
  }});
  document.querySelectorAll('#date-axis .dl').forEach((el,i) => el.classList.toggle('hl', i === idx));
  const d = raw[idx];
  if (!d) return;
  tt.innerHTML =
    '<div class="tt-date">' + d.date + '</div>' +
    '<div class="tt-sep"></div>' +
    '<div class="tt-row"><span class="tt-label">开盘(↑)</span><span class="tt-value tt-up">' + d.open_up + '</span><span class="tt-value tt-dn" style="margin-left:10px;">' + d.open_dn + '</span></div>' +
    '<div class="tt-row"><span class="tt-label">中午(↑)</span><span class="tt-value tt-up">' + d.noon_up + '</span><span class="tt-value tt-dn" style="margin-left:10px;">' + d.noon_dn + '</span></div>' +
    '<div class="tt-row"><span class="tt-label">午间成交额</span><span class="tt-value">' + (d.noon_amt/1e8).toFixed(2) + '亿</span></div>' +
    '<div class="tt-sep"></div>' +
    '<div class="tt-row"><span class="tt-label">下午(↑)</span><span class="tt-value tt-up">' + d.close_up + '</span><span class="tt-value tt-dn" style="margin-left:10px;">' + d.close_dn + '</span></div>' +
    '<div class="tt-row"><span class="tt-label">下午成交额</span><span class="tt-value">' + (d.close_amt/1e8).toFixed(2) + '亿</span></div>';
  tt.style.display = 'block';
  let tx = e.clientX + 16, ty = e.clientY + 16;
  const tw = tt.offsetWidth, th = tt.offsetHeight;
  if (tx + tw > window.innerWidth - 10) tx = e.clientX - tw - 16;
  if (ty + th > window.innerHeight - 10) ty = e.clientY - th - 16;
  if (tx < 10) tx = 10;
  if (ty < 10) ty = 10;
  tt.style.left = tx + 'px';
  tt.style.top = ty + 'px';
}}

function clearAllHovers() {{
  charts.forEach(ch => {{
    if (!ch) return;
    ch.setActiveElements([]);
    if (ch.tooltip) ch.tooltip.setActiveElements([], {{ x:0, y:0 }});
    ch.update('none');
  }});
  document.querySelectorAll('#date-axis .dl.hl').forEach(el => el.classList.remove('hl'));
}}

document.addEventListener('input', e => {{
  const input = e.target.closest('.height-input');
  if (!input) return;
  const targetId = input.dataset.target;
  const h = parseInt(input.value) || 120;
  const row = input.closest('tr');
  if (!row) return;
  const box = row.querySelector('.chart-box');
  const canvas = document.getElementById(targetId);
  if (!box || !canvas) return;
  box.style.height = h + 'px';
  const ch = charts.find(c => c.canvas === canvas);
  if (ch) ch.resize();
}});

let activeSwatch = null;
document.addEventListener('click', e => {{
  const span = e.target.closest('.color-grid span');
  if (span && activeSwatch) {{
    activeSwatch.style.background = span.dataset.color;
    grid.classList.remove('show'); activeSwatch = null; return;
  }}
  if (span) return;
  if (!e.target.closest('.color-picker')) {{ grid.classList.remove('show'); activeSwatch = null; }}
}});

function buildDateAxis() {{
  const axis = document.getElementById('date-axis');
  if (!axis || !dates.length) return;
  dates.forEach(d => {{
    const el = document.createElement('div');
    el.className = 'dl';
    el.textContent = d;
    axis.appendChild(el);
  }});
}}

function renderCharts() {{
  const upDatasets = [
    {{ label:'开盘(↑)', data:upOpen, backgroundColor:'#c62828', borderColor:'#000000', borderWidth:1, borderRadius:1, barPercentage:1.0, categoryPercentage:1.0, hoverBorderColor:'#fff', hoverBorderWidth:2 }},
    {{ label:'中午(↑)', data:upNoon, backgroundColor:'#ef5350', borderColor:'#000000', borderWidth:1, borderRadius:1, barPercentage:1.0, categoryPercentage:1.0, hoverBorderColor:'#fff', hoverBorderWidth:2 }},
    {{ label:'下午(↑)', data:upClose, backgroundColor:'#ef9a9a', borderColor:'#000000', borderWidth:1, borderRadius:1, barPercentage:1.0, categoryPercentage:1.0, hoverBorderColor:'#fff', hoverBorderWidth:2 }},
  ];
  const dnDatasets = [
    {{ label:'开盘(↓)', data:dnOpen, backgroundColor:'#00b8d4', borderColor:'#000000', borderWidth:1, borderRadius:1, barPercentage:1.0, categoryPercentage:1.0, hoverBorderColor:'#fff', hoverBorderWidth:2 }},
    {{ label:'中午(↓)', data:dnNoon, backgroundColor:'#00e5ff', borderColor:'#000000', borderWidth:1, borderRadius:1, barPercentage:1.0, categoryPercentage:1.0, hoverBorderColor:'#fff', hoverBorderWidth:2 }},
    {{ label:'下午(↓)', data:dnClose, backgroundColor:'#80deea', borderColor:'#000000', borderWidth:1, borderRadius:1, barPercentage:1.0, categoryPercentage:1.0, hoverBorderColor:'#fff', hoverBorderWidth:2 }},
  ];
  const amtDatasets = [
    {{ label:'午间成交额', data:amtNoon, backgroundColor:'#ffb300', borderColor:'#000000', borderWidth:1, borderRadius:1, barPercentage:1.0, categoryPercentage:1.0, hoverBorderColor:'#fff', hoverBorderWidth:2 }},
    {{ label:'下午成交额', data:amtClose, backgroundColor:'#ffd740', borderColor:'#000000', borderWidth:1, borderRadius:1, barPercentage:1.0, categoryPercentage:1.0, hoverBorderColor:'#fff', hoverBorderWidth:2 }},
  ];

  const ctxUp = document.getElementById('c-up-5m');
  if (ctxUp && dates.length) {{
    charts.push(new Chart(ctxUp, {{
      type:'bar',
      data:{{ labels:dates, datasets:upDatasets }},
      options:{{
        responsive:true, maintainAspectRatio:false,
        interaction:{{ mode:'index', intersect:false }},
        plugins:{{ legend:{{ display:false }}, tooltip:{{ enabled:false }} }},
        scales:{{
          x:{{ offset:true, ticks:{{ display:false }}, grid:{{ display:false }} }},
          y:{{ display:true, position:'right', ticks:{{ display:false }}, grid:{{ color:'#485c7b55', borderDash:[3,4], lineWidth:1 }}, border:{{ display:false }}, max:maxUp }}
        }}
      }}
    }}));
  }}

  const ctxDn = document.getElementById('c-dn-5m');
  if (ctxDn && dates.length) {{
    charts.push(new Chart(ctxDn, {{
      type:'bar',
      data:{{ labels:dates, datasets:dnDatasets }},
      options:{{
        responsive:true, maintainAspectRatio:false,
        interaction:{{ mode:'index', intersect:false }},
        plugins:{{ legend:{{ display:false }}, tooltip:{{ enabled:false }} }},
        scales:{{
          x:{{ offset:true, ticks:{{ display:false }}, grid:{{ display:false }} }},
          y:{{ display:true, position:'right', ticks:{{ display:false }}, grid:{{ color:'#485c7b55', borderDash:[3,4], lineWidth:1 }}, border:{{ display:false }} }}
        }}
      }}
    }}));
  }}

  const ctxAmt = document.getElementById('c-amt-5m');
  if (ctxAmt && dates.length) {{
    charts.push(new Chart(ctxAmt, {{
      type:'bar',
      data:{{ labels:dates, datasets:amtDatasets }},
      options:{{
        responsive:true, maintainAspectRatio:false,
        interaction:{{ mode:'index', intersect:false }},
        plugins:{{ legend:{{ display:false }}, tooltip:{{ enabled:false }} }},
        scales:{{
          x:{{ offset:true, ticks:{{ display:false }}, grid:{{ display:false }} }},
          y:{{ display:true, position:'right', ticks:{{ display:false, callback:v=>v+'亿' }}, grid:{{ color:'#485c7b55', borderDash:[3,4], lineWidth:1 }}, border:{{ display:false }}, max:maxAmt }}
        }}
      }}
    }}));
  }}

  // 用 Chart.js 柱子的精确 X 坐标定位 D 行标签
  setTimeout(() => {{
    const ch = charts.find(c => c.canvas && c.canvas.id === 'c-up-5m');
    if (!ch) return;
    const meta = ch.getDatasetMeta(0);
    if (!meta || !meta.data || !meta.data.length) return;
    const axis = document.getElementById('date-axis');
    if (!axis) return;
    const labels = axis.querySelectorAll('.dl');
    if (!labels.length) return;
    const firstX = meta.data[0].x;
    const lastX = meta.data[meta.data.length-1].x;
    const gaps = [];
    for (let i = 1; i < meta.data.length; i++) gaps.push(meta.data[i].x - meta.data[i-1].x);
    const avgGap = gaps.length ? Math.round(gaps.reduce((a,b)=>a+b,0)/gaps.length) : 11;
    const totalW = lastX - firstX + avgGap;
    axis.style.width = totalW + 'px';
    axis.style.paddingLeft = firstX + 'px';
    labels.forEach((el, i) => {{
      el.style.left = (meta.data[i].x - firstX) + 'px';
      el.style.width = avgGap + 'px';
      el.style.transform = 'translateX(-50%)';
    }});
  }}, 400);
}}

function init() {{
  if (!dates.length) {{
    document.querySelector('#scroll-wrap table tbody').innerHTML = '<tr><td colspan="3" class="empty" style="color:#485c7b;font-size:14px;padding:40px;text-align:center;">暂无数据</td></tr>';
    return;
  }}
  buildDateAxis();
  setTimeout(() => renderCharts(), 60);
}}

init();
</script>
</body>
</html>'''

    output = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'target_5m.html')
    with open(output, 'w', encoding='utf-8') as f:
        f.write(html)
    webbrowser.open(output)
    print(f'[SHOW_5M_MOTION] {len(data)} days -> {output}')