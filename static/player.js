// Spelarvyn. Servern äger sanningen; här ritas bara det servern skickar plus lite lokalt läge.
'use strict';

const KEY = 'ingenaning';
const app = document.getElementById('app');
const render = makeRenderer(app);
const load = () => { try { return JSON.parse(localStorage.getItem(KEY)) || null; } catch (_) { return null; } };
const save = (v) => { try { v ? localStorage.setItem(KEY, JSON.stringify(v)) : localStorage.removeItem(KEY); } catch (_) { /* privat läge */ } };

let session = load();          // { code, pid, name }
let pending = null;            // första meddelandet när vi inte har någon session än
let S = null;                  // senaste läget från servern
let online = true;
let toast = '';
let toastTimer = null;
const urlCode = (new URLSearchParams(location.search).get('kod') || '').toUpperCase().slice(0, 4);
const L = { round: 0, flipped: false, cardDone: false, closing: false, peek: false, pick: null, chips: new Set(), mode: urlCode ? 'join' : null };

const sock = makeSocket({
  hello: () => pending || (session && { t: 'join', code: session.code, pid: session.pid, name: session.name }),
  onStatus: (ok) => { online = ok; draw(); },
  onMessage: (m) => {
    if (m.t === 'joined') {
      session = { code: m.code, pid: m.pid, name: (pending && pending.name) || (session && session.name) || '' };
      pending = null;
      save(session);
    } else if (m.t === 'state') {
      S = m.state;
      draw();
    } else if (m.t === 'error') {
      if (m.fatal) { leave(); }
      say(m.msg);
    }
  },
});

function say(msg) {
  toast = msg;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast = ''; draw(); }, 3500);
  draw();
}

function leave() {
  sock.stop();
  session = null; pending = null; S = null;
  save(null);
  draw();
}

// ---------- skärmar ----------

function home() {
  let last = ''; try { last = localStorage.getItem(KEY + '-namn') || ''; } catch (_) { /* privat läge */ }
  const name = esc((session && session.name) || last);
  const nameField = `<div class="field"><label class="kicker" for="name">Ditt namn</label>
      <input class="input" id="name" maxlength="16" autocomplete="given-name" value="${name}"></div>`;
  let body;
  if (L.mode === 'join') {
    body = `<h1>Gå med i ett rum</h1>${nameField}
    <div class="field"><label class="kicker" for="code">Rumskod, fyra bokstäver</label>
      <input class="input code" id="code" maxlength="4" autocomplete="off" autocapitalize="characters" spellcheck="false" value="${esc(urlCode)}"></div>
    <button class="btn" data-act="join">Gå med</button>
    <button class="btn ghost slim" data-act="modeNone">Tillbaka</button>`;
  } else if (L.mode === 'create') {
    body = `<h1>Starta ett nytt rum</h1>${nameField}
    <p class="muted small">Du blir värd och får en rumskod som de andra går in med.</p>
    <button class="btn" data-act="create">Starta rummet</button>
    <button class="btn ghost slim" data-act="modeNone">Tillbaka</button>`;
  } else {
    body = `<div class="logo">Ingen<br><em>aning</em></div>
    <p class="muted">Alla utom en kan ordet. Ett ord var, sedan röstar ni.</p>
    <button class="btn" data-act="modeJoin">Gå med i ett rum</button>
    <button class="btn ghost" data-act="modeCreate">Starta ett nytt rum</button>`;
  }
  return ['home-' + (L.mode || 'start'), `
  <div class="screen __ENTER__">
    <div class="grow"></div>
    ${body}
    <div class="grow"></div>
    <a class="tvlink" href="/tv">Visa spelet på en TV eller stor skärm</a>
  </div>`];
}

function lobby(you) {
  const active = S.players.filter((p) => p.connected).length;
  const chips = S.players.map((p) => {
    const fresh = !L.chips.has(p.id);
    L.chips.add(p.id);
    return `<div class="chip ${fresh ? 'new' : ''} ${p.connected ? '' : 'off'}">${dot(p)}<span>${esc(p.name)}${p.id === you.id ? ' (du)' : ''}</span></div>`;
  }).join('');
  const cats = [{ id: 'blandat', name: 'Blandat' }, ...S.categories];
  const catName = (cats.find((c) => c.id === S.categoryId) || cats[0]).name;
  const host = byId(S, S.hostId);
  const pick = you.isHost
    ? `<div class="field"><div class="kicker">Kategori, svep för fler</div><div class="pills scrollx">${cats.map((c) =>
        `<button class="pill ${c.id === S.categoryId ? 'on' : ''}" data-act="category" data-id="${esc(c.id)}" aria-pressed="${c.id === S.categoryId}">${esc(c.name)}</button>`).join('')}</div></div>`
    : `<p class="muted">Kategori <b style="color:var(--cream)">${esc(catName)}</b>.</p>`;
  const action = you.isHost
    ? (active >= S.minPlayers
      ? `<button class="btn" data-act="start">Starta rundan</button>`
      : `<button class="btn" disabled>Ni behöver vara minst tre</button>`)
    : `<p class="muted" style="text-align:center">${esc(host.name)} startar rundan.</p>`;
  return ['lobby', `
  <div class="screen __ENTER__">
    <div class="toprow">
      <div class="field"><div class="kicker">Rumskod</div>${tiles(S.code)}</div>
      <button class="link" data-act="leave">Lämna</button>
    </div>
    ${S.players.length > 8 ? `<div class="kicker">${active} är med</div>` : `<h1>${active === 1 ? 'Du är först här' : `${active} är med`}</h1>`}
    <div class="chips ${S.players.length > 8 ? 'dense' : ''}">${chips}</div>
    ${pick}
    <div class="foot">
      ${hostGone(you)}
      ${action}
    </div>
  </div>`];
}

const catPill = () => `<div class="cat"><span>Kategori</span><b>${esc(S.round.category)}</b></div>`;

function hostGone(you) {
  const host = byId(S, S.hostId);
  if (you.isHost || host.connected) return '';
  return `<button class="btn ghost slim" data-act="claimHost">${esc(host.name)} är borta. Ta över som värd</button>`;
}

function spectator() {
  return ['spectator', `
  <div class="screen center middle __ENTER__">
    <div class="dots" aria-hidden="true"><span></span><span></span><span></span></div>
    <h1>En runda pågår</h1>
    <p class="muted">Du är med från nästa runda.</p>
  </div>`];
}

function card(you) {
  const back = you.role === 'spy'
    ? `<span class="q">?</span><span class="big sub">Du har ingen aning</span>
       <span class="note">Men kategorin är</span><span class="word catword">${esc(S.round.category)}</span>`
    : `<span class="note">Ordet är</span><span class="word">${esc(you.word)}</span>
       <span class="note">Kategori</span><span class="catword ink">${esc(S.round.category)}</span>`;
  return ['card' + S.round.n, `
  <div class="screen center __ENTER__">
    <h1>Din lapp</h1>
    <p class="muted">Vänd den så att ingen annan ser.</p>
    <div class="hang ${L.flipped ? 'flipped' : ''}" id="hang">
      <span class="knob" aria-hidden="true"></span><span class="string" aria-hidden="true"></span>
      <button class="tag" data-act="flip" aria-label="Vänd lappen">
        <span class="inner">
          <span class="face front"><span class="gj">God jul</span><span class="big">Till dig</span><span class="note">Tryck för att vända</span></span>
          <span class="face back">${back}</span>
        </span>
      </button>
    </div>
    <div class="foot after">
      <p class="muted small">Tryck på lappen igen eller på knappen när du har läst.</p>
      <button class="btn" data-act="cardDone">Jag har sett, göm lappen</button>
    </div>
  </div>`];
}

function clues(you) {
  const starter = byId(S, S.round.starter);
  const mine = starter.id === you.id;
  const host = byId(S, S.hostId);
  const peekText = you.role === 'spy' ? `${esc(S.round.category)}, men vad?` : esc(you.word);
  return ['clues' + S.round.n, `
  <div class="screen center __ENTER__">
    ${catPill()}
    ${dot(starter, 'avatar')}
    <h1>${mine ? 'Du börjar' : `${esc(starter.name)} börjar`}</h1>
    <p class="muted">Ett ord var, sedan medsols. ${lapsText(S.round.laps)}</p>
    <button class="btn ghost slim" data-act="peek">${L.peek ? 'Göm lappen' : 'Kika på min lapp'}</button>
    ${L.peek ? `<div class="peek">${peekText}</div>` : ''}
    <div class="foot">
      ${hostGone(you)}
      ${you.isHost
        ? `<button class="btn" data-act="openVote">Alla har sagt sitt</button>`
        : `<p class="muted">${esc(host.name)} startar röstningen.</p>`}
    </div>
  </div>`];
}

function voteKnower(you) {
  const others = S.players.filter((p) => p.inRound && p.id !== you.id);
  return ['vote' + S.round.n, `
  <div class="screen __ENTER__">
    ${catPill()}
    <h1>Vem har ingen aning?</h1>
    <div class="grid2 ${others.length > 6 ? 'three' : ''}">${others.map((p) => `
      <button class="vote ${L.pick === p.id ? 'on' : ''}" data-act="pick" data-id="${esc(p.id)}" aria-pressed="${L.pick === p.id}">${dot(p)}<span>${esc(p.name)}</span></button>`).join('')}
    </div>
    <div class="foot">
      ${L.pick ? `<button class="btn" data-act="vote">Lås min röst</button>` : `<button class="btn" disabled>Välj en person</button>`}
    </div>
  </div>`];
}

function waiting(you, title, names, key) {
  const text = names.length ? `Väntar på ${names.map(esc).join(', ').replace(/, ([^,]*)$/, ' och $1')}.` : 'Strax klart.';
  return [key + S.round.n, `
  <div class="screen center middle __ENTER__">
    ${catPill()}
    <div class="dots" aria-hidden="true"><span></span><span></span><span></span></div>
    <h1>${title}</h1>
    <p class="muted">${text}</p>
    ${hostGone(you)}
    ${you.isHost && names.length ? `<button class="btn ghost slim" data-act="force">Gå vidare utan att vänta</button>` : ''}
  </div>`];
}

function guessJury() {
  const spy = byId(S, S.spyId);
  return ['guess' + S.round.n, `
  <div class="screen staged __ENTER__" style="--t0:${SUSPENSE_MS}ms">
    ${suspense(S)}
    <div class="field center" style="align-items:center">
      <div class="kicker">Den som inte hade en aning</div>
      <div class="stamp" style="${stampSize(spy.name, 'clamp(34px, 7.5dvh, 56px)', 125)}">${esc(spy.name)}</div>
    </div>
    <h1 class="d1" style="text-align:center">Gissade ${esc(spy.name)} rätt?</h1>
    <p class="muted d1" style="text-align:center">${esc(spy.name)} säger sin gissning högt. Svara när du har hört den. Minst hälften ja räcker.</p>
    <div class="foot d1">
      <div class="row2">
        <button class="btn ghost" data-act="juryNo">Nej</button>
        <button class="btn" data-act="juryYes">Ja, rätt</button>
      </div>
    </div>
  </div>`];
}

function guessSpy() {
  return ['guess' + S.round.n, `
  <div class="screen center staged __ENTER__" style="--t0:${SUSPENSE_MS}ms">
    ${suspense(S)}
    <div class="field center" style="align-items:center">
      <div class="kicker">Den som inte hade en aning</div>
      <div class="stamp">Du</div>
    </div>
    <h1 class="d1">Säg din gissning högt</h1>
    <div class="d1">${catPill()}</div>
    <p class="muted d1">De andra avgör om det var rätt. Har du ingen aning, säg det.</p>
  </div>`];
}

function reveal(you) {
  const r = S.result;
  const v = verdict(S, you.id);
  const host = byId(S, S.hostId);
  const votes = r.tally.map((t) => `${t.id === r.spyId ? '<b style="color:var(--yellow)">' : '<b style="color:var(--cream)">'}${esc(byId(S, t.id).name)} ${t.count}</b>`).join(', ');
  return ['reveal' + S.round.n, `
  <div class="screen tight staged __ENTER__" style="--t0:1100ms">
    <div class="field center now" style="align-items:center">
      <div class="kicker">Juryn säger</div>
      <div class="stamp ${v.good ? '' : 'no'}">${v.stamp}</div>
    </div>
    <p class="rword d1">${v.word}</p>
    <p class="rguess d2">${v.detail}</p>
    <p class="muted small d3" style="text-align:center">${v.pointed}${votes && S.players.length <= 8 ? ` Röster: ${votes}` : ''}</p>
    <div class="panel board d4 ${S.players.length > 4 ? 'two' : ''} ${S.players.length > 8 ? 'dense' : ''}"><div class="kicker">Ställning</div>${boardLines(S)}</div>
    <div class="foot last">
      ${hostGone(you)}
      ${you.isHost
        ? `<div class="footrow"><button class="btn" data-act="start">En runda till</button><button class="btn ghost" data-act="lobby" style="font-size:16px">Byt kategori</button></div>`
        : `<p class="muted" style="text-align:center">${esc(host.name)} startar nästa runda.</p>`}
    </div>
  </div>`];
}

function screen() {
  if (!session || !S) return session ? ['connecting', `<div class="screen center middle __ENTER__"><div class="dots" aria-hidden="true"><span></span><span></span><span></span></div><p class="muted">Ansluter</p></div>`] : home();
  const you = S.you;
  if (S.round && S.round.n !== L.round) Object.assign(L, { round: S.round.n, flipped: false, cardDone: false, closing: false, peek: false, pick: null });
  if (S.phase === 'lobby') return lobby(you);
  if (S.phase === 'reveal') return reveal(you);
  if (!you.inRound) return spectator();
  const inRound = S.players.filter((p) => p.inRound);
  if (S.phase === 'clues') return L.cardDone ? clues(you) : card(you);
  if (S.phase === 'vote') {
    if (!you.locked) return voteKnower(you); // alla röstar, även den ovetande, så att ingen syns på vad de gör
    const slow = inRound.filter((p) => p.connected && !S.round.locked.includes(p.id)).map((p) => p.name);
    return waiting(you, 'Rösten är låst', slow, 'wait');
  }
  if (S.phase === 'guess') {
    if (you.role === 'spy') return guessSpy();
    if (you.juryVoted) return waiting(you, 'Tack, juryn räknar', [`${S.round.jurySize - S.round.juryVoted} till`].filter(() => S.round.jurySize > S.round.juryVoted), 'jurywait');
    return guessJury();
  }
  return home();
}

function draw() {
  const [key, html] = screen();
  const extra = (online || !session ? '' : `<div class="offline" role="status">Återansluter</div>`)
    + (toast ? `<div class="toast" role="alert">${esc(toast)}</div>` : '');
  document.body.classList.toggle('drift', /^(home|connecting|spectator|wait|jurywait)/.test(key));
  render(key, html + extra);
  runSuspense(app);
}

// ---------- händelser ----------

const actions = {
  join() {
    const name = document.getElementById('name').value.trim();
    const code = document.getElementById('code').value.trim().toUpperCase();
    if (!name) return say('Skriv ditt namn först.');
    if (code.length !== 4) return say('Rumskoden har fyra bokstäver.');
    try { localStorage.setItem(KEY + '-namn', name); } catch (_) { /* privat läge */ }
    session = { code, pid: '', name };
    pending = { t: 'join', code, name };
    sock.stop(); sock.start(); draw();
  },
  create() {
    const name = document.getElementById('name').value.trim();
    if (!name) return say('Skriv ditt namn först.');
    try { localStorage.setItem(KEY + '-namn', name); } catch (_) { /* privat läge */ }
    session = { code: '', pid: '', name };
    pending = { t: 'create', name };
    sock.stop(); sock.start(); draw();
  },
  leave,
  flip() {
    if (L.flipped) return actions.cardDone(); // att trycka på den öppna lappen betyder "jag har sett"
    L.flipped = true;
    document.getElementById('hang').classList.add('flipped'); // utan omritning, så att vändningen animeras
  },
  cardDone() {
    if (L.closing) return;
    L.closing = true;
    const hang = document.getElementById('hang');
    if (hang) hang.classList.remove('flipped', 'open');
    const n = L.round;
    setTimeout(() => {
      if (L.round !== n) return;
      L.closing = false; L.flipped = false; L.cardDone = true;
      sock.send({ t: 'seen' });
      draw();
    }, 480);
  },
  modeJoin() { L.mode = 'join'; draw(); const el = document.getElementById(document.getElementById('name').value ? 'code' : 'name'); if (el) el.focus(); },
  modeCreate() { L.mode = 'create'; draw(); const el = document.getElementById('name'); if (el) el.focus(); },
  modeNone() { L.mode = null; draw(); },
  peek() { L.peek = !L.peek; draw(); },
  pick(el) { L.pick = el.dataset.id; draw(); },
  vote() { if (L.pick) sock.send({ t: 'vote', target: L.pick }); },
  juryYes() { sock.send({ t: 'jury', ok: true }); },
  juryNo() { sock.send({ t: 'jury', ok: false }); },
  category(el) { sock.send({ t: 'category', id: el.dataset.id }); },
  start() { sock.send({ t: 'start' }); },
  openVote() { sock.send({ t: 'openVote' }); },
  force() { sock.send({ t: 'force' }); },
  lobby() { sock.send({ t: 'lobby' }); },
  claimHost() { sock.send({ t: 'claimHost' }); },
};

app.addEventListener('click', (e) => {
  const el = e.target.closest('[data-act]');
  if (el && !el.disabled && actions[el.dataset.act]) actions[el.dataset.act](el);
});
app.addEventListener('keydown', (e) => {
  if (e.key !== 'Enter' || e.target.tagName !== 'INPUT') return;
  if (e.target.id === 'code' || e.target.id === 'name') (L.mode === 'create' ? actions.create : actions.join)();
});

snow(16);
if (session) sock.start();
draw();
