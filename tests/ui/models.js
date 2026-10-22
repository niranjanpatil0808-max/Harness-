const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const BASE = process.env.BASE_URL || 'http://127.0.0.1:8804';
(async () => {
  const b = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined, args: ['--no-sandbox'] });
  const errs = [];
  const c = await b.newContext({ viewport: { width: 390, height: 780 }, isMobile: true, hasTouch: true });
  const p = await c.newPage();
  p.on('pageerror', e => errs.push('pageerror: ' + e.message));
  await p.goto(BASE + '/#token=tok123');
  await p.waitForSelector('#topbar');
  await p.click('#topbar button >> nth=0'); await p.click('button[aria-label="Settings"]');
  await p.click('.set-item:has-text("Models")');
  await p.waitForSelector('text=No model is set up yet');
  // a bad address is refused with a readable message and nothing is saved
  await p.selectOption('select[aria-label="Provider type"]', 'custom');
  await p.fill('input[aria-label="Address"]', 'http://evil.example.com/v1'); await p.fill('input[aria-label="API key"]', 'sk-ui-secret-key');
  await p.fill('input[aria-label="Model name"]', 'm1'); await p.click('text=Save >> nth=-1');
  await p.waitForSelector('#toast.show, #toast:has-text("https")', { timeout: 5000 }).catch(() => errs.push('no error shown for a bad address'));
  // a good one is saved, becomes the default, and the key never appears on the page
  await p.selectOption('select[aria-label="Provider type"]', 'groq'); await p.fill('input[aria-label="API key"]', 'sk-ui-secret-key');
  await p.click('text=Save >> nth=-1'); await p.waitForSelector('strong:has-text("Groq")');
  if (!(await p.locator('strong:has-text("default")').count())) errs.push('first provider is not the default');
  if ((await p.content()).includes('sk-ui-secret-key')) errs.push('API KEY VISIBLE');
  if (await p.evaluate(() => document.querySelector('.dialog').scrollWidth > document.querySelector('.dialog').clientWidth + 1)) errs.push('models tab overflows');
  await p.click('button:has-text("Remove")'); await p.click('.overlay:last-child .btn.primary'); await p.waitForSelector('text=No model is set up yet');
  console.log(errs.length ? 'PROBLEMS:\n' + errs.join('\n') : 'no errors');
  await b.close();
})().catch(e => { console.error('FAILED', e.message); process.exit(1); });
