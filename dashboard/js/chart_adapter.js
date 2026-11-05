/* 图表适配层：把 lightweight-charts v5 封装成 KlineChart / CapitalChart。
 * 以后换 klinecharts 等只需改本文件（dashboard/vendor/klinecharts.min.js 已留作候选，
 * v10 UMD API 与 v9 不同且无 applyNewData，v1 采用本地已验证的 lightweight-charts 5.0.8）。
 */
import { UP, DOWN, fmtBarTime, isIntraday } from './util.js?v=20261105d';

const LW = () => window.LightweightCharts;

const SUB_IND = ['VOL', 'MACD', 'KDJ'];
const MAIN_IND = ['MA', 'BOLL'];

/* ---------------- indicators ---------------- */
export function sma(bars, period, key = 'close') {
  const out = [];
  let sum = 0;
  for (let i = 0; i < bars.length; i++) {
    sum += bars[i][key];
    if (i >= period) sum -= bars[i - period][key];
    if (i >= period - 1) out.push({ time: bars[i].time, value: sum / period });
  }
  return out;
}

function emaArr(values, period) {
  const out = [];
  const f = 2 / (period + 1);
  let prev = null;
  for (let i = 0; i < values.length; i++) {
    prev = prev == null ? values[i] : values[i] * f + prev * (1 - f);
    out.push(prev);
  }
  return out;
}

export function boll(bars, period = 20, mult = 2) {
  const mid = [], up = [], low = [];
  let sum = 0, sum2 = 0;
  for (let i = 0; i < bars.length; i++) {
    const c = bars[i].close;
    sum += c; sum2 += c * c;
    if (i >= period) { const x = bars[i - period].close; sum -= x; sum2 -= x * x; }
    if (i >= period - 1) {
      const m = sum / period;
      const sd = Math.sqrt(Math.max(0, sum2 / period - m * m));
      mid.push({ time: bars[i].time, value: m });
      up.push({ time: bars[i].time, value: m + mult * sd });
      low.push({ time: bars[i].time, value: m - mult * sd });
    }
  }
  return { mid, up, low };
}

export function macd(bars, fast = 12, slow = 26, sig = 9) {
  const closes = bars.map((b) => b.close);
  const ef = emaArr(closes, fast);
  const es = emaArr(closes, slow);
  const dif = closes.map((_, i) => ef[i] - es[i]);
  const dea = emaArr(dif, sig);
  const hist = [], difLine = [], deaLine = [];
  for (let i = 0; i < bars.length; i++) {
    const h = (dif[i] - dea[i]) * 2;
    hist.push({ time: bars[i].time, value: h, color: h >= 0 ? 'rgba(214,40,40,.75)' : 'rgba(0,119,182,.8)' });
    difLine.push({ time: bars[i].time, value: dif[i] });
    deaLine.push({ time: bars[i].time, value: dea[i] });
  }
  return { hist, dif: difLine, dea: deaLine };
}

export function kdj(bars, period = 9) {
  const k = [], d = [], j = [];
  let pk = 50, pd = 50;
  for (let i = 0; i < bars.length; i++) {
    const from = Math.max(0, i - period + 1);
    let hi = -Infinity, lo = Infinity;
    for (let x = from; x <= i; x++) { hi = Math.max(hi, bars[x].high); lo = Math.min(lo, bars[x].low); }
    const rsv = hi === lo ? 50 : ((bars[i].close - lo) / (hi - lo)) * 100;
    pk = (2 * pk + rsv) / 3;
    pd = (2 * pd + pk) / 3;
    k.push({ time: bars[i].time, value: pk });
    d.push({ time: bars[i].time, value: pd });
    j.push({ time: bars[i].time, value: 3 * pk - 2 * pd });
  }
  return { k, d, j };
}

function volColor(b) {
  return b.close >= b.open ? 'rgba(214,40,40,.55)' : 'rgba(0,119,182,.55)';
}

/* ---------------- utils ---------------- */
function lowerBound(bars, time) {
  let lo = 0, hi = bars.length;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (bars[mid].time < time) lo = mid + 1; else hi = mid; }
  return lo;
}
function upperBound(bars, time) {
  let lo = 0, hi = bars.length;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (bars[mid].time <= time) lo = mid + 1; else hi = mid; }
  return lo - 1;
}

function lowerBoundTimes(times, time) {
  let lo = 0, hi = times.length;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (times[mid] < time) lo = mid + 1; else hi = mid; }
  return lo;
}
function upperBoundTimes(times, time) {
  let lo = 0, hi = times.length;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (times[mid] <= time) lo = mid + 1; else hi = mid; }
  return lo - 1;
}

function tickDate(time) {
  const d = new Date(Number(time) * 1000);
  const y = d.getUTCFullYear(), m = String(d.getUTCMonth() + 1).padStart(2, '0'), da = String(d.getUTCDate()).padStart(2, '0');
  return `${y}-${m}-${da}`;
}

/* ---------------- KlineChart ---------------- */
export class KlineChart {
  constructor(container, handlers = {}) {
    this.container = container;
    this.handlers = handlers;
    this.chart = null;
    this.candle = null;
    this.markerPrim = null;
    this.bars = [];
    this.period = '1d';
    this._volMap = new Map();
    this._applying = false;
    this._disposed = false;
  }

  _baseOptions(period) {
    const LWg = LW();
    const intraday = isIntraday(period);
    return {
      autoSize: true,
      layout: {
        background: { type: 'solid', color: '#0b1017' },
        textColor: '#8b98ab',
        fontSize: 11,
        fontFamily: 'Consolas, "Cascadia Mono", "Courier New", monospace',
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: 'rgba(255,255,255,0.04)' },
        horzLines: { color: 'rgba(255,255,255,0.04)' },
      },
      rightPriceScale: {
        borderColor: 'rgba(255,255,255,0.08)',
        scaleMargins: { top: 0.07, bottom: 0.07 },
      },
      timeScale: {
        borderColor: 'rgba(255,255,255,0.08)',
        rightOffset: 3,
        barSpacing: 6,
        minBarSpacing: 0.8,
        timeVisible: intraday,
        secondsVisible: false,
        tickMarkFormatter: (time, tickMarkType) => {
          const intraday = isIntraday(this.period);
          const d = new Date(Number(time) * 1000);
          const y = d.getUTCFullYear();
          const mo = String(d.getUTCMonth() + 1).padStart(2, '0');
          const da = String(d.getUTCDate()).padStart(2, '0');
          const hh = String(d.getUTCHours()).padStart(2, '0');
          const mi = String(d.getUTCMinutes()).padStart(2, '0');
          if (!intraday) return `${y}-${mo}-${da}`;
          // TickMarkType: 0=Year 1=Month 2=Day 3=Time 4=TimeWithSeconds
          if (tickMarkType === 0) return String(y);
          if (tickMarkType === 1 || tickMarkType === 2) return `${mo}-${da}`;
          return `${hh}:${mi}`;
        },
      },
      localization: {
        locale: 'zh-CN',
        timeFormatter: (time) => fmtBarTime(time, this.period),
      },
      crosshair: {
        mode: LWg && LWg.CrosshairMode ? LWg.CrosshairMode.Normal : 0,
        vertLine: { color: 'rgba(148,163,184,.55)', width: 1, style: 2, labelBackgroundColor: '#1e293b' },
        horzLine: { color: 'rgba(148,163,184,.55)', width: 1, style: 2, labelBackgroundColor: '#1e293b' },
      },
      handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
      handleScale: { mouseWheel: true, pinch: true, axisPressedMouseMove: { time: true, price: true }, axisDoubleClickReset: { time: true, price: true } },
    };
  }

  render(bars, period, indicators = [], opts = {}) {
    this.disposeChart();
    if (!bars || !bars.length) { this.bars = []; return; }
    const LWg = LW();
    if (!LWg) throw new Error('图表库未加载（vendor/lightweight-charts）');
    this.bars = bars;
    this.period = period;
    this._programmaticUntil = 0;
    this._volMap = new Map(bars.map((b) => [b.time, b.volume]));
    // 5m/15m/30m 数据是窗口化的：只画最近一段连续窗口，禁止把两段窗口拼成连续走势
    const plot = opts.fullRange ? bars : this._gapPlot(bars, period);
    this._plotTimes = plot.map((b) => b.time);
    this._plotSet = new Set(this._plotTimes);
    const chart = LWg.createChart(this.container, this._baseOptions(period));
    this.chart = chart;
    const candle = chart.addSeries(LWg.CandlestickSeries, {
      upColor: UP, downColor: DOWN, borderUpColor: UP, borderDownColor: DOWN,
      wickUpColor: UP, wickDownColor: DOWN, priceLineVisible: false, lastValueVisible: !opts.hideLastValue,
      priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
    }, 0);
    this.candle = candle;
    candle.setData(plot.map((b) => (b.open == null
      ? { time: b.time }
      : { time: b.time, open: b.open, high: b.high, low: b.low, close: b.close })));

    let paneIdx = 1;
    const subUsed = SUB_IND.filter((x) => indicators.includes(x));
    if (subUsed.includes('VOL')) {
      const vs = chart.addSeries(LWg.HistogramSeries, {
        priceFormat: { type: 'volume' }, priceLineVisible: false, lastValueVisible: false,
        priceScaleId: 'vol', base: 0,
      }, paneIdx);
      vs.setData(plot.map((b) => (b.open == null
        ? { time: b.time }
        : { time: b.time, value: b.volume || 0, color: volColor(b) })));
      this._stylePane(paneIdx, 0.22);
      paneIdx++;
    }
    if (subUsed.includes('MACD')) {
      const m = macd(plot);
      const hs = chart.addSeries(LWg.HistogramSeries, {
        priceLineVisible: false, lastValueVisible: false, base: 0,
      }, paneIdx);
      hs.setData(m.hist);
      const difS = chart.addSeries(LWg.LineSeries, { color: '#f5c518', lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false }, paneIdx);
      difS.setData(m.dif);
      const deaS = chart.addSeries(LWg.LineSeries, { color: '#60a5fa', lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false }, paneIdx);
      deaS.setData(m.dea);
      this._stylePane(paneIdx, 0.26);
      paneIdx++;
    }
    if (subUsed.includes('KDJ')) {
      const kd = kdj(plot);
      const ks = chart.addSeries(LWg.LineSeries, { color: '#f5c518', lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false }, paneIdx);
      ks.setData(kd.k);
      const ds = chart.addSeries(LWg.LineSeries, { color: '#60a5fa', lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false }, paneIdx);
      ds.setData(kd.d);
      const js = chart.addSeries(LWg.LineSeries, { color: '#f472b6', lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false }, paneIdx);
      js.setData(kd.j);
      this._stylePane(paneIdx, 0.26);
      paneIdx++;
    }

    // 主图叠加
    {
      const colors = { 5: '#f5c518', 10: '#f472b6', 20: '#60a5fa', 30: '#34d399', 60: '#c084fc', 120: '#fb923c' };
      const periods = Array.isArray(opts.ma) ? opts.ma : (indicators.includes('MA') ? [5, 10, 20] : []);
      for (const p of periods) {
        if (!colors[p]) continue;
        const s = chart.addSeries(LWg.LineSeries, { color: colors[p], lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false }, 0);
        s.setData(sma(plot, p));
      }
    }
    if (indicators.includes('BOLL')) {
      const b = boll(plot, 20, 2);
      const mid = chart.addSeries(LWg.LineSeries, { color: '#c084fc', lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false }, 0);
      mid.setData(b.mid);
      const up = chart.addSeries(LWg.LineSeries, { color: '#38bdf8', lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false }, 0);
      up.setData(b.up);
      const lo = chart.addSeries(LWg.LineSeries, { color: '#38bdf8', lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false }, 0);
      lo.setData(b.low);
    }

    this._bindEvents();
    this.setMarkers(opts.markers || []);

    if (opts.focus) {
      this.focusIndexRange(opts.focus.center, opts.focus.before, opts.focus.after);
    } else {
      this.fitContent();
    }
  }

  /** 5m/15m/30m 窗口化数据：只保留最近一段连续窗口（缺口>3 天视为数据窗口断点）。
   *  日线不裁剪。这样不会把两段窗口拼成连续走势，也不会出现假日期刻度。 */
  _gapPlot(bars, period) {
    if (!isIntraday(period) || bars.length < 2) return bars;
    let start = 0;
    for (let i = 1; i < bars.length; i++) {
      if (bars[i].time - bars[i - 1].time > 3 * 86400) start = i;
    }
    if (!start) return bars;
    const clipped = bars.slice(start);
    // 最后一段太短（<30 根）时退化显示最近 30 根以内的连续片段
    return clipped.length >= 30 ? clipped : bars.slice(Math.max(0, bars.length - 30));
  }

  /** 指标序列对齐到含空白 bar 的横轴（缺口处断线） */
  _alignSeries(data, plotTimes) {
    const map = new Map((data || []).map((d) => [d.time, d]));
    return plotTimes.map((t) => map.get(t) || { time: t });
  }

  _stylePane(idx, stretch) {
    try {
      const p = this.chart.panes()[idx];
      if (p) { p.setStretchFactor(stretch); }
    } catch (e) { /* 兼容旧版忽略 */ }
  }

  _bindEvents() {
    const chart = this.chart;
    chart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      if (this._applying || this._disposed) return;
      if (Date.now() < (this._programmaticUntil || 0)) return;
      if (range && this.handlers.onRange) this.handlers.onRange(range);
    });
    chart.subscribeCrosshairMove((param) => {
      if (this._disposed || this._applying) return;
      if (!param || param.time == null || !this.candle) {
        if (this.handlers.onCrosshair) this.handlers.onCrosshair(null);
        return;
      }
      let d = null;
      try { d = param.seriesData && param.seriesData.get(this.candle); } catch (e) { d = null; }
      if (!d) {
        if (this.handlers.onCrosshair) this.handlers.onCrosshair(null);
        return;
      }
      const bar = {
        time: param.time, open: d.open, high: d.high, low: d.low, close: d.close,
        volume: this._volMap.get(param.time),
      };
      if (this.handlers.onCrosshair) this.handlers.onCrosshair(bar);
    });
  }

  setMarkers(markers) {
    if (!this.chart || !this.candle) return;
    const LWg = LW();
    if (!LWg || !LWg.createSeriesMarkers) return;
    let list = markers || [];
    if (this._plotSet) list = list.filter((m) => this._plotSet.has(m.time)); // 裁剪窗口外的标记不画
    try {
      if (!this.markerPrim) this.markerPrim = LWg.createSeriesMarkers(this.candle, list);
      else this.markerPrim.setMarkers(list);
    } catch (e) { /* markers 失败不影响主图 */ }
  }

  getVisibleTimeRange() {
    if (!this.chart) return null;
    try { return this.chart.timeScale().getVisibleRange(); } catch (e) { return null; }
  }

  setVisibleByTime(from, to) {
    if (!this.chart || !this.bars.length || from == null || to == null) return false;
    const times = this._plotTimes || this.bars.map((b) => b.time);
    if (to < times[0] || from > times[times.length - 1]) return false;
    const a = Math.max(0, lowerBoundTimes(times, from));
    const b = Math.min(times.length - 1, upperBoundTimes(times, to));
    if (b < a) return false;
    this._applying = true;
    this._programmaticUntil = Date.now() + 150;
    try { this.chart.timeScale().setVisibleLogicalRange({ from: a - 0.5, to: b + 0.5 }); } catch (e) { /* ignore */ } finally { this._applying = false; }
    return true;
  }

  focusIndexRange(center, before = 20, after = 8) {
    if (!this.chart || !this.bars.length) return;
    const realIdx = Math.max(0, Math.min(this.bars.length - 1, center));
    const real = this.bars[realIdx];
    let i = realIdx;
    if (real && this._plotTimes) {
      const pi = this._plotTimes.indexOf(real.time);
      if (pi < 0) return; // 定位日不在当前绘制窗口内
      i = pi;
    }
    this._applying = true;
    this._programmaticUntil = Date.now() + 250;
    try { this.chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, i - before), to: i + after }); } catch (e) { /* ignore */ } finally { this._applying = false; }
  }

  /** 按时间定位到最近 bar（跨周期/跨面板定位卖出日用） */
  indexAtTime(time, mode = 'first') {
    if (!this.bars.length || time == null) return -1;
    let idx = lowerBound(this.bars, time);
    if (idx >= this.bars.length) idx = this.bars.length - 1;
    if (mode === 'last') {
      const i2 = upperBound(this.bars, time);
      if (i2 >= 0) idx = i2;
    }
    return idx;
  }

  setCrosshairByTime(time) {
    if (!this.chart || !this.candle || time == null || !this.bars.length) return;
    const idx = this.indexAtTime(time);
    const bar = this.bars[idx];
    if (!bar) return;
    this._applying = true;
    try { this.chart.setCrosshairPosition(bar.close, bar.time, this.candle); } catch (e) { /* ignore */ } finally { this._applying = false; }
  }

  clearCrosshair() {
    if (!this.chart) return;
    this._applying = true;
    try { this.chart.clearCrosshairPosition(); } catch (e) { /* ignore */ } finally { this._applying = false; }
  }

  fitContent() {
    if (!this.chart) return;
    this._applying = true;
    this._programmaticUntil = Date.now() + 250;
    try { this.chart.timeScale().fitContent(); } catch (e) { /* ignore */ } finally { this._applying = false; }
  }

  disposeChart() {
    if (this.markerPrim) { try { this.markerPrim.setMarkers([]); } catch (e) { /* ignore */ } this.markerPrim = null; }
    if (this.chart) {
      try { this.chart.remove(); } catch (e) { /* ignore */ }
      this.chart = null;
      this.candle = null;
    }
    this._plotTimes = null;
    this._plotSet = null;
  }

  destroy() {
    this._disposed = true;
    this.disposeChart();
    this.bars = [];
  }
}

/* ---------------- CapitalChart（回测资金 K 线，非 K 线面板） ---------------- */
export class CapitalChart {
  constructor(container) {
    this.container = container;
    this.chart = null;
    this.candle = null;
    this.maSeries = {};
  }

  _ensure() {
    const LWg = LW();
    if (!LWg) throw new Error('图表库未加载');
    if (this.chart) return;
    this.chart = LWg.createChart(this.container, {
      autoSize: true,
      layout: {
        background: { type: 'solid', color: '#0b1017' }, textColor: '#8b98ab', fontSize: 11,
        fontFamily: 'Consolas, "Cascadia Mono", monospace', attributionLogo: false,
      },
      grid: { vertLines: { color: 'rgba(255,255,255,0.04)' }, horzLines: { color: 'rgba(255,255,255,0.04)' } },
      rightPriceScale: { borderColor: 'rgba(255,255,255,0.08)' },
      timeScale: {
        borderColor: 'rgba(255,255,255,0.08)', rightOffset: 3, barSpacing: 8, timeVisible: false,
        tickMarkFormatter: (time) => tickDate(time).slice(5),
      },
      localization: { locale: 'zh-CN', timeFormatter: (time) => tickDate(time) },
      crosshair: {
        mode: LWg.CrosshairMode ? LWg.CrosshairMode.Normal : 0,
        vertLine: { color: 'rgba(148,163,184,.55)', labelBackgroundColor: '#1e293b' },
        horzLine: { color: 'rgba(148,163,184,.55)', labelBackgroundColor: '#1e293b' },
      },
    });
    this.candle = this.chart.addSeries(LWg.CandlestickSeries, {
      upColor: UP, downColor: DOWN, borderUpColor: UP, borderDownColor: DOWN,
      wickUpColor: UP, wickDownColor: DOWN, priceLineVisible: false,
      priceFormat: { type: 'price', precision: 0, minMove: 1 },
    }, 0);
  }

  render(capitalKline, maOn = {}) {
    this._ensure();
    const LWg = LW();
    if (!capitalKline || !capitalKline.length) {
      this.candle.setData([]);
      return;
    }
    const bars = capitalKline.map((x) => {
      const t = x.time && typeof x.time === 'string' ? x.time : '';
      let ts;
      if (t && t.length === 10) {
        const p = t.split('-');
        ts = Date.UTC(Number(p[0]), Number(p[1]) - 1, Number(p[2])) / 1000;
      } else {
        ts = Number(x.time) || 0;
      }
      return { time: ts, open: x.open, high: x.high, low: x.low, close: x.close };
    }).filter((b) => b.time > 0);
    this.candle.setData(bars);
    const closes = bars.map((b) => b.close);
    for (const w of [5, 10, 20, 30, 60, 120]) {
      let s = this.maSeries[w];
      if (!s) {
        const colors = { 5: '#f5c518', 10: '#f472b6', 20: '#60a5fa', 30: '#34d399', 60: '#c084fc', 120: '#fb923c' };
        s = this.maSeries[w] = this.chart.addSeries(LWg.LineSeries, {
          color: colors[w], lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
        }, 0);
      }
      const data = [];
      let sum = 0;
      for (let i = 0; i < closes.length; i++) {
        sum += closes[i];
        if (i >= w) sum -= closes[i - w];
        if (i >= w - 1) data.push({ time: bars[i].time, value: sum / w });
      }
      s.setData(data);
      s.applyOptions({ visible: !!maOn[w] });
    }
    this.chart.timeScale().fitContent();
  }

  dispose() {
    if (this.chart) { try { this.chart.remove(); } catch (e) { /* ignore */ } this.chart = null; this.maSeries = {}; }
  }
}
