const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const SHOTS = process.env.SHOTS || '/tmp';
const BASE = process.env.BASE_URL || 'http://127.0.0.1:8804';
(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined, args: ['--no-sandbox'] });
  const errors = [];
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await ctx.newPage();
  page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
  page.on('pageerror', e => errors.push('pageerror: ' + e.message));
  await page.goto(BASE + '/#token=tok123');
  await page.waitForSelector('.sys');
  await page.screenshot({ path: SHOTS + '/s1_welcome.png' });
  // chat with alice via DM
  await page.click('#sidebar .item:has-text("alice")');
  await page.waitForSelector('.hello');
  await page.screenshot({ path: SHOTS + '/s2_empty.png' });
  await page.fill('#msg', 'hi alice');
  await page.keyboard.press('Enter');
  await page.waitForSelector('.row:not(.me) .body');
  const html = await page.innerHTML('.row:not(.me) .body');
  if (html.includes('<script')) errors.push('XSS: script survived sanitising');
  if (!html.includes('<li>')) errors.push('markdown list not rendered');
  // approval flow
  await page.fill('#msg', 'use python to compute 17*23');
  await page.keyboard.press('Enter');
  await page.waitForSelector('.perm', {timeout: 8000});
  await page.screenshot({ path: SHOTS + '/s3_approval.png' });
  await page.click('.perm .btn.primary');
  await page.waitForFunction(() => document.body.innerText.includes('Done!'), null, { timeout: 15000 });
  await page.screenshot({ path: SHOTS + '/s4_done.png' });
  // lesson via failing tool
  await page.fill('#msg', 'read missing');
  await page.keyboard.press('Enter');
  await page.waitForFunction(() => document.querySelectorAll('.row:not(.me)').length >= 4, null, { timeout: 15000 });
  // drawer tabs
  await page.click('text=Details');
  await page.click('.tab:has-text("Lessons")');
  await page.waitForSelector('.card');
  await page.screenshot({ path: SHOTS + '/s5_drawer.png' });
  for (const t of ['Files', 'Schedule', 'Apps', 'Log', 'Agent']) { await page.click(`.tab:has-text("${t}")`); await page.waitForTimeout(300); }
  // new agent dialog
  await page.click('#sidebar >> text=New agent');
  await page.fill('.dialog input[type=text]', 'carol');
  await page.click('.dialog .btn.primary');
  await page.waitForSelector('#topbar .title:has-text("carol")');
  // mobile
  const m = await browser.newContext({ viewport: { width: 390, height: 780 }, deviceScaleFactor: 2 });
  const mp = await m.newPage();
  mp.on('pageerror', e => errors.push('mobile pageerror: ' + e.message));
  await mp.goto(BASE + '/#token=tok123');
  await mp.waitForSelector('.sys');
  await mp.screenshot({ path: SHOTS + '/m1.png' });
  await mp.click('#topbar button[aria-label="Open sidebar"]');
  await mp.waitForTimeout(400);
  await mp.screenshot({ path: SHOTS + '/m2.png' });
  const overflow = await mp.evaluate(() => document.documentElement.scrollWidth > innerWidth);
  if (overflow) errors.push('mobile: horizontal overflow');
  console.log(errors.length ? 'PROBLEMS:\n' + errors.join('\n') : 'no errors');
  await browser.close();
})().catch(e => { console.error('FAILED', e.message); process.exit(1); });
