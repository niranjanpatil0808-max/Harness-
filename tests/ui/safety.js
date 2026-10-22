const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const SHOTS = process.env.SHOTS || '/tmp';
const BASE = process.env.BASE_URL || 'http://127.0.0.1:8804';
(async () => {
  const b = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined, args: ['--no-sandbox'] });
  const errs = [];
  const ctx = await b.newContext({ viewport: { width: 1280, height: 800 }, acceptDownloads: true });
  const p = await ctx.newPage();
  p.on('pageerror', e => errs.push('pageerror ' + e.message));
  p.on('console', m => { if (m.type() === 'error') errs.push('console ' + m.text()); });
  await p.goto(BASE + '/#token=tok123');
  await p.waitForSelector('.sys');
  await p.click('#sidebar .item:has-text("alice")');
  await p.click('text=Details');
  // secrets
  await p.fill('input[aria-label="Secret name"]', 'DEMO_KEY');
  await p.fill('input[aria-label="Secret value"]', 'sk-very-secret-value');
  await p.click('text=Save secret');
  await p.waitForSelector('.card code:has-text("DEMO_KEY")');
  if ((await p.content()).includes('sk-very-secret-value')) errs.push('SECRET VALUE VISIBLE IN PAGE');
  // safety tab
  await p.click('.tab:has-text("Safety")');
  await p.waitForSelector('text=Where your code runs');
  await p.screenshot({ path: SHOTS + '/e1_safety.png' });
  const [dl] = await Promise.all([p.waitForEvent('download'), p.click('text=Download everything')]);
  const fs = require('fs'); const path = await dl.path(); const txt = fs.readFileSync(path, 'utf8');
  if (txt.includes('sk-very-secret-value')) errs.push('SECRET IN EXPORT');
  if (!txt.includes('"agents"')) errs.push('export malformed');
  // publish an app through the API and open signed link
  await p.evaluate(async () => { });
  // delete bob
  await p.click('#sidebar .item:has-text("team")');
  await p.waitForSelector('#drawer select');
  await p.selectOption('#drawer select', 'bob');
  await p.waitForTimeout(500);
  await p.click('.tab:has-text("Safety")');
  await p.click('button:has-text("Delete agent bob")');
  await p.click('.dialog .btn.primary');
  await p.waitForFunction(() => !document.querySelector('#sidebar').innerText.includes('bob'), null, { timeout: 8000 });
  await p.screenshot({ path: SHOTS + '/e2_after_delete.png' });
  // approval card isolation wording
  await p.click('#sidebar .item:has-text("alice")');
  await p.fill('#msg', 'use python to compute 17*23'); await p.keyboard.press('Enter');
  await p.waitForSelector('.perm');
  const meta = await p.textContent('.perm .meta');
  console.log('approval meta:', meta);
  console.log(errs.length ? 'PROBLEMS:\n' + errs.join('\n') : 'no errors');
  await b.close();
})().catch(e => { console.error('FAILED', e.message); process.exit(1); });
