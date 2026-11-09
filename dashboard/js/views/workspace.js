/* K 线工作区：1/2/4 布局、每面板独立周期/指标、股票联动 + 时间轴联动、交易标记 */
import { h, clear, fmt, pct, chgClass, fmtBarTime, dateToTs, toast, openPopover, closePopover } from '../util.js?v=20261106j';
import { API } from '../api.js?v=20261106j';
import { KlineChart } from '../chart_adapter.js?v=20261106j';
import { ChartDrawings } from '../chart_drawings.js?v=20261106j';
import { AVAILABLE_PERIODS, INDICATORS, PERIODS, panelCount } from '../store.js?v=20261106j';

const MA_PERIODS = [5, 10, 20, 30, 60, 120];
const MA_COLORS = { 5: '#f5c518', 10: '#f472b6', 20: '#60a5fa', 30: '#34d399', 60: '#c084fc', 120: '#fb923c' };

function loadMaState(key) {
  try {
    const v = JSON.parse(localStorage.getItem(key) || 'null');
    if (Array.isArray(v)) return v.filter((x) => MA_PERIODS.includes(x));
  } catch (e) { /* ignore */ }
  return [5, 60];
}

function barYmdAny(t) {
  if (typeof t === 'number') {
    const d = new Date(t * 1000);
    return `${d.getUTCFullYear()}${String(d.getUTCMonth() + 1).padStart(2, '0')}${String(d.getUTCDate()).padStart(2, '0')}`;
  }
  const m = String(t || '').match(/(\d{4})-?(\d{2})-?(\d{2})/);
  return m ? `${m[1]}${m[2]}${m[3]}` : '';
}

const COUNT_BY_PERIOD = { '1d': 320, '5m': 600, '15m': 600, '30m': 600 };
const CODE_RE = /^\d{6}\.(SH|SZ|BJ)$/;

function pad2(n) { return String(n).padStart(2, '0'); }

function barYmd(ts) {
  const d = new Date(Number(ts) * 1000);
  return `${d.getUTCFullYear()}${pad2(d.getUTCMonth() + 1)}${pad2(d.getUTCDate())}`;
}

class Panel {
  constructor(view, index) {
    this.view = view;
    this.index = index;
    this.state = { code: '', name: '', period: '1d', indicators: ['MA'] };
    this.bars = [];
    this.chart = null;
    this.data = null;
    this.loadToken = 0;
    this._status = 'idle';
    this._build();
  }

  _build() {
    this.symInput = h('input', {
      class: 'ws-sym', list: 'symbol-list', placeholder: '代码',
      title: '输入股票代码，如 600118.SH；回车加载',
      onchange: () => this._onSymbolCommit(),
      onkeydown: (e) => { if (e.key === 'Enter') { e.preventDefault(); this._onSymbolCommit(); } },
    });
    this.nameEl = h('span', { class: 'ws-name' }, '—');
    this.periodSel = h('select', {
      class: 'sel ws-period', title: '本面板周期（周期始终独立，不受联动影响）',
      onchange: () => this.view.changePeriod(this.index, this.periodSel.value),
    });
    for (const p of AVAILABLE_PERIODS) this.periodSel.appendChild(h('option', { value: p.id }, p.label));
    // 未开放周期灰显（v1 只做 1d/5m/15m/30m；60m/1w/1mo 服务端已能正确重采样，按 P1-10 开放）
    for (const p of PERIODS.filter((x) => !x.available)) {
      this.periodSel.appendChild(h('option', { value: p.id, disabled: '', title: p.note || '' }, p.label));
    }
    this.indBtn = h('button', {
      class: 'ws-ind-btn', title: '本面板指标（MA/BOLL 主图，VOL/MACD/KDJ 副图）',
      onclick: (e) => { e.stopPropagation(); this._openIndicators(); },
    }, '指标');
    this.fitBtn = h('button', {
      class: 'ws-tools-btn', title: '自适应 (F)', onclick: (e) => { e.stopPropagation(); if (this.chart) this.chart.fitContent(); },
    }, '自适应');
    this.priceBox = h('div', { class: 'ws-price' });

    this.rangeTag = h('span', { class: 'ws-range-tag', hidden: true });
    const head = h('div', { class: 'ws-head' }, this.symInput, this.nameEl, this.periodSel, this.indBtn, this.fitBtn, this.rangeTag, this.priceBox);
    this.chartEl = h('div', { class: 'ws-chart' });
    this.overlay = h('div', { class: 'ws-overlay', hidden: true });
    this.readout = h('div', { class: 'ws-readout' });
    this.markerTag = h('div', { class: 'ws-marker-tag', hidden: true });
    this.draw = new ChartDrawings(this.chartEl, { pageKey: 'workspace' });
    head.appendChild(this.draw.toolbarEl);
    this.chartEl.appendChild(this.draw.propsEl);
    this.maKey = `marco.ma.${this.view.pageKey || 'workspace'}.${this.index}`;
    this.maState = loadMaState(this.maKey);
    this.maBar = h('div', { class: 'ws-ma-bar' });
    for (const p of MA_PERIODS) {
      const cb = h('input', { type: 'checkbox', checked: this.maState.includes(p) });
      cb.addEventListener('change', () => {
        const set = new Set(this.maState);
        if (cb.checked) set.add(p); else set.delete(p);
        this.maState = MA_PERIODS.filter((x) => set.has(x));
        try { localStorage.setItem(this.maKey, JSON.stringify(this.maState)); } catch (e) { /* ignore */ }
        this.renderChart();
      });
      this.maBar.appendChild(h('label', { title: `MA${p}` }, cb,
        h('span', { class: 'dot', style: `background:${MA_COLORS[p]}` }), String(p)));
    }
    this.chartEl.appendChild(this.maBar);
    this.hoverEl = h('div', { class: 'ws-hover', hidden: true });
    this.chartEl.appendChild(this.hoverEl);
    this.body = h('div', { class: 'ws-body' }, this.chartEl, this.readout, this.markerTag, this.overlay);
    this.el = h('div', { class: 'ws-panel', 'data-panel': this.index }, head, this.body);
    this.el.addEventListener('mousedown', () => this.view.setActive(this.index), true);
  }

  ensureChart() {
    if (!this.chart) {
      this.chart = new KlineChart(this.chartEl, {
        onRange: (range) => this.view.onPanelRange(this, range),
        onCrosshair: (bar) => this.view.onPanelCrosshair(this, bar),
      });
    }
    return this.chart;
  }

  setState(state, { silent = true } = {}) {
    if (!state) return;
    this.state = {
      code: state.code || '',
      name: state.name || '',
      period: AVAILABLE_PERIODS.some((p) => p.id === state.period) ? state.period : '1d',
      indicators: (state.indicators || ['MA']).filter((x) => INDICATORS.some((i) => i.id === x)),
    };
    this.symInput.value = this.state.code;
    this.nameEl.textContent = this.state.name || this.state.code || '—';
    this.periodSel.value = this.state.period;
    this._updateIndBtn();
  }

  _updateIndBtn() {
    const on = this.state.indicators;
    this.indBtn.textContent = on.length ? '指标 ' + on.join('/') : '指标';
    this.indBtn.classList.toggle('has', on.length > 0);
  }

  _openIndicators() {
    const wrap = h('div', {});
    wrap.appendChild(h('div', { class: 'pop-title' }, '主图指标'));
    for (const ind of INDICATORS.filter((x) => ['MA', 'BOLL'].includes(x.id))) wrap.appendChild(this._indRow(ind));
    wrap.appendChild(h('div', { class: 'pop-sep' }));
    wrap.appendChild(h('div', { class: 'pop-title' }, '副图指标（可多选）'));
    for (const ind of INDICATORS.filter((x) => ['VOL', 'MACD', 'KDJ'].includes(x.id))) wrap.appendChild(this._indRow(ind));
    openPopover(this.indBtn, wrap);
  }

  _indRow(ind) {
    const cb = h('input', { type: 'checkbox', checked: this.state.indicators.includes(ind.id) });
    cb.addEventListener('change', () => {
      const set = new Set(this.state.indicators);
      if (cb.checked) set.add(ind.id); else set.delete(ind.id);
      const order = INDICATORS.map((x) => x.id);
      this.state.indicators = [...set].sort((a, b) => order.indexOf(a) - order.indexOf(b));
      this.view.changeIndicators(this.index, this.state.indicators);
      this._updateIndBtn();
    });
    return h('label', { class: 'pop-row' }, cb, h('span', { class: 'k' }, ind.label), h('span', { class: 'd' }, ind.desc));
  }

  _onSymbolCommit() {
    const code = (this.symInput.value || '').trim().toUpperCase();
    if (!CODE_RE.test(code)) {
      toast('代码格式应为 000001.SZ / 600000.SH', 'err');
      this.symInput.value = this.state.code;
      return;
    }
    if (code === this.state.code) return;
    this.view.changeSymbol(this.index, code, '');
  }

  setStatus(kind, title, sub, { retry = false } = {}) {
    this._status = kind;
    clear(this.overlay);
    if (kind === 'ok') { this.overlay.hidden = true; return; }
    this.overlay.hidden = false;
    if (kind === 'loading') {
      this.overlay.appendChild(h('div', { class: 'spin' }));
      this.overlay.appendChild(h('div', { class: 't' }, title || '行情加载中…'));
      if (sub) this.overlay.appendChild(h('div', { class: 's' }, sub));
      return;
    }
    this.overlay.appendChild(h('div', { class: 't' }, title || '暂无数据'));
    if (sub) this.overlay.appendChild(h('div', { class: 's' }, sub));
    if (retry) {
      this.overlay.appendChild(h('button', { class: 'btn btn-xs', onclick: () => this.load() }, '重试'));
    }
  }

  async load() {
    if (!this.state.code) return;
    const token = ++this.loadToken;
    this.setStatus('loading', '行情加载中…');
    this.readout.textContent = '';
    try {
      const isDaily = this.state.period === '1d';
      // 选股页：1D 显示全部日线；只有 5m 等盘中周期使用 T-3~T+1 区间
      const useRange = (this.view.rangeStart || this.view.rangeEnd) && !isDaily;
      const rangeEnd = useRange ? this.view.rangeEnd : null;
      const endDate = rangeEnd || this.view.endDate || null;
      const count = useRange
        ? 600
        : (isDaily ? (COUNT_BY_PERIOD['1d'] || 320)
          : (endDate ? 480 : (COUNT_BY_PERIOD[this.state.period] || 600)));
      const res = await API.kline(this.state.code, this.state.period, count, endDate);
      if (token !== this.loadToken) return;
      this.data = res;
      if (!res.bars || !res.bars.length) {
        this.bars = [];
        if (this.chart) this.chart.disposeChart();
        const is5m = ['5m', '15m', '30m'].includes(this.state.period);
        const reason = res.reason || (is5m ? '本地 5M 数据集无该股（仅覆盖 253 只，未自动触发通达信补数）' : '本地 1D 数据集无该股');
        this.setStatus('empty', '暂无K线数据', reason + '；可切换周期或换股。', { retry: true });
        this._updateMarkerTag();
        this.priceBox.textContent = '';
        return;
      }
      this.bars = res.bars;
      if (useRange) {
        const lo = this.view.rangeStart || '00000000';
        const hi = this.view.rangeEnd || '99999999';
        this.bars = this.bars.filter((b) => {
          const y = barYmdAny(b.time);
          return y >= lo && y <= hi;
        });
      } else if (this.view.cutoffDate) {
        this.bars = this.bars.filter((b) => barYmdAny(b.time) < this.view.cutoffDate);
      }
      this._updateRangeTag();
      this.renderChart();
      this.setStatus('ok');
    } catch (e) {
      if (token !== this.loadToken) return;
      this.setStatus('error', '行情加载失败', String((e && e.message) || e), { retry: true });
    }
  }

  renderChart() {
    if (!this.bars.length) return;
    const chart = this.ensureChart();
    const markers = this.view.markersFor(this);
    const focus = this.view.takeFocus(this);
    // 程序化渲染/自适应期间不触发跨面板时间轴联动，避免把 5m 的可视区间套到日线上
    this._suppressRange = true;
    clearTimeout(this._suppressTimer);
    this._suppressTimer = setTimeout(() => { this._suppressRange = false; }, 350);
    try {
      chart.render(this.bars, this.state.period, this.state.indicators, { markers, focus, fullRange: !!this.view.endDate || (!!this.view.rangeEnd && this.state.period !== '1d'), ma: this.maState, hideLastValue: !!this.view.hideLastPriceLine, dayGrid: this.state.period === '5m' && !!this.view.rangeEnd, code: this.state.code });
      // 5m 按日网格由 chart_adapter 的原生 primitive 绘制（随缩放移动）
      if (this.view.hideLastPriceLine && chart.candle) {
        try { chart.candle.applyOptions({ priceLineVisible: false, lastValueVisible: false }); } catch (e) { /* ignore */ }
      }
      if (!this._hoverBound && chart.chart) {
        this._hoverBound = true;
        chart.chart.subscribeCrosshairMove((p) => this._updateHover(p));
        this.chartEl.addEventListener('mousemove', (ev) => this._updateHoverAt(ev));
        this.chartEl.addEventListener('mouseleave', () => { if (this.hoverEl) this.hoverEl.hidden = true; });
      }
      if (this.draw) {
        this.draw.setBars(this.bars);
        this.draw.setChart(chart.chart, chart.candle);
        this.draw.setContext({ pageKey: this.view.pageKey || 'workspace', code: this.state.code, period: this.state.period });
      }
    } catch (e) {
      this.setStatus('error', '图表渲染失败', String((e && e.message) || e), { retry: true });
      return;
    }
    this._updatePrice();
    this._updateMarkerTag();
    this.readout.textContent = '';
  }

  _updateRangeTag() {
    if (!this.rangeTag) return;
    const a = this.view.rangeStart, b = this.view.rangeEnd;
    if (!a && !b) { this.rangeTag.hidden = true; this.rangeTag.textContent = ''; return; }
    if (this.state.period === '1d') { this.rangeTag.textContent = '全部日线'; this.rangeTag.hidden = false; return; }
    const f = (y) => y && y.length === 8 ? `${y.slice(0, 4)}-${y.slice(4, 6)}-${y.slice(6, 8)}` : '—';
    this.rangeTag.textContent = `${f(a)} ~ ${f(b)}`;
    this.rangeTag.hidden = false;
  }

  _updateHoverAt(ev) {
    if (!this.hoverEl || !this.bars || !this.bars.length || !this.chart || !this.chart.chart) return;
    const rect = this.chartEl.getBoundingClientRect();
    const x = ev.clientX - rect.left;
    let best = 0, bestD = Infinity;
    for (let i = 0; i < this.bars.length; i++) {
      let cx = null;
      try { cx = this.chart.chart.timeScale().timeToCoordinate(this.bars[i].time); } catch (e) { cx = null; }
      if (cx == null) continue;
      const d = Math.abs(cx - x);
      if (d < bestD) { bestD = d; best = i; }
    }
    this._showHoverBar(best);
  }

  _updateHover(param) {
    if (!this.hoverEl) return;
    if (!param || param.time == null || !this.bars || !this.bars.length) { this.hoverEl.hidden = true; return; }
    let idx = -1;
    for (let i = 0; i < this.bars.length; i++) {
      if (String(this.bars[i].time) === String(param.time)) { idx = i; break; }
    }
    if (idx < 0) { this.hoverEl.hidden = true; return; }
    this._showHoverBar(idx);
  }

  _showHoverBar(idx) {
    if (!this.hoverEl || !this.bars || !this.bars[idx]) return;
    const b = this.bars[idx];
    const prev = idx > 0 ? this.bars[idx - 1] : null;
    const prevClose = prev ? Number(prev.close) : Number(b.open);
    const chg = prevClose ? ((Number(b.close) - prevClose) / prevClose) * 100 : null;
    const ma = [];
    for (const per of (this.maState || [])) {
      if (idx < per - 1) continue;
      let sum = 0;
      for (let j = idx - per + 1; j <= idx; j++) sum += Number(this.bars[j].close);
      ma.push(`MA${per} ${(sum / per).toFixed(2)}`);
    }
    const t = typeof b.time === 'number' ? new Date(b.time * 1000).toISOString().slice(0, 10) : String(b.time).slice(0, 10);
    const timeText = fmtBarTime(b.time, this.state.period);
    const vol = Number(b.volume);
    const volText = Number.isFinite(vol) ? (vol / 10000).toFixed(1) + ' 万' : '—';
    const amt = Number(b.amount);
    const amtText = Number.isFinite(amt) && amt > 0 ? (amt / 100000000).toFixed(2) + ' 亿' : null;
    const cls = chg > 0 ? 'up' : chg < 0 ? 'down' : '';
    this.hoverEl.innerHTML = `<div class="t">${timeText}</div>`
      + `<div class="r"><span>开 ${Number(b.open).toFixed(2)}</span><span>高 ${Number(b.high).toFixed(2)}</span><span>低 ${Number(b.low).toFixed(2)}</span><span>收 ${Number(b.close).toFixed(2)}</span></div>`
      + `<div class="r"><span class="${cls}">涨跌 ${chg == null ? '—' : (chg >= 0 ? '+' : '') + chg.toFixed(2) + '%'}</span><span>量 ${volText}</span>${amtText ? `<span>额 ${amtText}</span>` : ''}</div>`
      + (ma.length ? `<div class="r ma">${ma.join(' · ')}</div>` : '');
    this.hoverEl.hidden = false;
  }

  _updatePrice() {
    if (this.view.hideLastPriceLine) {
      clear(this.priceBox);
      this.priceBox.hidden = true;
      return;
    }
    this.priceBox.hidden = false;
    const bars = this.bars;
    if (!bars || !bars.length) { clear(this.priceBox); return; }
    const last = bars[bars.length - 1];
    const prev = bars.length > 1 ? bars[bars.length - 2] : null;
    const chg = prev && prev.close ? ((last.close - prev.close) / prev.close) * 100 : null;
    clear(this.priceBox);
    this.priceBox.appendChild(h('span', { class: 'ws-eod' }, '收盘'));
    this.priceBox.appendChild(h('span', { class: 'ws-close ' + chgClass(chg) }, fmt(last.close, 2)));
    this.priceBox.appendChild(h('span', { class: 'ws-chg ' + chgClass(chg) }, (chg == null ? '—' : pct(chg, 2) + '%')));
  }

  updateReadout(bar) {
    if (!bar) {
      if (this.bars.length) {
        const b = this.bars[this.bars.length - 1];
        this.readout.textContent = `${fmtBarTime(b.time, this.state.period)}  O ${fmt(b.open)} H ${fmt(b.high)} L ${fmt(b.low)} C ${fmt(b.close)}`;
      }
      return;
    }
    const prev = this._prevBar(bar.time);
    const chg = prev && prev.close ? ((bar.close - prev.close) / prev.close) * 100 : null;
    const cls = chgClass(chg);
    this.readout.innerHTML = '';
    this.readout.appendChild(document.createTextNode(fmtBarTime(bar.time, this.state.period) + '  '));
    this.readout.appendChild(h('span', {}, `O ${fmt(bar.open)} H ${fmt(bar.high)} L ${fmt(bar.low)} `));
    this.readout.appendChild(h('span', { class: cls }, `C ${fmt(bar.close)}`));
    if (chg != null) this.readout.appendChild(h('span', { class: cls }, ` ${pct(chg, 2)}%`));
    if (bar.volume) this.readout.appendChild(h('span', {}, `  V ${(bar.volume / 10000).toFixed(1)}万`));
  }

  _prevBar(time) {
    if (!this.bars || !this.bars.length) return null;
    let lo = 0, hi = this.bars.length - 1, idx = -1;
    while (lo <= hi) { const mid = (lo + hi) >> 1; if (this.bars[mid].time < time) { idx = mid; lo = mid + 1; } else hi = mid - 1; }
    return idx >= 0 ? this.bars[idx] : null;
  }

  _updateMarkerTag() {
    const trade = this.view.trade;
    clear(this.markerTag);
    if (!trade || this.state.code !== trade.code) { this.markerTag.hidden = true; return; }
    this.markerTag.hidden = false;
    this.markerTag.appendChild(h('span', { class: 't2' }, '选股日 T-2 ' + trade.t2Label));
    this.markerTag.appendChild(h('span', { class: 't0' }, '卖出日 T-0 ' + trade.t0Label));
  }

  setMarkersOnly() {
    if (!this.chart || !this.bars.length) return;
    this.chart.setMarkers(this.view.markersFor(this));
    this._updateMarkerTag();
  }

  setActiveVisual(on) { this.el.classList.toggle('active', !!on); }
}

export class WorkspaceView {
  constructor(root, ctx) {
    this.root = root;
    this.ctx = ctx;
    this.grid = null;
    this.panels = [];
    this.activeIndex = 0;
    this.trade = null;
    this._focusFlags = new Set();
    this._syncGuard = false;
    this._crossGuard = false;
    this._mounted = false;
    this.cutoffDate = null;
    this.endDate = null;
    this.rangeStart = null;
    this.rangeEnd = null;
    this.pageKey = 'workspace';
  }

  mount() {
    if (this._mounted) { this.reloadFromStore(); return; }
    this._mounted = true;
    clear(this.root);
    // 每个实例拥有自己的 grid（主工作区与策略选股页左侧工作区互不干扰）
    this.grid = h('div', { class: 'ws-grid' });
    this.root.appendChild(this.grid);
    for (let i = 0; i < 4; i++) {
      const p = new Panel(this, i);
      this.panels.push(p);
      this.grid.appendChild(p.el);
    }
    this.applyStore({ load: true });
  }

  setCutoff(date) {
    const d = String(date || '').replace(/-/g, '').slice(0, 8);
    const v = /^\d{8}$/.test(d) ? d : null;
    if (this.cutoffDate === v) return;
    this.cutoffDate = v;
    this.loadVisible();
  }

  setRange(start, end) {
    const a = start || null, b = end || null;
    this.rangeStart = a; this.rangeEnd = b;
    for (const p of this.panels) { if (!p.el.hidden) p.load(); }
  }

  setEnd(date) {
    const d = String(date || '').replace(/-/g, '').slice(0, 8);
    const v = /^\d{8}$/.test(d) ? d : null;
    if (this.endDate === v) return;
    this.endDate = v;
    this.loadVisible();
  }

  applyStore({ load = false } = {}) {
    const w = this.ctx.store.active();
    this.ws = w;
    this.grid.className = 'ws-grid layout-' + w.layout;
    const visible = panelCount(w.layout);
    if (this.activeIndex >= visible) this.activeIndex = 0;
    this.panels.forEach((p, i) => {
      p.el.hidden = i >= visible;
      p.setState(w.panels[i]);
    });
    this.markActive();
    if (load) this.loadVisible();
    // 同步顶栏联动开关（工作区切换时联动状态随工作区恢复）
    this.ctx.onStoreChanged && this.ctx.onStoreChanged({ source: 'workspace' });
  }

  reloadFromStore() {
    this.clearTrade({ silent: true });
    this.applyStore({ load: true });
  }

  loadVisible() {
    this.panels.forEach((p) => { if (!p.el.hidden) p.load(); });
  }

  markActive() {
    this.panels.forEach((p, i) => p.setActiveVisual(i === this.activeIndex && !p.el.hidden));
  }

  setActive(index) {
    if (this.activeIndex === index) return;
    this.activeIndex = index;
    this.markActive();
  }

  changeSymbol(index, code, name) {
    const w = this.ctx.store.active();
    const targets = [];
    if (w.stockLink) {
      const visible = panelCount(w.layout);
      for (let i = 0; i < visible; i++) targets.push(i);
      if (!targets.includes(index)) targets.push(index);
    } else {
      targets.push(index);
    }
    for (const i of targets) {
      const p = this.panels[i];
      if (!p) continue;
      if (p.state.code === code && p.state.name === name) continue;
      p.setState(Object.assign({}, p.state, { code, name: name || p.state.name || '' }));
      this.ctx.store.updatePanel(i, { code, name: name || p.state.name || '' });
      if (!p.el.hidden) p.load();
    }
  }

  changePeriod(index, period) {
    const p = this.panels[index];
    if (!p) return;
    if (!AVAILABLE_PERIODS.some((x) => x.id === period)) return;
    p.state.period = period;
    this.ctx.store.updatePanel(index, { period });
    p.load();
  }

  changeIndicators(index, list) {
    const p = this.panels[index];
    if (!p) return;
    p.state.indicators = list;
    this.ctx.store.updatePanel(index, { indicators: list });
    if (p.bars && p.bars.length) p.renderChart();
  }

  /** 从选股表点行：联动股票 + 标记 T-2/T-0 + 定位卖出日 */
  selectTrade(trade) {
    this.trade = trade || null;
    if (!trade) { this.clearTrade(); return; }
    const w = this.ctx.store.active();
    const targets = w.stockLink ? this.panels.map((p, i) => i).filter((i) => !this.panels[i].el.hidden) : [this.activeIndex];
    for (const i of targets) {
      const p = this.panels[i];
      if (!p) continue;
      if (p.state.code !== trade.code) {
        p.setState(Object.assign({}, p.state, { code: trade.code, name: trade.name || '' }));
        this.ctx.store.updatePanel(i, { code: trade.code, name: trade.name || '' });
      }
      this._focusFlags.add(i);
      p.load();
    }
    this.ctx.setTradeChip && this.ctx.setTradeChip(trade);
  }

  clearTrade({ silent = false } = {}) {
    this.trade = null;
    this._focusFlags.clear();
    this.panels.forEach((p) => { if (p.chart) p.setMarkersOnly(); else p._updateMarkerTag(); });
    this.ctx.setTradeChip && this.ctx.setTradeChip(null);
    if (!silent) toast('已清除选股日/卖出日标记');
  }

  markersFor(panel) {
    const trade = this.trade;
    if (!trade || panel.state.code !== trade.code || !panel.bars || !panel.bars.length) return [];
    const out = [];
    const mk = (ymd, color, text, position) => {
      if (!ymd) return;
      const t = this.markerTime(panel.bars, panel.state.period, ymd);
      if (t == null) return;
      out.push({ time: t, position, color, shape: 'arrowDown', text });
    };
    mk(trade.t2, '#3b82f6', '选股日 T-2', 'aboveBar');
    mk(trade.t0, '#d62828', '卖出日 T-0', 'belowBar');
    return out;
  }

  markerTime(bars, period, ymd) {
    if (!ymd) return null;
    if (period === '1d') {
      const ts = dateToTs(ymd);
      for (const b of bars) if (b.time === ts) return b.time;
      return null;
    }
    for (const b of bars) if (barYmd(b.time) === ymd) return b.time;
    return null;
  }

  takeFocus(panel) {
    if (!this.trade || !this._focusFlags.has(panel.index)) return null;
    this._focusFlags.delete(panel.index);
    if (panel.state.code !== this.trade.code || !panel.bars.length) return null;
    const t = this.markerTime(panel.bars, panel.state.period, this.trade.t0);
    if (t == null) return null;
    let idx = panel.bars.findIndex((b) => b.time === t);
    if (idx < 0) return null;
    if (panel.state.period === '1d') return { center: idx, before: 22, after: 8 };
    return { center: idx, before: 70, after: 40 };
  }

  /** 面板点 [+] / 选股页加入 */
  addStock(stock) {
    const w = this.ctx.store.active();
    const visible = panelCount(w.layout);
    const isVisible = (i) => i < visible;
    let target = -1;
    for (let i = 0; i < visible; i++) {
      if (this.panels[i].state.code === stock.code) { target = i; break; }
    }
    if (target >= 0) {
      return { ok: true, already: true, panel: target + 1, workspace: w.name };
    }
    target = isVisible(this.activeIndex) ? this.activeIndex : 0;
    const p = this.panels[target];
    p.setState(Object.assign({}, p.state, { code: stock.code, name: stock.name || '' }));
    this.ctx.store.updatePanel(target, { code: stock.code, name: stock.name || '' });
    this.setActive(target);
    p.load();
    return { ok: true, already: false, panel: target + 1, workspace: w.name };
  }

  onPanelRange(source, range) {
    const w = this.ctx.store.active();
    if (!w.timeLink || this._syncGuard) return;
    if (source._suppressRange) return;
    const r = source.chart && source.chart.getVisibleTimeRange();
    if (!r || r.from == null || r.to == null) return;
    this._syncGuard = true;
    try {
      for (const p of this.panels) {
        if (p === source || p.el.hidden || !p.chart || !p.bars.length) continue;
        p.chart.setVisibleByTime(r.from, r.to);
      }
    } finally {
      setTimeout(() => { this._syncGuard = false; }, 40);
    }
  }

  onPanelCrosshair(source, bar) {
    if (this._crossGuard) return;
    source.updateReadout(bar);
    const w = this.ctx.store.active();
    if (!w.timeLink) return;
    this._crossGuard = true;
    try {
      for (const p of this.panels) {
        if (p === source || p.el.hidden || !p.chart || !p.bars.length) continue;
        if (bar) p.chart.setCrosshairByTime(bar.time);
        else p.chart.clearCrosshair();
      }
    } finally {
      setTimeout(() => { this._crossGuard = false; }, 0);
    }
  }

  fitActive() {
    const p = this.panels[this.activeIndex];
    if (p && p.chart) p.chart.fitContent();
  }

  cyclePeriod(delta) {
    const p = this.panels[this.activeIndex];
    if (!p) return;
    const list = AVAILABLE_PERIODS.map((x) => x.id);
    let idx = list.indexOf(p.state.period);
    if (idx < 0) idx = 0;
    idx = (idx + delta + list.length) % list.length;
    this.changePeriod(this.activeIndex, list[idx]);
  }
}
