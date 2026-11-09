/* 应用入口：顶栏（数据状态/工作区/布局/联动）+ 三个视图的装配与快捷键 */
import { API } from './api.js?v=20261106j';
import { Store, LAYOUTS } from './store.js?v=20261106j';
import { h, clear, fmtDate, toast, modalPrompt, modalConfirm, closePopover } from './util.js?v=20261106j';
import { WorkspaceView } from './views/workspace.js?v=20261106j';
import { BacktestView } from './views/backtest.js?v=20261106j';
import { PicksView } from './views/picks.js?v=20261106j';
import { RealtimeView } from './views/realtime.js?v=20261106j';
import { TrainingView } from './views/training.js?v=20261106j';

const state = {
  meta: null,
  store: null,
  symbols: [],
  view: 'realtime',
  views: {},
  trade: null,
};

const $ = (id) => document.getElementById(id);

const ctx = {
  get meta() { return state.meta; },
  get store() { return state.store; },
  get symbols() { return state.symbols; },
  api: API,
  onStoreChanged: () => syncHeaderControls(),
  setTradeChip,
  openTrade,
  linkSymbol,
  addToWorkspace,
};

/** 当前生效的 K 线工作区：工作区页=主实例；策略选股页=左栏实例 */
function activeWorkspace() {
  if (state.view === 'picks') {
    const pv = state.views.picks;
    if (pv && pv.leftWorkspace) return pv.leftWorkspace;
  }
  return state.views.workspace || null;
}

/* ---------------- header ---------------- */

function renderMeta() {
  const meta = state.meta || {};
  const dsMain = $('ds-main');
  clear(dsMain);
  const latest = meta.latestTradingDate;
  dsMain.appendChild(document.createTextNode('数据日 '));
  dsMain.appendChild(h('b', {}, latest ? fmtDate(latest) : '未找到'));
  dsMain.appendChild(document.createTextNode(`（${meta.tMinus || 'T-1'}）· ${meta.realtime && meta.realtime.available ? '实时' : '非实时（EOD）'}`));
  const ver = meta.dataVersion ? `版本 ${meta.dataVersion}` : '版本 —';
  $('ds-version').textContent = ver;
  $('ds-version').title = meta.data_mtime_text ? `数据文件最新生成时间：${meta.data_mtime_text}` : '';
  $('ds-5m').textContent = `5M ${meta.has_5m_count == null ? '—' : meta.has_5m_count} 只`;
  $('ds-5m').title = 'AIData/5M 本地覆盖股票数（窗口化，不连续）';
  const rt = $('ds-realtime');
  rt.textContent = meta.realtime && meta.realtime.available ? '实时' : '非实时（EOD）';
  rt.title = (meta.realtime && meta.realtime.reason) || '';
  rt.className = 'chip ' + (meta.realtime && meta.realtime.available ? 'ok' : 'warn');
  if (meta.backend && meta.backend.ok === false) {
    rt.textContent = '后端降级';
    rt.title = meta.backend.error || '';
  }
  document.title = `MarcoAI 新看板 v1.4 · 数据日 ${latest ? fmtDate(latest) : '—'}`;
}

function syncHeaderControls() {
  if (!state.store) return;
  const active = state.store.active();
  const sel = $('ws-select');
  clear(sel);
  for (const w of state.store.list()) {
    sel.appendChild(h('option', { value: w.id }, (w.preset ? '预设 · ' : '') + w.name));
  }
  sel.value = active.id;
  document.querySelectorAll('#layout-btns .seg-btn').forEach((b) => {
    b.classList.toggle('on', b.dataset.layout === active.layout);
  });
  $('link-stock').checked = active.stockLink !== false;
  $('link-time').checked = active.timeLink !== false;
  $('btn-ws-del').disabled = state.store.list().length <= 1;
}

async function onRefreshMeta() {
  try {
    state.meta = await API.meta();
    renderMeta();
    toast('数据状态已刷新', 'ok', 1500);
  } catch (e) {
    toast('数据状态刷新失败：' + ((e && e.message) || e), 'err');
  }
}

/* ---------------- view switching ---------------- */

function switchView(name) {
  if (!['realtime', 'backtest', 'picks', 'training'].includes(name)) return;
  const prevName = state.view;
  if (prevName !== name) {
    const prev = state.views[prevName];
    if (prev && typeof prev.onHide === 'function') {
      try { prev.onHide(); } catch (e) { /* ignore */ }
    }
  }
  state.view = name;
  document.querySelectorAll('#nav-tabs .tab').forEach((t) => t.classList.toggle('on', t.dataset.view === name));
  for (const key of ['realtime', 'backtest', 'picks', 'training']) {
    $('view-' + key).hidden = key !== name;
  }
  let v = state.views[name];
  if (!v) {
    const root = $('view-' + name);
    const C = name === 'workspace' ? WorkspaceView
      : name === 'backtest' ? BacktestView
        : name === 'picks' ? PicksView
          : name === 'training' ? TrainingView : RealtimeView;
    v = new C(root, ctx);
    state.views[name] = v;
  }
  v.mount();
  if (typeof v.onShow === 'function') {
    try { v.onShow(); } catch (e) { /* ignore */ }
  }
  syncHeaderControls();
  setTradeChip((activeWorkspace() && activeWorkspace().trade) || null);
}

function ensureWorkspaceMounted() {
  if (state.views.workspace) return state.views.workspace;
  return null;
}

/* ---------------- workspace header actions ---------------- */

function switchWorkspace(id) {
  if (!state.store.setActive(id)) return;
  syncHeaderControls();
  const ws = activeWorkspace();
  if (ws) ws.reloadFromStore();
  setTradeChip(null);
  const w = state.store.active();
  toast('已切换到工作区：' + w.name, '', 1500);
}

function setLayout(layout) {
  if (!LAYOUTS.some((l) => l.id === layout)) return;
  state.store.setLayout(layout);
  syncHeaderControls();
  const ws = activeWorkspace();
  if (ws) ws.applyStore({ load: true });
}

function setLink(kind, on) {
  state.store.setLink(kind, on);
  syncHeaderControls();
  const label = kind === 'stock' ? '股票联动' : '时间轴联动';
  toast(`${label}已${on ? '开启' : '关闭'}（周期始终独立）`, '', 1600);
}

async function newWorkspace() {
  const n = state.store.list().length + 1;
  const name = await modalPrompt('新建工作区', `工作区 ${n}`, { placeholder: '例如：竞价盯盘 / 打板盯盘 / 复盘' });
  if (name == null) return;
  const id = state.store.create(name || `工作区 ${n}`);
  syncHeaderControls();
  const ws = activeWorkspace();
  if (ws) ws.reloadFromStore();
  toast('已新建工作区：' + state.store.active().name, 'ok');
}

async function renameWorkspace() {
  const w = state.store.active();
  const name = await modalPrompt('重命名工作区', w.name);
  if (name == null || !name) return;
  state.store.rename(w.id, name);
  syncHeaderControls();
  toast('已重命名：' + name, 'ok');
}

async function deleteWorkspace() {
  const w = state.store.active();
  if (state.store.list().length <= 1) { toast('至少保留一个工作区', 'err'); return; }
  const ok = await modalConfirm(`确定删除工作区「${w.name}」？该工作区的布局/面板状态将丢失。`, { title: '删除工作区', okText: '删除', danger: true });
  if (!ok) return;
  state.store.remove(w.id);
  syncHeaderControls();
  const ws = activeWorkspace();
  if (ws) ws.reloadFromStore();
  toast('已删除工作区：' + w.name, '', 1600);
}

async function restorePresets() {
  const ok = await modalConfirm('恢复 3 个内置预设工作区（竞价盯盘 / 打板盯盘 / 复盘验证）？同名预设会被覆盖，其余工作区保留。', { title: '恢复预设', okText: '恢复' });
  if (!ok) return;
  state.store.restorePresets();
  syncHeaderControls();
  const ws = activeWorkspace();
  if (ws) ws.reloadFromStore();
  toast('已恢复内置预设工作区', 'ok');
}

/* ---------------- trade chip / linkage ---------------- */

function setTradeChip(trade) {
  state.trade = trade || null;
  const wrap = $('trade-chip-wrap');
  const chip = $('trade-chip');
  clear(chip);
  if (!trade) { wrap.hidden = true; return; }
  wrap.hidden = false;
  chip.appendChild(document.createTextNode('联动 '));
  chip.appendChild(h('b', {}, trade.code + (trade.name ? ' ' + trade.name : '')));
  chip.appendChild(document.createTextNode(' · 卖出日 T-0 '));
  chip.appendChild(h('b', {}, shortDate(trade.t0Label || trade.date)));
  chip.appendChild(document.createTextNode(' · 选股日 T-2 '));
  chip.appendChild(h('b', {}, trade.t2Label ? shortDate(trade.t2Label) : '—'));
}

function shortDate(s) {
  const t = String(s || '');
  return t.length === 10 ? t.slice(5) : t;
}

function openTrade(trade) {
  // 策略选股页现在同屏联动左栏 K 线，不跳页；从其它入口调用时才切到工作区页
  if (state.view === 'picks' && state.views.picks && state.views.picks.leftWorkspace) {
    state.views.picks.leftWorkspace.selectTrade(trade);
    setTradeChip(trade);
    toast(`已联动 ${trade.code}${trade.name ? ' ' + trade.name : ''}｜卖出日 T-0 ${trade.t0Label || ''}｜选股日 T-2 ${trade.t2Label || '—'}`, '', 3200);
    return;
  }
  switchView('workspace');
  const ws = state.views.workspace;
  ws.selectTrade(trade);
  setTradeChip(trade);
  toast(`已联动 ${trade.code}${trade.name ? ' ' + trade.name : ''}｜卖出日 T-0 ${trade.t0Label || ''}｜选股日 T-2 ${trade.t2Label || '—'}`, '', 3200);
}

function linkSymbol(stock) {
  const ws = activeWorkspace();
  if (!ws) return;
  ws.changeSymbol(ws.activeIndex, stock.code, stock.name || '');
  toast(`K 线已联动：${stock.code}${stock.name ? ' ' + stock.name : ''}`, '', 1800);
}

function addToWorkspace(stock) {
  const ws = activeWorkspace();
  if (ws && ws._mounted) {
    const res = ws.addStock(stock);
    if (res && res.ok) {
      const msg = res.already ? `已在工作区「${res.workspace}」第 ${res.panel} 面板` : `已加入：工作区「${res.workspace}」（第 ${res.panel} 面板）`;
      toast(msg, 'ok', 2200);
    }
    return res;
  }
  // 工作区尚未打开：直接写 store（面板 1），真正打开时按原样恢复
  const w = state.store.active();
  const p = w.panels[0];
  const already = p.code === stock.code;
  if (!already) {
    p.code = stock.code;
    p.name = stock.name || '';
    state.store.save();
  }
  toast(already ? `已在工作区「${w.name}」第 1 面板` : `已加入：工作区「${w.name}」（第 1 面板）`, 'ok', 2200);
  return { ok: true, already, panel: 1, workspace: w.name };
}

/* ---------------- symbols ---------------- */

async function loadSymbols() {
  try {
    const res = await API.symbols();
    state.symbols = (res && res.symbols) || [];
    const dl = $('symbol-list');
    clear(dl);
    for (const s of state.symbols.slice(0, 900)) {
      dl.appendChild(h('option', { value: s.code }, s.name || ''));
    }
  } catch (e) { /* 代码联想失败不影响主流程 */ }
}

/* ---------------- events / shortcuts ---------------- */

function bindHeaderEvents() {
  $('nav-tabs').addEventListener('click', (e) => {
    const btn = e.target.closest('.tab');
    if (btn) switchView(btn.dataset.view);
  });
  $('btn-refresh-meta').addEventListener('click', onRefreshMeta);
  $('ws-select').addEventListener('change', () => switchWorkspace($('ws-select').value));
  $('btn-ws-new').addEventListener('click', newWorkspace);
  $('btn-ws-rename').addEventListener('click', renameWorkspace);
  $('btn-ws-del').addEventListener('click', deleteWorkspace);
  $('btn-ws-presets').addEventListener('click', restorePresets);
  $('layout-btns').addEventListener('click', (e) => {
    const btn = e.target.closest('.seg-btn');
    if (btn) setLayout(btn.dataset.layout);
  });
  $('link-stock').addEventListener('change', (e) => setLink('stock', e.target.checked));
  $('link-time').addEventListener('change', (e) => setLink('time', e.target.checked));
  $('btn-trade-clear').addEventListener('click', () => {
    const ws = activeWorkspace();
    if (ws) ws.clearTrade();
    setTradeChip(null);
  });
}

function isEditable(el) {
  if (!el || !el.tagName) return false;
  const t = el.tagName;
  return t === 'INPUT' || t === 'SELECT' || t === 'TEXTAREA' || el.isContentEditable;
}

function bindKeys() {
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { closePopover(); if (document.getElementById('modal-root').children.length) { /* modal 自己处理 */ } return; }
    if (isEditable(e.target)) return;
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === '1' || e.key === '2' || e.key === '4') {
      if (state.view === 'workspace' || state.view === 'picks') setLayout(e.key === '2' ? '2v' : e.key);
      return;
    }
    if (state.view !== 'workspace' && state.view !== 'picks') return;
    const ws = activeWorkspace();
    if (!ws) return;
    if (e.key === 'f' || e.key === 'F') { ws.fitActive(); e.preventDefault(); }
    else if (e.key === 'l' || e.key === 'L') { setLink('time', !state.store.active().timeLink); }
    else if (e.key === 's' || e.key === 'S') { setLink('stock', !state.store.active().stockLink); }
    else if (e.key === '[') { ws.cyclePeriod(-1); e.preventDefault(); }
    else if (e.key === ']') { ws.cyclePeriod(1); e.preventDefault(); }
  });
}

/* ---------------- boot ---------------- */

function renderFatal(err) {
  const root = $('view-workspace');
  clear(root);
  root.style.overflow = 'auto';
  const box = h('div', { class: 'view-pad' },
    h('div', { class: 'error-box', style: 'margin:40px auto;max-width:720px' },
      h('div', {},
        h('div', { style: 'font-weight:700;margin-bottom:6px' }, '无法连接本地服务 /api/meta'),
        h('div', {}, String((err && err.message) || err)),
        h('div', { class: 'muted', style: 'margin-top:8px' }, '请确认服务已启动：python tools/dashboard_server.py --port 8765')),
      h('button', { class: 'btn btn-primary', onclick: () => boot() }, '重试')));
  root.appendChild(box);
}

let booted = false;

async function boot() {
  try {
    state.meta = await API.meta();
  } catch (e) {
    renderFatal(e);
    return;
  }
  state.store = new Store(state.meta);
  renderMeta();
  syncHeaderControls();
  if (!booted) {
    bindHeaderEvents();
    bindKeys();
    booted = true;
  }
  switchView(state.view || 'workspace');
  loadSymbols();
  // 测试/调试钩子
  window.__MARCO__ = {
    get meta() { return state.meta; },
    get store() { return state.store; },
    get view() { return state.view; },
    get views() { return state.views; },
    get trade() { return state.trade; },
    get activeWorkspace() { return activeWorkspace(); },
    switchView,
    setLayout,
    setLink,
    switchWorkspace,
    openTrade,
    api: API,
    ready: true,
  };
}

boot();
