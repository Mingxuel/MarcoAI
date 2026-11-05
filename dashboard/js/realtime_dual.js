/* 实时看盘双周期 K 线（1D + 5m）：涨停金黄、均线可选、画线、联动（默认关）。 */
import { ChartDrawings } from './chart_drawings.js';

const LW = () => window.LightweightCharts;
const MA_LIST = [5, 10, 20, 30, 60, 120];
const MA_COLOR = { 5: '#f5c518', 10: '#f472b6', 20: '#60a5fa', 30: '#34d399', 60: '#c084fc', 120: '#fb923c' };
const PERIODS = [
  { id: '1d', label: '1D 日线' },
  { id: '5m', label: '5m 分钟' },
];

function sma(bars, n) {
  const out = [];
  let sum = 0;
  for (let i = 0; i < bars.length; i++) {
    sum += bars[i].close;
    if (i >= n) sum -= bars[i - n].close;
    if (i >= n - 1) out.push({ time: bars[i].time, value: sum / n });
  }
  return out;
}

function ratioFor(code) {
  const c = String(code || '').toUpperCase();
  if (c.startsWith('300') || c.startsWith('301') || c.startsWith('688')) return 0.20;
  if (c.startsWith('8') || c.startsWith('4') || c.startsWith('92')) return 0.30;
  return 0.10;
}

function loadJson(key, fallback) {
  try { const v = JSON.parse(localStorage.getItem(key) || 'null'); return v == null ? fallback : v; } catch (e) { return fallback; }
}
function saveJson(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* ignore */ }
}

export class RealtimeDualChart {
  constructor(container) {
    this.container = container;
    this.charts = {};
    this.series = {};
    this.maState = { '1d': loadJson('marco.realtime.dual.ma.1d', [5, 60]), '5m': loadJson('marco.realtime.dual.ma.5m', [5, 60]) };
    this.drawings = {};
    this.tool = null;
    this.link = false;
    this.code = '';
    this.data = null;
    this._build();
  }

  _build() {
    this.container.innerHTML = '';
    this.toolbar = document.createElement('div');
    this.toolbar.className = 'rt-dual-toolbar';
    this.container.appendChild(this.toolbar);

    this.maRows = {};
    for (const p of PERIODS) {
      const row = document.createElement('div');
      row.className = 'rt-dual-ma-row';
      const tag = document.createElement('span');
      tag.className = 'rt-dual-tag';
      tag.textContent = p.label;
      row.appendChild(tag);
      for (const n of MA_LIST) {
        const lab = document.createElement('label');
        lab.className = 'rt-dual-ma';
        const cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.checked = (this.maState[p.id] || []).includes(n);
        cb.addEventListener('change', () => {
          const cur = new Set(this.maState[p.id] || []);
          if (cb.checked) cur.add(n); else cur.delete(n);
          this.maState[p.id] = [...cur].sort((a, b) => a - b);
          saveJson(`marco.realtime.dual.ma.${p.id}`, this.maState[p.id]);
          this._drawMa(p.id);
        });
        const dot = document.createElement('span');
        dot.className = 'dot';
        dot.style.background = MA_COLOR[n];
        lab.appendChild(cb);
        lab.appendChild(dot);
        lab.appendChild(document.createTextNode('MA' + n));
        row.appendChild(lab);
      }
      this.toolbar.appendChild(row);
      this.maRows[p.id] = row;
    }

    const tools = document.createElement('div');
    tools.className = 'rt-dual-tools';
    const linkLab = document.createElement('label');
    linkLab.className = 'rt-dual-link';
    this.linkCb = document.createElement('input');
    this.linkCb.type = 'checkbox';
    this.linkCb.checked = false;
    this.linkCb.addEventListener('change', () => { this.link = this.linkCb.checked; this._bindLink(); });
    linkLab.appendChild(this.linkCb);
    linkLab.appendChild(document.createTextNode('联动'));
    tools.appendChild(linkLab);
    this.toolbar.appendChild(tools);

    this.wraps = {};
    for (const p of PERIODS) {
      const wrap = document.createElement('div');
      wrap.className = 'rt-dual-chart rt-dual-' + p.id;
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.classList.add('rt-draw-svg');
      const host = document.createElement('div');
      host.className = 'rt-dual-chart-host';
      wrap.appendChild(host);
      wrap.appendChild(svg);
      this.container.appendChild(wrap);
      this.wraps[p.id] = { wrap, host, svg };
      wrap.addEventListener('click', (ev) => this._onChartClick(p.id, ev));
    }
  }

  _toolBtn(label, tool) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'btn btn-xs ghost rt-draw-btn';
    b.textContent = label;
    b.addEventListener('click', (ev) => {
      ev.stopPropagation();
      if (tool === 'del') { this._deleteLast(); return; }
      if (tool === 'clear') { this._clearAll(); return; }
      this.tool = this.tool === tool ? null : tool;
      this._syncToolBtns();
    });
    return b;
  }

  _syncToolBtns() {
    this.btnH.classList.toggle('on', this.tool === 'h');
    this.btnT.classList.toggle('on', this.tool === 't');
    for (const id of ['1d', '5m']) this.wraps[id].wrap.classList.toggle('drawing', !!this.tool);
  }

  render({ code, dailyBars, fiveBars }) {
    this.code = code || '';
    this.data = { dailyBars: dailyBars || [], fiveBars: fiveBars || [] };
    this.drawings = {
      '1d': loadJson(`marco.realtime.draw.${this.code}.1d`, []),
      '5m': loadJson(`marco.realtime.draw.${this.code}.5m`, []),
    };
    this._renderOne('1d', this.data.dailyBars);
    this._renderOne('5m', this.data.fiveBars);
    this._bindLink();
  }

  _chartOptions() {
    const g = LW();
    return {
      autoSize: true,
      layout: { background: { type: 'solid', color: '#0b1017' }, textColor: '#8b98ab', fontSize: 10,
        fontFamily: 'Consolas, "Cascadia Mono", monospace', attributionLogo: false },
      grid: { vertLines: { color: 'rgba(255,255,255,0.035)' }, horzLines: { color: 'rgba(255,255,255,0.035)' } },
      rightPriceScale: { borderColor: 'rgba(255,255,255,0.08)', scaleMargins: { top: 0.08, bottom: 0.08 } },
      timeScale: { borderColor: 'rgba(255,255,255,0.08)', rightOffset: 3, barSpacing: 3, timeVisible: true,
        secondsVisible: false },
      crosshair: { mode: g.CrosshairMode ? g.CrosshairMode.Normal : 0,
        vertLine: { color: 'rgba(148,163,184,.5)', width: 1, style: 2, labelBackgroundColor: '#1e293b' },
        horzLine: { color: 'rgba(148,163,184,.5)', width: 1, style: 2, labelBackgroundColor: '#1e293b' } },
      localization: { locale: 'zh-CN' },
    };
  }

  _renderOne(period, bars) {
    const g = LW();
    const prev = this.charts[period];
    if (prev) { try { prev.remove(); } catch (e) { /* ignore */ } }
    const host = this.wraps[period].host;
    host.innerHTML = '';
    if (!bars || !bars.length) {
      host.innerHTML = '<div class="empty-box">无 ' + period + ' 数据</div>';
      this.charts[period] = null;
      return;
    }
    const chart = g.createChart(host, this._chartOptions());
    this.charts[period] = chart;
    const ratio = ratioFor(this.code);
    const candles = [];
    for (let i = 0; i < bars.length; i++) {
      const b = bars[i];
      const prevClose = i > 0 ? bars[i - 1].close : b.open;
      const limit = prevClose * (1 + ratio);
      const isLimit = b.close >= limit - 1e-6;
      const up = b.close >= b.open;
      const color = isLimit ? '#f5c518' : (up ? '#ef4444' : '#60a5fa');
      candles.push({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close,
        color, borderColor: color, wickColor: color });
    }
    const candle = chart.addSeries(g.CandlestickSeries, {
      upColor: '#ef4444', downColor: '#60a5fa', borderUpColor: '#ef4444', borderDownColor: '#60a5fa',
      wickUpColor: '#ef4444', wickDownColor: '#60a5fa', priceLineVisible: false,
      priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
    });
    candle.setData(candles);
    this.series[period] = { chart, candle, mas: {} };
    this._drawMa(period);
    this.draws = this.draws || {};
    if (!this.draws[period]) this.draws[period] = new ChartDrawings(this.wraps[period].wrap, { pageKey: 'realtime', code: this.code, period });
    this.draws[period].setBars(bars);
    this.draws[period].setChart(chart, candle);
    this.draws[period].setContext({ pageKey: 'realtime', code: this.code, period });
    if (!this.draws[period].toolbarEl.parentNode) this.wraps[period].wrap.appendChild(this.draws[period].toolbarEl);
    if (!this.draws[period].propsEl.parentNode) this.wraps[period].wrap.appendChild(this.draws[period].propsEl);
    chart.timeScale().fitContent();
    chart.timeScale().subscribeVisibleTimeRangeChange(() => this._redrawDrawings(period));
    chart.subscribeCrosshairMove((param) => this._onCrosshair(period, param));
  }

  _drawMa(period) {
    const g = LW();
    const st = this.series[period];
    if (!st) return;
    for (const n of Object.keys(st.mas)) {
      try { st.chart.removeSeries(st.mas[n]); } catch (e) { /* ignore */ }
    }
    st.mas = {};
    const bars = period === '1d' ? this.data.dailyBars : this.data.fiveBars;
    for (const n of (this.maState[period] || [])) {
      const data = sma(bars, n);
      if (!data.length) continue;
      const s = st.chart.addSeries(g.LineSeries, {
        color: MA_COLOR[n], lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
      s.setData(data);
      st.mas[n] = s;
    }
  }

  _onCrosshair(period, param) {
    if (!this.link) return;
    const other = period === '1d' ? '5m' : '1d';
    const oc = this.series[other];
    if (!oc || !param || !param.time) return;
    try {
      oc.chart.setCrosshairPosition(param.seriesData && param.seriesData.size ? [...param.seriesData.values()][0] : undefined, param.time, oc.candle);
    } catch (e) { /* ignore */ }
  }

  _bindLink() {
    if (this._linkBound || !this.charts['1d'] || !this.charts['5m']) return;
    this._linkBound = true;
    let syncing = false;
    for (const p of ['1d', '5m']) {
      this.charts[p].timeScale().subscribeVisibleLogicalRangeChange((range) => {
        if (!this.link || syncing || !range) return;
        const other = p === '1d' ? '5m' : '1d';
        syncing = true;
        try { this.charts[other].timeScale().setVisibleLogicalRange(range); } catch (e) { /* ignore */ }
        setTimeout(() => { syncing = false; }, 0);
      });
    }
  }

  _coord(period, ev) {
    const w = this.wraps[period];
    const rect = w.wrap.getBoundingClientRect();
    const x = ev.clientX - rect.left;
    const y = ev.clientY - rect.top;
    const st = this.series[period];
    if (!st) return null;
    const price = st.candle.coordinateToPrice(y);
    const time = st.chart.timeScale().coordinateToTime(x);
    if (price == null || time == null) return null;
    return { x, y, price, time };
  }

  _onChartClick(period, ev) {
    if (!this.tool || ev.target.closest('.rt-dual-toolbar')) return;
    const c = this._coord(period, ev);
    if (!c) return;
    const list = this.drawings[period] || [];
    if (this.tool === 'h') {
      list.push({ type: 'h', price: c.price });
      this.drawings[period] = list;
    } else if (this.tool === 't') {
      if (this._pendingTrend) {
        list.push({ type: 't', p1: this._pendingTrend, p2: { time: c.time, price: c.price } });
        this.drawings[period] = list;
        this._pendingTrend = null;
      } else {
        this._pendingTrend = { time: c.time, price: c.price };
        return;
      }
    }
    saveJson(`marco.realtime.draw.${this.code}.${period}`, this.drawings[period]);
    this._redrawDrawings(period);
  }

  _deleteLast() {
    for (const p of ['5m', '1d']) {
      if ((this.drawings[p] || []).length) {
        this.drawings[p].pop();
        saveJson(`marco.realtime.draw.${this.code}.${p}`, this.drawings[p]);
        this._redrawDrawings(p);
        return;
      }
    }
  }

  _clearAll() {
    for (const p of ['1d', '5m']) {
      this.drawings[p] = [];
      saveJson(`marco.realtime.draw.${this.code}.${p}`, []);
      this._redrawDrawings(p);
    }
    this._pendingTrend = null;
  }

  _redrawDrawings(period) {
    const w = this.wraps[period];
    const st = this.series[period];
    const svg = w.svg;
    if (!st || !svg) return;
    const width = w.wrap.clientWidth;
    const height = w.wrap.clientHeight;
    svg.setAttribute('viewBox', `0 0 ${Math.max(1, width)} ${Math.max(1, height)}`);
    svg.setAttribute('width', width);
    svg.setAttribute('height', height);
    svg.innerHTML = '';
    const list = this.drawings[period] || [];
    for (const d of list) {
      if (d.type === 'h') {
        const y = st.candle.priceToCoordinate(d.price);
        if (y == null) continue;
        const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        line.setAttribute('x1', 0); line.setAttribute('x2', width);
        line.setAttribute('y1', y); line.setAttribute('y2', y);
        line.setAttribute('stroke', '#f5c518'); line.setAttribute('stroke-dasharray', '4 3');
        svg.appendChild(line);
      } else if (d.type === 't' && d.p1 && d.p2) {
        const x1 = st.chart.timeScale().timeToCoordinate(d.p1.time);
        const y1 = st.candle.priceToCoordinate(d.p1.price);
        const x2 = st.chart.timeScale().timeToCoordinate(d.p2.time);
        const y2 = st.candle.priceToCoordinate(d.p2.price);
        if ([x1, y1, x2, y2].some((v) => v == null)) continue;
        const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        line.setAttribute('x1', x1); line.setAttribute('y1', y1);
        line.setAttribute('x2', x2); line.setAttribute('y2', y2);
        line.setAttribute('stroke', '#f5c518');
        svg.appendChild(line);
      }
    }
  }
}
