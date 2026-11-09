/* 策略选股页（v1.1）：左侧 K 线工作区 + 右侧选股列表，同屏单页。
 * - 左侧复用 WorkspaceView（多面板/独立周期指标/联动/命名工作区）
 * - 右侧 PickList（只负责渲染与交互）+ picksAdapter（数据来源可替换）
 * - 点列表行只联动左侧 K 线并标注 T-2/T-0，不跳页、不丢列表状态
 */
import { h, clear, toast } from '../util.js?v=20261106j';
import { WorkspaceView } from './workspace.js?v=20261106j';
import { PickList } from '../components/pick_list.js?v=20261106j';
import { createDefaultPicksAdapter } from '../adapters/picks_adapter.js?v=20261106j';
import { API } from '../api.js?v=20261106j';

const SPLIT_KEY = 'marco.dashboard.picksSplitPct';
const DEFAULT_SPLIT = 65;   // 左 65% / 右 35%
const RIGHT_MIN = 280;      // 右栏最小宽度 px
const NARROW = 1200;        // 窗口 < 1200 右栏可收起

export class PicksView {
  constructor(root, ctx) {
    this.root = root;
    this.ctx = ctx;
    this.adapter = createDefaultPicksAdapter(ctx.api, ctx.meta);
    this.splitPct = this._loadSplit();
    this.collapsed = window.innerWidth < NARROW;
    this._dragging = false;
    this._mounted = false;
    this.leftWorkspace = null;
    this.pickList = null;
  }

  _loadSplit() {
    const raw = parseFloat(localStorage.getItem(SPLIT_KEY) || '');
    if (Number.isFinite(raw)) return Math.min(80, Math.max(45, raw));
    return DEFAULT_SPLIT;
  }

  _saveSplit() {
    try { localStorage.setItem(SPLIT_KEY, String(Math.round(this.splitPct * 10) / 10)); } catch (e) { /* ignore */ }
  }

  mount() {
    if (this._mounted) {
      if (this.leftWorkspace) this.leftWorkspace.mount();
      return;
    }
    this._mounted = true;
    clear(this.root);

    this.leftHost = h('div', { class: 'picks-left-ws' });
    this.splitter = h('div', { class: 'picks-splitter', title: '拖拽调整 K 线 / 选股列表宽度（会记住）' });
    this.listHost = h('div', { class: 'picks-list-host' });
    this.rightPane = h('div', { class: 'picks-right-pane' }, this.listHost);
    this.splitEl = h('div', { class: 'picks-split' }, this.leftHost, this.splitter, this.rightPane);
    this.expandBtn = h('button', {
      class: 'btn btn-xs picks-expand-btn', title: '展开选股列表',
      onclick: () => this.toggleCollapse(false),
    }, '‹ 选股列表');
    this.root.appendChild(this.splitEl);
    this.root.appendChild(this.expandBtn);

    // 左侧：复用 K 线工作区
    this.leftWorkspace = new WorkspaceView(this.leftHost, this.ctx);
    this.leftWorkspace.pageKey = 'picks';
    this.leftWorkspace.mount();

    // 右侧：选股列表（组件 + 适配器）
    this.pickList = new PickList(this.listHost, {
      adapter: this.adapter,
      meta: this.ctx.meta,
      onSelect: (row) => this.handleSelect(row),
      onAdd: (row) => this.handleAdd(row),
      onCollapse: () => this.toggleCollapse(true),
    });
    this.pickList.mount();

    this._applySplit();
    this._bindSplitter();
    this._bindResize();
    this._syncCollapsed();
  }

  /* ---------- 分割条 ---------- */
  _clampPct(pct) {
    const width = (this.splitEl && this.splitEl.clientWidth) || window.innerWidth;
    const maxByRightMin = 100 - (RIGHT_MIN / Math.max(width, 320)) * 100;
    return Math.min(Math.max(pct, 45), Math.min(80, Math.max(50, maxByRightMin)));
  }

  _applySplit(save = false) {
    if (!this.splitEl) return;
    this.splitPct = this._clampPct(this.splitPct);
    this.leftHost.style.flex = `0 0 ${this.splitPct}%`;
    if (save) this._saveSplit();
  }

  _bindSplitter() {
    const onMove = (e) => {
      if (!this._dragging || !this.splitEl) return;
      const rect = this.splitEl.getBoundingClientRect();
      if (!rect.width) return;
      this.splitPct = this._clampPct(((e.clientX - rect.left) / rect.width) * 100);
      this.leftHost.style.flex = `0 0 ${this.splitPct}%`;
    };
    const onUp = () => {
      if (!this._dragging) return;
      this._dragging = false;
      this.splitter.classList.remove('dragging');
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      this._saveSplit();
    };
    this.splitter.addEventListener('mousedown', (e) => {
      e.preventDefault();
      this._dragging = true;
      this.splitter.classList.add('dragging');
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    });
    this.splitter.addEventListener('dblclick', () => {
      this.splitPct = DEFAULT_SPLIT;
      this._applySplit(true);
    });
  }

  _bindResize() {
    this._onResize = () => {
      this._applySplit();
      this._syncCollapsed();
    };
    window.addEventListener('resize', this._onResize);
  }

  _syncCollapsed() {
    const narrow = window.innerWidth < NARROW;
    // 窄屏默认收起；宽屏默认展开（用户手动收起后 resize 不禁用，保持当前状态除非跨阈值）
    if (narrow) this.collapsed = true;
    else if (this._wasNarrow) this.collapsed = false;
    this._wasNarrow = narrow;
    this.root.classList.toggle('picks-collapsed', this.collapsed);
    if (this.expandBtn) this.expandBtn.hidden = !this.collapsed;
  }

  toggleCollapse(collapsed) {
    this.collapsed = collapsed == null ? !this.collapsed : !!collapsed;
    this.root.classList.toggle('picks-collapsed', this.collapsed);
    if (this.expandBtn) this.expandBtn.hidden = !this.collapsed;
    if (!this.collapsed) this._applySplit();
  }

  /* ---------- 列表 → 左侧 K 线联动 ---------- */
  async _picksRange(D) {
    const ymd = String(D || '').replace(/-/g, '').slice(0, 8);
    if (!/^\d{8}$/.test(ymd)) return null;
    const dt = new Date(Date.UTC(+ymd.slice(0, 4), +ymd.slice(4, 6) - 1, +ymd.slice(6, 8)));
    dt.setUTCDate(dt.getUTCDate() + 10);
    const endPlus = dt.toISOString().slice(0, 10).replace(/-/g, '');
    try {
      const res = await API.kline('000001.SH', '1d', 80, endPlus);
      const dates = (res.bars || []).map((b) => {
        const t = b.time;
        if (typeof t === 'number') {
          const d = new Date(t * 1000);
          return `${d.getUTCFullYear()}${String(d.getUTCMonth() + 1).padStart(2, '0')}${String(d.getUTCDate()).padStart(2, '0')}`;
        }
        return String(t).replace(/-/g, '').slice(0, 8);
      }).filter((d) => /^\d{8}$/.test(d));
      let idx = dates.indexOf(ymd);
      if (idx < 0) {
        for (let i = dates.length - 1; i >= 0; i--) if (dates[i] <= ymd) { idx = i; break; }
      }
      if (idx < 0) return { start: ymd, end: ymd };
      const start = dates[Math.max(0, idx - 3)];
      const end = dates[Math.min(dates.length - 1, idx + 1)];
      return { start, end };
    } catch (e) { return { start: ymd, end: ymd }; }
  }

  async handleSelect(row) {
    if (!this.leftWorkspace) return;
    const seq = (this._selectSeq || 0) + 1;
    this._selectSeq = seq;
    const trade = this.adapter.toTrade(row, this.pickList.getData());
    const ws = this.leftWorkspace;
    ws.trade = trade;
    const win = await this._picksRange(row.date);
    if (seq !== this._selectSeq) return;
    // 选股页要求点击任意行 → 所有可见面板（无论「股票联动」开关）都切到该股并重载
    ws.panels.forEach((p, i) => {
      if (p.el.hidden) return;
      if (p.state.code !== trade.code) {
        p.setState(Object.assign({}, p.state, { code: trade.code, name: trade.name || '' }));
        try { ws.ctx.store.updatePanel(i, { code: trade.code, name: trade.name || '' }); } catch (e) { /* ignore */ }
      }
    });
    if (win) ws.setRange(win.start, win.end);
    else { ws.setRange(null, null); ws.panels.forEach((p) => { if (!p.el.hidden) p.load(); }); }
    this.ctx.setTradeChip(trade);
    toast(`已联动 ${trade.code}${trade.name ? ' ' + trade.name : ''}｜卖出日 T-0 ${trade.t0Label}｜选股日 T-2 ${trade.t2Label}`, '', 2400);
  }

  handleAdd(row) {
    const res = this.ctx.addToWorkspace({ code: row.code, name: row.name });
    return res || { ok: false };
  }

  /** 供 main 在切视图/工作区时调用 */
  reloadFromStore() {
    if (this.leftWorkspace) this.leftWorkspace.reloadFromStore();
  }
}
