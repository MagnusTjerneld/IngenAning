// Delat mellan spelarvyn och TV-vyn: anslutning, rendering och små hjälpare.
'use strict';

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const dot = (p, cls = '') => `<span class="dot ${cls}" style="background:${esc(p.color)}">${esc((p.name || '?')[0].toUpperCase())}</span>`;
const tiles = (code) => `<div class="tiles" aria-label="Rumskod ${esc(code)}">${[...code].map((c) => `<span class="tile">${esc(c)}</span>`).join('')}</div>`;
const byId = (state, id) => state.players.find((p) => p.id === id) || { id, name: 'Någon', color: '#FFF4DC', score: 0 };
const lapsText = (n) => (n === 1 ? 'Ni kör ett varv.' : 'Ni kör två varv.');

function snow(count) {
  const el = document.getElementById('snow');
  let html = '';
  for (let i = 0; i < count; i++) {
    const size = 4 + (i * 7) % 5;
    html += `<span style="left:${(i * 37 + 9) % 100}%;width:${size}px;height:${size}px;opacity:${0.2 + ((i * 3) % 4) * 0.05};animation-duration:${11 + (i * 5) % 8}s;animation-delay:-${(i * 3.7) % 14}s"></span>`;
  }
  el.innerHTML = html;
}

// Ritar bara om när något faktiskt ändrats, och spelar in-animationer bara när skärmen byts.
function makeRenderer(root) {
  let lastHtml = null;
  let lastKey = null;
  return (key, html) => {
    const full = html.replace('__ENTER__', key !== lastKey ? 'enter' : '');
    const stable = html;
    if (stable === lastHtml) return;
    const keep = {};
    root.querySelectorAll('input[id]').forEach((i) => { keep[i.id] = i.value; });
    const focus = document.activeElement && document.activeElement.id;
    root.innerHTML = full;
    Object.entries(keep).forEach(([id, v]) => { const i = document.getElementById(id); if (i && v) i.value = v; });
    if (focus) { const f = document.getElementById(focus); if (f) f.focus(); }
    lastHtml = stable;
    lastKey = key;
  };
}

// WebSocket som återansluter av sig själv. hello() ger första meddelandet vid varje anslutning.
function makeSocket({ hello, onMessage, onStatus }) {
  let ws = null;
  let tries = 0;
  let timer = null;
  let wanted = false;
  const url = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`;
  function open() {
    clearTimeout(timer);
    if (ws && (ws.readyState === 0 || ws.readyState === 1)) return;
    const first = hello();
    if (!first) return;
    ws = new WebSocket(url);
    const mine = ws;
    mine.onopen = () => { tries = 0; mine.send(JSON.stringify(first)); onStatus(true); };
    mine.onmessage = (e) => { try { onMessage(JSON.parse(e.data)); } catch (_) { /* ogiltigt meddelande */ } };
    mine.onclose = () => {
      if (ws !== mine) return;
      onStatus(false);
      if (wanted) timer = setTimeout(open, Math.min(5000, 400 * 2 ** tries++));
    };
  }
  setInterval(() => { if (ws && ws.readyState === 1) ws.send('{"t":"ping"}'); }, 25000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden && wanted) open(); });
  window.addEventListener('online', () => { if (wanted) open(); });
  return {
    start() { wanted = true; open(); },
    stop() { wanted = false; clearTimeout(timer); if (ws) { const w = ws; ws = null; w.close(); } },
    send(msg) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(msg)); },
  };
}

function verdict(state, youId) {
  const r = state.result;
  const spy = byId(state, r.spyId);
  const me = r.spyId === youId;
  const who = me ? 'Du' : esc(spy.name);
  const word = `<b class="word">${esc(r.word)}</b>`;
  let a;
  if (r.outcome === 'exact') a = `${who} skrev rätt ord: ${word}.`;
  else if (r.outcome === 'none') a = `Ordet var ${word}. ${who} gissade inte.`;
  else {
    const g = `Ordet var ${word}. ${who} skrev ${esc(r.guess)}`;
    if (r.outcome === 'rejected') a = `${g}, och juryn sa nej med ${r.juryNo} mot ${r.juryYes}.`;
    else if (r.juryYes === r.juryNo) a = `${g}. Juryn blev oenig, ${r.juryYes} mot ${r.juryNo}, och lika går till den som gissade.`;
    else a = `${g}, och juryn godkände med ${r.juryYes} mot ${r.juryNo}.`;
  }
  const b = `${r.pointed === 0 ? 'Ingen' : `${r.pointed} av ${r.knowers}`} pekade ut ${me ? 'dig' : esc(spy.name)}${r.hid ? ', så det blev en bonuspoäng för att smälta in.' : '.'}`;
  return { a, b, spy, me };
}

function boardLines(state) {
  const gains = (state.result && state.result.gains) || {};
  return [...state.players].sort((x, y) => y.score - x.score).map((p) => `
    <div class="line">${dot(p)}<span class="name">${esc(p.name)}</span>
    <span class="gain ${gains[p.id] ? '' : 'none'}">+${gains[p.id] || 0}</span><span class="total">${p.score}</span></div>`).join('');
}
