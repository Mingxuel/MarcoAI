/* 工作区状态（localStorage 持久化）：布局 + 每面板股票/周期/指标 + 联动开关 */

export const PERIODS = [
  { id: '1d', label: '日线 1d', available: true },
  { id: '5m', label: '5 分钟', available: true },
  { id: '15m', label: '15 分钟', available: true },
  { id: '30m', label: '30 分钟', available: true },
  { id: '60m', label: '60 分钟（v1.1）', available: false, note: 'P1-10 开放（服务端已支持重采样）' },
  { id: '1w', label: '周线（v1.1）', available: false, note: 'P1-10 开放（服务端已支持重采样）' },
  { id: '1mo', label: '月线（v1.1）', available: false, note: 'P1-10 开放（服务端已支持重采样）' },
];

export const AVAILABLE_PERIODS = PERIODS.filter((p) => p.available);

export const INDICATORS = [
  { id: 'MA', label: 'MA', desc: '主图 MA5/10/20' },
  { id: 'BOLL', label: 'BOLL', desc: '主图 布林(20,2)' },
  { id: 'VOL', label: 'VOL', desc: '副图 成交量' },
  { id: 'MACD', label: 'MACD', desc: '副图 12/26/9' },
  { id: 'KDJ', label: 'KDJ', desc: '副图 9,3,3' },
];

export const LAYOUTS = [
  { id: '1', label: '1 图', panels: 1 },
  { id: '2v', label: '2 图上下', panels: 2 },
  { id: '2h', label: '2 图左右', panels: 2 },
  { id: '4', label: '4 图', panels: 4 },
];

export function panelCount(layout) {
  const l = LAYOUTS.find((x) => x.id === layout);
  return l ? l.panels : 2;
}

const KEY = 'marco.dashboard.v1';
const VERSION = 1;

function newPanels(code, name) {
  return [
    { code, name, period: '1d', indicators: ['MA', 'VOL'] },
    { code, name, period: '5m', indicators: ['MA', 'VOL'] },
    { code, name, period: '1d', indicators: ['MA'] },
    { code, name, period: '5m', indicators: ['MA'] },
  ];
}

function presetWorkspaces(code, name) {
  const p = (over) => newPanels(code, name).map((x, i) => Object.assign({}, x, (over[i] || {})));
  return [
    {
      id: 'w-auction', name: '① 竞价盯盘', preset: true, layout: '2v',
      stockLink: true, timeLink: true,
      panels: p([
        { period: '1d', indicators: ['MA', 'VOL'] },
        { period: '5m', indicators: ['MA', 'VOL'] },
      ]),
    },
    {
      id: 'w-limit-up', name: '② 打板盯盘', preset: true, layout: '4',
      stockLink: false, timeLink: true,
      panels: p([
        { period: '5m', indicators: ['MA', 'VOL'] },
        { period: '15m', indicators: ['MACD'] },
        { period: '1d', indicators: ['BOLL', 'VOL'] },
        { period: '30m', indicators: ['KDJ'] },
      ]),
    },
    {
      id: 'w-review', name: '③ 复盘验证', preset: true, layout: '2h',
      stockLink: true, timeLink: true,
      panels: p([
        { period: '1d', indicators: ['MA', 'MACD'] },
        { period: '5m', indicators: ['MA', 'VOL'] },
      ]),
    },
  ];
}

function defaults(meta) {
  const code = (meta && meta.defaultSymbol && meta.defaultSymbol.code) || '600118.SH';
  const name = (meta && meta.defaultSymbol && meta.defaultSymbol.name) || '';
  const all = [
    {
      id: 'w-default', name: '默认工作区', preset: false, layout: '2v',
      stockLink: true, timeLink: true, panels: newPanels(code, name),
    },
    ...presetWorkspaces(code, name),
  ];
  return { version: VERSION, activeId: 'w-default', workspaces: all };
}

function normPanel(p, code, name) {
  return {
    code: (p && p.code) || code,
    name: (p && p.name) || name,
    period: (p && AVAILABLE_PERIODS.some((x) => x.id === p.period)) ? p.period : '1d',
    indicators: Array.isArray(p && p.indicators)
      ? p.indicators.filter((x) => INDICATORS.some((i) => i.id === x))
      : ['MA'],
  };
}

function normWorkspace(w, idx, code, name) {
  const layout = LAYOUTS.some((l) => l.id === w.layout) ? w.layout : '2v';
  const srcPanels = Array.isArray(w.panels) ? w.panels : [];
  const panels = [];
  for (let i = 0; i < 4; i++) panels.push(normPanel(srcPanels[i], code, name));
  return {
    id: String(w.id || 'w-' + idx + '-' + Date.now().toString(36)),
    name: String(w.name || `工作区 ${idx + 1}`).slice(0, 40),
    preset: !!w.preset,
    layout,
    stockLink: w.stockLink !== false,
    timeLink: w.timeLink !== false,
    panels,
  };
}

export class Store {
  constructor(meta) {
    this.meta = meta || {};
    this.state = this._load();
  }

  _load() {
    const code = (this.meta.defaultSymbol && this.meta.defaultSymbol.code) || '600118.SH';
    const name = (this.meta.defaultSymbol && this.meta.defaultSymbol.name) || '';
    let raw = null;
    try { raw = JSON.parse(localStorage.getItem(KEY) || 'null'); } catch (e) { raw = null; }
    if (!raw || !Array.isArray(raw.workspaces) || !raw.workspaces.length) {
      return defaults(this.meta);
    }
    const workspaces = raw.workspaces.map((w, i) => normWorkspace(w || {}, i, code, name));
    let activeId = raw.activeId;
    if (!workspaces.some((w) => w.id === activeId)) activeId = workspaces[0].id;
    return { version: VERSION, activeId, workspaces };
  }

  save() {
    try { localStorage.setItem(KEY, JSON.stringify(this.state)); } catch (e) { /* 存储满时静默 */ }
  }

  active() {
    return this.state.workspaces.find((w) => w.id === this.state.activeId) || this.state.workspaces[0];
  }

  list() { return this.state.workspaces; }

  setActive(id) {
    if (!this.state.workspaces.some((w) => w.id === id)) return false;
    this.state.activeId = id;
    this.save();
    return true;
  }

  setLayout(layout) {
    if (!LAYOUTS.some((l) => l.id === layout)) return;
    this.active().layout = layout;
    this.save();
  }

  setLink(kind, on) {
    const w = this.active();
    if (kind === 'stock') w.stockLink = !!on;
    else if (kind === 'time') w.timeLink = !!on;
    this.save();
  }

  updatePanel(index, patch) {
    const panels = this.active().panels;
    if (!panels[index]) return;
    panels[index] = Object.assign({}, panels[index], patch);
    this.save();
  }

  create(name) {
    const n = this.state.workspaces.length + 1;
    const cur = this.active();
    const code = cur && cur.panels[0] ? cur.panels[0].code : '600118.SH';
    const nm = cur && cur.panels[0] ? cur.panels[0].name : '';
    const last = this.state.workspaces[this.state.workspaces.length - 1];
    const meta = {
      id: 'w-' + Date.now().toString(36) + '-' + Math.floor(Math.random() * 1e4),
      name: name || `工作区 ${n}`,
      preset: false,
      layout: '2v',
      stockLink: last ? last.stockLink : true,
      timeLink: last ? last.timeLink : true,
      panels: newPanels(code, nm),
    };
    this.state.workspaces.push(normWorkspace(meta, this.state.workspaces.length, code, nm));
    this.state.activeId = meta.id;
    this.save();
    return meta.id;
  }

  rename(id, name) {
    const w = this.state.workspaces.find((x) => x.id === id);
    if (!w || !name) return false;
    w.name = String(name).slice(0, 40);
    this.save();
    return true;
  }

  remove(id) {
    if (this.state.workspaces.length <= 1) return false;
    const idx = this.state.workspaces.findIndex((x) => x.id === id);
    if (idx < 0) return false;
    this.state.workspaces.splice(idx, 1);
    if (this.state.activeId === id) this.state.activeId = this.state.workspaces[Math.max(0, idx - 1)].id;
    this.save();
    return true;
  }

  restorePresets() {
    const code = (this.meta.defaultSymbol && this.meta.defaultSymbol.code) || '600118.SH';
    const name = (this.meta.defaultSymbol && this.meta.defaultSymbol.name) || '';
    for (const p of presetWorkspaces(code, name)) {
      const idx = this.state.workspaces.findIndex((w) => w.id === p.id);
      if (idx >= 0) this.state.workspaces[idx] = normWorkspace(p, idx, code, name);
      else this.state.workspaces.push(normWorkspace(p, this.state.workspaces.length, code, name));
    }
    this.save();
  }
}
