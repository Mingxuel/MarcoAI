/* 策略回测页：策略/买入/卖出三选择 + 8 指标卡 + 资金 K 线 + 月/季/年 + 收益分布 */
import { h, clear, fmt, pct, n, toast } from '../util.js?v=20261105d';
import { API } from '../api.js?v=20261105d';
import { CapitalChart } from '../chart_adapter.js?v=20261105d';
import { ChartDrawings } from '../chart_drawings.js?v=20261105d';

const PICK_MODES = [
  { id: 'first', label: 'first · 当日候选第一只（单票）' },
  { id: 'avg', label: '平均 · 当日全部候选等权（组合）' },
  { id: 'last', label: 'last · 当日候选最后一只（单票）' },
];
const SELL_MODES = [
  { id: 'bplus', label: 'B+ 新卖法（推荐）' },
  { id: '5m', label: '5 分钟卖出（5m）' },
  { id: 'day', label: '日线卖出（day）' },
];
const DEFAULT_SELL_MODE = 'bplus';

/** B+ 新卖法后端接口（只在回测页使用，避免改动公共 api.js）。 */
async function fetchBplus(strategy, pickMode) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 120000);
  try {
    const url = `/api/backtest/bplus?strategy=${encodeURIComponent(strategy)}&months=12&pick_mode=${encodeURIComponent(pickMode)}`;
    const res = await fetch(url, { signal: ctrl.signal, cache: 'no-store' });
    const data = await res.json();
    if (!res.ok || data.ok === false) throw new Error((data && (data.error || data.message)) || `HTTP ${res.status}`);
    return data;
  } catch (e) {
    if (e && e.name === 'AbortError') throw new Error('B+ 回测超时（>120s）');
    throw e;
  } finally {
    clearTimeout(timer);
  }
}
const MA_LIST = [5, 10, 20, 30, 60, 120];
const MA_COLORS = { 5: '#f5c518', 10: '#f472b6', 20: '#60a5fa', 30: '#34d399', 60: '#c084fc', 120: '#fb923c' };

const INDEX_OPTIONS = [
  { code: '000001.SH', name: '上证指数', color: '#60a5fa' },
  { code: '399001.SZ', name: '深证成指', color: '#f472b6' },
  { code: '399006.SZ', name: '创业板指', color: '#f5c518' },
  { code: '000300.SH', name: '沪深300', color: '#34d399' },
  { code: '000852.SH', name: '中证1000', color: '#c084fc' },
  { code: '000688.SH', name: '科创50', color: '#fb923c' },
  { code: '000905.SH', name: '中证500', color: '#22d3ee' },
  { code: '000016.SH', name: '上证50', color: '#a3e635' },
  { code: '399986.SZ', name: '中证银行', color: '#e879f9' },
  { code: '000015.SH', name: '红利指数', color: '#f87171' },
];
const DEFAULT_INDEX_CODES = ['399006.SZ', '000001.SH'];
const INDEX_SEL_KEY = 'marco.backtest.indexCodes';
const INDEX_HIDDEN_KEY = 'marco.backtest.indexHidden';

async function fetchIndexSeries(codes, start, end) {
  if (!codes.length) return { indices: [], errors: [] };
  const url = `/api/index-series?codes=${encodeURIComponent(codes.join(','))}&start=${encodeURIComponent(start || '')}&end=${encodeURIComponent(end || '')}`;
  try {
    const res = await fetch(url, { cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (e) {
    return { indices: [], errors: [{ code: 'all', error: String((e && e.message) || e) }] };
  }
}

function prevDateStr(dateStr) {
  const d = new Date(String(dateStr) + 'T00:00:00Z');
  if (Number.isNaN(d.getTime())) return String(dateStr);
  d.setUTCDate(d.getUTCDate() - 1);
  return d.toISOString().slice(0, 10);
}

function ensureBacktestCss() {
  if (document.querySelector('link[data-bt-css]')) return;
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = '/css/backtest.css';
  link.setAttribute('data-bt-css', '1');
  document.head.appendChild(link);
}

function metricCard(key, value, suffix, opts = {}) {
  const missing = value == null || value === '' || Number.isNaN(Number(value));
  let cls = 'na';
  if (!missing) {
    const v = Number(value);
    cls = v > 0 ? 'up' : v < 0 ? 'down' : '';
  }
  let text = missing ? '—' : (opts.signed && Number(value) > 0 ? '+' : '') + fmt(value, opts.digits == null ? 1 : opts.digits) + (suffix || '');
  if (missing) text = '—';
  return h('div', { class: 'metric', 'data-metric': key },
    h('div', { class: 'k' }, opts.label || key),
    h('div', { class: 'v ' + cls }, text));
}

function barCol(title, items) {
  const maxAbs = Math.max(0.1, ...items.map((x) => Math.abs(Number(x.ret) || 0)));
  const rows = items.map((x) => {
    const v = Number(x.ret) || 0;
    const w = (Math.abs(v) / maxAbs) * 50;
    const left = v >= 0 ? 50 : 50 - w;
    return h('div', { class: 'ret-row' },
      h('span', { class: 'ret-lbl' }, x.label),
      h('span', { class: 'ret-track' },
        h('span', { class: 'mid' }),
        h('span', { class: 'ret-bar ' + (v >= 0 ? 'up' : 'down'), style: `left:${left}%;width:${w}%` })),
      h('span', { class: 'ret-val ' + (v >= 0 ? 'up' : 'down') }, (v >= 0 ? '+' : '') + v.toFixed(1) + '%'));
  });
  return h('div', { class: 'ret-col' }, h('h4', {}, title), rows);
}

function retItems(arr) {
  return (arr || []).slice().sort((a, b) => (a.k < b.k ? -1 : 1));
}

function retLabel(kind, k) {
  const s = String(k || '');
  if (kind === 'm' && s.length === 6) return s.slice(0, 4) + '-' + s.slice(4, 6);
  return s;
}

function distBox(title, values) {
  const bins = new Array(21).fill(0);
  (values || []).forEach((v) => {
    const x = Number(v);
    if (Number.isNaN(x)) return;
    let i = Math.round(x * 100) + 10;
    if (i < 0) i = 0;
    if (i > 20) i = 20;
    bins[i]++;
  });
  const maxC = Math.max(1, ...bins);
  const bars = bins.map((c, i) => h('span', {
    class: 'dist-bar ' + (i > 10 ? 'up' : i < 10 ? 'down' : 'zero'),
    style: `height:${Math.max(1, (c / maxC) * 100)}%`,
    title: `${i - 10}%: ${c} 次`,
  }));
  return h('div', { class: 'dist-box' },
    h('div', { class: 'dist-title' }, title),
    h('div', { class: 'dist-bars' }, bars),
    h('div', { class: 'dist-axis' }, h('span', {}, '-10%'), h('span', {}, '0'), h('span', {}, '+10%')));
}

export class BacktestView {
  constructor(root, ctx) {
    this.root = root;
    this.ctx = ctx;
    this.strategy = (ctx.meta.strategies && ctx.meta.strategies[0]) || 'TPO_M5';
    this.pickMode = 'first';
    this.sellMode = DEFAULT_SELL_MODE;
    this.maOn = { 5: true, 10: false, 20: false, 30: false, 60: false, 120: false };
    this.data = null;
    this.chart = null;
    this.capChart = null;
    this.draw = null;
    this.indexCodes = this._loadIndexCodes();
    this.hiddenSeries = this._loadHiddenSeries();
    this._mounted = false;
    this._loading = false;
  }

  mount() {
    if (this._mounted) return;
    this._mounted = true;
    this._renderSkeleton();
    this.load();
  }

  _renderSkeleton() {
    clear(this.root);
    this.controlsEl = h('div', { class: 'bt-controls' });
    this.bodyEl = h('div', {});
    this.badgeEl = h('span', { class: 'chip dim bt-bplus-badge' }, 'B+ 卖法 · 2026 年起生效（此前回退现状）');
    this.root.appendChild(h('div', { class: 'view-pad' },
      h('div', { class: 'page-head' },
        h('div', { class: 'page-title' }, '策略回测'),
        h('div', { class: 'page-sub' }, '默认 B+ 新卖法（2026 起生效；此前回退现状） · 口径与离线看板一致'),
        this.badgeEl,
        h('div', { class: 'spacer' }),
        this.controlsEl),
      this.bodyEl));
    this._renderControls();
  }

  _renderControls() {
    clear(this.controlsEl);
    const strategySel = h('select', { class: 'sel', onchange: () => { this.strategy = strategySel.value; this.load(); } });
    for (const s of (this.ctx.meta.strategies || ['TPO_M5'])) strategySel.appendChild(h('option', { value: s }, s));
    strategySel.value = this.strategy;
    const pickSel = h('select', { class: 'sel', onchange: () => { this.pickMode = pickSel.value; this.load(); } });
    for (const m of PICK_MODES) pickSel.appendChild(h('option', { value: m.id }, m.label));
    pickSel.value = this.pickMode;
    const sellSel = h('select', { class: 'sel', onchange: () => { this.sellMode = sellSel.value; this.load(); } });
    for (const m of SELL_MODES) sellSel.appendChild(h('option', { value: m.id }, m.label));
    sellSel.value = this.sellMode;
    this.controlsEl.appendChild(h('div', { class: 'ctl' }, h('span', {}, '策略'), strategySel));
    this.controlsEl.appendChild(h('div', { class: 'ctl' }, h('span', {}, '买入方式'), pickSel));
    this.controlsEl.appendChild(h('div', { class: 'ctl' }, h('span', {}, '卖出方式'), sellSel));
    this.controlsEl.appendChild(h('button', { class: 'btn btn-xs ghost', onclick: () => this.load(true) }, '刷新'));
  }

  async load(refresh = false) {
    if (this._loading) return;
    this._loading = true;
    clear(this.bodyEl);
    this.bodyEl.appendChild(h('div', { class: 'loading-box' }, h('div', { class: 'spin' }), h('span', {}, '回测数据加载中…')));
    try {
      const data = this.sellMode === 'bplus'
        ? await fetchBplus(this.strategy, this.pickMode)
        : await API.dashboard(this.strategy, this.pickMode, this.sellMode);
      this.data = data;
      this._renderBadge(data);
      if (!data || data.ok === false || (data.degraded && !(data.monthRet || []).length)) {
        const msg = (data && (data.error || data.message)) || '回测数据为空';
        this._renderError(msg);
        return;
      }
      await this._renderBody();
    } catch (e) {
      this._renderBadge(null);
      this._renderError(String((e && e.message) || e));
    } finally {
      this._loading = false;
    }
  }

  _renderBadge(data) {
    if (!this.badgeEl) return;
    if (this.sellMode === 'bplus') {
      const fb = data && data.fallbackDays != null ? data.fallbackDays : null;
      const start = data && data.bplusStart ? ` · 生效自 ${data.bplusStart}` : '';
      this.badgeEl.className = 'chip ok bt-bplus-badge';
      this.badgeEl.textContent = `B+ 卖法 · 2026 年起生效（此前回退现状）${fb != null ? ` · 回退 ${fb} 天` : ''}${start}`;
      this.badgeEl.title = (data && data.fallbackNote) || '2026 年前 / MA60 不足的日期回退现状 5m 卖法';
    } else if (this.sellMode === '5m') {
      this.badgeEl.className = 'chip dim bt-bplus-badge';
      this.badgeEl.textContent = '卖法：5 分钟（现状口径）';
      this.badgeEl.title = '切回“卖出方式”选择 B+ 新卖法可查看推荐口径';
    } else {
      this.badgeEl.className = 'chip dim bt-bplus-badge';
      this.badgeEl.textContent = '卖法：日线（现状口径）';
      this.badgeEl.title = '切回“卖出方式”选择 B+ 新卖法可查看推荐口径';
    }
  }

  _renderError(msg) {
    clear(this.bodyEl);
    this.bodyEl.appendChild(h('div', { class: 'error-box' },
      h('span', {}, '回测数据加载失败：' + msg),
      h('button', { class: 'btn btn-xs', onclick: () => this.load() }, '重试')));
  }

  async _renderBody() {
    const d = this.data;
    clear(this.bodyEl);
    const m = d.metrics || {};

    // —— 指标卡（8 个，无数据显示 —）——
    const metrics = h('div', { class: 'metrics' },
      metricCard('totalReturn', m.totalReturn, '%', { label: '总收益', signed: true }),
      metricCard('win', m.win, '%', { label: '胜率' }),
      metricCard('drawdown', m.drawdown == null ? null : -Math.abs(Number(m.drawdown)), '%', { label: '最大回撤' }),
      metricCard('maxProfit', m.maxProfit, '%', { label: '最大盈利', signed: true }),
      metricCard('annual', m.annual, '%', { label: '年化收益', signed: true }),
      metricCard('count', m.count, ' 次', { label: '交易次数', digits: 0 }),
      metricCard('maxWinStreak', m.maxWinStreak, ' 次', { label: '最大连赢', digits: 0 }),
      metricCard('maxLossStreak', m.maxLossStreak, ' 次', { label: '最大连亏', digits: 0 }));

    // —— 月/季/年收益 ——
    const monthItems = retItems(d.monthRet).map((x) => ({ label: retLabel('m', x.k), ret: x.ret }));
    const quarterItems = retItems(d.quarterRet).map((x) => ({ label: retLabel('q', x.k), ret: x.ret }));
    const yearItems = retItems(d.yearRet).map((x) => ({ label: retLabel('y', x.k), ret: x.ret }));
    const retPanel = h('div', { class: 'panel-block' },
      h('div', { class: 'panel-head' }, '盈亏汇总', h('span', { class: 'hint' }, '月度 / 季度 / 年度（按真实周期）')),
      h('div', { class: 'panel-body' },
        (monthItems.length || quarterItems.length || yearItems.length)
          ? h('div', { class: 'ret-cols' },
            barCol('月度盈亏', monthItems),
            barCol('季度盈亏', quarterItems),
            barCol('年度盈亏', yearItems))
          : h('div', { class: 'empty-box' }, '该策略无月度/季度/年度收益数据')));

    // —— 资金曲线（线段）+ 指数叠加（百分比，起点=0%） ——
    const idxBoxes = h('div', { class: 'bt-index-sel' });
    for (const opt of INDEX_OPTIONS) {
      const cb = h('input', { type: 'checkbox', checked: this.indexCodes.includes(opt.code) });
      cb.addEventListener('change', () => {
        if (cb.checked) {
          if (!this.indexCodes.includes(opt.code)) this.indexCodes.push(opt.code);
        } else {
          this.indexCodes = this.indexCodes.filter((c) => c !== opt.code);
        }
        this._saveIndexCodes();
        this._renderLineChart();
      });
      idxBoxes.appendChild(h('label', { title: opt.code }, cb,
        h('span', { class: 'dot', style: `background:${opt.color}` }), opt.name));
    }
    this.legendEl = h('div', { class: 'bt-line-legend' });
    this.capHost = h('div', { class: 'bt-cap-chart bt-line-chart' });
    this.lineTip = h('div', { class: 'bt-line-tip', hidden: true });
    const capPanel = h('div', { class: 'panel-block bt-line-panel' },
      h('div', { class: 'panel-head' }, '资金曲线 × 指数走势',
        h('span', { class: 'hint' }, '资金为线段 · 指数可多选 · 起点=0%（百分比） · 点击图例隐藏')),
      h('div', { class: 'panel-body' }, idxBoxes, this.legendEl, this.capHost, this.lineTip));

    // —— 收益分布 ——
    const dist = d.dist || {};
    const recent = (arr) => (arr || []).filter((x) => x != null).slice(-20);
    const distPanel = h('div', { class: 'panel-block' },
      h('div', { class: 'panel-head' }, '每日涨跌幅分布', h('span', { class: 'hint' }, '1% 一档，−10% ~ +10% · 最近 20 日 / 全部')),
      h('div', { class: 'panel-body' },
        h('div', { class: 'dist-groups' },
          h('div', { class: 'dist-group' },
            h('div', { class: 'dist-group-h' }, '最近 20 日'),
            h('div', { class: 'dist-grid' },
              distBox('开盘', recent(dist.open)), distBox('最高', recent(dist.high)),
              distBox('最低', recent(dist.low)), distBox('收盘', recent(dist.close)))),
          h('div', { class: 'dist-group' },
            h('div', { class: 'dist-group-h' }, '全部'),
            h('div', { class: 'dist-grid' },
              distBox('开盘', dist.open), distBox('最高', dist.high),
              distBox('最低', dist.low), distBox('收盘', dist.close))))));

    this.bodyEl.appendChild(metrics);
    this.bodyEl.appendChild(h('div', { class: 'bt-grid' }, retPanel, capPanel));
    this.bodyEl.appendChild(distPanel);

    await this._renderLineChart();
  }

  /* ---------------- 资金曲线 + 指数叠加 ---------------- */
  _loadIndexCodes() {
    try {
      const raw = JSON.parse(localStorage.getItem(INDEX_SEL_KEY) || 'null');
      if (Array.isArray(raw)) {
        const valid = raw.filter((c) => INDEX_OPTIONS.some((o) => o.code === c));
        if (valid.length) return valid;
      }
    } catch (e) { /* ignore */ }
    return DEFAULT_INDEX_CODES.slice();
  }

  _saveIndexCodes() {
    try { localStorage.setItem(INDEX_SEL_KEY, JSON.stringify(this.indexCodes)); } catch (e) { /* ignore */ }
  }

  _loadHiddenSeries() {
    try {
      const raw = JSON.parse(localStorage.getItem(INDEX_HIDDEN_KEY) || '[]');
      return new Set(Array.isArray(raw) ? raw : []);
    } catch (e) { return new Set(); }
  }

  _saveHiddenSeries() {
    try { localStorage.setItem(INDEX_HIDDEN_KEY, JSON.stringify([...this.hiddenSeries])); } catch (e) { /* ignore */ }
  }

  _capitalPoints() {
    const bars = (this.data && this.data.capitalKline) || [];
    if (!bars.length) return { points: [], raw: new Map() };
    const base = Number(bars[0].pre_close || bars[0].open || bars[0].close || 100000) || 100000;
    const points = [{ time: prevDateStr(bars[0].time), value: 0 }];
    const raw = new Map();
    for (const b of bars) {
      const c = Number(b.close);
      if (!Number.isFinite(c) || !b.time) continue;
      points.push({ time: String(b.time), value: (c / base - 1) * 100 });
      raw.set(String(b.time), c);
    }
    return { points, raw };
  }

  async _renderLineChart() {
    ensureBacktestCss();
    const LWg = window.LightweightCharts;
    if (!this.capHost || !LWg) {
      if (this.capHost) { clear(this.capHost); this.capHost.appendChild(h('div', { class: 'empty-box' }, '图表库未加载')); }
      return;
    }
    if (this.capChart) {
      try { this.capChart.remove(); } catch (e) { /* ignore */ }
      this.capChart = null;
    }
    const bars = (this.data && this.data.capitalKline) || [];
    if (!bars.length) {
      clear(this.capHost);
      this.capHost.appendChild(h('div', { class: 'empty-box' }, '无资金曲线数据'));
      if (this.legendEl) clear(this.legendEl);
      return;
    }
    const start = String(bars[0].time || '');
    const end = String(bars[bars.length - 1].time || '');
    const series = [];
    const cap = this._capitalPoints();
    series.push({ id: 'capital', name: '资金曲线', color: '#4ade80', points: cap.points, raw: cap.raw, isCapital: true });

    const codes = this.indexCodes.slice();
    const idxRes = await fetchIndexSeries(codes, start, end);
    for (const item of (idxRes.indices || [])) {
      const opt = INDEX_OPTIONS.find((o) => o.code === item.code);
      const pts = (item.points || []).filter((x) => x.date >= start && x.date <= end);
      if (!pts.length) continue;
      const base = Number(pts[0].value) || 1;
      const raw = new Map();
      const points = [{ time: prevDateStr(pts[0].date), value: 0 }];
      for (const x of pts) {
        raw.set(String(x.date), Number(x.value));
        points.push({ time: String(x.date), value: (Number(x.value) / base - 1) * 100 });
      }
      series.push({ id: item.code, name: item.name || (opt && opt.name) || item.code,
        color: (opt && opt.color) || '#94a3b8', points, raw });
    }

    this.capChart = LWg.createChart(this.capHost, {
      autoSize: true,
      layout: { background: { type: 'solid', color: '#0b1017' }, textColor: '#8b98ab', fontSize: 11,
        fontFamily: 'Consolas, "Cascadia Mono", monospace', attributionLogo: false },
      grid: { vertLines: { color: 'rgba(255,255,255,0.04)' }, horzLines: { color: 'rgba(255,255,255,0.04)' } },
      rightPriceScale: { borderColor: 'rgba(255,255,255,0.08)', scaleMargins: { top: 0.08, bottom: 0.08 } },
      timeScale: { borderColor: 'rgba(255,255,255,0.08)', rightOffset: 4, barSpacing: 5, timeVisible: false },
      crosshair: { mode: LWg.CrosshairMode ? LWg.CrosshairMode.Normal : 0,
        vertLine: { color: 'rgba(148,163,184,.55)', width: 1, style: 2, labelBackgroundColor: '#1e293b' },
        horzLine: { color: 'rgba(148,163,184,.55)', width: 1, style: 2, labelBackgroundColor: '#1e293b' } },
      localization: { locale: 'zh-CN' },
    });
    this._lineSeries = [];
    for (const s of series) {
      const hidden = this.hiddenSeries.has(s.id);
      const ser = this.capChart.addSeries(LWg.LineSeries, {
        color: s.color, lineWidth: s.isCapital ? 2 : 1, priceLineVisible: false,
        lastValueVisible: true, crosshairMarkerVisible: true, visible: !hidden,
        priceFormat: { type: 'custom', formatter: (v) => (Number(v) > 0 ? '+' : '') + Number(v).toFixed(1) + '%' },
      });
      ser.setData(s.points);
      this._lineSeries.push({ ...s, chart: ser });
    }
    this.capChart.timeScale().fitContent();
    this._lineMap = new Map();
    for (const s of this._lineSeries) this._lineMap.set(s.id, s.raw);
    this.capChart.subscribeCrosshairMove((param) => this._updateLineTip(param, series));
    this._renderLineLegend(series);
    if (!this.draw) {
      this.draw = new ChartDrawings(this.capHost, { pageKey: 'backtest', code: 'capital' });
      if (this.legendEl && this.legendEl.parentNode) this.legendEl.parentNode.insertBefore(this.draw.toolbarEl, this.legendEl);
      this.capHost.appendChild(this.draw.propsEl);
    }
    this.draw.setBars(this.data.capitalKline || []);
    this.draw.setChart(this.capChart, this._lineSeries[0] ? this._lineSeries[0].chart : null);
    this.draw.setContext({ pageKey: 'backtest', code: 'capital', period: this.sellMode });
  }

  _renderLineLegend(series) {
    if (!this.legendEl) return;
    clear(this.legendEl);
    for (const s of series) {
      const hidden = this.hiddenSeries.has(s.id);
      const item = h('span', { class: 'bt-legend-item' + (hidden ? ' off' : ''), title: '点击显示/隐藏' },
        h('span', { class: 'dot', style: `background:${s.color}` }), s.name);
      item.addEventListener('click', () => {
        if (this.hiddenSeries.has(s.id)) this.hiddenSeries.delete(s.id);
        else this.hiddenSeries.add(s.id);
        this._saveHiddenSeries();
        const target = (this._lineSeries || []).find((x) => x.id === s.id);
        if (target) {
          try { target.chart.applyOptions({ visible: !this.hiddenSeries.has(s.id) }); } catch (e) { /* ignore */ }
        }
        item.classList.toggle('off', this.hiddenSeries.has(s.id));
      });
      this.legendEl.appendChild(item);
    }
  }

  _updateLineTip(param, series) {
    if (!this.lineTip) return;
    if (!param || !param.time || !param.point) { this.lineTip.hidden = true; return; }
    const date = String(param.time);
    const rows = [];
    for (const s of series) {
      if (this.hiddenSeries.has(s.id)) continue;
      const rawMap = s.raw;
      const raw = rawMap.get(date);
      const target = (this._lineSeries || []).find((x) => x.id === s.id);
      let val = null;
      if (target) {
        const d = target.points.find((p) => String(p.time) === date);
        if (d) val = d.value;
      }
      if (raw == null) continue;
      const keys = [...rawMap.keys()].sort();
      const idx = keys.indexOf(date);
      const prev = idx > 0 ? rawMap.get(keys[idx - 1]) : raw;
      const chg = prev ? (raw / prev - 1) * 100 : 0;
      rows.push({ name: s.name, value: val == null ? raw : val, chg, isCapital: !!s.isCapital });
    }
    if (!rows.length) { this.lineTip.hidden = true; return; }
    clear(this.lineTip);
    this.lineTip.appendChild(h('div', { class: 't' }, date));
    for (const r of rows) {
      this.lineTip.appendChild(h('div', { class: 'r' + (r.isCapital ? ' cap' : '') },
        h('span', { class: 'n', style: `color:${r.isCapital ? '#4ade80' : '#c7d5e6'}` }, r.name),
        h('span', { class: 'v' }, (r.value >= 0 ? '+' : '') + fmt(r.value, 1) + '%'),
        h('span', { class: 'c ' + (r.chg >= 0 ? 'up' : 'down') }, (r.chg >= 0 ? '+' : '') + fmt(r.chg, 2) + '%')));
    }
    const rect = this.capHost.getBoundingClientRect();
    const x = Math.min(Math.max(8, param.point.x + 14), Math.max(8, rect.width - 200));
    const y = Math.min(Math.max(8, param.point.y + 14), Math.max(8, rect.height - 120));
    this.lineTip.style.left = x + 'px';
    this.lineTip.style.top = y + 'px';
    this.lineTip.hidden = false;
  }
}
