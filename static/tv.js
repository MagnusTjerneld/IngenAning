// TV-vyn. Bara åskådare: servern skickar aldrig ordet hit före juryn eller avslöjandet.
'use strict';

const app = document.getElementById('app');
const render = makeRenderer(app);
let code = (new URLSearchParams(location.search).get('kod') || '').toUpperCase().slice(0, 4);
let S = null;
let message = '';
let juryDeadline = 0;
let juryTimer = null;
const seen = { chips: new Set(), locked: new Set(), round: 0 };

const sock = makeSocket({
  hello: () => (code ? { t: 'tv', code } : null),
  onStatus: () => {},
  onMessage: (m) => {
    if (m.t === 'state') {
      S = m.state;
      clearTimeout(juryTimer);
      if (S.phase === 'guess') { juryDeadline = Date.now() + S.round.juryLeft; juryTimer = setTimeout(draw, S.round.juryLeft + 60); }
      draw();
    }
    else if (m.t === 'error') { message = m.msg; code = ''; S = null; sock.stop(); draw(); }
  },
});

function qr(text) {
  const q = qrcode(0, 'M');
  q.addData(text);
  q.make();
  return q.createSvgTag({ cellSize: 4, margin: 0, scalable: true });
}

function form() {
  return ['form', `
  <div class="stage __ENTER__"><div class="form">
    <div class="logo">Ingen <em>aning</em></div>
    <p class="muted">Skriv rumskoden från värdens mobil för att visa spelet här.</p>
    <label class="kicker" for="code">Rumskod</label>
    <input class="input code" id="code" maxlength="4" autocomplete="off" autocapitalize="characters" spellcheck="false" style="text-align:center">
    <button class="btn" data-act="go">Visa på den här skärmen</button>
    ${message ? `<p role="alert" style="color:var(--yellow);font-weight:800">${esc(message)}</p>` : ''}
  </div><a class="tvlink" href="/">Gå med som deltagare i stället</a></div>`];
}

function lobby() {
  const chips = S.players.map((p) => {
    const fresh = !seen.chips.has(p.id);
    seen.chips.add(p.id);
    return `<div class="chip ${fresh ? 'new' : ''} ${p.connected ? '' : 'off'}">${dot(p)}<span>${esc(p.name)}</span></div>`;
  }).join('');
  const n = S.players.filter((p) => p.connected).length;
  return ['lobby', `
  <div class="stage spread __ENTER__">
    <div class="split">
      <div class="col">
        <h1>Ta fram mobilen</h1>
        <p class="lead">Skanna koden eller gå till <b>${esc(location.host)}</b> och skriv</p>
        ${tiles(S.code)}
      </div>
      <div class="qr" role="img" aria-label="QR-kod till rummet">${qr(`${location.origin}/?kod=${S.code}`)}</div>
    </div>
    <div class="col">
      <div class="kicker">${n === 0 ? 'Ingen har gått in än' : n === 1 ? 'En är med' : `${n} är med`}</div>
      <div class="chips">${chips}</div>
    </div>
  </div>`];
}

function clues() {
  const r = S.round;
  const starter = byId(S, r.starter);
  return ['clues' + r.n, `
  <div class="stage __ENTER__" style="align-items:center;text-align:center;justify-content:center">
    <div class="kicker">Kategori ${esc(r.category)}</div>
    ${dot(starter, 'avatar')}
    <h1>${esc(starter.name)} börjar</h1>
    <p class="lead">Ett ord var, sedan medsols. ${lapsText(r.laps)}</p>
    <p class="lead">${r.seen < r.size ? `${r.seen} av ${r.size} har tittat på sin lapp.` : 'Alla har tittat på sin lapp.'}</p>
  </div>`];
}

function vote() {
  const r = S.round;
  const people = S.players.filter((p) => p.inRound).map((p) => {
    const done = r.locked.includes(p.id);
    const fresh = done && !seen.locked.has(p.id);
    if (done) seen.locked.add(p.id);
    return `<div class="person ${done ? 'done' : 'wait'} ${fresh ? 'new' : ''}">${dot(p)}<span class="nm">${esc(p.name)}</span><span class="st">${done ? 'låst' : p.connected ? 'tänker' : 'borta'}</span></div>`;
  }).join('');
  return ['vote' + r.n, `
  <div class="stage __ENTER__" style="align-items:center;text-align:center">
    <div class="kicker">Kategori ${esc(r.category)}</div>
    <h1>Vem har ingen aning?</h1>
    <p class="lead">Rösta i mobilen. ${r.locked.length} av ${r.size} har låst.</p>
    <div class="grow"></div>
    <div class="people">${people}</div>
    <div class="grow"></div>
  </div>`];
}

function guess() {
  const r = S.round;
  const spy = byId(S, S.spyId);
  const left = Math.max(0, juryDeadline - Date.now());
  return ['guess' + r.n, `
  <div class="stage __ENTER__" style="justify-content:center;align-items:center;text-align:center;--t0:${SUSPENSE_MS}ms">
    ${suspense(S)}
    <div class="kicker hold">Den som inte hade en aning</div>
    <div class="stamp" style="${stampSize(spy.name, '11vw', 110)}">${esc(spy.name)}</div>
    <h1 class="d1">${esc(spy.name)}, vad var ordet?</h1>
    <p class="lead d2">Säg det högt. De andra avgör i mobilen om det var rätt.</p>
    <p class="lead d2">${left > 0 ? `${r.juryVoted} av ${r.jurySize} har svarat.` : `Tiden är ute. ${esc(byId(S, r.decider).name)} avgör.`}</p>
    ${left > 0 ? `<div class="d2" style="width:50vw">${timerBar(left)}</div>` : ''}
  </div>`];
}

function reveal() {
  const v = verdict(S, null);
  return ['reveal' + S.round.n, `
  <div class="stage __ENTER__" style="justify-content:center;--t0:1100ms">
    <div class="split">
      <div class="col">
        <div class="kicker">Juryn säger</div>
        <div class="stamp ${v.good ? '' : 'no'}">${v.stamp}</div>
        <p class="lead rword d1" style="color:var(--cream);margin-top:2vh">${v.word}</p>
        <p class="lead rguess d2" style="color:var(--cream)">${v.detail}</p>
        <p class="lead d3">${v.pointed}</p>
      </div>
      <div class="boardbox d4"><div class="kicker">Ställning</div>${boardLines(S)}</div>
    </div>
  </div>`];
}

function draw() {
  if (!code || !S) { const [k, h] = code ? ['connecting', `<div class="stage __ENTER__" style="align-items:center;justify-content:center"><div class="dots" aria-hidden="true"><span></span><span></span><span></span></div></div>`] : form(); return render(k, h); }
  if (S.round && S.round.n !== seen.round) { seen.round = S.round.n; seen.locked.clear(); }
  const view = { lobby, clues, vote, guess, reveal }[S.phase] || lobby;
  const [key, html] = view();
  render(key, html);
  runSuspense(app);
}

function go() {
  const v = document.getElementById('code').value.trim().toUpperCase();
  if (v.length !== 4) { message = 'Rumskoden har fyra bokstäver.'; return draw(); }
  code = v; message = '';
  sock.stop(); sock.start(); draw();
}
app.addEventListener('click', (e) => { if (e.target.closest('[data-act="go"]')) go(); });
app.addEventListener('keydown', (e) => { if (e.key === 'Enter' && e.target.id === 'code') go(); });

snow(22);
if (code) sock.start();
draw();
