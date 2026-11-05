/* 后端 API 客户端（零依赖，fetch + 超时） */

async function getJSON(url, timeout = 20000) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeout);
  try {
    const res = await fetch(url, { signal: ctrl.signal, cache: 'no-store' });
    const text = await res.text();
    let data;
    try {
      data = text ? JSON.parse(text) : {};
    } catch (e) {
      throw new Error(`接口返回非 JSON（HTTP ${res.status}）：${text.slice(0, 120)}`);
    }
    if (!res.ok) throw new Error(data && data.error ? data.error : `HTTP ${res.status}`);
    return data;
  } catch (e) {
    if (e && e.name === 'AbortError') throw new Error(`接口超时（>${Math.round(timeout / 1000)}s）：${url}`);
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

async function postJSON(url, body, timeout = 20000) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeout);
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: ctrl.signal,
      cache: 'no-store',
    });
    const text = await res.text();
    let data;
    try { data = text ? JSON.parse(text) : {}; } catch (e) { throw new Error(`接口返回非 JSON（HTTP ${res.status}）`); }
    if (!res.ok) throw new Error(data && data.error ? data.error : `HTTP ${res.status}`);
    return data;
  } catch (e) {
    if (e && e.name === 'AbortError') throw new Error(`接口超时（>${Math.round(timeout / 1000)}s）：${url}`);
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

const enc = encodeURIComponent;

export const API = {
  meta: () => getJSON('/api/meta?ts=' + Date.now(), 8000),
  strategies: () => getJSON('/api/strategies'),
  dashboard: (strategy, pickMode = 'first', sellMode = '5m') =>
    getJSON(`/api/dashboard?strategy=${enc(strategy)}&pick_mode=${enc(pickMode)}&sell_mode=${enc(sellMode)}`, 30000),
  picks: (strategy, refresh = false) =>
    getJSON(`/api/picks?strategy=${enc(strategy)}${refresh ? '&refresh=1' : ''}`, 120000),
  kline: (code, period, count = 600, end = null) =>
    getJSON(`/api/kline?code=${enc(code)}&period=${enc(period)}&adjust=front&count=${count}${end ? '&end=' + enc(String(end)) : ''}`, 15000),
  symbols: () => getJSON('/api/symbols', 15000),
  realtime: () => getJSON('/api/realtime?ts=' + Date.now(), 8000),
  realtimeKline: (code, period = '5m', days = 10) =>
    getJSON(`/api/realtime/kline?code=${enc(code)}&period=${enc(period)}&days=${days}`, 15000),
  holdings: () => getJSON('/api/realtime/holdings', 8000),
  saveHoldings: (holdings) => postJSON('/api/realtime/holdings', { holdings }, 10000),
};
