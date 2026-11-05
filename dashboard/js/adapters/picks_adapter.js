/* 选股列表数据适配层（picksAdapter）。
 *
 * v1.1 唯一来源：策略选股 `GET /api/picks?strategy=`（现有口径，不造数）。
 * 未来扩展点（保持接口稳定即可替换/新增来源）：
 *   1) 不同列表来源：实现同样的 `listSources / load / monthOptions / rowsForMonth / toTrade`
 *      然后 `picksAdapterRegistry.register(adapter)`；PickList 组件只依赖这套接口。
 *   2) 选股条件设置：adapter.getSettings() / setSettings(settings) 预留（返回 null 表示暂无）。
 *   3) 专门回测面板：adapter.getBacktestRequest(row) 返回 {api, params}（当前指向 /api/dashboard）。
 *   4) 新后端接口（如 /api/screen）：在 adapter.load() 内切换数据源即可，UI 不改。
 */

export const PICK_COLUMNS = [
  { key: 'code', label: '代码', short: '代码', sortable: true, type: 'str', align: 'left', width: '15%' },
  { key: 'name', label: '名称', short: '名称', sortable: false, type: 'str', align: 'left', width: '15%' },
  { key: 'chg', label: '涨跌幅%', short: '涨跌%', sortable: true, type: 'num', align: 'num', width: '11%' },
  { key: 'sell', label: '实际卖出涨幅%(5m,扣费)', short: '卖出(5m)', sortable: true, type: 'num', align: 'num', width: '19%' },
  { key: 'highPct', label: '最高涨幅%', short: '最高%', sortable: true, type: 'num', align: 'num', width: '11%' },
  { key: 'lowPct', label: '最低涨幅%', short: '最低%', sortable: true, type: 'num', align: 'num', width: '11%' },
  { key: 'mcap', label: '市值(亿)', short: '市值', sortable: true, type: 'num', align: 'num', width: '11%' },
  { key: 'ops', label: '操作', short: '+', sortable: false, type: 'str', align: 'center', width: '7%' },
];

const SORT_KEYS = ['code', 'chg', 'sell', 'highPct', 'lowPct', 'mcap'];

export class PicksAdapter {
  constructor(api, meta) {
    this.api = api;
    this.meta = meta || {};
    this.sourceId = 'strategy-picks';
    this.name = '策略选股';
    this._cache = new Map();
  }

  /** 可用列表来源（未来可返回多套选股策略/条件） */
  listSources() {
    const list = (this.meta.strategies && this.meta.strategies.length) ? this.meta.strategies : ['TPO_M5'];
    return list.map((s) => ({ id: s, label: s }));
  }

  columns() { return PICK_COLUMNS; }

  /** 拉取并归一化数据（当前走 /api/picks） */
  async load({ strategy, refresh = false } = {}) {
    const data = await this.api.picks(strategy, refresh);
    return this.normalize(data, strategy);
  }

  normalize(data, strategy) {
    const raw = data || {};
    const months = Array.isArray(raw.months) ? raw.months : [];
    const dates = Array.isArray(raw.dates) ? raw.dates : [];
    const picks = raw.picks || {};
    const candidateDates = Array.isArray(raw.candidate_dates)
      ? raw.candidate_dates
      : (Array.isArray(raw.cand_group_dates) ? raw.cand_group_dates : []);
    const latestCand = candidateDates[0] || raw.latest_cand_date || null;
    return {
      ok: raw.ok !== false,
      degraded: !!raw.degraded,
      error: raw.error || raw.message || null,
      strategy: raw.strategy || strategy,
      months,
      dates,
      picks,
      candidateDates,
      latestCandidateDate: latestCand,
      tpoWindow: raw.tpoWindow || {},
      dateMeta: raw.dateMeta || {},
      cachedAt: raw.cachedAt || null,
      elapsedMs: raw.elapsedMs || null,
      raw,
    };
  }

  /** 默认月份：优先有回测数据的最新月份 */
  defaultMonth(data) {
    const months = (data && data.months) || [];
    if (!months.length) return null;
    return (months.find((m) => m.hasData) || months[0]).value;
  }

  monthOptions(data) {
    return ((data && data.months) || []).map((m) => ({
      value: m.value,
      label: m.label + (m.hasData ? ` · ${m.count} 只` : ' · 暂无回测'),
      hasData: !!m.hasData,
      count: m.count || 0,
      dates: m.dates || 0,
    }));
  }

  monthDates(data, month) {
    if (!data || !month) return [];
    return (data.dates || []).filter((d) => String(d).slice(0, 6) === month);
  }

  isCandDate(data, date) {
    return !!data && (data.candidateDates || []).includes(String(date));
  }

  /** TPO 窗口 → 与日期分组同构的分组（同一套表格渲染，仅标题带 (T)/(T-1)） */
  tpoGroups(data) {
    const tw = (data && data.tpoWindow) || {};
    const mk = (key, date, label, rows) => {
      const list = rows || [];
      const d = String(date || '');
      if (!d && !list.length) return null;
      return {
        key, date: d, tpo: key, cand: false,
        title: d ? `${formatYmd(d)}（${label}）` : `${label} 窗口`,
        rows: list.map((r) => this._tpoRow(r, { key, date: d })),
      };
    };
    return [mk('T', tw.today, 'T', tw.T), mk('TM1', tw.prev, 'T-1', tw.TM1)].filter(Boolean);
  }

  _tpoRow(entry, group) {
    const code = entry[0];
    const name = entry[1] || '';
    const market = entry[2] == null || entry[2] === '' ? null : Number(entry[2]);
    return {
      key: `tpo|${group.key}|${group.date}|${code}`,
      tpo: group.key,
      date: group.date,
      code,
      name,
      chg: null,
      sell: null,
      highPct: null,
      lowPct: null,
      mcap: Number.isFinite(market) && market > 0 ? market / 1e8 : null,
      cand: false,
      stock: { code, name },
    };
  }

  _row(stock, date, cand) {
    const pre = Number(stock.pre);
    const high = stock.high == null ? null : Number(stock.high);
    const low = stock.low == null ? null : Number(stock.low);
    return {
      key: `${date}|${stock.code}`,
      date: String(date),
      code: stock.code || '',
      name: stock.name || '',
      chg: stock.chg == null ? null : Number(stock.chg),
      sell: stock.sell_chg_5m == null ? null : Number(stock.sell_chg_5m),
      highPct: pre && high != null && !Number.isNaN(high) ? ((high - pre) / pre) * 100 : null,
      lowPct: pre && low != null && !Number.isNaN(low) ? ((low - pre) / pre) * 100 : null,
      mcap: stock.mcap == null ? null : Number(stock.mcap),
      cand: !!cand,
      stock,
    };
  }

  /** 当前月份 → 按日期分组；TPO 窗口（T/T-1）作为同构分组置顶 */
  rowsForMonth(data, month) {
    const groups = [];
    const rows = [];
    const tpoGroups = this.tpoGroups(data);
    for (const g of tpoGroups) {
      groups.push(g);
      rows.push(...g.rows);
    }
    const picks = (data && data.picks) || {};
    for (const date of this.monthDates(data, month)) {
      const cand = this.isCandDate(data, date);
      const list = (picks[date] || []).map((s) => this._row(s, date, cand));
      groups.push({ date, cand, rows: list });
      rows.push(...list);
    }
    return { groups, rows, tpoGroups };
  }

  sortRows(rows, sortKey, sortDir) {
    if (!sortKey || !SORT_KEYS.includes(sortKey)) return null;
    const key = sortKey;
    const dir = sortDir || -1;
    return rows.slice().sort((a, b) => {
      if (a.cand !== b.cand) return a.cand ? -1 : 1;
      const va = a[key], vb = b[key];
      const na = va == null || Number.isNaN(Number(va));
      const nb = vb == null || Number.isNaN(Number(vb));
      if (na && nb) return 0;
      if (na) return 1; // 空值永远置后，不参与数值排序
      if (nb) return -1;
      if (typeof va === 'string' || typeof vb === 'string') return dir * String(va).localeCompare(String(vb));
      return dir * (Number(va) - Number(vb));
    });
  }

  /** 行 → K 线联动/交易标记数据（T-2 已在服务端按交易日历反查） */
  toTrade(row, data) {
    const dm = ((data && data.dateMeta) || {})[row.date] || {};
    return {
      code: row.code,
      name: row.name,
      date: row.date,
      t0: row.date,
      t2: dm.t2 || null,
      t0Label: dm.t0_label || formatYmd(row.date),
      t2Label: dm.t2_label || (dm.t2 ? formatYmd(dm.t2) : '—'),
      chg: row.chg,
      sell: row.sell,
    };
  }

  /* ---- 扩展占位（未来选股条件 / 回测面板） ---- */
  getSettings() { return null; }
  setSettings() { return false; }
  getBacktestRequest(row) {
    return { api: '/api/dashboard', params: { strategy: this._strategy || 'TPO_M5', pick_mode: 'first', sell_mode: '5m' }, code: row && row.code };
  }
}

function formatYmd(d) {
  const s = String(d || '').replace(/-/g, '');
  return s.length === 8 ? `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}` : String(d || '');
}

/** 适配器注册表：PickList 可绑定任意实现同一接口的数据源。 */
export const picksAdapterRegistry = {
  adapters: new Map(),
  register(adapter) {
    if (!adapter || !adapter.sourceId) throw new Error('adapter 需提供 sourceId');
    this.adapters.set(adapter.sourceId, adapter);
    return adapter;
  },
  list() { return [...this.adapters.values()]; },
  get(id) { return this.adapters.get(id) || null; },
};

export function createDefaultPicksAdapter(api, meta) {
  const adapter = new PicksAdapter(api, meta);
  adapter._strategy = (meta && meta.strategies && meta.strategies[0]) || 'TPO_M5';
  return picksAdapterRegistry.register(adapter);
}
