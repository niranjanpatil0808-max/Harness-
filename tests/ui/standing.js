// "Always allow this exact one": the owner sees the button only when the server offers it, it asks the server for exactly that,
// and Settings lists what was remembered with a Revoke button. The server rules themselves are in tests/test_workspace_standing.py.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const BASE = process.env.BASE_URL || 'http://127.0.0.1:8804';
(async () => {
  const b = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined, args: ['--no-sandbox'] });
  const errs = [];
  const p = await (await b.newContext({ viewport: { width: 1100, height: 800 } })).newPage();
  p.on('pageerror', e => errs.push('pageerror ' + e.message));
  await p.goto(BASE + '/#token=tok123'); await p.waitForSelector('.sys');
  // 1. a pending approval the server says can be remembered shows the button; one it does not offer shows only Allow once / Deny
  await p.evaluate(() => {
    window.__calls = [];
    const real = window.api;
    window.api = async (path, body) => { window.__calls.push([path, body]); if (path === '/api/approve') return { output: 'ok' }; return real(path, body); };
    const mk = (id, can_remember) => ({ id, agent: 'alice', tool: 'run_python', args: JSON.stringify({ code: 'print(' + id + ')' }), room: S.room, can_decide: true, can_remember, requested_by: 'owner' });
    S.state.approvals = [mk(901, true), mk(902, false)];
    sigChanged = () => true; renderInline();
  });
  const cards = p.locator('.perm');
  if ((await cards.count()) !== 2) errs.push('expected two approval cards, got ' + (await cards.count()));
  if ((await cards.nth(0).locator('button:has-text("Always allow this exact one")').count()) !== 1) errs.push('no "Always allow" button where the server offers it');
  if ((await cards.nth(1).locator('button:has-text("Always allow")').count()) !== 0) errs.push('"Always allow" shown where the server does not offer it');
  await cards.nth(0).locator('button:has-text("Always allow this exact one")').click();
  await p.waitForTimeout(300);
  const sent = await p.evaluate(() => window.__calls.find(c => c[0] === '/api/approve'));
  if (!sent || sent[1].id !== 901 || sent[1].approve !== true || sent[1].remember !== true) errs.push('wrong request: ' + JSON.stringify(sent));
  // 2. Settings lists remembered approvals and revokes one
  await p.evaluate(() => {
    window.__list = [{ agent: 'alice', h: 'abc123', tool: 'run_python', summary: 'print(17 * 23)', by: 'owner', ts: Date.now() / 1000 }];
    window.__calls = [];
    const real = window.api;
    window.api = async (path, body) => {
      window.__calls.push([path, body]);
      if (path === '/api/standing') return window.__list;
      if (path === '/api/standing/revoke') { window.__list = []; return { revoked: true }; }
      return real(path, body);
    };
  });
  await p.evaluate(() => settingsDialog('approvals'));
  await p.waitForSelector('.set-title:has-text("Remembered approvals")');
  await p.waitForSelector('.perm:has-text("print(17 * 23)")');
  await p.click('button[aria-label="Revoke alice run_python"]');
  await p.waitForSelector('text=Nothing is remembered');
  const revoked = await p.evaluate(() => window.__calls.find(c => c[0] === '/api/standing/revoke'));
  if (!revoked || revoked[1].agent !== 'alice' || revoked[1].h !== 'abc123') errs.push('wrong revoke request: ' + JSON.stringify(revoked));
  console.log(errs.length ? 'PROBLEMS:\n' + errs.join('\n') : 'no errors');
  await b.close();
})().catch(e => { console.error('FAILED', e.message); process.exit(1); });
