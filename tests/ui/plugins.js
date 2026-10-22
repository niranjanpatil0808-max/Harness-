const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const BASE = process.env.BASE_URL || 'http://127.0.0.1:8804';
(async () => {
  const b = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined, args: ['--no-sandbox'] });
  const errs = [];
  const c = await b.newContext({ viewport: { width: 1100, height: 800 } });
  const p = await c.newPage();
  p.on('pageerror', e => errs.push('pageerror: ' + e.message));
  await p.goto(BASE + '/#token=tok123');
  await p.waitForSelector('#sidebar .item:has-text("alice")');
  await p.click('button[aria-label="Settings"]'); await p.click('.tab:has-text("Plugins")');
  await p.waitForSelector('text=No plugins yet');
  // preview shows everything: hosts, the full skill text, a fingerprint; nothing is installed yet
  await p.click('.chip:has-text("Weather")');
  await p.waitForSelector('text=It can contact: ');
  await p.waitForSelector('text=api.open-meteo.com');
  await p.waitForSelector('text=Fingerprint');
  await p.waitForSelector('pre:has-text("call open_meteo__now")');
  await p.check('input[aria-label="Switch on for alice"]');
  await p.click('.overlay:last-child .btn.primary:has-text("Install")');
  await p.waitForSelector('strong:has-text("Weather (Open-Meteo) 1.0.0")');
  if (!(await p.locator('.chip.on:has-text("alice")').count())) errs.push('alice was not switched on');
  if (await p.locator('.chip.on:has-text("bob")').count()) errs.push('bob must stay off until the owner switches it on');
  // the agent drawer shows the same switch
  await p.click('.dialog .btn.primary:has-text("Done")');
  await p.click('#sidebar .item:has-text("alice")'); await p.click('#topbar button:has-text("Details")');
  await p.waitForSelector('h4:has-text("Plugins")');
  await p.waitForSelector('#drawer .chip.on:has-text("Weather")');
  await p.click('#drawer .chip:has-text("Weather")');
  await p.waitForSelector('#drawer .chip:not(.on):has-text("Weather")');
  // a broken manifest gives a plain message
  await p.click('button[aria-label="Settings"]'); await p.click('.tab:has-text("Plugins")');
  await p.click('summary:has-text("paste")'); await p.fill('textarea[aria-label="Plugin manifest"]', '{"id": "xx"}'); await p.click('details >> text=Preview');
  await p.waitForSelector('#toast:has-text("at least one")', { timeout: 5000 }).catch(() => errs.push('no readable error for a bad manifest'));
  await p.click('.btn.danger:has-text("Remove")'); await p.click('.overlay:last-child .btn.primary'); await p.waitForSelector('text=No plugins yet');
  console.log(errs.length ? 'PROBLEMS:\n' + errs.join('\n') : 'no errors');
  await b.close();
})().catch(e => { console.error('FAILED', e.message); process.exit(1); });
