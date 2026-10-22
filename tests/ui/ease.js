const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const BASE = process.env.BASE_URL || 'http://127.0.0.1:8804';
(async () => {
  const b = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined, args: ['--no-sandbox'] });
  const errs = [];
  const c = await b.newContext({ viewport: { width: 390, height: 780 }, isMobile: true, hasTouch: true });
  const p = await c.newPage();
  p.on('pageerror', e => errs.push('pageerror: ' + e.message));
  await p.goto(BASE + '/#token=tok123');
  await p.waitForSelector('#to .chip');
  // a room defaults to its first agent, shown in the placeholder, so no @ is needed
  if (!(await p.getAttribute('#msg', 'placeholder')).includes('@alice')) errs.push('placeholder does not name the recipient');
  if ((await p.locator('#starters .chip').count()) < 3) errs.push('starter ideas missing');
  // a starter fills the box instead of sending
  await p.click('#starters .chip >> nth=0');
  if (!(await p.inputValue('#msg')).length) errs.push('starter did not fill the message');
  // a plain message is addressed to the chosen agent
  await p.fill('#msg', 'hello there'); await p.keyboard.press('Enter');
  await p.waitForSelector('.row.me .bubble:has-text("@alice hello there")');
  if (await p.locator('#starters .chip').count()) errs.push('starters should go away after the first message');
  // switching the recipient changes who gets the next plain message
  await p.click('#to .chip:has-text("@bob")');
  if (!(await p.getAttribute('#msg', 'placeholder')).includes('@bob')) errs.push('placeholder did not follow the recipient');
  await p.fill('#msg', 'status please'); await p.keyboard.press('Enter');
  await p.waitForSelector('.row.me .bubble:has-text("@bob status please")');
  // an explicit @ is never overridden
  await p.fill('#msg', '@alice and you?'); await p.keyboard.press('Enter');
  await p.waitForSelector('.row.me .bubble:has-text("@alice and you?")');
  if (await p.locator('.row.me .bubble:has-text("@bob @alice")').count()) errs.push('double addressing');
  if (await p.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)) errs.push('page overflows sideways');
  console.log(errs.length ? 'PROBLEMS:\n' + errs.join('\n') : 'no errors');
  await b.close();
})().catch(e => { console.error('FAILED', e.message); process.exit(1); });
