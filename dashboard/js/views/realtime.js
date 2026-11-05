/* 实时看盘 v2：左侧 5m K 线 + 右侧「当日策略 / 今日持仓(T) / 明日预选(T-1) / 昨日已了结(T-0)」。
 * tqcenter 快照 2s 轮询；K 线数据来自 /api/realtime/kline（TDX vipdoc lc5 + 日线 MA）。
 * 只做行情与判断，不接 miniQMT、不下单。
 */
import { h, clear, fmt, pct, n, toast, modalConfirm } from '../util.js?v=20261105d';
import { API } from '../api.js?v=20261105d';
import { RealtimeDualChart } from '../realtime_dual.js?v=20261105d';

const REFRESH_MS = 2000;
const KLINE_REFRESH_MS = 15000;
const CODE_RE = /^\d{6}\.(SH|SZ|BJ)$/;
const KLINE_HIDDEN_KEY = 'marco.realtime.klineHidden';

const SIGNAL_CLS = {
  '可买（强）': 'sig-buy', '观察': 'sig-watch', '不买': 'sig-no', '回避': 'sig-avoid',
  '数据缺失': 'sig-missing', '止损卖': 'sig-stop', '弱势卖': 'sig-weak',
  '减仓/卖': 'sig-cut', '持有': 'sig-hold', '持有到14:55（涨停/止损优先）': 'sig-hold',
  '10:00卖出': 'sig-stop', '涨停价卖': 'sig-limit',
};

function sigClass(signal) {
  const s = String(signal || '');
  if (s.startsWith('待定')) return 'sig sig-watch';
  if (s.startsWith('持有到14:55')) return 'sig sig-hold';
  return 'sig ' + (SIGNAL_CLS[s] || 'sig-missing');
}

/** 判断列窄（96px），显示短名；完整信号放 title。 */
function sigLabel(signal) {
  const s = String(signal || '');
  if (s.startsWith('持有到14:55')) return '持有到14:55';
  if (s.startsWith('待定')) {
    const m = s.match(/(\d+)\/7/);
    return m ? `待定 ${m[1]}/7` : '待定';
  }
  return s;
}

function priceCls(v) {
  const x = n(v);
  if (x == null) return '';
  return x > 0 ? 'up' : x < 0 ? 'down' : '';
}

function fmtTime(iso) {
  const s = String(iso || '');
  return s.length >= 19 ? s.slice(11, 19) : (s || '—');
}

function fmtDateTime(iso) {
  const s = String(iso || '');
  return s.length >= 19 ? s.slice(0, 10) + ' ' + s.slice(11, 19) : (s || '—');
}

export class RealtimeView {
  constructor(root, ctx) {
    this.root = root;
    this.ctx = ctx;
    this.data = null;
    this.timer = null;
    this.loading = false;
    this._visible = false;
    this._mounted = false;
    this._saving = false;

    this.selectedCode = null;
    this.selectedName = '';
    this.klineData = null;
    this.dailyData = null;
    this.dual = null;
    this.klineCode = null;
    this.klineToken = 0;
    this.klineAt = 0;
    this.klineHidden = this._loadKlineHidden();
  }

  _loadKlineHidden() {
    try { return localStorage.getItem(KLINE_HIDDEN_KEY) === '1'; } catch (e) { return false; }
  }

  _saveKlineHidden() {
    try { localStorage.setItem(KLINE_HIDDEN_KEY, this.klineHidden ? '1' : '0'); } catch (e) { /* ignore */ }
  }

  /* ---------------- lifecycle ---------------- */
  mount() {
    if (this._mounted) return;
    this._mounted = true;
    clear(this.root);
    this._build();
    this.load();
  }

  onShow() { this._visible = true; this.startPolling(); }

  onHide() { this._visible = false; this.stopPolling(); }

  startPolling() {
    if (this.timer) return;
    const tick = async () => {
      this.timer = null;
      if (!this._visible) return;
      await this.load();
      if (this._visible && !this.timer) this.timer = setTimeout(tick, REFRESH_MS);
    };
    this.timer = setTimeout(tick, 0);
  }

  stopPolling() {
    if (this.timer) { clearTimeout(this.timer); this.timer = null; }
  }

  _bindVisibility() {
    if (this._visBound) return;
    this._visBound = true;
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) this.stopPolling();
      else if (this._visible) this.startPolling();
    });
  }

  /* ---------------- skeleton ---------------- */
  _build() {
    this.marketChip = h('span', { class: 'chip dim' }, '市场 —');
    this.timeChip = h('span', { class: 'chip dim' }, '数据时间 —');
    this.envChip = h('span', { class: 'chip dim' }, 'T-1环境 — · 盘中宽度 —');
    this.pollChip = h('span', { class: 'chip dim' }, '2s 轮询');
    this.toggleBtn = h('button', { class: 'btn btn-xs ghost', onclick: () => this.toggleKline() }, this.klineHidden ? '显示K线' : '隐藏K线');
    this.errorEl = h('div', { class: 'rt-error', hidden: true });
    this.indicesEl = h('div', { class: 'rt-index-strip' });
    this.topPickEl = h('div', { class: 'rt-toppick panel-block' });

    // 左：5m K 线
    this.klineTitle = h('span', { class: 'rt-k-title' }, '5分钟K线 · —');
    this.klineAsOf = h('span', { class: 'chip dim' }, '数据截至 —');
    this.hideBtn = h('button', { class: 'btn btn-xs ghost', onclick: () => this.toggleKline() }, this.klineHidden ? '显示K线' : '隐藏K线');
    this.chartHost = h('div', { class: 'rt-dual-host' });
    this.klineOverlay = h('div', { class: 'rt-k-overlay', hidden: true });
    this.leftPanel = h('div', { class: 'rt-v2-left panel-block' },
      h('div', { class: 'rt-k-head' }, this.klineTitle, this.klineAsOf,
        h('span', { class: 'spacer' }), this.hideBtn),
      h('div', { class: 'rt-k-body' }, this.chartHost, this.klineOverlay));

    // 右：策略卡 + 列表
    this.strategyEl = h('div', { class: 'rt-strategy panel-block' });
    this.holdingsTodayEl = h('div', { class: 'rt-panel-block' });
    this.candidatesTomorrowEl = h('div', { class: 'rt-panel-block' });
    this.closedEl = h('details', { class: 'rt-weak' });
    this.manualEl = h('details', { class: 'rt-weak' });
    this.rightScroll = h('div', { class: 'rt-v2-scroll' },
      this.holdingsTodayEl, this.candidatesTomorrowEl, this.closedEl, this.manualEl);
    this.rightPanel = h('div', { class: 'rt-v2-right' }, this.strategyEl, this.rightScroll);

    this.bodyEl = h('div', { class: 'rt-v2-body' }, this.leftPanel, this.rightPanel);
    this.pageEl = h('div', { class: 'view-pad rt-page rt-v2' + (this.klineHidden ? ' kline-hidden' : '') },
      h('div', { class: 'rt-head' },
        h('div', {}, h('div', { class: 'page-title' }, '实时看盘'),
          h('div', { class: 'page-sub' }, '5 分钟 K 线 + 当日策略 / 今日持仓(T) / 明日预选(T-1) · tqcenter 快照 2s 轮询 · 只判断不下单')),
        h('div', { class: 'spacer' }),
        h('div', { class: 'rt-chips' }, this.marketChip, this.timeChip, this.envChip, this.pollChip, this.toggleBtn,
          h('button', { class: 'btn btn-xs ghost', onclick: () => this.load() }, '立即刷新'))),
      this.errorEl, this.indicesEl, this.topPickEl, this.bodyEl);
    this.root.appendChild(this.pageEl);
    this._bindVisibility();
  }

  /* ---------------- data ---------------- */
  async load() {
    if (this.loading) return;
    this.loading = true;
    try {
      const d = await API.realtime();
      this.data = d || {};
      this._render();
      await this._syncSelectionAndKline();
    } catch (e) {
      this._renderError(String((e && e.message) || e));
    } finally {
      this.loading = false;
    }
  }

  _renderError(msg) {
    this.errorEl.hidden = false;
    clear(this.errorEl);
    this.errorEl.appendChild(h('span', {}, '实时行情加载失败：' + msg));
    this.errorEl.appendChild(h('button', { class: 'btn btn-xs', onclick: () => this.load() }, '重试'));
    this.pollChip.textContent = '轮询失败 · ' + new Date().toLocaleTimeString('zh-CN', { hour12: false });
  }

  _render() {
    const d = this.data || {};
    if (d.error) {
      this.errorEl.hidden = false;
      clear(this.errorEl);
      this.errorEl.appendChild(h('span', {}, '实时行情提示：' + d.error));
      if (!(d.tq && d.tq.ready)) {
        this.errorEl.appendChild(h('span', { class: 'muted' }, '（tqcenter 未连接；其它页面不受影响，恢复后自动继续）'));
      }
    } else {
      this.errorEl.hidden = true;
    }

    const ms = d.marketState || '—';
    this.marketChip.textContent = `市场 ${ms}${d.marketLabel ? ' · ' + d.marketLabel : ''}`;
    this.marketChip.className = 'chip ' + (ms === '盘中' ? 'ok' : 'dim');
    this.timeChip.textContent = `数据时间 ${fmtDateTime(d.time)}`;
    const env = d.env || {};
    this.envChip.textContent = env.label || 'T-1环境 — · 盘中宽度 —';
    this.envChip.className = 'chip ' + (env.t1 === '好' ? 'ok' : env.t1 === '差' ? 'warn' : 'dim');
    this.envChip.title = env.date ? `T-1 ${env.date}：成长端 ${env.above}/${env.total} 在日线 MA60 上；盘中宽度 ${env.breadth}/${env.breadthTotal}` : '';
    this.pollChip.textContent = '2s 轮询';

    this._renderIndices(d.indices || []);
    this._renderTopPicks(d);
    this._renderStrategy(d.strategy, d);
    this._renderHoldingsToday(d.holdingsToday || [], d.strategy);
    this._renderCandidatesTomorrow(d.candidatesTomorrow || [], d.strategy);
    this._renderClosed(d.closedYesterday || [], d.strategy);
    this._renderManualHoldings(d.holdings || []);
  }

  _renderIndices(list) {
    clear(this.indicesEl);
    if (!list.length) {
      this.indicesEl.appendChild(h('div', { class: 'empty-box' }, '指数行情加载中…'));
      return;
    }
    for (const it of list) {
      const chg = n(it.zaf);
      this.indicesEl.appendChild(h('div', { class: 'rt-idx' + (it.growth ? ' growth' : '') },
        h('div', { class: 'nm' }, it.name),
        h('div', { class: 'px ' + priceCls(chg) }, it.now == null ? '—' : fmt(it.now, 2)),
        h('div', { class: 'chg ' + priceCls(chg) }, chg == null ? '—' : pct(chg, 2) + '%')));
    }
  }

  _renderTopPicks(d) {
    clear(this.topPickEl);
    const picks = d.topPicks || [];
    const closed = ['收盘', '休市'].includes(d.marketState) || !d.topPickNow;
    this.topPickEl.appendChild(h('div', { class: 'rt-toppick-head' },
      h('span', { class: 'rt-toppick-title' }, '实时最该买'),
      h('span', { class: 'chip dim', title: '评分 = 涨幅×45% + 现价/开盘×25% + 现价/均价×20% + 涨速×10%；仅参考，不下单' }, '参考 · 2s'),
      h('span', { class: 'spacer' }),
      h('span', { class: 'chip ' + (d.marketState === '盘中' ? 'ok' : 'dim') }, d.marketState || '—')));
    if (closed) {
      this.topPickEl.appendChild(h('div', { class: 'rt-tp-empty' },
        d.marketState === '收盘' ? '收盘——明日名单见下（14:45 预生成 / 15:50 正式）' : '暂无实时候选'));
      return;
    }
    const p = picks[0];
    this.topPickEl.appendChild(h('div', { class: 'rt-tp-body' },
      h('div', { class: 'rt-tp-first', title: '点击切换左侧 K 线', onclick: () => this.selectCode(p.code, p.name) },
        h('span', { class: 'rt-tp-code' }, p.code),
        h('span', { class: 'rt-tp-name' }, p.name || '—'),
        h('span', { class: 'rt-tp-price ' + priceCls(p.zaf) }, p.now == null ? '—' : fmt(p.now, 2)),
        h('span', { class: 'rt-tp-chg ' + priceCls(p.zaf) }, p.zaf == null ? '—' : pct(p.zaf, 2) + '%'),
        h('span', { class: 'rt-tp-score' }, `评分 ${fmt(p.score, 1)}`)),
      h('div', { class: 'rt-tp-reason', title: p.reason || '' }, p.reason || ''),
      picks.length > 1 ? h('div', { class: 'rt-tp-rest' },
        ...picks.slice(1).map((x) => h('span', {
          class: 'rt-tp-mini', title: '点击切换左侧 K 线',
          onclick: () => this.selectCode(x.code, x.name),
        }, `${x.code} ${x.name || ''} `, h('b', { class: priceCls(x.zaf) }, x.zaf == null ? '—' : pct(x.zaf, 2) + '%')))) : null));
  }

  _renderStrategy(strategy, d) {
    clear(this.strategyEl);
    if (!strategy) {
      this.strategyEl.appendChild(h('div', { class: 'empty-box' }, '当日策略加载中…'));
      return;
    }
    const nd = (d && d.nextDay) || {};
    const env = strategy.env || {};
    const todayStr = String(nd.today || '').replace(/-/g, '');
    const nextStr = String(nd.nextTradeDate || '').replace(/-/g, '');
    const buyD = String(nd.buyDate || nd.buyDateLabel || '').replace(/-/g, '');
    const sellD = String(nd.forTradeDate || nd.forTradeDateLabel || '').replace(/-/g, '');
    const buyTag = todayStr && buyD === todayStr ? '（今日尾盘）' : '（尾盘买入）';
    const sellTag = nextStr && sellD === nextStr
      ? '（下一交易日）'
      : (todayStr && sellD === todayStr ? '（今日卖出）' : '（卖出日）');
    const envText = env.t1
      ? `T-1 环境 ${env.t1}（成长端 ${env.above}/${env.total} 在日线 MA60 上）`
      : 'T-1 环境 数据缺失';
    const actionCls = strategy.actionType === 'hold' ? 'act-hold'
      : strategy.actionType === 'bplus-pending' ? 'act-bplus-pending'
        : strategy.actionType === 'bplus-hold' ? 'act-bplus-hold' : 'act-bplus-sell';
    const sellPlan = (d && d.nextDay && d.nextDay.sellPlan) || strategy.sellPlan || {};

    const headChips = [h('span', { class: 'chip dim' }, `${strategy.name || 'TPO_M5'} · 文件 ${strategy.fileDateLabel || '—'}`)];
    if (nd.source === 'preclose') {
      headChips.push(h('span', { class: 'chip warn', title: nd.label || '' }, '14:45 预生成（尾盘买入用）'));
    } else if (nd.available) {
      headChips.push(h('span', { class: 'chip dim' }, '每日更新正式名单'));
    }
    if (nd.available) {
      headChips.push(h('span', { class: 'chip ok' },
        `买入日 ${nd.buyDateLabel || '—'} → 卖出日 ${nd.forTradeDateLabel || '—'}`));
    } else {
      headChips.push(h('span', {
        class: 'chip warn', title: nd.reason || 'AIData/NEXT_DAY/strategy.json 未生成或已过期',
      }, '名单未生成（等每日更新）'));
    }
    this.strategyEl.appendChild(h('div', { class: 'rt-strategy-head' },
      h('span', { class: 'rt-strategy-title' }, '当日策略'),
      ...headChips,
      h('span', { class: 'spacer' }),
      h('span', { class: 'chip dim' }, `T ${strategy.tDateLabel || '—'} · T-1 ${strategy.t1DateLabel || '—'}`)));

    if (nd.available) {
      this.strategyEl.appendChild(h('div', { class: 'rt-strategy-dates' },
        h('span', { class: 'chip ok' }, `买入日 ${nd.buyDateLabel || '—'}${buyTag}`),
        h('span', { class: 'date-arrow' }, '→'),
        h('span', { class: 'chip ok' }, `卖出日 ${nd.forTradeDateLabel || '—'}${sellTag}`),
        nd.generatedAt ? h('span', { class: 'muted', style: 'font-size:10px' }, `生成于 ${String(nd.generatedAt).replace('T', ' ').slice(0, 19)}`) : null));
      const fp = nd.firstPick;
      if (fp && fp.code) {
        this.strategyEl.appendChild(h('div', {
          class: 'rt-firstpick', title: '点击切换左侧 K 线',
          onclick: () => this.selectCode(fp.code, fp.name),
        },
        h('span', { class: 'fp-badge' }, todayStr && buyD === todayStr ? '今日尾盘首选' : '尾盘首选'),
        h('b', {}, `${fp.code} ${fp.name || ''}`),
        h('span', { class: 'fp-price' }, `买入价 ${fp.buyPrice == null ? '—' : fmt(fp.buyPrice, 2)}`),
        fp.marketValue != null ? h('span', { class: 'muted' }, `市值 ${fmt(fp.marketValue / 1e8, 2)} 亿`) : null));
      }
    } else {
      this.strategyEl.appendChild(h('div', { class: 'rt-strategy-dates' },
        h('span', { class: 'chip warn', title: nd.reason || '' }, nd.reason || '名单未生成（等每日更新）'),
        h('span', { class: 'muted', style: 'font-size:10px' }, '当前回退：最新 STRATEGY 文件 T / T-1 拆分')));
    }

    if (sellPlan && sellPlan.mode) {
      this.strategyEl.appendChild(h('div', { class: 'rt-sellplan' },
        h('span', { class: 'bplus-badge' }, `明日卖法：${sellPlan.mode}`),
        h('span', {}, sellPlan.rule || '差环境10:00宽度≥4抗/≤3卖；-5%止损；涨停价优先'),
        sellPlan.breadth1000 != null ? h('span', { class: 'muted' }, `10:00 宽度 ${sellPlan.breadth1000}/7`) : null));
    }

    this.strategyEl.appendChild(h('div', { class: 'rt-strategy-env' },
      h('span', { class: 'chip ' + (env.t1 === '好' ? 'ok' : env.t1 === '差' ? 'warn' : 'dim') }, envText),
      h('span', { class: 'chip ' + ((strategy.breadth || 0) >= 4 ? 'ok' : 'warn') },
        `盘中宽度 ${strategy.breadth == null ? '—' : strategy.breadth}/${strategy.breadthTotal || 7}`)));
    this.strategyEl.appendChild(h('div', { class: 'rt-action ' + actionCls }, strategy.actionText || '—'));
    this.strategyEl.appendChild(h('details', { class: 'rt-rule' },
      h('summary', {}, '规则摘要'),
      h('div', {}, strategy.ruleText || '买点：T-1 尾盘买入；卖点：14:55 / 涨停 / 止损优先；仓位：环境差 B+ 半仓。')));
  }

  _panelHead(title, hint, count) {
    return h('div', { class: 'panel-head rt-v2-panel-head' },
      h('span', {}, title), h('span', { class: 'hint' }, hint || ''),
      h('span', { class: 'spacer' }), h('span', { class: 'rt-count' }, `${count} 只`));
  }

  _selectOnClick(tr, code, name) {
    tr.addEventListener('click', () => this.selectCode(code, name));
  }

  /** 今日持仓 / 候选股共用同一套 7 列 + 同一套列宽：代码|名称|现价|涨跌幅|成本|判断|理由 */
  _listColgroup() {
    return h('colgroup', {},
      h('col', { style: 'width:92px' }),
      h('col', { style: 'width:88px' }),
      h('col', { style: 'width:76px' }),
      h('col', { style: 'width:84px' }),
      h('col', { style: 'width:84px' }),
      h('col', { style: 'width:96px' }),
      h('col', {}));  // 理由：剩余自适应
  }

  _listTable(rows, mode) {
    const isHold = mode === 'hold';
    const tb = h('tbody', {});
    for (const r of rows) {
      const chg = isHold ? r.pnlPct : r.zaf;
      const signal = isHold ? r.sellSignal : r.signal;
      const reason = isHold ? r.sellReason : r.reason;
      const note = isHold ? r.sellNote : null;
      const reasonText = [reason, note].filter(Boolean).join('；');
      const tr = h('tr', { class: 'rt-row' + (r.code === this.selectedCode ? ' sel' : '') + (isHold && r.firstPick ? ' first-pick' : '') },
        h('td', { class: 'code' }, r.code),
        h('td', { class: 'name' }, r.name || '—', isHold && r.firstPick ? h('span', { class: 'first-badge' }, '首选') : null),
        h('td', { class: 'num ' + priceCls(r.zaf) }, r.now == null ? '—' : fmt(r.now, 2)),
        h('td', { class: 'num ' + priceCls(chg) }, chg == null ? '—' : pct(chg, 2) + '%'),
        h('td', { class: 'num' + (isHold && r.cost != null ? '' : ' muted') },
          isHold && r.cost != null ? fmt(r.cost, 2) : '—'),
        h('td', { class: 'sig-cell' },
          h('span', { class: sigClass(signal), title: signal || '' }, sigLabel(signal) || '—'),
          !isHold && r.limitUp ? h('span', { class: 'sig sig-limit', style: 'margin-left:4px' }, '涨停') : null),
        h('td', { class: 'rt-reason', title: reasonText || '' }, reasonText || '—'));
      this._selectOnClick(tr, r.code, r.name);
      tb.appendChild(tr);
    }
    return h('div', { class: 'rt-table-scroll' },
      h('table', { class: 'tbl rt-tbl rt-list-tbl' },
        this._listColgroup(),
        h('thead', {}, h('tr', {},
          h('th', { class: 'l' }, '代码'),
          h('th', { class: 'l' }, '名称'),
          h('th', { class: 'num' }, '现价'),
          h('th', { class: 'num' }, '涨跌幅'),
          h('th', { class: 'num' }, '成本'),
          h('th', { class: 'l' }, '判断'),
          h('th', { class: 'l' }, '理由'))),
        tb));
  }

  _renderHoldingsToday(rows, strategy) {
    clear(this.holdingsTodayEl);
    const nd = (this.data && this.data.nextDay) || {};
    const dateHint = nd.available
      ? `买入日 ${nd.buyDateLabel || '—'} → 卖出日 ${nd.forTradeDateLabel || '—'}`
      : (strategy && strategy.tDateLabel ? `今日 ${strategy.tDateLabel} 卖出` : '今日卖出');
    const title = nd.available ? '今日持仓 · 明日卖出' : '今日持仓 · 昨日尾盘买入（今日卖出）';
    const bplusHint = (nd.sellPlan && nd.sellPlan.mode ? ` · 明日卖法：${nd.sellPlan.mode}` : '');
    this.holdingsTodayEl.appendChild(this._panelHead(title, dateHint + bplusHint, rows.length));
    if (!rows.length) {
      this.holdingsTodayEl.appendChild(h('div', { class: 'empty-box' },
        nd.available ? '名单为空（NEXT_DAY buyList 无股票）' : '今日空仓（昨日名单为空）'));
      return;
    }
    this.holdingsTodayEl.appendChild(this._listTable(rows, 'hold'));
  }

  _renderCandidatesTomorrow(rows, strategy) {
    clear(this.candidatesTomorrowEl);
    const nd = (this.data && this.data.nextDay) || {};
    const hint = nd.available
      ? `${nd.forTradeDateLabel || '—'} 之后（后日预选）`
      : (strategy && strategy.t1DateLabel ? `${strategy.t1DateLabel} 盘后确认` : '明日盘后确认');
    const title = nd.available ? '候选股 · 后日预选' : '候选股 · 明日预选';
    this.candidatesTomorrowEl.appendChild(this._panelHead(title, hint, rows.length));
    if (!rows.length) {
      this.candidatesTomorrowEl.appendChild(h('div', { class: 'empty-box' },
        nd.available ? '后日预选为空（NEXT_DAY candidates 为空）' : '明日预选为空（T-1 窗口无候选）'));
      return;
    }
    this.candidatesTomorrowEl.appendChild(this._listTable(rows, 'cand'));
  }

  _renderClosed(rows, strategy) {
    clear(this.closedEl);
    const label = strategy && strategy.fileDateLabel ? strategy.fileDateLabel : '—';
    const sum = h('summary', {}, `昨日已了结（T-0 · ${label}，复盘用）`, h('span', { class: 'rt-weak-count' }, `${rows.length} 只`));
    this.closedEl.appendChild(sum);
    if (!rows.length) {
      this.closedEl.appendChild(h('div', { class: 'empty-box' }, '昨日无已了结记录'));
      return;
    }
    const tb = h('tbody', {});
    for (const r of rows) {
      const tr = h('tr', { class: 'rt-row' + (r.code === this.selectedCode ? ' sel' : '') },
        h('td', { class: 'code' }, r.code),
        h('td', { class: 'name' }, r.name || '—'),
        h('td', { class: 'num ' + priceCls(r.chg) }, r.chg == null ? '—' : pct(r.chg, 2) + '%'),
        h('td', { class: 'num ' + priceCls(r.sellChg5m) }, r.sellChg5m == null ? '—' : pct(r.sellChg5m, 2) + '%'),
        h('td', { class: 'num' }, r.mcap == null ? '—' : fmt(r.mcap, 2)));
      this._selectOnClick(tr, r.code, r.name);
      tb.appendChild(tr);
    }
    this.closedEl.appendChild(h('table', { class: 'tbl rt-tbl' },
      h('thead', {}, h('tr', {},
        h('th', { class: 'l' }, '代码'), h('th', { class: 'l' }, '名称'), h('th', { class: 'num' }, '涨跌幅%'),
        h('th', { class: 'num' }, '实际卖出%(5m)'), h('th', { class: 'num' }, '市值(亿)'))),
      tb));
  }

  _renderManualHoldings(rows) {
    clear(this.manualEl);
    this.manualEl.appendChild(h('summary', {}, `我的持仓（holdings.json 手动，${rows.length} 只）`));
    this.manualEl.appendChild(h('div', { class: 'rt-manual-form' },
      this._buildHoldForm()));
    if (!rows.length) {
      this.manualEl.appendChild(h('div', { class: 'empty-box' }, '暂无手动持仓（可上方添加，或直接编辑 dashboard/holdings.json）'));
      return;
    }
    const tb = h('tbody', {});
    for (const r of rows) {
      tb.appendChild(h('tr', { class: 'rt-row' },
        h('td', { class: 'code' }, r.code),
        h('td', { class: 'name' }, r.name || '—'),
        h('td', { class: 'num' }, r.cost == null ? '—' : fmt(r.cost, 2)),
        h('td', { class: 'num ' + priceCls(r.zaf) }, r.now == null ? '—' : fmt(r.now, 2)),
        h('td', { class: 'num ' + priceCls(r.pnlPct) }, r.pnlPct == null ? '—' : pct(r.pnlPct, 2) + '%'),
        h('td', { class: 'rt-sig' }, h('span', { class: sigClass(r.signal) }, r.signal || '—')),
        h('td', { class: 'ops' }, h('button', {
          class: 'btn btn-xs ghost danger', title: '删除该持仓',
          onclick: (e) => { e.stopPropagation(); this._removeHolding(r.code); },
        }, '删除'))));
    }
    this.manualEl.appendChild(h('table', { class: 'tbl rt-tbl' },
      h('thead', {}, h('tr', {},
        h('th', { class: 'l' }, '代码'), h('th', { class: 'l' }, '名称'), h('th', { class: 'num' }, '成本'),
        h('th', { class: 'num' }, '现价'), h('th', { class: 'num' }, '盈亏%'), h('th', { class: 'c' }, '判断'),
        h('th', { class: 'c' }, '操作'))),
      tb));
  }

  _buildHoldForm() {
    this.codeInput = h('input', { class: 'input rt-in-code', placeholder: '代码 600118.SH' });
    this.costInput = h('input', { class: 'input rt-in-num', placeholder: '成本' });
    this.qtyInput = h('input', { class: 'input rt-in-num', placeholder: '数量' });
    return h('form', { class: 'rt-hold-form', onsubmit: (e) => { e.preventDefault(); this._addHolding(); } },
      this.codeInput, this.costInput, this.qtyInput,
      h('button', { class: 'btn btn-xs btn-primary', type: 'submit' }, '添加 / 更新'));
  }

  /* ---------------- selection / kline ---------------- */
  async _syncSelectionAndKline() {
    const d = this.data || {};
    const today = d.holdingsToday || [];
    const tomorrow = d.candidatesTomorrow || [];
    const weak = d.closedYesterday || [];
    const pool = today.length ? today : tomorrow;
    let code = this.selectedCode;
    let name = this.selectedName;
    if (!code && pool.length) {
      code = pool[0].code;
      name = pool[0].name || '';
    }
    if (code) {
      const hit = [...today, ...tomorrow, ...weak].find((r) => r.code === code);
      if (hit && hit.name) name = hit.name;
      if (code !== this.selectedCode || !this.klineData) {
        this.selectedCode = code;
        this.selectedName = name || '';
        await this.loadKline(code, name, { silent: false });
        return;
      }
      this.selectedName = name || this.selectedName;
      const now = Date.now();
      if (this._visible && now - this.klineAt > KLINE_REFRESH_MS) {
        this.loadKline(code, name, { silent: true });
      }
    }
  }

  selectCode(code, name) {
    if (!code) return;
    if (code === this.selectedCode && this.klineData) {
      this.selectedName = name || this.selectedName;
      this._highlightRows();
      return;
    }
    this.selectedCode = code;
    this.selectedName = name || '';
    this._highlightRows();
    this.loadKline(code, name, { silent: false });
  }

  _highlightRows() {
    for (const tr of this.rightScroll.querySelectorAll('tr.rt-row')) {
      const td = tr.querySelector('td.code');
      tr.classList.toggle('sel', !!(td && td.textContent === this.selectedCode));
    }
  }

  _setKlineOverlay(text, kind = 'loading') {
    clear(this.klineOverlay);
    if (!text) { this.klineOverlay.hidden = true; return; }
    this.klineOverlay.hidden = false;
    if (kind === 'loading') this.klineOverlay.appendChild(h('div', { class: 'spin' }));
    this.klineOverlay.appendChild(h('div', { class: 't' }, text));
  }

  async loadKline(code, name, { silent = false } = {}) {
    const token = ++this.klineToken;
    if (!silent) this._setKlineOverlay('K 线加载中…', 'loading');
    try {
      const [five, daily] = await Promise.all([
        API.realtimeKline(code),
        API.kline(code, '1d', 600).catch(() => ({ ok: false, bars: [] })),
      ]);
      if (token !== this.klineToken) return;
      this.klineData = five;
      this.dailyData = daily;
      this.klineCode = code;
      this.klineAt = Date.now();
      if (five && five.name && !name) this.selectedName = five.name;
      this._updateKlineTitle();
      this._setKlineOverlay('');
      if (!this.klineHidden) this.renderDual();
    } catch (e) {
      if (token !== this.klineToken) return;
      this.klineData = null;
      this.dailyData = null;
      this._setKlineOverlay('K 线加载失败：' + ((e && e.message) || e), 'error');
    }
  }

  _updateKlineTitle() {
    if (this.klineTitle) {
      this.klineTitle.textContent = `双周期K线 · ${this.klineCode || '—'} ${this.selectedName || ''}`;
    }
    if (this.klineAsOf) {
      const d = this.klineData;
      if (d && d.ok) {
        this.klineAsOf.textContent = `数据截至 ${d.asOf || '—'}${d.hasToday ? '' : '（今日 5m 未落盘）'}`;
        this.klineAsOf.className = 'chip ' + (d.hasToday ? 'dim' : 'warn');
        this.klineAsOf.title = d.source === 'tdx-lc5' ? '来源：TDX vipdoc/fzline .lc5' : '来源：AIData/5M';
      } else {
        this.klineAsOf.textContent = '数据截至 —';
        this.klineAsOf.className = 'chip dim';
      }
    }
  }

  renderDual() {
    const five = this.klineData;
    const daily = this.dailyData;
    const fiveBars = (five && five.ok && five.bars) || [];
    const dailyBars = (daily && daily.ok && daily.bars) || [];
    if (!fiveBars.length && !dailyBars.length) {
      this._setKlineOverlay((five && (five.error || five.reason)) || '该股无 K 线数据', 'error');
      return;
    }
    if (!this.dual) this.dual = new RealtimeDualChart(this.chartHost);
    try {
      this.dual.render({ code: this.klineCode, dailyBars, fiveBars });
      this._setKlineOverlay('');
    } catch (e) {
      this._setKlineOverlay('图表渲染失败：' + ((e && e.message) || e), 'error');
    }
  }

  toggleKline(force) {
    this.klineHidden = force == null ? !this.klineHidden : !!force;
    this._saveKlineHidden();
    this.pageEl.classList.toggle('kline-hidden', this.klineHidden);
    if (this.toggleBtn) this.toggleBtn.textContent = this.klineHidden ? '显示K线' : '隐藏K线';
    if (this.hideBtn) this.hideBtn.textContent = this.klineHidden ? '显示K线' : '隐藏K线';
    if (!this.klineHidden) this.renderDual();
  }

  /* ---------------- manual holdings（holdings.json） ---------------- */
  _currentHoldings() {
    return (this.data && this.data.holdings ? this.data.holdings : []).map((x) => {
      const row = { code: x.code };
      if (x.cost != null) row.cost = x.cost;
      if (x.qty != null) row.qty = x.qty;
      if (x.name) row.name = x.name;
      return row;
    });
  }

  async _save(rows, okMsg) {
    if (this._saving) return;
    this._saving = true;
    try {
      await API.saveHoldings(rows);
      if (okMsg) toast(okMsg, 'ok', 1800);
      await this.load();
    } catch (e) {
      toast('保存持仓失败：' + ((e && e.message) || e), 'err', 3200);
    } finally {
      this._saving = false;
    }
  }

  _addHolding() {
    const code = (this.codeInput.value || '').trim().toUpperCase();
    if (!CODE_RE.test(code)) { toast('代码格式应为 600118.SH / 000001.SZ', 'err'); return; }
    const costRaw = (this.costInput.value || '').trim();
    const qtyRaw = (this.qtyInput.value || '').trim();
    const cost = costRaw === '' ? null : Number(costRaw);
    const qty = qtyRaw === '' ? null : Number(qtyRaw);
    if (costRaw !== '' && (!Number.isFinite(cost) || cost <= 0)) { toast('成本需为正数', 'err'); return; }
    if (qtyRaw !== '' && (!Number.isFinite(qty) || qty <= 0)) { toast('数量需为正数', 'err'); return; }
    const rows = this._currentHoldings();
    const idx = rows.findIndex((r) => r.code === code);
    const row = { code };
    if (cost != null) row.cost = cost;
    if (qty != null) row.qty = qty;
    if (idx >= 0) rows[idx] = Object.assign({}, rows[idx], row);
    else rows.push(row);
    this._save(rows, `持仓已保存：${code}`).then(() => {
      this.codeInput.value = '';
      this.costInput.value = '';
      this.qtyInput.value = '';
    });
  }

  async _removeHolding(code) {
    const ok = await modalConfirm(`确定删除持仓 ${code}？`, { title: '删除持仓', okText: '删除', danger: true });
    if (!ok) return;
    this._save(this._currentHoldings().filter((r) => r.code !== code), `已删除持仓：${code}`);
  }
}
