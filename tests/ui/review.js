const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const BASE = process.env.BASE_URL || 'http://127.0.0.1:8804';
(async () => {
  const b = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined, args: ['--no-sandbox'] });
  const errs = [];
  const ctx = await b.newContext({ viewport: { width: 1100, height: 800 } });
  const p = await ctx.newPage();
  p.on('pageerror', e => errs.push('pageerror: ' + e.message));
  await p.goto(BASE + '/#token=tok123');
  await p.waitForSelector('#sidebar .item:has-text("alice")');
  // 1. hostile message HTML cannot restyle, cover, or imitate the app
  const result = await p.evaluate(() => {
    const evil = '<style>.perm pre{display:none}body{display:none}</style><div style="position:fixed;inset:0;z-index:99999">cover</div><form action="https://evil.example"><input name="pw"></form><p id="x" class="perm">fake</p><img src=x onerror="window.pwned=1">';
    const card = document.createElement('div'); card.className = 'perm'; card.innerHTML = '<pre id="real">real code</pre>'; document.body.append(card);
    const msg = md(evil); document.body.append(msg);
    const out = { style: msg.querySelectorAll('style').length, inline: msg.querySelectorAll('[style]').length, form: msg.querySelectorAll('form,input').length, ids: msg.querySelectorAll('[id]').length, classes: msg.querySelectorAll('[class]:not(.copy)').length,
      realVisible: getComputedStyle(document.getElementById('real')).display !== 'none', bodyVisible: getComputedStyle(document.body).display !== 'none', pwned: !!window.pwned, text: msg.textContent.includes('cover') };
    card.remove(); msg.remove(); return out;
  });
  if (result.style || result.inline || result.form || result.ids || result.classes) errs.push('hostile markup survived: ' + JSON.stringify(result));
  if (!result.realVisible || !result.bodyVisible) errs.push('hostile CSS changed the app: ' + JSON.stringify(result));
  if (result.pwned) errs.push('script ran');
  // 2. a link with someone else's token must not silently replace who you are
  const member = await p.evaluate(async () => {
    const inv = await (await fetch('/api/team/invite', { method: 'POST', headers: { 'X-Token': 'tok123', 'Content-Type': 'application/json' }, body: '{}' })).json();
    return await (await fetch('/api/join', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code: inv.code, name: 'mallory' }) })).json();
  });
  await p.goto(BASE + '/#token=' + member.token); await p.reload();  // a link opened in a fresh tab runs the app from the start
  await p.waitForSelector('.dialog:has-text("Sign in as mallory")');
  await p.click('.btn:has-text("Keep my current sign-in")');
  await p.waitForSelector('#sidebar .side-foot:has-text("you")');
  if (await p.evaluate(() => localStorage.getItem('kt-token')) !== 'tok123') errs.push('the stored token was replaced without consent');
  await p.goto(BASE + '/#token=' + member.token); await p.reload();  // a link opened in a fresh tab runs the app from the start
  await p.waitForSelector('.dialog:has-text("Sign in as mallory")');
  await p.click('.btn.primary:has-text("Sign in as mallory")');
  await p.waitForSelector('#sidebar .side-foot:has-text("mallory")');
  // 3. sign-out clears drafts left on the device
  await p.evaluate(() => { localStorage.setItem('kt-draft-team', 'unsent private text'); localStorage.setItem('kt-seen', '{}'); });
  await p.click('button[aria-label="Settings"]');
  await p.click('.btn:has-text("Sign out on this device")'); await p.click('.overlay:last-child .btn.primary');
  await p.waitForSelector('input[aria-label="Access token"]', { timeout: 8000 });
  const left = await p.evaluate(() => Object.keys(localStorage).filter(k => k.startsWith('kt-draft-') || k === 'kt-seen'));
  if (left.length) errs.push('sign-out left data behind: ' + left.join(','));
  console.log(errs.length ? 'PROBLEMS:\n' + errs.join('\n') : 'no errors');
  await b.close();
})().catch(e => { console.error('FAILED', e.message); process.exit(1); });
