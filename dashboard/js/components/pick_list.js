/* PickList 组件：只负责「日期 + 该日股票 + 股票数据」列表的渲染与交互。
 * 数据来源由 picksAdapter 注入（当前=/api/picks），组件本身不依赖具体接口。
 * 事件：onSelect(row) 点击行；onAdd(row) 点击 +；onCollapse() 收起右栏。
 * v1.2：TPO T/T-1 不再用独立卡片，而是与日期分组同构渲染（同一套列/表头/行高/颜色/排序）。
 */
import { h, clear, fmt, pct, n, fmtDate, fmtYm, isLimitUp, toast } from '../util.js?v=20261106aa';

const TPO_KEY = 'marco.picks.tpoOpenV2';
const SORTABLE = (col) => !!col.sortable;

function numCell(v, { limit = false } = {}) {
  const x = n(v);
  if (x == null) return h('td', { class: 'num muted' }, '—');
  const cls = x > 0 ? 'up' : x < 0 ? 'down' : '';
  const gold = limit && isLimitUp(x);
  return h('td', { class: 'num ' + cls + (gold ? ' gold' : '') }, pct(x, 2));
}

export class PickList {
  /**
   * @param {HTMLElement} host 容器
   * @param {object} opts {adapter, meta, onSelect, onAdd, onCollapse}
   */
  constructor(host, opts = {}) {
    this.host = host;
    this.adapter = opts.adapter;
    this.meta = opts.meta || {};
    this.onSelect = opts.onSelect || (() => {});
    this.onAdd = opts.onAdd || (() => {});
    this.onCollapse = opts.onCollapse || null;

    this.strategy = (this.adapter.listSources()[0] || {}).id || 'TPO_M5';
    this.data = null;
    this.month = null;
    this.sortKey = null;
    this.sortDir = -1;
    this.selectedKey = null;
    this.joined = new Set();
    this.loading = false;
    this._mounted = false;
    this.tpoOpen = this._loadTpoOpen();   // T/T-1 分组是否展开（默认展开）
  }

  _loadTpoOpen() {
    try {
      const raw = JSON.parse(localStorage.getItem(TPO_KEY) || 'null');
      if (raw && typeof raw === 'object') return { T: raw.T !== false, TM1: raw.TM1 !== false };
    } catch (e) { /* ignore */ }
    return { T: true, TM1: true };
  }

  _saveTpoOpen() {
    try { localStorage.setItem(TPO_KEY, JSON.stringify(this.tpoOpen)); } catch (e) { /* ignore */ }
  }

  mount() {
    if (this._mounted) return;
    this._mounted = true;
    clear(this.host);
    this.el = h('div', { class: 'pick-list' });
    this.toolbarEl = h('div', { class: 'pick-toolbar' });
    this.tableWrap = h('div', { class: 'pick-table-wrap' });
    this.el.appendChild(this.toolbarEl);
    this.el.appendChild(this.tableWrap);
    this.host.appendChild(this.el);
    this.load();
  }

  async load(refresh = false) {
    if (this.loading) return;
    this.loading = true;
    this._renderLoading();
    try {
      const data = await this.adapter.load({ strategy: this.strategy, refresh });
      this.data = data;
      if (!data || data.ok === false) {
        this._renderError((data && data.error) || '选股数据为空');
        return;
      }
      const months = data.months || [];
      if (!this.month || !months.some((m) => m.value === this.month)) {
        this.month = this.adapter.defaultMonth(data);
      }
      // 切换数据源后保持已选中的行（若仍存在）
      this._keepSelectionValid();
      this._renderToolbar();
      this._renderTable();
    } catch (e) {
      this._renderError(String((e && e.message) || e));
    } finally {
      this.loading = false;
    }
  }

  _keepSelectionValid() {
    if (!this.selectedKey || !this.data) return;
    const { rows } = this.adapter.rowsForMonth(this.data, this.month);
    if (!rows.some((r) => r.key === this.selectedKey)) this.selectedKey = null;
  }

  _renderLoading() {
    clear(this.tableWrap);
    this.tableWrap.appendChild(h('div', { class: 'loading-box' },
      h('div', { class: 'spin' }),
      h('span', {}, '选股数据加载中…（首次计算约数十秒，服务端已预热缓存）')));
  }

  _renderError(msg) {
    clear(this.tableWrap);
    this.tableWrap.appendChild(h('div', { class: 'error-box', style: 'margin:8px' },
      h('span', {}, '加载失败：' + msg),
      h('button', { class: 'btn btn-xs', onclick: () => this.load(true) }, '重试')));
  }

  _sourceOptions() {
    return this.adapter.listSources();
  }

  async addToThsTest(btn) {
    if (!this.month) { toast('请先选择月份', 'warn', 3000); return; }
    if (btn && btn.disabled) return;
    const old = btn ? btn.textContent : '';
    if (btn) { btn.disabled = true; btn.textContent = '写入中…'; }
    try {
      const res = await fetch('/api/ths/test-block', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ month: this.month }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.ok) throw new Error(data.error || `HTTP ${res.status}`);
      toast(`已写入同花顺 TEST：${data.count} 只（${data.month}）${data.restarted ? '，已重启同花顺' : '，重启失败：' + (data.restartDetail || '未知')}`, data.restarted ? '' : 'warn', 6000);
    } catch (e) {
      toast('添加到同花顺失败：' + ((e && e.message) || e), 'error', 6000);
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = old; }
    }
  }

  _renderToolbar() {
    clear(this.toolbarEl);
    const sources = this._sourceOptions();
    const strategySel = h('select', {
      class: 'sel sel-sm', title: '选股来源 / 策略',
      onchange: () => { this.strategy = strategySel.value; this.sortKey = null; this.load(); },
    });
    for (const s of sources) strategySel.appendChild(h('option', { value: s.id }, s.label));
    strategySel.value = this.strategy;

    const months = this.adapter.monthOptions(this.data);
    const monthSel = h('select', {
      class: 'sel sel-sm', title: '月份（切换只更新列表，不影响左侧 K 线）',
      onchange: () => {
        this.month = monthSel.value;
        this.sortKey = null;
        this._keepSelectionValid();
        this._renderToolbar();
        this._renderTable();
      },
    });
    for (const m of months) monthSel.appendChild(h('option', { value: m.value }, m.label));
    if (this.month) monthSel.value = this.month;

    const thsBtn = h('button', {
      class: 'btn btn-xs ghost', title: '把当前月份全部股票写入同花顺 ===TEST=== 板块（按代码去重）',
      onclick: () => this.addToThsTest(thsBtn),
    }, '添加到同花顺');
    const row = h('div', { class: 'pick-toolbar-row' },
      h('span', { class: 'pt-label' }, '策略'), strategySel,
      h('span', { class: 'pt-label' }, '月份'), monthSel,
      h('button', { class: 'btn btn-xs ghost', title: '重新拉取选股数据', onclick: () => this.load(true) }, '刷新'),
      thsBtn);
    if (this.onCollapse) {
      row.appendChild(h('button', { class: 'btn btn-xs ghost pt-collapse', title: '收起选股列表（Ctrl+\\）', onclick: () => this.onCollapse() }, '⟩'));
    }

    const cur = months.find((m) => m.value === this.month);
    const metaRow = h('div', { class: 'pick-toolbar-meta' });
    if (cur) metaRow.appendChild(h('span', { class: 'chip dim' }, `${cur.dates} 交易日 · ${cur.count} 只`));
    if (this.data) {
      const latestCand = (this.data.candidateDates || [])[0];
      if (latestCand) {
        const cnt = ((this.data.picks || {})[latestCand] || []).length;
        metaRow.appendChild(h('span', {
          class: 'chip dim',
          title: '最新一期候选池尚未回测：相关列显示「— 暂无数据 —」',
        }, `最新候选 ${fmtDate(latestCand)} · ${cnt} 只`));
      }
    }
    if (this.sortKey) {
      const col = this.adapter.columns().find((c) => c.key === this.sortKey);
      metaRow.appendChild(h('span', { class: 'sort-chip' },
        `按 ${(col && col.short) || this.sortKey} ${this.sortDir > 0 ? '↑' : '↓'}`,
        h('button', { class: 'btn btn-xs ghost', onclick: () => { this.sortKey = null; this._renderTable(); this._renderToolbar(); } }, '恢复分组')));
    }

    this.toolbarEl.appendChild(row);
    this.toolbarEl.appendChild(metaRow);
  }

  _toggleTpo(key) {
    const scroll = this.tableWrap.scrollTop;
    const open = this.tpoOpen[key] !== false;
    this.tpoOpen[key] = !open;
    this._saveTpoOpen();
    this._renderTable();
    this.tableWrap.scrollTop = scroll;
  }

  _renderTable() {
    clear(this.tableWrap);
    if (!this.data) return;
    const { groups, rows } = this.adapter.rowsForMonth(this.data, this.month);
    const columns = this.adapter.columns();
    const sorted = this.adapter.sortRows(rows, this.sortKey, this.sortDir);

    const table = h('table', { class: 'tbl pick-list-tbl' });
    const colgroup = h('colgroup', {}, columns.map((c) => h('col', { style: `width:${c.width}` })));
    const thead = h('thead', {}, h('tr', {}, columns.map((c) => {
      const th = h('th', {
        class: (c.align === 'left' ? 'l' : c.align === 'center' ? 'c' : 'num'),
        title: c.label + (SORTABLE(c) ? '（点击排序）' : ''),
      }, c.short || c.label);
      if (SORTABLE(c)) {
        th.style.cursor = 'pointer';
        if (this.sortKey === c.key) th.appendChild(h('span', { class: 'arrow' }, this.sortDir > 0 ? '↑' : '↓'));
        th.addEventListener('click', () => {
          if (this.sortKey === c.key) this.sortDir = -this.sortDir;
          else { this.sortKey = c.key; this.sortDir = -1; }
          this._renderToolbar();
          this._renderTable();
        });
      }
      return th;
    })));
    const tbody = h('tbody', {});
    const emptyRow = (text) => h('tr', { class: 'empty-row' }, h('td', { colspan: columns.length }, text));
    const appendDataRow = (row) => tbody.appendChild(this._rowEl(row, columns, !!row.cand));

    const addGroup = (g) => {
      if (g.tpo) {
        // TPO 窗口：同一套表格/分组行样式，仅标题带 (T)/(T-1)，可点击折叠/展开
        const open = this.tpoOpen[g.tpo] !== false;
        tbody.appendChild(h('tr', {
          class: 'group-row tpo-group',
          title: `点击${open ? '收起' : '展开'} ${g.title}`,
          onclick: () => this._toggleTpo(g.tpo),
        }, h('td', { colspan: columns.length },
          h('span', { class: 'gt-chev' + (open ? ' open' : '') }, open ? '▾' : '▸'),
          `${g.title}（${g.rows.length} 只）`,
          h('span', { class: 'gt-hint' }, g.hint || (g.tpo === 'T' ? '符合 T-3→T-1' : '符合 T-3→T-2')))));
        if (!open) return;
        if (!g.rows.length) { tbody.appendChild(emptyRow('该窗口暂无符合标的')); return; }
        g.rows.forEach(appendDataRow);
        return;
      }
      const label = g.cand
        ? `候选 · 未回测 ${fmtDate(g.date)}（${g.rows.length} 只）`
        : `${fmtDate(g.date)}（${g.rows.length} 只）`;
      tbody.appendChild(h('tr', { class: 'group-row' + (g.cand ? ' cand' : '') },
        h('td', { colspan: columns.length }, label)));
      if (!g.rows.length) {
        tbody.appendChild(emptyRow(g.cand ? '该日暂无候选（未回测）' : '该日无股票'));
        return;
      }
      g.rows.forEach(appendDataRow);
    };

    if (this.sortKey && sorted) {
      for (const row of sorted) appendDataRow(row);
      if (!sorted.length) tbody.appendChild(emptyRow('本月无已回测数据'));
    } else {
      const emptyDates = [];
      for (const g of groups) {
        if (g.tpo) { addGroup(g); continue; }
        if (!g.cand && !g.rows.length) { emptyDates.push(g.date); continue; } // 右栏窄，空日期汇总到底部一行
        addGroup(g);
      }
      if (emptyDates.length && emptyDates.length <= 2) {
        // 少量空日期照样按「该日无股票」分组展示（如 20261102 必须明确可见）
        for (const date of emptyDates) addGroup({ date, cand: false, rows: [] });
      } else if (emptyDates.length) {
        const sample = emptyDates.slice(0, 3).map(fmtDate).join('、');
        tbody.appendChild(h('tr', {
          class: 'empty-row',
          title: emptyDates.map(fmtDate).join('、'),
        }, h('td', { colspan: columns.length },
          `其余 ${emptyDates.length} 个交易日无股票（${sample}${emptyDates.length > 3 ? ' 等' : ''}）`)));
      }
      if (!groups.length) {
        tbody.appendChild(emptyRow('该月无选股数据，请切换月份'));
      }
    }

    table.appendChild(colgroup);
    table.appendChild(thead);
    table.appendChild(tbody);
    this.tableWrap.appendChild(table);
  }

  _rowEl(row, columns, cand) {
    const tr = h('tr', {
      class: 'data-row' + (cand ? ' cand' : '') + (row.tpo ? ' tpo-row' : '') + (this.selectedKey === row.key ? ' on' : ''),
      dataset: { key: row.key },
      title: row.tpo ? `${row.tpo} 窗口（未回测，仅代码/名称/市值；点击联动左侧 K 线）` : '',
      onclick: () => this.selectRow(row),
    });
    if (cand) {
      tr.appendChild(h('td', { class: 'code' }, row.code));
      tr.appendChild(h('td', { class: 'name' }, row.name, h('span', { class: 'cand-note' }, '未回测')));
      tr.appendChild(h('td', { class: 'num tmp', colspan: 4 }, '— 暂无数据 —'));
      tr.appendChild(h('td', { class: 'num' }, row.mcap == null ? '—' : fmt(row.mcap, 2)));
      tr.appendChild(h('td', { class: 'ops' }, this._plusBtn(row)));
      return tr;
    }
    tr.appendChild(h('td', { class: 'code' }, row.code));
    tr.appendChild(h('td', { class: 'name' }, row.name));
    tr.appendChild(numCell(row.chg, { limit: true }));
    tr.appendChild(numCell(row.sell));
    tr.appendChild(numCell(row.highPct));
    tr.appendChild(numCell(row.lowPct));
    tr.appendChild(h('td', { class: 'num' }, row.mcap == null ? '—' : fmt(row.mcap, 2)));
    tr.appendChild(h('td', { class: 'ops' }, this._plusBtn(row)));
    return tr;
  }

  _plusBtn(row) {
    const done = this.joined.has(row.code);
    return h('button', {
      class: 'plus' + (done ? ' done' : ''),
      title: done ? '已加入左侧工作区' : '加入左侧 K 线工作区',
      onclick: (e) => {
        e.stopPropagation();
        if (this.joined.has(row.code)) return;
        const res = this.onAdd(row);
        if (res === true || (res && res.ok)) {
          this.joined.add(row.code);
          this._refreshPlus(row);
        }
      },
    }, done ? '已加入' : '＋');
  }

  _refreshPlus(row) {
    const tr = this.tableWrap.querySelector(`tr[data-key="${CSS.escape(row.key)}"]`);
    if (!tr) return;
    const btn = tr.querySelector('.plus');
    if (!btn) return;
    btn.classList.add('done');
    btn.textContent = '已加入';
    btn.title = '已加入左侧工作区';
  }

  /** 点击行：只高亮 + 通知父级联动 K 线，不重绘整表（保留滚动/排序状态） */
  selectRow(row) {
    this.selectedKey = row.key;
    this.tableWrap.querySelectorAll('tr.data-row.on').forEach((el) => el.classList.remove('on'));
    const tr = this.tableWrap.querySelector(`tr[data-key="${CSS.escape(row.key)}"]`);
    if (tr) tr.classList.add('on');
    this.onSelect(row);
  }

  /** 供父级/测试使用 */
  getData() { return this.data; }
  getMonth() { return this.month; }

  setStrategy(strategy) {
    if (!strategy) return;
    this.strategy = strategy;
    this.load();
  }
}
