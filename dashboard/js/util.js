/* 通用工具：DOM 构造、数字格式、时间格式、toast/modal、popover */
export const UP = '#d62828';
export const DOWN = '#0077b6';
export const GOLD = '#f5c518';

/** 轻量 DOM 构造器：h('div', {class:'x', onclick:fn}, child1, child2,...) */
export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  if (attrs) {
    for (const k of Object.keys(attrs)) {
      const v = attrs[k];
      if (v == null || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k === 'style' && typeof v === 'string') el.style.cssText = v;
      else if (k === 'html') el.innerHTML = v;
      else if (k === 'dataset') Object.assign(el.dataset, v);
      else if (k === 'value') el.value = v;
      else if (k === 'checked') el.checked = !!v;
      else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
      else el.setAttribute(k, v === true ? '' : String(v));
    }
  }
  const add = (c) => {
    if (c == null || c === false) return;
    if (Array.isArray(c)) { c.forEach(add); return; }
    if (c instanceof Node) { el.appendChild(c); return; }
    el.appendChild(document.createTextNode(String(c)));
  };
  children.forEach(add);
  return el;
}

export function clear(el) { while (el && el.firstChild) el.removeChild(el.firstChild); }

export function n(v) { return v == null || v === '' || Number.isNaN(Number(v)) ? null : Number(v); }

export function fmt(v, d = 2) {
  const x = n(v);
  return x == null ? '—' : x.toFixed(d);
}

export function pct(v, d = 2, withSign = true) {
  const x = n(v);
  if (x == null) return '—';
  return (withSign && x > 0 ? '+' : '') + x.toFixed(d);
}

export function fmtInt(v) {
  const x = n(v);
  return x == null ? '—' : String(Math.round(x));
}

export function fmtDate(ymd) {
  const s = String(ymd || '').replace(/-/g, '');
  return s.length === 8 ? `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}` : String(ymd || '');
}

export function fmtYm(ym) {
  const s = String(ym || '');
  return s.length === 6 ? `${s.slice(0, 4)}-${s.slice(4, 6)}` : s;
}

export function chgClass(v) {
  const x = n(v);
  if (x == null) return '';
  return x > 0 ? 'up' : x < 0 ? 'down' : '';
}

export function isLimitUp(chg) {
  const x = n(chg);
  return x != null && x >= 9.8;
}

/** 服务端时间戳已是「本地挂钟按 UTC 表示」→ 用 UTC getter 显示 */
export function fmtBarTime(ts, period) {
  if (ts == null) return '—';
  const d = new Date(Number(ts) * 1000);
  const y = d.getUTCFullYear(), mo = String(d.getUTCMonth() + 1).padStart(2, '0'), da = String(d.getUTCDate()).padStart(2, '0');
  if (period === '1d' || period === '1w' || period === '1mo') return `${y}-${mo}-${da}`;
  const hh = String(d.getUTCHours()).padStart(2, '0'), mi = String(d.getUTCMinutes()).padStart(2, '0');
  return `${y}-${mo}-${da} ${hh}:${mi}`;
}

/** 'YYYY-MM-DD' -> UTC 秒（日线坐标） */
export function dateToTs(ymd) {
  const s = String(ymd || '').replace(/-/g, '');
  if (s.length !== 8) return null;
  return Date.UTC(Number(s.slice(0, 4)), Number(s.slice(4, 6)) - 1, Number(s.slice(6, 8))) / 1000;
}

export function isIntraday(period) { return !['1d', '1w', '1mo'].includes(period); }

export function debounce(fn, ms = 80) {
  let t = null;
  return function (...args) {
    clearTimeout(t);
    t = setTimeout(() => fn.apply(this, args), ms);
  };
}

let toastTimer = 0;
export function toast(msg, type = '', ms = 2800) {
  const wrap = document.getElementById('toast-wrap');
  if (!wrap) return;
  const el = h('div', { class: 'toast ' + type }, msg);
  wrap.appendChild(el);
  const id = ++toastTimer;
  setTimeout(() => { if (el.parentNode) el.parentNode.removeChild(el); }, ms);
  return id;
}

/* ---------- modal ---------- */
export function modalConfirm(message, { title = '确认', okText = '确定', danger = false } = {}) {
  return new Promise((resolve) => {
    const root = document.getElementById('modal-root');
    let done = false;
    const close = (val) => {
      if (done) return;
      done = true;
      if (mask.parentNode) mask.parentNode.removeChild(mask);
      resolve(val);
    };
    const ok = h('button', { class: 'btn ' + (danger ? 'danger' : 'btn-primary'), onclick: () => close(true) }, okText);
    const cancel = h('button', { class: 'btn', onclick: () => close(false) }, '取消');
    const box = h('div', { class: 'modal' },
      h('h3', {}, title),
      h('p', {}, message),
      h('div', { class: 'actions' }, cancel, ok));
    const mask = h('div', { class: 'modal-mask', onclick: (e) => { if (e.target === mask) close(false); } }, box);
    root.appendChild(mask);
    ok.focus();
  });
}

export function modalPrompt(title, defaultValue = '', { okText = '确定', placeholder = '' } = {}) {
  return new Promise((resolve) => {
    const root = document.getElementById('modal-root');
    let done = false;
    const close = (val) => {
      if (done) return;
      done = true;
      if (mask.parentNode) mask.parentNode.removeChild(mask);
      resolve(val);
    };
    const input = h('input', { class: 'input', value: defaultValue, placeholder });
    const ok = h('button', { class: 'btn btn-primary', onclick: () => close(input.value.trim()) }, okText);
    const cancel = h('button', { class: 'btn', onclick: () => close(null) }, '取消');
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); close(input.value.trim()); }
      if (e.key === 'Escape') { e.preventDefault(); close(null); }
    });
    const box = h('div', { class: 'modal' },
      h('h3', {}, title),
      input,
      h('div', { class: 'actions' }, cancel, ok));
    const mask = h('div', { class: 'modal-mask', onclick: (e) => { if (e.target === mask) close(null); } }, box);
    root.appendChild(mask);
    input.focus(); input.select();
  });
}

/* ---------- popover ---------- */
let activePopover = null;

export function closePopover() {
  if (activePopover && activePopover.parentNode) activePopover.parentNode.removeChild(activePopover);
  activePopover = null;
}

export function openPopover(anchor, content, { width = null } = {}) {
  closePopover();
  const rect = anchor.getBoundingClientRect();
  const pop = h('div', { class: 'popover' }, content);
  if (width) pop.style.width = width + 'px';
  pop.style.visibility = 'hidden';
  document.body.appendChild(pop);
  const pw = pop.offsetWidth, ph = pop.offsetHeight;
  let left = rect.left;
  let top = rect.bottom + 6;
  if (left + pw > window.innerWidth - 8) left = Math.max(8, window.innerWidth - pw - 8);
  if (top + ph > window.innerHeight - 8) top = Math.max(8, rect.top - ph - 6);
  pop.style.left = left + 'px';
  pop.style.top = top + 'px';
  pop.style.visibility = '';
  const onDoc = (e) => {
    if (pop.contains(e.target) || anchor.contains(e.target)) return;
    closePopover();
    document.removeEventListener('mousedown', onDoc, true);
  };
  setTimeout(() => document.addEventListener('mousedown', onDoc, true), 0);
  activePopover = pop;
  return pop;
}

export function escapeHtml(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}
