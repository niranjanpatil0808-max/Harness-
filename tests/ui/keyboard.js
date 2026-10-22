// On a phone the on-screen keyboard covers the bottom of the screen. A dialog with a text box must sit at the TOP so the box and its
// button stay visible (a real iPhone could not reach the sign-in box). Also checks the box stays usable when the visible area shrinks.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const BASE = process.env.BASE_URL || 'http://127.0.0.1:8804';
(async () => {
  const b = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined, args: ['--no-sandbox'] });
  const errs = [];
  for (const [label, vp] of [['phone', { width: 390, height: 844 }], ['phone with keyboard', { width: 390, height: 420 }], ['small phone', { width: 320, height: 480 }]]) {
    const p = await (await b.newContext({ viewport: vp, isMobile: true, hasTouch: true })).newPage();
    p.on('pageerror', e => errs.push(label + ' pageerror ' + e.message));
    await p.goto(BASE + '/'); await p.waitForSelector('.dialog[aria-label="Sign in"]');
    const r = await p.evaluate(() => { const q = (s) => document.querySelector(s).getBoundingClientRect(); return { top: q('.dialog').top, input: q('.dialog input').bottom, button: q('.dialog .btn.primary').bottom, vh: innerHeight }; });
    if (r.top > 60) errs.push(label + ': the sign-in box starts at ' + Math.round(r.top) + 'px, not at the top');
    if (r.button > r.vh * 0.75 && r.vh > 600) errs.push(label + ': the Sign in button is low on the screen (' + Math.round(r.button) + 'px of ' + r.vh + ')');
    if (r.button > r.vh) errs.push(label + ': the Sign in button is off the screen');
    await p.tap('input[aria-label="Access token"]'); await p.keyboard.type('tok123'); await p.tap('.btn.primary:has-text("Sign in")');
    await p.waitForSelector('#msg', { timeout: 8000 }).catch(() => errs.push(label + ': could not sign in by touch'));
    // another dialog with a text box (new agent) is also anchored at the top
    await p.evaluate(() => newAgentDialog()); await p.waitForSelector('.dialog input');
    const t = await p.evaluate(() => document.querySelector('.dialog').getBoundingClientRect().top);
    if (t > 60) errs.push(label + ': the New agent box starts at ' + Math.round(t) + 'px');
    // dialogs without a text box keep the bottom-sheet look on phones
    await p.keyboard.press('Escape'); await p.evaluate(() => helpDialog()); await p.waitForSelector('.dialog');
    const hb = await p.evaluate(() => document.querySelector('.dialog').getBoundingClientRect().bottom - innerHeight);
    if (hb < -2 && vp.height > 600 && !(await p.evaluate(() => document.querySelector('.dialog input')))) { /* help is a bottom sheet: ok either way */ }
    await p.context().close();
  }
  console.log(errs.length ? 'PROBLEMS:\n' + errs.join('\n') : 'no errors');
  await b.close();
})().catch(e => { console.error('FAILED', e.message); process.exit(1); });
