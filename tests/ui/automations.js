const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const SHOTS = process.env.SHOTS || '/tmp';
const BASE = process.env.BASE_URL || 'http://127.0.0.1:8804';
(async () => {
  const b = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined, args: ['--no-sandbox'] });
  const errs = [];
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, timezoneId: 'Asia/Kolkata' });
  const p = await ctx.newPage();
  p.on('pageerror', e => errs.push('pageerror ' + e.message));
  p.on('console', m => { if (m.type() === 'error' && !m.text().includes('status of 400')) errs.push('console ' + m.text()); });
  await p.goto(BASE + '/#token=tok123'); await p.waitForSelector('.sys');
  await p.click('#topbar button[aria-label="Open sidebar"]');
  await p.click('#sidebar >> text=Automations');
  await p.waitForSelector('text=Use my phone\'s time zone');
  await p.screenshot({ path: SHOTS + '/a1_empty.png' });
  // time zone from the phone
  await p.click('text=Use my phone\'s time zone');
  await p.waitForSelector('text=/Asia\/(Kolkata|Calcutta)/');
  if (!(await p.locator('text=Web search is off').count())) errs.push('missing search-off notice');
  // a daily briefing on weekdays at 07:30
  await p.click('text=Daily briefing >> nth=-1');
  await p.fill('textarea[aria-label="Topics"]', 'AI news\nStartup funding');
  await p.fill('input[aria-label="Time"]', '07:30');
  await p.selectOption('select[aria-label="Days"]', 'weekdays');
  await p.click('.overlay:last-child .btn.primary');
  await p.waitForSelector('#auto-list >> text=Every weekday at 07:30');
  const card = await p.textContent('#auto-list .card');
  if (!/Next:/.test(card)) errs.push('no next run: ' + card);
  await p.screenshot({ path: SHOTS + '/a2_list.png' });
  // run it now: the title (not the long prompt) appears in the chat, followed by the reply
  await p.click('#auto-list >> text=Run now');
  await p.click('text=Done');
  await p.waitForSelector('.sys.cron:has-text("Daily briefing")', { timeout: 15000 });
  await p.waitForSelector('.row:not(.me) .body', { timeout: 15000 });
  // pause it
  await p.click('#sidebar >> text=Automations').catch(async () => { await p.click('#topbar button[aria-label="Open sidebar"]'); await p.click('#sidebar >> text=Automations'); });
  await p.click('#auto-list >> text=Pause'); await p.waitForSelector('#auto-list >> text=Paused >> nth=0');
  await p.click('#auto-list >> text=Resume'); await p.waitForSelector('#auto-list >> text=Next:');
  // a one-off research report starts immediately
  await p.click('text=Research report >> nth=-1');
  await p.fill('input[aria-label="Research topic"]', 'The electric scooter market in India');
  await p.check('#auto-now');
  if (await p.locator('#auto-when').isVisible()) errs.push('schedule fields still shown for a one-off report');
  await p.click('.overlay:last-child .btn.primary');
  await p.waitForSelector('#toast:has-text("report will appear")');
  // delete
  await p.click('#auto-list >> text=Delete'); await p.click('.overlay:last-child .btn.primary');
  await p.waitForSelector('#auto-list >> text=No automations yet');
  console.log(errs.length ? 'PROBLEMS:\n' + errs.join('\n') : 'no errors');
  await b.close();
})().catch(e => { console.error('FAILED', e.message); process.exit(1); });
