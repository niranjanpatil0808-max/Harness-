const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const BASE = process.env.BASE_URL || 'http://127.0.0.1:8804';
const FAKES = `
  window.__sr = { started: 0, mode: 'ok' }; window.__spoken = [];
  class FakeSR { start() { window.__sr.started++; this.onstart && this.onstart();
      setTimeout(() => { if (window.__sr.mode === 'denied') { this.onerror && this.onerror({ error: 'not-allowed' }); this.onend && this.onend(); return; }
        const r = Object.assign([{ transcript: window.__sr.say || 'hello there' }], { isFinal: true });
        this.onresult && this.onresult({ resultIndex: 0, results: [r] }); this.onend && this.onend(); }, 40); }
    stop() { this.onend && this.onend(); } }
  window.SpeechRecognition = FakeSR; window.webkitSpeechRecognition = FakeSR;
  window.SpeechSynthesisUtterance = function (t) { this.text = t; };
  Object.defineProperty(window, 'speechSynthesis', { configurable: true, value: { speaking: false, speak(u) { window.__spoken.push(u.text); setTimeout(() => u.onend && u.onend(), 15); }, cancel() {} } });
`;
(async () => {
  const b = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined, args: ['--no-sandbox'] });
  const errs = [];
  const open = async (init, setup) => {
    const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
    if (init) await ctx.addInitScript(init);
    const p = await ctx.newPage(); p.on('pageerror', e => errs.push('pageerror ' + e.message));
    await p.goto(BASE + '/#token=tok123'); await p.waitForSelector('.sys');
    await p.click('#topbar button[aria-label="Open sidebar"]'); await p.click('#sidebar .item:has-text("alice")'); await p.waitForSelector('#msg:not([disabled])');
    return p;
  };
  // 1. speech to text fills the box, and does not send by itself
  let p = await open(FAKES);
  await p.click('#mic'); await p.waitForFunction(() => document.querySelector('#msg').value.includes('hello there'));
  if ((await p.locator('.row.me').count()) !== 0) errs.push('sent without being asked');
  // 2. read aloud: new replies only, with code/links cleaned
  await p.click('#spk');
  const before = await p.evaluate(() => window.__spoken.length);
  await p.fill('#msg', 'hi alice'); await p.keyboard.press('Enter');
  await p.waitForFunction(() => window.__spoken.length > 0, null, { timeout: 15000 });
  const said = (await p.evaluate(() => window.__spoken))[0];
  if (before !== 0) errs.push('backlog was spoken');
  if (/```|print\(|https?:|\*\*/.test(said)) errs.push('speech not cleaned: ' + said);
  if (!said.includes('code omitted') || !said.includes('a link')) errs.push('speech content wrong: ' + said);
  // 3. a reload must not read the history aloud
  await p.reload(); await p.waitForSelector('.sys'); await p.waitForTimeout(1500);
  if ((await p.evaluate(() => window.__spoken.length)) !== 0) errs.push('history spoken after reload');
  await p.context().close();
  // 4. hands-free: speak -> sent -> reply spoken -> listens again
  p = await open(FAKES);
  await p.click('#topbar button[aria-label="Open sidebar"]'); await p.click('button[aria-label="Settings"]');
  await p.waitForSelector('text=Hands-free conversation');
  await p.click('input[type=checkbox] >> nth=1');
  await p.keyboard.press('Escape');  // closes Settings
  await p.keyboard.press('Escape');  // closes the sidebar behind it
  await p.waitForTimeout(300);
  await p.click('#mic');
  await p.waitForFunction(() => window.__sr.started >= 2 && window.__spoken.length >= 1, null, { timeout: 20000 });
  await p.context().close();
  // 5. a blocked microphone gives a human message
  p = await open(FAKES + "window.__sr.mode = 'denied';");
  await p.click('#mic'); await p.waitForSelector('#toast.err'); const msg = await p.textContent('#toast');
  if (!/Microphone blocked/.test(msg)) errs.push('denied message: ' + msg);
  await p.context().close();
  // 6. a browser with no speech support shows no mic and says so in settings
  p = await open("window.SpeechRecognition = undefined; window.webkitSpeechRecognition = undefined;");
  if ((await p.locator('#mic').count()) !== 0) errs.push('mic shown without support');
  await p.click('#topbar button[aria-label="Open sidebar"]'); await p.click('button[aria-label="Settings"]');
  await p.waitForSelector('text=Voice input is not available');
  console.log(errs.length ? 'PROBLEMS:\n' + errs.join('\n') : 'no errors');
  await b.close();
})().catch(e => { console.error('FAILED', e.message); process.exit(1); });
