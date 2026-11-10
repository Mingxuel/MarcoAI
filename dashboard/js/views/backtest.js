/* 策略回测页：策略/买入/卖出三选择 + 8 指标卡 + 资金 K 线 + 月/季/年 + 收益分布 */
import { h, clear, fmt, pct, n, toast } from '../util.js?v=20261106aa';
import { API } from '../api.js?v=20261106aa';
import { CapitalChart } from '../chart_adapter.js?v=20261106aa';
import { ChartDrawings } from '../chart_drawings.js?v=20261106aa';

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
async function fetchBplus(strategy, pickMode, sellMode = 'bplus') {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 120000);
  try {
    const apiMode = sellMode === '5m' ? 'legacy5m' : (sellMode === 'day' ? 'day' : 'bplus');
    const url = `/api/backtest/bplus?strategy=${encodeURIComponent(strategy)}&months=12&pick_mode=${encodeURIComponent(pickMode)}&sell_mode=${apiMode}`;
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
    this.sellHelpEl = h('div', { class: 'bt-sell-help', hidden: true });
    this.badgeEl = h('span', { class: 'chip dim bt-bplus-badge' }, 'B+ 卖法 · 2026 年起生效（此前回退现状）');
    this.root.appendChild(h('div', { class: 'view-pad' },
      h('div', { class: 'page-head' },
        h('div', { class: 'page-title' }, '策略回测'),
        h('div', { class: 'page-sub' }, '默认 B+ 新卖法（2026 起生效；此前回退现状） · 口径与离线看板一致'),
        this.badgeEl,
        h('div', { class: 'spacer' }),
        this.controlsEl),
      this.sellHelpEl,
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
    this.helpBtn = h('button', { class: 'btn btn-xs ghost bt-help-btn', title: '卖出方式详细说明', onclick: () => this._toggleSellHelp() }, '说明 ⓘ');
    this.controlsEl.appendChild(h('div', { class: 'ctl' }, h('span', {}, '卖出方式'), sellSel, this.helpBtn));
    this.controlsEl.appendChild(h('button', { class: 'btn btn-xs ghost', onclick: () => this.load(true) }, '刷新'));
  }

  _toggleSellHelp(force) {
    const show = force == null ? this.sellHelpEl.hidden : !!force;
    this.sellHelpEl.hidden = !show;
    if (this.helpBtn) this.helpBtn.classList.toggle('on', show);
    if (show) this._renderSellHelp();
  }

  _sellSampleRange() {
    const d = this.data || {};
    if (d.dateFrom && d.dateTo) return `${d.dateFrom} ~ ${d.dateTo}`;
    const bars = d.capitalKline || [];
    if (bars.length) return `${String(bars[0].time).slice(0, 10)} ~ ${String(bars[bars.length - 1].time).slice(0, 10)}`;
    return '2026-01-09 ~ 2026-11-04（近 12 个月）';
  }

  _renderSellHelp() {
    if (!this.sellHelpEl) return;
    const cur = this.sellMode;
    const sec = (id, title, body) => h('div', { class: 'bt-help-sec' + (cur === id ? ' cur' : '') },
      h('div', { class: 'bt-help-h' }, title, cur === id ? h('span', { class: 'bt-help-cur' }, '当前') : null),
      h('div', { class: 'bt-help-b' }, ...body));
    const li = (t) => h('div', { class: 'bt-help-li' }, t);
    clear(this.sellHelpEl);
    this.sellHelpEl.appendChild(h('div', { class: 'bt-help-head' },
      h('span', {}, '卖出方式说明'),
      h('span', { class: 'hint' }, '口径：买入 T-1 收盘 · 卖出 T-0 · 单票满仓 · 日收益复利 · 毛收益未计费用'),
      h('span', { class: 'spacer' }),
      h('span', { class: 'hint' }, `样本区间 ${this._sellSampleRange()}`),
      h('button', { class: 'btn btn-xs ghost', onclick: () => this._toggleSellHelp(false) }, '关闭 ✕')));
    const grid = h('div', { class: 'bt-help-grid' },
      sec('5m', '5 分钟卖出（5m）· 现状卖法', [
        li('买入：T-1 收盘价（原始价）。'),
        li('T-0 按 5m K 线顺序：① 先触及涨停价 → 按涨停价卖；② 跌破 成本×0.95 → 按该 bar 收盘止损；③ 都未触发 → 14:55 那根收盘卖出。'),
        li('使用 vipdoc lc5 原始价，含盘中细节；不接交易、仅回测。'),
      ]),
      sec('day', '日线卖出（day）', [
        li('买入：T-1 收盘价。'),
        li('T-0 用日线 OHLC 近似：开盘跌破止损按开盘、最低跌破按止损价、最高触涨停按涨停价，否则按收盘价卖出。'),
        li('没有盘中 5m 细节，适合长周期/缺 5m 数据的粗回测。'),
      ]),
      sec('bplus', 'B+ 新卖法（推荐）', [
        li('环境 S6（T-1）：沪深300>MA60 +1、创业板指>MA60 +1、中证银行≤MA60 +1 → score=0~3；MA60=日线K线（vipdoc lday 原始日线）。任一数据不足=不可用（回退满仓·14:55）。'),
        li('T-0 满仓：① 涨停价优先卖出；② -5% 止损；③ score≥2 → 持有到 14:55；④ score=1 → 10:00 看沪深300+创业板指红盘宽度（10:00价>前一日日线收盘，不含银行）：2/2 持有，否则 10:00 卖；⑤ score=0 → 10:00 卖出。'),
        li('数据限制：INDEX_5M 自 2026-01-05 起；此前区间回退 5m 卖法，页头标注（回退 43 天 · 生效自 2026-04-09）。'),
        li('毛收益，未计手续费/滑点；同 bar 双触发按止损（保守）。'),
      ]));
    this.sellHelpEl.appendChild(grid);
    this.sellHelpEl.appendChild(h('div', { class: 'bt-help-foot' },
      '说明：以上为回测口径，不代表实盘收益；切换上方「卖出方式」后本面板高亮会自动更新。'));
  }

  async load(refresh = false) {
    if (this._loading) return;
    this._loading = true;
    clear(this.bodyEl);
    this.bodyEl.appendChild(h('div', { class: 'loading-box' }, h('div', { class: 'spin' }), h('span', {}, '回测数据加载中…')));
    try {
      const data = await fetchBplus(this.strategy, this.pickMode, this.sellMode);
      this.data = data;
      this._renderBadge(data);
      if (this.sellHelpEl && !this.sellHelpEl.hidden) this._renderSellHelp();
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
      this.badgeEl.textContent = `B+ S6 · 满仓 · 日线MA60评分 + 宽度2${fb != null ? ` · 回退 ${fb} 天` : ''}${start}`;
      this.badgeEl.title = (data && data.fallbackNote) || '环境=沪深300上+创业板指上+中证银行下；2026 年前 / 数据不足回退 5m 卖法';
    } else if (this.sellMode === '5m') {
      this.badgeEl.className = 'chip ok bt-bplus-badge';
      this.badgeEl.textContent = '原始价 5m 卖法（毛收益）';
      this.badgeEl.title = 'vipdoc lc5 原始价：涨停优先→-5%止损→14:55；与 B+ 同数据源';
    } else {
      this.badgeEl.className = 'chip ok bt-bplus-badge';
      this.badgeEl.textContent = '原始价日线卖法（毛收益）';
      this.badgeEl.title = 'vipdoc lday 原始日线 OHLC：涨停优先→止损→收盘；与 B+ 同数据源';
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
    if (this.candleChart) { try { this.candleChart.remove(); } catch (e) { /* ignore */ } this.candleChart = null; }
    if (this.sentChart) { try { this.sentChart.remove(); } catch (e) { /* ignore */ } this.sentChart = null; }
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

    // —— 右列：资金蜡烛主图 + 情绪副图（同一卡片） ——
    this.candleHost = h('div', { class: 'bt-candle-chart' });
    this.candleTip = h('div', { class: 'bt-line-tip', hidden: true });
    this.candleLegend = h('div', { class: 'bt-line-legend' });
    this.sentLegend = h('div', { class: 'bt-line-legend bt-sent-legend' });
    this.sentHost = h('div', { class: 'bt-sent-chart' });
    this.sentTip = h('div', { class: 'bt-line-tip', hidden: true });
    this.comboPanel = h('div', { class: 'panel-block bt-candle-panel bt-combo-panel' },
      h('div', { class: 'panel-head' }, '资金曲线蜡烛 × 情绪指数副图',
        h('span', { class: 'hint' }, '主图 open=前日权益/5m路径 high-low · 副图三指数情绪 · MA可勾选 · 时间轴联动')),
      h('div', { class: 'panel-body bt-combo-body' },
        this.candleLegend, this.candleHost, this.candleTip,
        h('div', { class: 'bt-sub-sep' }, '情绪指数（0 轴）'),
        this.sentLegend, this.sentHost, this.sentTip));

    const leftCol = h('div', { class: 'bt-col bt-col-left' }, metrics, retPanel, capPanel);
    const rightCol = h('div', { class: 'bt-col bt-col-right' }, this.comboPanel);
    this.bodyEl.appendChild(h('div', { class: 'bt-grid bt-layout2' }, leftCol, rightCol));
    this.bodyEl.appendChild(distPanel);

    await this._renderLineChart();
    this._bindChartPan(this.capHost, this.capChart);
    this._renderCandleChart();
    this._renderSentimentChart();
    this._bindChartPan(this.candleHost, this.candleChart);
    this._bindChartPan(this.sentHost, this.sentChart);
    this._linkChartRanges();
    setTimeout(() => this._linkChartRanges(), 80);
  }

  _capCandleMaKey() { return 'marco.backtest.capitalCandles.ma'; }

  _renderCandleChart() {
    const LWg = window.LightweightCharts;
    if (!this.candleHost) return;
    if (!LWg) { clear(this.candleHost); this.candleHost.appendChild(h('div', { class: 'empty-box' }, '图表库未加载')); return; }
    const rows = (this.data && this.data.capitalCandles) || [];
    if (!rows.length) { clear(this.candleHost); this.candleHost.appendChild(h('div', { class: 'empty-box' }, '无资金蜡烛数据')); return; }
    const base = Number(rows[0].open) || 100000;
    const data = rows.map((c) => ({
      time: String(c.time),
      open: (Number(c.open) / base - 1) * 100,
      high: (Number(c.high) / base - 1) * 100,
      low: (Number(c.low) / base - 1) * 100,
      close: (Number(c.close) / base - 1) * 100,
      raw: c,
    }));
    clear(this.candleHost);
    const chart = LWg.createChart(this.candleHost, {
      autoSize: true, layout: { background: { color: 'transparent' }, textColor: '#8b9bb0' },
      grid: { vertLines: { color: '#1a2635' }, horzLines: { color: '#1a2635' } },
      rightPriceScale: { borderColor: '#24354a', scaleMargins: { top: 0.08, bottom: 0.08 } },
      timeScale: { borderColor: '#24354a', timeVisible: false },
      handleScale: { axisPressedMouseMove: { time: false, price: false } },
      handleScroll: { pressedMouseMove: false, mouseWheel: true, horzTouchDrag: false, vertTouchDrag: false },
      crosshair: {
        mode: LWg.CrosshairMode ? LWg.CrosshairMode.Normal : 0,
        vertLine: { visible: true, color: '#94a3b8', width: 1, style: 2, labelVisible: true },
        horzLine: { visible: true, color: '#94a3b8', width: 1, style: 2, labelVisible: true },
      },
      localization: { priceFormatter: (v) => `${v >= 0 ? '+' : ''}${v.toFixed(1)}%` },
    });
    this.candleChart = chart;
    const series = chart.addSeries(LWg.CandlestickSeries, {
      upColor: '#ef4444', downColor: '#1d9bf0', borderUpColor: '#ef4444', borderDownColor: '#1d9bf0',
      wickUpColor: '#ef4444', wickDownColor: '#1d9bf0', priceLineVisible: false, lastValueVisible: false,
    });
    series.setData(data.map(({ raw, ...x }) => x));
    this.candleSeries = series;
    // MA 勾选（5/10/20/60，默认 5+60，独立 localStorage）
    let maSel = [5, 60];
    try {
      const raw = JSON.parse(localStorage.getItem(this._capCandleMaKey()) || 'null');
      if (Array.isArray(raw)) maSel = raw.filter((x) => [5, 10, 20, 30, 60, 120].includes(x));
    } catch (e) { /* ignore */ }
    const maColors = { 5: '#f5c518', 10: '#f472b6', 20: '#60a5fa', 30: '#34d399', 60: '#c084fc', 120: '#fb923c' };
    const maSeries = {};
    clear(this.candleLegend);
    const redrawMa = () => {
      for (const [p, s] of Object.entries(maSeries)) { try { chart.removeSeries(s); } catch (e) { /* ignore */ } delete maSeries[p]; }
      for (const p of maSel) {
        const s = chart.addSeries(LWg.LineSeries, { color: maColors[p], lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
        const out = [];
        for (let i = 0; i < data.length; i++) {
          if (i < p - 1) continue;
          let sum = 0;
          for (let j = i - p + 1; j <= i; j++) sum += data[j].close;
          out.push({ time: data[i].time, value: sum / p });
        }
        s.setData(out);
        maSeries[p] = s;
      }
    };
    for (const p of [5, 10, 20, 30, 60, 120]) {
      const cb = h('input', { type: 'checkbox', checked: maSel.includes(p) });
      cb.addEventListener('change', () => {
        if (cb.checked) { if (!maSel.includes(p)) maSel.push(p); }
        else maSel = maSel.filter((x) => x !== p);
        maSel.sort((a, b) => a - b);
        try { localStorage.setItem(this._capCandleMaKey(), JSON.stringify(maSel)); } catch (e) { /* ignore */ }
        redrawMa();
      });
      this.candleLegend.appendChild(h('label', { class: 'bt-legend-item' }, cb,
        h('span', { class: 'dot', style: `background:${maColors[p]}` }), `MA${p}`));
    }
    redrawMa();
    // 画线工具（独立 localStorage：backtest.capitalCandles）
    if (!this.candleDraw) {
      this.candleDraw = new ChartDrawings(this.candleHost, { pageKey: 'backtest', code: 'capitalCandles', period: '1d', storageKey: 'backtest.capitalCandles' });
      const comboBody = (this.comboPanel || this.candlePanel).querySelector('.panel-body');
      comboBody.insertBefore(this.candleDraw.toolbarEl, this.candleLegend);
      this.candleHost.appendChild(this.candleDraw.propsEl);
    }
    this.candleDraw.setBars(data);
    this.candleDraw.setChart(chart, series);
    this.candleDraw.setContext({ pageKey: 'backtest', code: 'capitalCandles', period: '1d' });
    chart.subscribeCrosshairMove((param) => {
      if (!param || !param.time) { this.candleTip.hidden = true; return; }
      const row = rows.find((c) => String(c.time) === String(param.time));
      if (!row) { this.candleTip.hidden = true; return; }
      this.candleTip.innerHTML = `<div class="t">${row.time}</div>`
        + `<div class="r"><span>权益 O ${Number(row.open).toFixed(2)}</span><span>H ${Number(row.high).toFixed(2)}</span>`
        + `<span>L ${Number(row.low).toFixed(2)}</span><span>C ${Number(row.close).toFixed(2)}</span></div>`;
      this.candleTip.hidden = false;
    });
    chart.timeScale().fitContent();
    try { const lr = chart.timeScale().getVisibleLogicalRange(); if (lr) chart.timeScale().setVisibleLogicalRange({ from: lr.from - 12, to: lr.to + 12 }); } catch (e) { /* ignore */ }
  }

  _bindChartPan(host, chart) {
    if (!host || !chart || host.dataset.panBound) return;
    host.dataset.panBound = '1';
    const ts = chart.timeScale();
    let pan = null;
    host.addEventListener('pointerdown', (ev) => {
      if (ev.button !== 0) return;
      const tg = ev.target;
      if (tg && tg.closest && tg.closest('.cd-toolbar, .cd-props, .bt-line-legend, .bt-sub-sep')) return;
      const r = host.getBoundingClientRect();
      if (ev.clientX > r.right - 70 || ev.clientY > r.bottom - 40) return;
      const lr = ts.getVisibleLogicalRange();
      if (!lr) return;
      pan = { x: ev.clientX, range: lr };
      host.classList.add('bt-panning');
      try { host.setPointerCapture(ev.pointerId); } catch (e) { /* ignore */ }
    });
    host.addEventListener('pointermove', (ev) => {
      if (!pan) return;
      const r = host.getBoundingClientRect();
      const w = Math.max(1, r.width);
      const span = pan.range.to - pan.range.from;
      const shift = ((ev.clientX - pan.x) / w) * span;
      const n = ((this.data && this.data.capitalCandles) || []).length;
      const minL = -12, maxL = n > 0 ? n + 11 : 1e9;
      let from = pan.range.from - shift, to = pan.range.to - shift;
      if (from < minL) { to += minL - from; from = minL; }
      if (to > maxL) { from -= to - maxL; to = maxL; }
      try { ts.setVisibleLogicalRange({ from, to }); } catch (e) { /* ignore */ }
    });
    const end = () => { if (!pan) return; pan = null; host.classList.remove('bt-panning'); };
    host.addEventListener('pointerup', end);
    host.addEventListener('pointercancel', end);
  }

  _linkChartRanges() {
    const a = this.candleChart, b = this.sentChart;
    if (!a || !b || this._rangesLinked) return;
    this._rangesLinked = true;
    let syncing = false;
    let syncTimer = null;
    const bindRange = (src, dst) => {
      try {
        src.timeScale().subscribeVisibleLogicalRangeChange((range) => {
          if (!range || syncing) return;
          // 拖拽过程中只记录，松手/停止后再同步，避免两端在边缘互相夹逼造成“放大”
          clearTimeout(syncTimer);
          syncTimer = setTimeout(() => {
            if (syncing) return;
            const cur = src.timeScale().getVisibleLogicalRange();
            if (!cur) return;
            syncing = true;
            try { dst.timeScale().setVisibleLogicalRange(cur); } catch (e) { /* ignore */ } finally { syncing = false; }
          }, 180);
        });
      } catch (e) { /* ignore */ }
    };
    bindRange(a, b);
    bindRange(b, a);
    // 十字光标垂直日期联动（主/副图同日期竖线）
    let crossSyncing = false;
    const bindCross = (src, dst, dstSeries, priceAt) => {
      try {
        src.subscribeCrosshairMove((param) => {
          if (crossSyncing) return;
          if (!param || !param.time) {
            try { dst.clearCrosshairPosition(); } catch (e) { /* ignore */ }
            return;
          }
          crossSyncing = true;
          try {
            const price = priceAt(param.time);
            if (price != null) dst.setCrosshairPosition(price, param.time, dstSeries);
            else try { dst.clearCrosshairPosition(); } catch (e) { /* ignore */ }
          } catch (e) { /* ignore */ } finally { crossSyncing = false; }
        });
      } catch (e) { /* ignore */ }
    };
    const candleRows = (this.data && this.data.capitalCandles) || [];
    const sentRows = (this.data && this.data.sentiment) || [];
    const candlePrice = (time) => {
      const r = candleRows.find((x) => String(x.time) === String(time));
      return r ? Number(r.close) : null;
    };
    const sentPrice = (time) => {
      const r = sentRows.find((x) => String(x.time) === String(time));
      return r && r.value != null ? Number(r.value) : 0;
    };
    bindCross(a, b, this.sentSeries, sentPrice);
    bindCross(b, a, this.candleSeries, candlePrice);
    // 初始加左右空档，避免在右端拖拽被库夹逼成“放大”；两图同一 logical 区间
    try {
      const n = ((this.data && this.data.capitalCandles) || []).length;
      if (n > 0) {
        a.timeScale().setVisibleLogicalRange({ from: -12, to: n + 11 });
        b.timeScale().setVisibleLogicalRange({ from: -12, to: n + 11 });
      }
    } catch (e) { /* ignore */ }
  }

  _renderSentimentChart() {
    const LWg = window.LightweightCharts;
    if (!this.sentHost) return;
    if (!LWg) { clear(this.sentHost); this.sentHost.appendChild(h('div', { class: 'empty-box' }, '图表库未加载')); return; }
    const rows = (this.data && this.data.sentiment) || [];
    const valid = rows.filter((x) => x.value != null);
    clear(this.sentHost);
    if (!valid.length) { this.sentHost.appendChild(h('div', { class: 'empty-box' }, '情绪数据不足（MA60 未成形）')); return; }
    const chart = LWg.createChart(this.sentHost, {
      autoSize: true, layout: { background: { color: 'transparent' }, textColor: '#8b9bb0' },
      grid: { vertLines: { color: '#1a2635' }, horzLines: { color: '#1a2635' } },
      rightPriceScale: { borderColor: '#24354a', scaleMargins: { top: 0.1, bottom: 0.1 } },
      timeScale: { borderColor: '#24354a', timeVisible: false },
      handleScale: { axisPressedMouseMove: { time: false, price: false } },
      handleScroll: { pressedMouseMove: false, mouseWheel: true, horzTouchDrag: false, vertTouchDrag: false },
      crosshair: {
        mode: LWg.CrosshairMode ? LWg.CrosshairMode.Normal : 0,
        vertLine: { visible: true, color: '#94a3b8', width: 1, style: 2, labelVisible: true },
        horzLine: { visible: true, color: '#94a3b8', width: 1, style: 2, labelVisible: true },
      },
    });
    this.sentChart = chart;
    const baseOpts = {
      baseValue: { type: 'price', price: 0 },
      topLineColor: '#ef4444', bottomLineColor: '#22c55e',
      topFillColor1: 'rgba(239,68,68,0.22)', topFillColor2: 'rgba(239,68,68,0.03)',
      bottomFillColor1: 'rgba(34,197,94,0.03)', bottomFillColor2: 'rgba(34,197,94,0.22)',
      lineWidth: 2, priceLineVisible: false, lastValueVisible: true,
    };
    let series;
    if (LWg.BaselineSeries) series = chart.addSeries(LWg.BaselineSeries, baseOpts);
    else series = chart.addSeries(LWg.LineSeries, { color: '#22c55e', lineWidth: 2, priceLineVisible: false });
    series.setData(rows.map((x) => (x.value == null ? { time: x.time } : { time: x.time, value: x.value })));
    this.sentSeries = series;
    try {
      series.createPriceLine({ price: 0, color: '#64748b', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: '0' });
    } catch (e) { /* ignore */ }
    clear(this.sentLegend);
    this.sentLegend.appendChild(h('span', { class: 'bt-legend-item' }, h('span', { class: 'dot', style: 'background:#ef4444' }), '情绪（正/红）'));
    this.sentLegend.appendChild(h('span', { class: 'bt-legend-item' }, h('span', { class: 'dot', style: 'background:#22c55e' }), '情绪（负/绿）'));
    // 情绪 MA 5/10/20/30/60/120（默认 5+60）
    const sentMaKey = 'marco.backtest.sentiment.ma';
    let sentMaSel = [5, 60];
    try {
      const raw = JSON.parse(localStorage.getItem(sentMaKey) || 'null');
      if (Array.isArray(raw)) sentMaSel = raw.filter((x) => [5, 10, 20, 30, 60, 120].includes(x));
    } catch (e) { /* ignore */ }
    const sentMaColors = { 5: '#f5c518', 10: '#f472b6', 20: '#60a5fa', 30: '#34d399', 60: '#c084fc', 120: '#fb923c' };
    const sentMaSeries = {};
    const sentVals = valid.map((x) => x.value);
    const calcMa = (i, p) => {
      if (i < p - 1) return null;
      let sum = 0;
      for (let j = i - p + 1; j <= i; j++) {
        if (sentVals[j] == null) return null;
        sum += sentVals[j];
      }
      return sum / p;
    };
    const redrawSentMa = () => {
      for (const [p, sr] of Object.entries(sentMaSeries)) { try { chart.removeSeries(sr); } catch (e) { /* ignore */ } delete sentMaSeries[p]; }
      for (const p of sentMaSel) {
        const sr = chart.addSeries(LWg.LineSeries, { color: sentMaColors[p], lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
        sr.setData(valid.map((x, i) => ({ time: x.time, value: calcMa(i, p) })).filter((x) => x.value != null));
        sentMaSeries[p] = sr;
      }
    };
    for (const p of [5, 10, 20, 30, 60, 120]) {
      const cb = h('input', { type: 'checkbox', checked: sentMaSel.includes(p) });
      cb.addEventListener('change', () => {
        if (cb.checked) { if (!sentMaSel.includes(p)) sentMaSel.push(p); }
        else sentMaSel = sentMaSel.filter((x) => x !== p);
        sentMaSel.sort((a, b) => a - b);
        try { localStorage.setItem(sentMaKey, JSON.stringify(sentMaSel)); } catch (e) { /* ignore */ }
        redrawSentMa();
      });
      this.sentLegend.appendChild(h('label', { class: 'bt-legend-item' }, cb,
        h('span', { class: 'dot', style: `background:${sentMaColors[p]}` }), `MA${p}`));
    }
    redrawSentMa();
    chart.subscribeCrosshairMove((param) => {
      if (!param || !param.time) { this.sentTip.hidden = true; return; }
      const idx = valid.findIndex((x) => String(x.time) === String(param.time));
      if (idx < 0) { this.sentTip.hidden = true; return; }
      const row = valid[idx];
      const fmtv = (v) => v == null ? '—' : `${v >= 0 ? '+' : ''}${Number(v).toFixed(2)}`;
      const maTxt = sentMaSel.map((p) => {
        const mv = calcMa(idx, p);
        return `MA${p} ${mv == null ? '—' : mv.toFixed(2)}`;
      }).join(' · ');
      this.sentTip.innerHTML = `<div class="t">${row.time}</div>`
        + `<div class="r"><span>情绪</span><span>${fmtv(row.value)}</span></div>`
        + `<div class="r"><span>沪深300</span><span>${fmtv(row.h300)}</span></div>`
        + `<div class="r"><span>创业板指</span><span>${fmtv(row.cyb)}</span></div>`
        + `<div class="r"><span>银行(反向)</span><span>${fmtv(row.bank)}</span></div>`
        + (maTxt ? `<div class="r ma">${maTxt}</div>` : '');
      this.sentTip.hidden = false;
    });
    chart.timeScale().fitContent();
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

  _capitalPoints(dates) {
    const bars = (this.data && this.data.capitalKline) || [];
    if (!bars.length) return { points: [], raw: new Map() };
    const base = Number(bars[0].pre_close || bars[0].open || bars[0].close || 100000) || 100000;
    const byDate = new Map();
    for (const b of bars) {
      const c = Number(b.close);
      if (!Number.isFinite(c) || !b.time) continue;
      byDate.set(String(b.time).slice(0, 10), c);
    }
    const raw = new Map();
    const points = [];
    let lastNorm = 0;
    let firstDone = false;
    for (const date of (dates || [])) {
      let val = lastNorm;
      if (byDate.has(date)) {
        val = (byDate.get(date) / base - 1) * 100;
        firstDone = true;
      }
      // 起点显示 0%，之后含空仓日沿用前值
      points.push({ time: date, value: firstDone && points.length === 0 ? 0 : val });
      raw.set(date, byDate.has(date) ? byDate.get(date) : (raw.size ? [...raw.values()].slice(-1)[0] : base));
      lastNorm = val;
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
    const start = String(bars[0].time || '').slice(0, 10);
    const end = String(bars[bars.length - 1].time || '').slice(0, 10);
    let dates = (this.data.tradingDates || []).filter((d) => d >= start && d <= end);
    if (!dates.length) {
      const set = new Set(bars.map((b) => String(b.time).slice(0, 10)));
      for (const d of set) dates.push(d);
      dates.sort();
    }
    const series = [];
    const cap = this._capitalPoints(dates);
    series.push({ id: 'capital', name: '资金曲线', color: '#4ade80', points: cap.points, raw: cap.raw, isCapital: true });

    const codes = this.indexCodes.slice();
    const idxRes = await fetchIndexSeries(codes, start, end);
    for (const item of (idxRes.indices || [])) {
      const opt = INDEX_OPTIONS.find((o) => o.code === item.code);
      const pts = (item.points || []).filter((x) => x.date >= start && x.date <= end);
      if (!pts.length) continue;
      const base = Number(pts[0].value) || 1;
      const raw = new Map();
      for (const x of pts) raw.set(String(x.date), Number(x.value));
      const points = dates.map((d) => ({ time: d, value: raw.has(d) ? (raw.get(d) / base - 1) * 100 : null })).filter((x) => x.value != null);
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
      handleScale: { axisPressedMouseMove: { time: false, price: false } },
      handleScroll: { pressedMouseMove: false, mouseWheel: true, horzTouchDrag: false, vertTouchDrag: false },
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
