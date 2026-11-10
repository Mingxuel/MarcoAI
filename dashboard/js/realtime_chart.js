/* 实时看盘 5 分钟 K 线（v2）：candlestick + 5m MA + 日线 MA（step line）。
 * 日线 MA 数据由后端按「截至前一交易日」计算，避免未来函数。
 */
import { UP, DOWN, fmtBarTime, isIntraday } from './util.js?v=20261106aa';

const LW = () => window.LightweightCharts;

export const MA_DEFS = [
  { id: 'm5_5', scope: '5m', period: 5, label: '5m MA5', color: '#f5c518', defaultOn: true },
  { id: 'm5_60', scope: '5m', period: 60, label: '5m MA60', color: '#60a5fa', defaultOn: true },
  { id: 'd_5', scope: 'day', period: 5, label: '日均 MA5', color: '#34d399', defaultOn: true, step: true },
  { id: 'd_60', scope: 'day', period: 60, label: '日均 MA60', color: '#c084fc', defaultOn: true, step: true },
  { id: 'm5_10', scope: '5m', period: 10, label: '5m MA10', color: '#94a3b8', defaultOn: false },
  { id: 'm5_20', scope: '5m', period: 20, label: '5m MA20', color: '#a78bfa', defaultOn: false },
  { id: 'm5_30', scope: '5m', period: 30, label: '5m MA30', color: '#fb923c', defaultOn: false },
  { id: 'm5_120', scope: '5m', period: 120, label: '5m MA120', color: '#64748b', defaultOn: false },
  { id: 'd_10', scope: 'day', period: 10, label: '日均 MA10', color: '#5eead4', defaultOn: false, step: true },
  { id: 'd_20', scope: 'day', period: 20, label: '日均 MA20', color: '#fdba74', defaultOn: false, step: true },
  { id: 'd_30', scope: 'day', period: 30, label: '日均 MA30', color: '#e879f9', defaultOn: false, step: true },
  { id: 'd_120', scope: 'day', period: 120, label: '日均 MA120', color: '#94a3b8', defaultOn: false, step: true },
];

export function defaultMaState() {
  const state = {};
  for (const d of MA_DEFS) state[d.id] = !!d.defaultOn;
  return state;
}

function sma(bars, period) {
  const out = [];
  let sum = 0;
  for (let i = 0; i < bars.length; i++) {
    sum += bars[i].close;
    if (i >= period) sum -= bars[i - period].close;
    if (i >= period - 1) out.push({ time: bars[i].time, value: sum / period });
  }
  return out;
}

export class RealtimeChart {
  constructor(container) {
    this.container = container;
    this.chart = null;
    this.candle = null;
    this.series = {};
    this.activeSeries = {};
    this._disposed = false;
  }

  _baseOptions() {
    const LWg = LW();
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
      rightPriceScale: { borderColor: 'rgba(255,255,255,0.08)', scaleMargins: { top: 0.08, bottom: 0.08 } },
      timeScale: {
        borderColor: 'rgba(255,255,255,0.08)', rightOffset: 3, barSpacing: 4, minBarSpacing: 0.8,
        timeVisible: true, secondsVisible: false,
        tickMarkFormatter: (time, tickMarkType) => {
          const d = new Date(Number(time) * 1000);
          const y = d.getUTCFullYear();
          const mo = String(d.getUTCMonth() + 1).padStart(2, '0');
          const da = String(d.getUTCDate()).padStart(2, '0');
          const hh = String(d.getUTCHours()).padStart(2, '0');
          const mi = String(d.getUTCMinutes()).padStart(2, '0');
          if (tickMarkType === 0) return String(y);
          if (tickMarkType === 1 || tickMarkType === 2) return `${mo}-${da}`;
          return `${hh}:${mi}`;
        },
      },
      localization: { locale: 'zh-CN', timeFormatter: (t) => fmtBarTime(t, '5m') },
      crosshair: {
        mode: LWg && LWg.CrosshairMode ? LWg.CrosshairMode.Normal : 0,
        vertLine: { color: 'rgba(148,163,184,.55)', width: 1, style: 2, labelBackgroundColor: '#1e293b' },
        horzLine: { color: 'rgba(148,163,184,.55)', width: 1, style: 2, labelBackgroundColor: '#1e293b' },
      },
      handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
      handleScale: { mouseWheel: true, pinch: true, axisPressedMouseMove: { time: true, price: true }, axisDoubleClickReset: { time: true, price: true } },
    };
  }

  /** @param {{bars:Array, dayMa:Object, maState:Object}} data */
  render(bars, dailyMa, maState) {
    this.dispose();
    if (!this.container) return;
    const LWg = LW();
    if (!LWg) throw new Error('图表库未加载（vendor/lightweight-charts）');
    if (!bars || !bars.length) { this.activeSeries = {}; return; }

    this.chart = LWg.createChart(this.container, this._baseOptions());
    this.candle = this.chart.addSeries(LWg.CandlestickSeries, {
      upColor: UP, downColor: DOWN, borderUpColor: UP, borderDownColor: DOWN,
      wickUpColor: UP, wickDownColor: DOWN, priceLineVisible: false, lastValueVisible: true,
      priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
    }, 0);
    this.candle.setData(bars.map((b) => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close })));

    const active = {};
    for (const def of MA_DEFS) {
      if (!maState || maState[def.id] !== true) continue;
      let data;
      if (def.scope === '5m') data = sma(bars, def.period);
      else data = (dailyMa && dailyMa[String(def.period)]) || [];
      if (!data.length) continue;
      const lineType = def.step && LWg.LineType && LWg.LineType.WithSteps != null ? LWg.LineType.WithSteps : 0;
      const s = this.chart.addSeries(LWg.LineSeries, {
        color: def.color, lineWidth: def.step ? 1 : 1, lineType,
        priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
        lineStyle: def.step ? 0 : 0,
      }, 0);
      s.setData(data);
      active[def.id] = s;
    }
    this.activeSeries = active;
    this.chart.timeScale().fitContent();
  }

  fitContent() {
    if (this.chart) {
      try { this.chart.timeScale().fitContent(); } catch (e) { /* ignore */ }
    }
  }

  dispose() {
    this.activeSeries = {};
    if (this.chart) {
      try { this.chart.remove(); } catch (e) { /* ignore */ }
      this.chart = null;
      this.candle = null;
    }
  }

  destroy() {
    this._disposed = true;
    this.dispose();
  }
}
