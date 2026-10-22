// "Share to Kintsugi" from the phone: the shared text lands in the message box as a draft, is removed from the address bar,
// and is never sent without a tap.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const BASE = process.env.BASE_URL || 'http://127.0.0.1:8804';
(async () => {
  const b = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined, args: ['--no-sandbox'] });
  const errs = [];
  const p = await (await b.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })).newPage();
  p.on('pageerror', e => errs.push('pageerror ' + e.message));
  await p.goto(BASE + '/#token=tok123'); await p.waitForSelector('.sys');
  const manifest = await p.evaluate(async () => (await fetch(document.querySelector('link[rel=manifest]').href)).json());
  const t = manifest.share_target;
  if (!t || t.method !== 'GET' || t.params.text !== 'share_text' || t.params.url !== 'share_url') errs.push('manifest has no usable share_target: ' + JSON.stringify(t));
  const before = await p.locator('.msg').count();
  await p.goto(BASE + '/?share_title=Launch%20plan&share_text=Summarise%20this%20page&share_url=https%3A%2F%2Fexample.com%2Fa');
  await p.waitForSelector('.sys');
  await p.waitForFunction(() => document.querySelector('#msg') && document.querySelector('#msg').value.includes('example.com'));
  const v = await p.inputValue('#msg');
  if (!/Launch plan\nSummarise this page\nhttps:\/\/example\.com\/a/.test(v)) errs.push('draft is wrong: ' + JSON.stringify(v));
  if (p.url().includes('share_')) errs.push('shared text left in the address bar: ' + p.url());
  if (await p.locator('.msg.me:has-text("Summarise this page")').count()) errs.push('shared text was sent without a tap');
  if ((await p.locator('#send').isDisabled())) errs.push('send is disabled although there is a draft');
  console.log(errs.length ? 'PROBLEMS:\n' + errs.join('\n') : 'no errors');
  await b.close();
})().catch(e => { console.error('FAILED', e.message); process.exit(1); });
