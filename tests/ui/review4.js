// Regressions from the fourth review round: waiting messages and drafts never cross accounts or get lost, a retry never posts twice,
// a failed approval click can be retried, switching rooms mid-load keeps rooms apart, look-alike link labels, deleted messages
// disappear from other open screens, and a refused / command keeps its words.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const BASE = process.env.BASE_URL || 'http://127.0.0.1:8804';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const call = (p, path, body, token = 'tok123') => p.evaluate(async ([path, body, token]) => { const r = await fetch(path, { method: body ? 'POST' : 'GET', headers: { 'X-Token': token, 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined }); return { status: r.status, data: await r.json().catch(() => ({})) }; }, [path, body, token]);
(async () => {
  const b = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined, args: ['--no-sandbox'] });
  const errs = [];
  const p = await (await b.newContext({ viewport: { width: 1100, height: 800 } })).newPage();
  p.on('pageerror', e => errs.push('pageerror ' + e.message));
  await p.goto(BASE + '/#token=tok123'); await p.waitForSelector('.sys'); await p.waitForTimeout(600);

  // 1. someone else's waiting message is neither shown nor sent, and a change of account wipes drafts and waiting messages
  await p.evaluate(() => { localStorage.setItem('kt-outbox', JSON.stringify([{ id: 1, user: 'somebody-else', room: 'team', text: 'LEAKED TEXT', cid: 'x1', tries: 0 }])); localStorage.setItem('kt-draft-team', 'old private draft'); });
  await p.evaluate(() => flushOutbox()); await p.waitForTimeout(600);
  if (await p.locator('#outbox .queued').count()) errs.push('another account\'s waiting message is shown');
  if ((await call(p, '/api/messages?room=team&after=0')).data.some(m => m.text.includes('LEAKED TEXT'))) errs.push('another account\'s waiting message was sent');
  await p.evaluate(() => store.set('kt-token', 'tok-different'));
  const left = await p.evaluate(() => [localStorage.getItem('kt-outbox'), localStorage.getItem('kt-draft-team')]);
  if (left[0] || left[1]) errs.push('a change of account kept the old drafts/outbox: ' + JSON.stringify(left));
  await p.evaluate(() => store.set('kt-token', 'tok123')); await p.evaluate(() => { S.token = 'tok123'; });

  // 2. a message the server refuses goes back into the message box; a server hiccup keeps it waiting (and counts tries); every send carries a client id
  await p.evaluate(() => { window.__sent = []; const real = window.api; window.__real = real; window.api = async (path, body) => { if (path === '/api/say') { window.__sent.push(body); if (/REFUSED/.test(body.text)) throw Object.assign(new Error('not allowed'), { status: 403 }); if (/HICCUP/.test(body.text)) throw Object.assign(new Error('Request failed (502)'), { status: 502 }); } return real(path, body); }; });
  await p.evaluate(() => saveOutbox([{ id: 11, user: me().name, room: S.room, text: 'REFUSED one', cid: 'c-refused', tries: 0 }, { id: 12, user: me().name, room: S.room, text: 'HICCUP two', cid: 'c-hiccup', tries: 0 }]));
  await p.evaluate(() => flushOutbox()); await p.waitForTimeout(600);
  const ta = await p.inputValue('#msg');
  if (!ta.includes('REFUSED one')) errs.push('a refused waiting message was lost instead of returned to the message box: ' + JSON.stringify(ta));
  const kept = await p.evaluate(() => outbox().map(x => [x.text, x.tries]));
  if (JSON.stringify(kept) !== JSON.stringify([['HICCUP two', 1]])) errs.push('a server hiccup should keep the message waiting: ' + JSON.stringify(kept));
  if (!(await p.evaluate(() => window.__sent.every(s => s.cid)))) errs.push('a send had no client id');
  await p.evaluate(() => { saveOutbox([]); window.api = window.__real; });

  // 3. a failed approval click can be retried (the buttons come back)
  await p.evaluate(() => {
    const real = window.__real;
    S.state.approvals = [{ id: 951, agent: 'alice', tool: 'run_python', args: JSON.stringify({ code: 'print(1)' }), room: S.room, can_decide: true, can_remember: false, requested_by: 'owner' }];
    window.api = async (path, body) => { if (path === '/api/approve') throw Object.assign(new Error('Request failed (502)'), { status: 502 }); if (path === '/api/state') { const st = await real(path, body); st.approvals = S.state.approvals; return st; } return real(path, body); };
    sigChanged('inline', null); renderInline();
  });
  await p.click('.perm .btn.primary:has-text("Allow once")');
  await p.waitForTimeout(900);
  if (await p.locator('.perm .btn.primary:has-text("Allow once")').isDisabled()) errs.push('Allow once stayed disabled after a failed request');
  await p.evaluate(() => { window.api = window.__real; S.state.approvals = []; sigChanged('inline', null); renderInline(); });

  // 4. a refused / command keeps its words
  await p.evaluate(() => { window.api = async (path, body) => { if (path === '/api/tasks/create') throw new Error('this room has too many open tasks'); return window.__real(path, body); }; });
  await p.fill('#msg', '/task finish the budget'); await p.keyboard.press('Enter');
  await p.waitForFunction(() => document.querySelector('#msg').value.includes('/task finish the budget'), null, { timeout: 4000 }).catch(() => errs.push('a refused /task lost its text'));
  await p.evaluate(() => { window.api = window.__real; document.querySelector('#msg').value = ''; });

  // 5. look-alike link labels show where the link really goes
  const links = await p.evaluate(() => md('[paypal.com](https://paypal.co/login) [example.com/a](https://example.com/a) [bank.com/secure](https://bank.c/x)').innerHTML);
  if (!/\(paypal\.co\)/.test(links)) errs.push('paypal.com -> paypal.co is not flagged');
  if (!/\(bank\.c\)/.test(links)) errs.push('bank.com -> bank.c is not flagged');
  if (/example\.com\/a<\/a><span/.test(links)) errs.push('an honest link was flagged');

  // 6. a message deleted elsewhere disappears from this open screen
  const made = await call(p, '/api/say', { room: 'team', text: 'to be deleted by someone', as: 'you' });
  await p.waitForSelector('.row:has-text("to be deleted by someone")');
  await call(p, '/api/message/delete', { id: made.data.id });
  await p.waitForFunction(() => !document.body.innerText.includes('to be deleted by someone'), null, { timeout: 8000 }).catch(() => errs.push('a deleted message stayed on another open screen'));

  // 7. switching rooms while messages load never shows one room's messages in the other
  await call(p, '/api/dm', { a: 'you', b: 'bob' });
  await p.reload(); await p.waitForSelector('#msg', { state: 'attached' }); await p.waitForTimeout(800);
  await p.evaluate(() => poll(true));
  const dm = (await call(p, '/api/state')).data.rooms.find(r => r.kind === 'dm').name;
  await call(p, '/api/say', { room: dm, text: 'ONLY IN THE PRIVATE CHAT', as: 'you' });
  await p.route(new RegExp('/api/messages\\?room=' + dm), async (route) => { await sleep(1500); route.continue(); });
  await p.evaluate((dm) => openRoom(dm), dm);
  await sleep(150);
  await p.evaluate(() => openRoom('team'));
  await sleep(2600);
  const teamText = await p.innerText('#thread');
  if (teamText.includes('ONLY IN THE PRIVATE CHAT')) errs.push('the private chat\'s message appeared in #team after a quick room switch');
  await p.unroute(new RegExp('/api/messages\\?room=' + dm));

  console.log(errs.length ? 'PROBLEMS:\n' + errs.join('\n') : 'no errors');
  await b.close();
})().catch(e => { console.error('FAILED', e.message); process.exit(1); });
