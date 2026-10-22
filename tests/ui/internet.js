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
  await p.click('#sidebar .item:has-text("alice")');
  await p.click('#topbar button:has-text("Details")');
  await p.waitForSelector('h4:has-text("Internet")');
  // new agents start on Ask (never silently Allow)
  if (!(await p.getAttribute('[aria-label="Internet access"] button:has-text("Ask")', 'class') || '').includes('on')) errs.push('default is not Ask');
  await p.click('[aria-label="Internet access"] button:has-text("Allow")');
  await p.waitForSelector('[aria-label="Internet access"] button.on:has-text("Allow")');
  await p.waitForSelector('text=may search and read public pages');
  // the workspace switch overrides it and the drawer says so
  await p.click('button[aria-label="Settings"]'); await p.click('.tab:has-text("Internet")');
  await p.waitForSelector('input[aria-label="Let agents use the internet"]');
  await p.uncheck('input[aria-label="Let agents use the internet"]'); await p.fill('input[aria-label="Page fetches per day"]', '5');
  await p.click('.dialog .btn.primary:has-text("Save")'); await p.waitForTimeout(600);
  await p.click('.dialog .btn.primary:has-text("Done")');
  await p.waitForSelector('text=workspace switch in Settings > Internet is OFF', { timeout: 6000 }).catch(() => errs.push('drawer does not warn that the master switch is off'));
  console.log(errs.length ? 'PROBLEMS:\n' + errs.join('\n') : 'no errors');
  await b.close();
})().catch(e => { console.error('FAILED', e.message); process.exit(1); });
