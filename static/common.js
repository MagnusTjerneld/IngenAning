// Delat mellan spelarvyn och TV-vyn: anslutning, rendering och små hjälpare.
'use strict';

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const dot = (p, cls = '') => `<span class="dot ${cls}" style="background:${esc(p.color)}">${esc((p.name || '?')[0].toUpperCase())}</span>`;
const tiles = (code) => `<div class="tiles" aria-label="Rumskod ${esc(code)}">${[...code].map((c) => `<span class="tile">${esc(c)}</span>`).join('')}</div>`;
const byId = (state, id) => state.players.find((p) => p.id === id) || { id, name: 'Någon', color: '#FFF4DC', score: 0 };
const lapsText = (n) => (n === 1 ? 'Ni kör ett varv.' : 'Ni kör två varv.');

function snow(count) {
  const el = document.getElementById('snow');
  let seed = 7;
  const rnd = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
  let html = '';
  for (let i = 0; i < count; i++) {
    const depth = rnd();                        // 0 = långt bort, 1 = nära
    const size = 3 + depth * 6;
    const dur = 26 - depth * 18 + rnd() * 5;    // ungefär 8 till 31 sekunder
    html += `<span style="left:${(rnd() * 100).toFixed(1)}%;width:${size.toFixed(1)}px;height:${size.toFixed(1)}px;opacity:${(0.14 + depth * 0.26).toFixed(2)};animation-duration:${dur.toFixed(1)}s;animation-delay:-${(rnd() * dur).toFixed(1)}s"></span>`;
  }
  el.innerHTML = html + SLEIGH;
}

const SLEIGH = `<svg class="sleigh" viewBox="0 0 230 74" aria-hidden="true" fill="#FFF9EF" stroke="#FFF9EF" stroke-linecap="round" stroke-linejoin="round">
  <path d="M8 64 H74 Q88 64 88 50" fill="none" stroke-width="3.5"/>
  <path d="M24 64 V54 M62 64 V54" fill="none" stroke-width="3"/>
  <path d="M10 54 Q6 32 22 30 L26 42 H58 L66 26 Q80 30 76 54 Z" stroke-width="2"/>
  <circle cx="22" cy="25" r="11" stroke="none"/>
  <path d="M36 40 V26 Q36 18 44 18 Q52 18 52 26 V40 Z" stroke="none"/>
  <circle cx="44" cy="13" r="6.5" stroke="none"/>
  <path d="M38 10 Q44 -2 56 6 L50 11 Z" fill="#FFC94A" stroke="#FFC94A" stroke-width="1"/>
  <path d="M74 38 L150 36 M74 42 L150 40" fill="none" stroke-width="1.4"/>
  <ellipse cx="172" cy="40" rx="24" ry="9.5" stroke="none"/>
  <path d="M188 38 L200 18 L214 20 L211 27 L200 30 L196 44 Z" stroke-width="2"/>
  <path d="M202 18 L200 6 M201 12 L195 7 M201 11 L207 5 M208 19 L210 9 M209 14 L214 10" fill="none" stroke-width="2"/>
  <path d="M188 46 L200 62 M182 47 L178 66 M158 46 L146 60 M163 47 L168 66 M149 38 L143 34" fill="none" stroke-width="3.5"/>
  <circle cx="215" cy="22" r="3" fill="#FFC94A" stroke="none"/>
</svg>`;

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
  else if (r.outcome === 'none') a = `Ordet var ${word}. ${who} hade ingen aning.`;
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
