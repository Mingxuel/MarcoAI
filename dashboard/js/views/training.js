/* 选股训练 v2：按日期分组、列出每日全部候选、多选后等权计算。 */
import { h, clear, fmt, pct, toast } from '../util.js?v=20261106aa';
import { API } from '../api.js?v=20261106aa';
import { WorkspaceView } from './workspace.js?v=20261106aa';

const INPUT_KEY = 'marco.training.inputs';
const SELECT_KEY = 'marco.training.selected';

async function fetchJson(url, opts) {
  const res = await fetch(url, { cache: 'no-store', ...opts });
  const data = await res.json();
  if (!res.ok || data.ok === false) throw new Error((data && (data.error || data.message)) || `HTTP ${res.status}`);
  return data;
}
function loadInputs() { try { return JSON.parse(localStorage.getItem(INPUT_KEY) || '{}') || {}; } catch (e) { return {}; } }
function saveInputs(v) { try { localStorage.setItem(INPUT_KEY, JSON.stringify(v)); } catch (e) { /* ignore */ } }
function loadSelected() { try { return new Set(JSON.parse(localStorage.getItem(SELECT_KEY) || '[]')); } catch (e) { return new Set(); } }
function saveSelected(set) { try { localStorage.setItem(SELECT_KEY, JSON.stringify([...set])); } catch (e) { /* ignore */ } }

export class TrainingView {
  constructor(root, ctx) {
    this.root = root; this.ctx = ctx;
    this.month = null; this.groups = []; this.items = [];
    this.results = {}; this.summary = null; this.daily = [];
    this.inputs = loadInputs();
    this.selected = loadSelected();
    this.chart = null; this._mounted = false; this.leftWorkspace = null;
  }

  mount() {
    if (this._mounted) return;
    this._mounted = true;
    this._build();
    this._loadMonths();
  }

  _build() {
    clear(this.root);
    this.monthSel = h('select', { class: 'sel', onchange: () => this._loadMonth(this.monthSel.value) });
    this.summaryEl = h('div', { class: 'tr-summary' });
    this.dailyEl = h('div', { class: 'tr-daily' });
    this.chartHost = h('div', { class: 'tr-left-ws' });
    this.chartTitle = h('span', { class: 'tr-chart-title' }, 'K 线（截止 T-1）');
    this.tableEl = h('div', { class: 'tr-table-wrap' });
    this.pageEl = h('div', { class: 'view-pad tr-page' },
      h('div', { class: 'page-head' },
        h('div', {}, h('div', { class: 'page-title' }, '选股训练'),
          h('div', { class: 'page-sub' }, '按日期分组 · 每日全部候选 · 勾选后等权计算训练 vs B+ 原策略 · K 线只看 T-1')),
        h('div', { class: 'spacer' }),
        h('div', { class: 'tr-controls' },
          h('span', { class: 'tool-label' }, '月份'), this.monthSel,
          h('button', { class: 'btn btn-primary btn-xs', onclick: () => this._calc() }, '计算勾选'),
          h('button', { class: 'btn btn-xs ghost', onclick: () => this._clear() }, '清空数据'))),
      this.summaryEl, this.dailyEl,
      h('div', { class: 'tr-grid' },
        h('div', { class: 'panel-block tr-chart-panel' },
          h('div', { class: 'panel-head' }, 'K 线（与策略选股同组件）', h('span', { class: 'hint' }, this.chartTitle)),
          h('div', { class: 'panel-body tr-left-body' }, this.chartHost)),
        h('div', { class: 'panel-block tr-list-panel' },
          h('div', { class: 'panel-head' }, '每日候选与训练', h('span', { class: 'hint' }, '勾选参与汇总 · 点击行看 T-1 前 K 线 · 留空=不设')),
          h('div', { class: 'panel-body' }, this.tableEl))));
    this.root.appendChild(this.pageEl);
    // 复用策略选股页左侧同一套 WorkspaceView（图表/布局/均线/配色/周期切换）
    this.leftWorkspace = new WorkspaceView(this.chartHost, this.ctx);
    this.leftWorkspace.pageKey = 'training';
    this.leftWorkspace.hideLastPriceLine = true;
    this.leftWorkspace.mount();
  }

  async _loadMonths() {
    try {
      const d = await fetchJson('/api/training/months');
      clear(this.monthSel);
      for (const m of d.months || []) this.monthSel.appendChild(h('option', { value: m }, `${m.slice(0, 4)}-${m.slice(4, 6)}`));
      const months = d.months || [];
      const m = d.latest || months[0];
      if (!m) { this._renderEmpty('无可用月份'); return; }
      this.monthSel.value = m;
      await this._loadMonth(m);
      if (this.groups.length < 5 && months.length > 1) {
        const prev = months[months.length - 2];
        this.monthSel.value = prev;
        await this._loadMonth(prev);
      }
    } catch (e) {
      this._renderEmpty('月份加载失败：' + ((e && e.message) || e));
    }
  }

  async _loadMonth(month) {
    this.month = month;
    this.results = {}; this.summary = null; this.daily = [];
    this._renderSummary();
    try {
      const d = await fetchJson(`/api/training/list?month=${encodeURIComponent(month)}`);
      this.groups = d.groups || [];
      this.items = d.items || [];
      // 默认全不选：打开页面/切换月份时清空勾选；localStorage 只记录用户主动勾选
      this.selected = new Set();
      this._renderTable();
      if (this.items.length) this._showChart(this.items[0]);
    } catch (e) {
      this._renderEmpty('名单加载失败：' + ((e && e.message) || e));
    }
  }

  _key(it) { return `${it.date}_${it.code}`; }

  _renderSummary() {
    clear(this.summaryEl);
    clear(this.dailyEl);
    if (!this.summary) {
      this.summaryEl.appendChild(h('div', { class: 'tr-sum-empty' }, '勾选候选后点「计算勾选」；可填写止盈/止损，未勾选行不参与汇总'));
      return;
    }
    const s = this.summary;
    const sign = (v) => (v == null ? '—' : (v > 0 ? '+' : '') + fmt(v, 2) + '%');
    const card = (label, value, cls) => h('div', { class: 'tr-sum-card' }, h('div', { class: 'k' }, label), h('div', { class: 'v ' + (cls || '') }, value));
    const avgText = `训练 ${sign(s.trainAvgPnlPct)} / 原 ${sign(s.originalAvgPnlPct)}`;
    const winText = `训练 ${s.trainWinRate == null ? '—' : fmt(s.trainWinRate, 1) + '%'} / 原 ${s.originalWinRate == null ? '—' : fmt(s.originalWinRate, 1) + '%'}`;
    this.summaryEl.appendChild(h('div', { class: 'tr-sum-cards' },
      card(`训练总收益（逐日复利 ${s.count} 只）`, sign(s.trainTotalPnlPct), s.trainTotalPnlPct > 0 ? 'up' : s.trainTotalPnlPct < 0 ? 'down' : ''),
      card('原策略总收益（逐日复利）', sign(s.originalTotalPnlPct), s.originalTotalPnlPct > 0 ? 'up' : s.originalTotalPnlPct < 0 ? 'down' : ''),
      card('差异（复利）', sign(s.diffPct), s.diffPct > 0 ? 'up' : s.diffPct < 0 ? 'down' : ''),
      card('单笔平均', avgText, ''),
      card('胜率', winText, 'dim')));
    if ((this.daily || []).length) {
      const rows = this.daily.map((d) => h('div', { class: 'tr-daily-row' },
        h('span', { class: 'd' }, d.dateLabel),
        h('span', { class: 'c' }, `${d.count} 只`),
        h('span', { class: 'v ' + (d.trainPnlPct > 0 ? 'up' : d.trainPnlPct < 0 ? 'down' : '') }, '训练 ' + sign(d.trainPnlPct)),
        h('span', { class: 'v ' + (d.originalPnlPct > 0 ? 'up' : d.originalPnlPct < 0 ? 'down' : '') }, '原 ' + sign(d.originalPnlPct)),
        h('span', { class: 'v ' + (d.diffPct > 0 ? 'up' : d.diffPct < 0 ? 'down' : '') }, '差 ' + sign(d.diffPct))));
      this.dailyEl.appendChild(h('div', { class: 'tr-daily-title' }, '按日小计（选中票等权）'));
      this.dailyEl.appendChild(h('div', { class: 'tr-daily-list' }, ...rows));
    }
  }

  _renderEmpty(msg) {
    clear(this.tableEl);
    this.tableEl.appendChild(h('div', { class: 'empty-box' }, msg));
  }

  _colgroup() {
    return h('colgroup', {},
      h('col', { style: 'width:34px' }), h('col', { style: 'width:92px' }), h('col', { style: 'width:84px' }),
      h('col', { style: 'width:78px' }), h('col', { style: 'width:90px' }), h('col', { style: 'width:90px' }),
      h('col', {}), h('col', { style: 'width:84px' }));
  }

  _renderTable() {
    clear(this.tableEl);
    if (!this.groups.length) { this.tableEl.appendChild(h('div', { class: 'empty-box' }, '该月无 TPO_M5 候选')); return; }
    const tb = h('tbody', {});
    for (const g of this.groups) {
      const keys = g.candidates.map((it) => this._key(it));
      const selCount = keys.filter((k) => this.selected.has(k)).length;
      const groupCb = h('input', { type: 'checkbox', checked: selCount === keys.length });
      groupCb.indeterminate = selCount > 0 && selCount < keys.length;
      groupCb.addEventListener('click', (ev) => {
        ev.stopPropagation();
        const all = selCount === keys.length;
        for (const k of keys) { if (all) this.selected.delete(k); else this.selected.add(k); }
        saveSelected(this.selected);
        this._renderTable();
      });
      tb.appendChild(h('tr', { class: 'tr-group' },
        h('td', {}, groupCb),
        h('td', { colspan: 7 }, `${g.dateLabel} · ${g.count} 只候选 · 全选（已选 ${selCount}/${g.count}）`)));
      for (const it of g.candidates) {
        const key = this._key(it);
        const inp = this.inputs[key] || {};
        const res = this.results[key] || {};
        const rowCb = h('input', { type: 'checkbox', checked: this.selected.has(key) });
        rowCb.addEventListener('click', (ev) => {
          ev.stopPropagation();
          if (rowCb.checked) this.selected.add(key); else this.selected.delete(key);
          saveSelected(this.selected);
          this._renderTable();
        });
        const tpInput = h('input', { class: 'input tr-in', type: 'number', step: '0.01', placeholder: '止盈价', value: inp.tp == null ? '' : inp.tp });
        tpInput.addEventListener('change', () => this._saveInput(key, 'tp', tpInput.value));
        tpInput.addEventListener('click', (ev) => ev.stopPropagation());
        const slInput = h('input', { class: 'input tr-in', type: 'number', step: '0.01', placeholder: '止损价', value: inp.sl == null ? '' : inp.sl });
        slInput.addEventListener('change', () => this._saveInput(key, 'sl', slInput.value));
        slInput.addEventListener('click', (ev) => ev.stopPropagation());
        const tr = h('tr', { class: 'tr-row' + (res.trainPnlPct != null ? ' done' : '') + (this.selected.has(key) ? '' : ' unselected') },
          h('td', {}, rowCb),
          h('td', { class: 'l code' }, it.code),
          h('td', { class: 'l name' }, it.name || '—'),
          h('td', { class: 'num' }, it.buy == null ? '—' : fmt(it.buy, 2)),
          h('td', { class: 'num' }, tpInput),
          h('td', { class: 'num' }, slInput),
          h('td', { class: 'l tr-reason', title: res.trainReason || '' }, res.trainReason || '—'),
          h('td', { class: 'num ' + (res.trainPnlPct > 0 ? 'up' : res.trainPnlPct < 0 ? 'down' : '') },
            res.trainPnlPct == null ? '—' : pct(res.trainPnlPct, 2) + '%'));
        tr.addEventListener('click', (ev) => {
          if (ev.target.tagName === 'INPUT') return;
          this._showChart(it);
        });
        tb.appendChild(tr);
      }
    }
    this.tableEl.appendChild(h('table', { class: 'tbl tr-tbl' },
      this._colgroup(),
      h('thead', {}, h('tr', {},
        h('th', {}), h('th', { class: 'l' }, '代码'), h('th', { class: 'l' }, '名称'),
        h('th', { class: 'num' }, '买入价'),
        h('th', { class: 'num' }, '训练止盈'), h('th', { class: 'num' }, '训练止损'),
        h('th', { class: 'l' }, '训练说明'), h('th', { class: 'num' }, '训练盈亏%'))),
      tb));
  }

  _saveInput(key, field, value) {
    const v = value === '' ? null : Number(value);
    if (!this.inputs[key]) this.inputs[key] = {};
    this.inputs[key][field] = (v != null && Number.isFinite(v)) ? v : null;
    saveInputs(this.inputs);
  }

  async _calc() {
    const items = [];
    for (const it of this.items) {
      if (!this.selected.has(this._key(it))) continue;
      const inp = this.inputs[this._key(it)] || {};
      items.push({ code: it.code, date: it.date, name: it.name, tp: inp.tp, sl: inp.sl });
    }
    if (!items.length) { toast('请先勾选要计算的候选', 'err'); return; }
    try {
      const d = await fetchJson('/api/training/calc', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ items, strategy: 'TPO_M5' }),
      });
      this.results = {};
      for (const r of d.rows || []) this.results[`${r.date}_${r.code}`] = r;
      this.summary = d.summary;
      this.daily = d.daily || [];
      this._renderSummary();
      this._renderTable();
      toast('计算完成：训练等权 ' + (d.summary && d.summary.trainTotalPnlPct != null ? fmt(d.summary.trainTotalPnlPct, 2) + '%' : '—'), 'ok', 1800);
    } catch (e) {
      toast('计算失败：' + ((e && e.message) || e), 'err', 3200);
    }
  }

  _clear() {
    this.inputs = {};
    saveInputs(this.inputs);
    this.selected = new Set();
    saveSelected(this.selected);
    this.results = {}; this.summary = null; this.daily = [];
    this._renderSummary();
    this._renderTable();
    toast('已清空训练输入与结果', 'ok', 1500);
  }

  async _showChart(it) {
    const ws = this.leftWorkspace;
    if (!ws) return;
    // D=T-0；接口按 T-1 结束日取约 10 日 5m / 250 根日线，cutoff 再兜底 < D
    ws.setEnd(it.t1 || null);
    ws.setCutoff(it.date);
    ws.trade = null;
    ws.ctx.setTradeChip && ws.ctx.setTradeChip(null);
    const w = ws.ctx.store.active();
    ws.panels.forEach((p, i) => {
      if (p.el.hidden) return;
      p.setState(Object.assign({}, p.state, { code: it.code, name: it.name || '' }));
      ws.ctx.store.updatePanel(i, { code: it.code, name: it.name || '' });
      p.load();
    });
    this.chartTitle.textContent = `截止 T-1（< ${it.dateLabel}）· ${it.code} ${it.name || ''}`;
  }
}