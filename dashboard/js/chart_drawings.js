/* 专业画线组件：多工具 + 属性条 + 拖动/选中 + 撤销重做 + localStorage（page+code+period）。 */
const COLORS = ['#f5c518', '#ef4444', '#60a5fa', '#34d399', '#c084fc', '#fb923c', '#22d3ee', '#f8fafc'];
const WIDTHS = [1, 2, 3];
const STYLES = [{ id: 'solid', label: '实' }, { id: 'dashed', label: '虚' }, { id: 'dotted', label: '点' }];
const TOOLS = [
  { id: 'cursor', icon: '↖', label: '选择 / 光标（拖动端点或整体）' },
  { id: 'h', icon: '—', label: '水平线（支撑/压力）' },
  { id: 'v', icon: '│', label: '垂直线' },
  { id: 'trend', icon: '╱', label: '趋势线（两点）' },
  { id: 'ray', icon: '↗', label: '射线（两点向前延伸）' },
  { id: 'channel', icon: '∥', label: '平行通道（三点）' },
  { id: 'fib', icon: 'F', label: '斐波那契回撤（0/23.6/38.2/50/61.8/78.6/100）' },
  { id: 'rect', icon: '▭', label: '矩形' },
  { id: 'text', icon: 'T', label: '文本标注' },
  { id: 'measure', icon: '↔', label: '测量（价差/涨跌幅）' },
];
const NEED = { h: 1, v: 1, trend: 2, ray: 2, channel: 3, fib: 2, rect: 2, text: 1, measure: 2 };
const FIB = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1];
const svgNS = 'http://www.w3.org/2000/svg';
const mkSvg = (tag, attrs = {}) => { const el = document.createElementNS(svgNS, tag); for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v); return el; };

export class ChartDrawings {
  constructor(container, opts = {}) {
    this.container = container;
    this.pageKey = opts.pageKey || 'page';
    this.code = opts.code || '';
    this.period = opts.period || '1d';
    this.storageKey = opts.storageKey || null;
    this.chart = null;
    this.series = null;
    this.bars = [];
    this.drawings = [];
    this.tool = 'cursor';
    this.selected = null;
    this.style = { color: COLORS[0], width: 1, lineStyle: 'solid' };
    this.magnet = false;
    this._tmp = [];
    this._drag = null;
    this._undo = [];
    this._redo = [];
    this._active = false;
    this._svg = mkSvg('svg', { class: 'cd-svg' });
    if (getComputedStyle(container).position === 'static') container.style.position = 'relative';
    container.appendChild(this._svg);
    container.tabIndex = 0;
    container.classList.add('cd-focusable');
    this._buildUI();
    this._bind();
    this.load();
  }

  _buildUI() {
    this.toolbarEl = document.createElement('div');
    this.toolbarEl.className = 'cd-toolbar';
    for (const t of TOOLS) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'cd-tool' + (t.id === this.tool ? ' on' : '');
      b.title = t.label;
      b.textContent = t.icon;
      b.dataset.tool = t.id;
      b.addEventListener('click', (ev) => { ev.stopPropagation(); this.setTool(t.id); });
      this.toolbarEl.appendChild(b);
    }
    this.collapseBtn = document.createElement('button');
    this.collapseBtn.type = 'button';
    this.collapseBtn.className = 'cd-tool cd-collapse';
    this.collapseBtn.title = '折叠/展开工具栏';
    this.collapseBtn.textContent = '⌃';
    this.collapseBtn.addEventListener('click', (ev) => { ev.stopPropagation(); this.toolbarEl.classList.toggle('collapsed'); });
    this.toolbarEl.appendChild(this.collapseBtn);

    this.propsEl = document.createElement('div');
    this.propsEl.className = 'cd-props';
    this.swatches = [];
    for (const c of COLORS) {
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'cd-swatch' + (c === this.style.color ? ' on' : '');
      b.style.background = c; b.title = '颜色 ' + c;
      b.addEventListener('click', (ev) => { ev.stopPropagation(); this._applyStyle({ color: c }); });
      this.propsEl.appendChild(b); this.swatches.push([c, b]);
    }
    const sep = document.createElement('span');
    sep.className = 'cd-sep'; this.propsEl.appendChild(sep);
    this.widthBtns = WIDTHS.map((w) => {
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'cd-w' + (w === this.style.width ? ' on' : '');
      b.textContent = String(w); b.title = '线宽 ' + w;
      b.addEventListener('click', (ev) => { ev.stopPropagation(); this._applyStyle({ width: w }); });
      this.propsEl.appendChild(b); return [w, b];
    });
    this.styleBtns = STYLES.map((s) => {
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'cd-style' + (s.id === this.style.lineStyle ? ' on' : '');
      b.textContent = s.label; b.title = '线型 ' + s.label;
      b.addEventListener('click', (ev) => { ev.stopPropagation(); this._applyStyle({ lineStyle: s.id }); });
      this.propsEl.appendChild(b); return [s.id, b];
    });
    const magnet = document.createElement('label');
    magnet.className = 'cd-magnet';
    this.magnetCb = document.createElement('input');
    this.magnetCb.type = 'checkbox'; this.magnetCb.checked = false;
    this.magnetCb.addEventListener('change', () => { this.magnet = this.magnetCb.checked; });
    magnet.appendChild(this.magnetCb); magnet.appendChild(document.createTextNode('吸附OHLC'));
    this.propsEl.appendChild(magnet);
    this.undoBtn = this._iconBtn('撤销', '撤销 Ctrl+Z', () => this.undo());
    this.redoBtn = this._iconBtn('重做', '重做 Ctrl+Y', () => this.redo());
    this.delBtn = this._iconBtn('删除', '删除选中 Del', () => this.deleteSelected());
    this.clearBtn = this._iconBtn('清空', '清空全部（需确认，清空后可撤销）', () => this.clearAll());
    for (const b of [this.undoBtn, this.redoBtn, this.delBtn, this.clearBtn]) this.propsEl.appendChild(b);
  }

  _iconBtn(txt, title, fn) {
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'cd-icon'; b.title = title; b.textContent = txt;
    b.addEventListener('click', (ev) => { ev.stopPropagation(); fn(); });
    return b;
  }

  _bind() {
    this.container.addEventListener('pointerenter', () => { this._active = true; });
    this.container.addEventListener('pointerleave', () => { if (!this._drag) this._active = false; });
    this.container.addEventListener('pointerdown', (ev) => this._onDown(ev), true);
    this.container.addEventListener('pointermove', (ev) => this._onMove(ev), true);
    this.container.addEventListener('pointerup', (ev) => this._onUp(ev), true);
    this.container.addEventListener('pointerdown', () => { this._active = true; try { this.container.focus({ preventScroll: true }); } catch (e) { /* ignore */ } });
    this.container.addEventListener('click', (ev) => { const ui = ev.target && ev.target.closest && ev.target.closest('.cd-toolbar, .cd-props'); if (this.tool !== 'cursor' && !ui) ev.stopPropagation(); }, true);
    this.container.addEventListener('keydown', (ev) => { this._active = true; this._onKey(ev, true); ev.stopPropagation(); });
    document.addEventListener('keydown', (ev) => this._onKey(ev));
  }

  _key() { return this.storageKey || `marco.draw.${this.pageKey}.${this.code}.${this.period}`; }
  load() {
    try {
      const raw = JSON.parse(localStorage.getItem(this._key()) || '[]') || [];
      this.drawings = raw.map((d) => this._normalize(d)).filter(Boolean);
    } catch (e) { this.drawings = []; }
    this.render();
  }
  save() { try { localStorage.setItem(this._key(), JSON.stringify(this.drawings)); } catch (e) { /* ignore */ } }

  _normalize(d) {
    if (!d || !d.type) return null;
    if (d.type === 'h' && d.points) return d;
    if (d.type === 'h' && d.price != null) return { type: 'h', points: [{ price: d.price }], color: '#f5c518', width: 1, lineStyle: 'solid' };
    if (d.type === 't' && d.p1) return { type: 'trend', points: [d.p1, d.p2], color: '#f5c518', width: 1, lineStyle: 'solid' };
    return d;
  }

  setTool(tool) {
    this.tool = tool; this._tmp = [];
    for (const b of this.toolbarEl.querySelectorAll('.cd-tool')) b.classList.toggle('on', b.dataset.tool === tool);
    this.container.classList.toggle('cd-drawing', tool !== 'cursor');
  }

  setChart(chart, series) {
    this.chart = chart; this.series = series;
    if (chart && !this._rangeBound) {
      try { chart.timeScale().subscribeVisibleTimeRangeChange(() => this.render()); } catch (e) { /* ignore */ }
      this._rangeBound = true;
    }
    this.render();
  }
  setBars(bars) { this.bars = bars || []; }
  setContext({ pageKey, code, period }) {
    const p = pageKey || this.pageKey, c = code || '', pe = period || '1d';
    if (p === this.pageKey && c === this.code && pe === this.period) { this.render(); return; }
    this.pageKey = p; this.code = c; this.period = pe;
    this.selected = null; this._tmp = [];
    this.load();
  }

  _xy(point) {
    if (!this.chart || !this.series) return null;
    let x = null, y = null;
    try { x = this.chart.timeScale().timeToCoordinate(point.time); } catch (e) { x = null; }
    try { y = this.series.priceToCoordinate(point.price); } catch (e) { y = null; }
    return (x == null || y == null) ? null : { x, y };
  }

  _fromEvent(ev) {
    const rect = this.container.getBoundingClientRect();
    const x = ev.clientX - rect.left, y = ev.clientY - rect.top;
    let price = null, time = null;
    try { price = this.series.coordinateToPrice(y); } catch (e) { price = null; }
    try { time = this.chart.timeScale().coordinateToTime(x); } catch (e) { time = null; }
    if (price == null) return null;
    if (this.magnet && this.bars && this.bars.length) price = this._snapPrice(x, price);
    return { x, y, price, time };
  }

  _snapPrice(x, price) {
    let bestBar = null, bestDist = Infinity;
    for (const b of this.bars) {
      let bx = null;
      try { bx = this.chart.timeScale().timeToCoordinate(b.time); } catch (e) { bx = null; }
      if (bx == null) continue;
      const d = Math.abs(bx - x);
      if (d < bestDist) { bestDist = d; bestBar = b; }
    }
    if (!bestBar) return price;
    let best = null, bestP = Infinity;
    for (const key of ['open', 'high', 'low', 'close']) {
      const p = Number(bestBar[key]);
      if (!Number.isFinite(p)) continue;
      const d = Math.abs(p - price);
      if (d < bestP) { bestP = d; best = p; }
    }
    return best == null ? price : best;
  }

  _onDown(ev) {
    if (!this.chart || !this.series) return;
    if (ev.target && ev.target.closest && ev.target.closest('.cd-toolbar, .cd-props')) return;
    this._active = true;
    const pos = this._fromEvent(ev);
    if (!pos) return;
    if (this.tool === 'cursor') {
      const hit = this._hit(pos);
      if (hit) {
        this.selected = hit.d;
        this._drag = { d: hit.d, endpoint: hit.endpoint, start: pos, _last: pos };
        this.render();
        ev.preventDefault(); ev.stopPropagation();
      } else {
        const near = this._hitBox(pos);
        if (near) {
          this.selected = near;
          this._drag = { d: near, endpoint: null, start: pos, _last: pos };
          this.render();
          ev.preventDefault(); ev.stopPropagation();
        } else if (this.drawings.length) {
          this.selected = this.drawings[this.drawings.length - 1];
          this._drag = { d: this.selected, endpoint: null, start: pos, _last: pos };
          this.render();
          ev.preventDefault(); ev.stopPropagation();
        } else { this.selected = null; this.render(); }
      }
      return;
    }
    ev.preventDefault(); ev.stopPropagation();
    if (this.tool === 'text') {
      const text = window.prompt('文本标注内容', '');
      if (!text) return;
      this._pushUndo();
      this.drawings.push({ type: 'text', points: [{ time: pos.time, price: pos.price, text }], ...this.style });
      this.save(); this.render(); return;
    }
    this._tmp.push({ time: pos.time, price: pos.price });
    if (this._tmp.length >= NEED[this.tool]) {
      this._pushUndo();
      this.drawings.push({ type: this.tool, points: this._tmp.slice(0, NEED[this.tool]), ...this.style });
      this._tmp = [];
      this.save(); this.render();
    } else this.render();
  }

  _onMove(ev) {
    if (!this._drag || !this.chart) return;
    const pos = this._fromEvent(ev);
    if (!pos) return;
    const drag = this._drag, d = drag.d;
    if (drag.endpoint != null && d.points[drag.endpoint]) {
      d.points[drag.endpoint] = { time: pos.time, price: pos.price };
    } else {
      const dPrice = pos.price - drag._last.price;
      d.points = d.points.map((p) => ({ time: p.time, price: p.price + dPrice }));
      drag._last = pos;
    }
    drag._moved = true;
    this.render();
  }

  _onUp() {
    if (this._drag) {
      if (this._drag._moved) { this.save(); }
      this._drag = null;
      this.render();
    }
  }

  _pushUndo() {
    this._undo.push(JSON.stringify(this.drawings));
    if (this._undo.length > 80) this._undo.shift();
    this._redo = [];
  }
  undo() {
    if (!this._undo.length) return;
    this._redo.push(JSON.stringify(this.drawings));
    this.drawings = JSON.parse(this._undo.pop());
    this.selected = null; this.save(); this.render();
  }
  redo() {
    if (!this._redo.length) return;
    this._undo.push(JSON.stringify(this.drawings));
    this.drawings = JSON.parse(this._redo.pop());
    this.selected = null; this.save(); this.render();
  }
  deleteSelected() {
    if (!this.selected) return;
    this._pushUndo();
    this.drawings = this.drawings.filter((d) => d !== this.selected);
    this.selected = null; this.save(); this.render();
  }
  clearAll() {
    if (!this.drawings.length) return;
    if (!window.confirm('确定清空当前图表全部画线？')) return;
    this._pushUndo();
    this.drawings = []; this.selected = null; this._tmp = []; this.save(); this.render();
  }

  _applyStyle(patch) {
    Object.assign(this.style, patch);
    if (this.selected) { Object.assign(this.selected, patch); this.save(); }
    this.render();
    this._syncProps();
  }
  _syncProps() {
    for (const [c, b] of this.swatches) b.classList.toggle('on', c === this.style.color);
    for (const [w, b] of this.widthBtns) b.classList.toggle('on', w === this.style.width);
    for (const [s, b] of this.styleBtns) b.classList.toggle('on', s === this.style.lineStyle);
  }

  _onKey(ev, force = false) {
    if (!force && !this._active) return;
    const tag = (ev.target && ev.target.tagName) || '';
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
    if (ev.key === 'Delete' || ev.key === 'Backspace') { ev.preventDefault(); this.deleteSelected(); }
    else if (ev.key === 'Escape') { this._tmp = []; this.selected = null; this.setTool('cursor'); this.render(); }
    else if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === 'z') { ev.preventDefault(); this.undo(); }
    else if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === 'y') { ev.preventDefault(); this.redo(); }
  }

  _hit(pos) {
    let best = null, bestDist = 10;
    for (const d of this.drawings) {
      if (!d.points || !d.points.length) continue;
      const pts = d.points.map((p) => this._xy(p));
      if (pts.some((p) => !p)) continue;
      for (let i = 0; i < pts.length; i++) {
        const dd = Math.hypot(pts[i].x - pos.x, pts[i].y - pos.y);
        if (dd < bestDist) { bestDist = dd; best = { d, endpoint: i }; }
      }
      const edges = this._edges(d, pts);
      for (const [a, b] of edges) {
        const dd = this._distToSeg(pos, a, b);
        if (dd < bestDist) { bestDist = dd; best = { d, endpoint: null }; }
      }
    }
    return best;
  }

  _hitBox(pos) {
    for (let i = this.drawings.length - 1; i >= 0; i--) {
      const d = this.drawings[i];
      if (!d.points || !d.points.length) continue;
      const pts = d.points.map((p) => this._xy(p)).filter(Boolean);
      if (!pts.length) continue;
      const xs = pts.map(p => p.x), ys = pts.map(p => p.y);
      const pad = 24;
      if (pos.x >= Math.min(...xs) - pad && pos.x <= Math.max(...xs) + pad
          && pos.y >= Math.min(...ys) - pad && pos.y <= Math.max(...ys) + pad) return d;
    }
    return null;
  }

  _edges(d, pts) {
    const edges = [];
    const addSeg = (a, b) => { if (a && b) edges.push([a, b]); };
    if (d.type === 'h') addSeg({ x: 0, y: pts[0].y }, { x: this.container.clientWidth, y: pts[0].y });
    else if (d.type === 'v') addSeg({ x: pts[0].x, y: 0 }, { x: pts[0].x, y: this.container.clientHeight });
    else if (d.type === 'trend' || d.type === 'measure' || d.type === 'ray') addSeg(pts[0], pts[1]);
    else if (d.type === 'channel' && pts[2]) {
      addSeg(pts[0], pts[1]);
      const ox = pts[2].x - pts[0].x, oy = pts[2].y - pts[0].y;
      addSeg({ x: pts[0].x + ox, y: pts[0].y + oy }, { x: pts[1].x + ox, y: pts[1].y + oy });
    } else if (d.type === 'fib') {
      for (const lv of FIB) {
        const y = pts[0].y + (pts[1].y - pts[0].y) * lv;
        addSeg({ x: Math.min(pts[0].x, pts[1].x), y }, { x: Math.max(pts[0].x, pts[1].x), y });
      }
    } else if (d.type === 'rect') {
      const x1 = pts[0].x, y1 = pts[0].y, x2 = pts[1].x, y2 = pts[1].y;
      addSeg({ x: x1, y: y1 }, { x: x2, y: y1 }); addSeg({ x: x2, y: y1 }, { x: x2, y: y2 });
      addSeg({ x: x2, y: y2 }, { x: x1, y: y2 }); addSeg({ x: x1, y: y2 }, { x: x1, y: y1 });
    } else if (d.type === 'text') addSeg({ x: pts[0].x - 20, y: pts[0].y }, { x: pts[0].x + 20, y: pts[0].y });
    return edges;
  }

  _distToSeg(p, a, b) {
    const dx = b.x - a.x, dy = b.y - a.y;
    const len = dx * dx + dy * dy;
    let t = len ? ((p.x - a.x) * dx + (p.y - a.y) * dy) / len : 0;
    t = Math.max(0, Math.min(1, t));
    return Math.hypot(a.x + t * dx - p.x, a.y + t * dy - p.y);
  }

  _line(d, x1, y1, x2, y2, extra = {}) {
    this._svg.appendChild(mkSvg('line', {
      x1, y1, x2, y2, stroke: d.color || '#f5c518', 'stroke-width': d.width || 1,
      'stroke-dasharray': d.lineStyle === 'dashed' ? '6 4' : d.lineStyle === 'dotted' ? '2 3' : '',
      ...extra,
    }));
  }

  render() {
    if (!this._svg) return;
    const w = this.container.clientWidth, h = this.container.clientHeight;
    this._svg.setAttribute('viewBox', `0 0 ${Math.max(1, w)} ${Math.max(1, h)}`);
    this._svg.setAttribute('width', w); this._svg.setAttribute('height', h);
    this._svg.innerHTML = '';
    if (!this.chart || !this.series) return;
    for (const d of this.drawings) this._renderOne(d);
    if (this._tmp.length) {
      const pt = this._xy(this._tmp[0]);
      if (pt) this._svg.appendChild(mkSvg('circle', { cx: pt.x, cy: pt.y, r: 3, fill: this.style.color }));
    }
  }

  _renderOne(d) {
    if (!d.points || !d.points.length) return;
    const pts = d.points.map((p) => this._xy(p));
    if (pts.some((p) => !p)) return;
    const sel = d === this.selected;
    const extra = sel ? { stroke: '#ffffff', 'stroke-width': (d.width || 1) + 1 } : {};
    const color = d.color || '#f5c518';
    if (d.type === 'h') this._line(d, 0, pts[0].y, this.container.clientWidth, pts[0].y, extra);
    else if (d.type === 'v') this._line(d, pts[0].x, 0, pts[0].x, this.container.clientHeight, extra);
    else if (d.type === 'trend' && pts[1]) this._line(d, pts[0].x, pts[0].y, pts[1].x, pts[1].y, extra);
    else if (d.type === 'ray' && pts[1]) {
      const dx = pts[1].x - pts[0].x, dy = pts[1].y - pts[0].y;
      const scale = 5000 / Math.max(1, Math.hypot(dx, dy));
      this._line(d, pts[0].x, pts[0].y, pts[0].x + dx * scale, pts[0].y + dy * scale, extra);
    } else if (d.type === 'channel' && pts[2]) {
      this._line(d, pts[0].x, pts[0].y, pts[1].x, pts[1].y, extra);
      const ox = pts[2].x - pts[0].x, oy = pts[2].y - pts[0].y;
      this._line(d, pts[0].x + ox, pts[0].y + oy, pts[1].x + ox, pts[1].y + oy, extra);
      this._svg.appendChild(mkSvg('polygon', {
        points: `${pts[0].x},${pts[0].y} ${pts[1].x},${pts[1].y} ${pts[1].x + ox},${pts[1].y + oy} ${pts[0].x + ox},${pts[0].y + oy}`,
        fill: color, opacity: 0.08,
      }));
    } else if (d.type === 'fib' && pts[1]) {
      const x1 = Math.min(pts[0].x, pts[1].x), x2 = Math.max(pts[0].x, pts[1].x);
      for (const lv of FIB) {
        const y = pts[0].y + (pts[1].y - pts[0].y) * lv;
        this._line({ ...d, width: 1 }, x1, y, x2, y, {});
        const label = mkSvg('text', { x: x2 + 3, y: y + 3, fill: color, 'font-size': 10 });
        const price = d.points[0].price + (d.points[1].price - d.points[0].price) * lv;
        label.textContent = `${(lv * 100).toFixed(1)}% ${price.toFixed(2)}`;
        this._svg.appendChild(label);
      }
    } else if (d.type === 'rect' && pts[1]) {
      this._svg.appendChild(mkSvg('rect', {
        x: Math.min(pts[0].x, pts[1].x), y: Math.min(pts[0].y, pts[1].y),
        width: Math.abs(pts[1].x - pts[0].x), height: Math.abs(pts[1].y - pts[0].y),
        fill: color, 'fill-opacity': 0.09, stroke: sel ? '#fff' : color, 'stroke-width': d.width || 1,
        'stroke-dasharray': d.lineStyle === 'dashed' ? '6 4' : d.lineStyle === 'dotted' ? '2 3' : '',
      }));
    } else if (d.type === 'text') {
      const txt = mkSvg('text', { x: pts[0].x, y: pts[0].y, fill: color, 'font-size': 12, 'font-weight': 600 });
      txt.textContent = d.points[0].text || '文本';
      this._svg.appendChild(txt);
    } else if (d.type === 'measure' && pts[1]) {
      this._line({ ...d, lineStyle: 'dashed' }, pts[0].x, pts[0].y, pts[1].x, pts[1].y, extra);
      const dp = d.points[1].price - d.points[0].price;
      const pct = d.points[0].price ? (dp / d.points[0].price) * 100 : 0;
      const txt = mkSvg('text', { x: Math.max(pts[1].x + 6, 6), y: pts[1].y - 6, fill: color, 'font-size': 11 });
      txt.textContent = `${dp >= 0 ? '+' : ''}${dp.toFixed(2)} (${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%)`;
      this._svg.appendChild(txt);
    }
    if (sel) for (const p of pts) this._svg.appendChild(mkSvg('circle', { cx: p.x, cy: p.y, r: 4, fill: '#fff', stroke: color, 'stroke-width': 2 }));
  }
}
