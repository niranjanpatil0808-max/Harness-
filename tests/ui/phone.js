// Phone-size checks found by looking at real screenshots: the top bar keeps the room name when an approval is waiting,
// no keyboard hints on a touch screen, a one-day usage chart is not a giant block, no sideways scrolling anywhere.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const BASE = process.env.BASE_URL || 'http://127.0.0.1:8804';
(async () => {
  const b = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined, args: ['--no-sandbox'] });
  const errs = [];
  const p = await (await b.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })).newPage();
  p.on('pageerror', e => errs.push('pageerror ' + e.message));
  await p.goto(BASE + '/#token=tok123'); await p.waitForSelector('#msg', { state: 'attached' }); await p.waitForTimeout(800);
  const overflow = async (where) => { if (await p.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)) errs.push('sideways scroll: ' + where); };
  await overflow('chat');
  await p.fill('#msg', '@alice work it out with python'); await p.keyboard.press('Enter');
  await p.waitForSelector('.perm', { timeout: 15000 });
  const pill = await p.evaluate(() => { const n = document.querySelector('#topbar .pill-btn.warn .pill-n'); return n.textContent + getComputedStyle(n, '::after').content; });
  if (!/1.*to approve/i.test(pill)) errs.push('approval pill text on a phone: ' + pill);
  const titleW = await p.evaluate(() => document.querySelector('#topbar .title').getBoundingClientRect().width);
  if (titleW < 60) errs.push('room name is squashed to ' + titleW + 'px by the approval pill');
  await p.click('.perm .btn.primary:has-text("Allow once")');
  await p.click('#topbar button[aria-label="Open sidebar"]');
  if (await p.locator('#sidebar kbd').isVisible().catch(() => false)) errs.push('a keyboard shortcut hint is shown on a touch screen');
  await p.keyboard.press('Escape');
  for (const tab of ['general', 'models', 'usage', 'team', 'internet', 'plugins', 'backup']) {
    await p.evaluate((t) => settingsDialog(t), tab); await p.waitForTimeout(350); await overflow('settings ' + tab);
    if (tab === 'usage') {
      const barW = await p.evaluate(() => { const el = document.querySelector('.bar'); return el ? el.getBoundingClientRect().width : 0; });
      if (barW > 60) errs.push('a one-day usage bar is ' + barW + 'px wide');
    }
    await p.keyboard.press('Escape');
  }
  await p.evaluate(() => tasksDialog()); await p.waitForTimeout(300); await overflow('tasks'); await p.keyboard.press('Escape');
  await p.evaluate(() => helpDialog()); await p.waitForTimeout(300); await overflow('help'); await p.keyboard.press('Escape');
  console.log(errs.length ? 'PROBLEMS:\n' + errs.join('\n') : 'no errors');
  await b.close();
})().catch(e => { console.error('FAILED', e.message); process.exit(1); });
