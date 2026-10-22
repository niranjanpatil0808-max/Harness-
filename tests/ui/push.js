const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const BASE = process.env.BASE_URL || 'http://127.0.0.1:8804';
// Headless Chromium cannot reach a real push service, so the browser's subscription API is faked; the server side is real.
const FAKE_PUSH = `
  window.__sub = null;
  Object.defineProperty(Notification, 'permission', { get: () => window.__perm || 'default', configurable: true });
  Notification.requestPermission = async () => { window.__perm = window.__deny ? 'denied' : 'granted'; return window.__perm; };
  const fakeManager = { getSubscription: async () => window.__sub,
    subscribe: async (opts) => { window.__opts = opts; window.__sub = { endpoint: 'http://127.0.0.1:8806/push/phone-1', toJSON() { return { endpoint: this.endpoint }; }, unsubscribe: async () => { window.__sub = null; return true; } }; return window.__sub; } };
  Object.defineProperty(ServiceWorkerRegistration.prototype, 'pushManager', { get: () => fakeManager, configurable: true });
`;
(async () => {
  const b = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined, args: ['--no-sandbox'] });
  const errs = [];
  const mk = async (init) => { const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true }); if (init) await ctx.addInitScript(init);
    const p = await ctx.newPage(); p.on('pageerror', e => errs.push('pageerror ' + e.message)); await p.goto(BASE + '/#token=tok123'); await p.waitForSelector('.sys');
    await p.click('#topbar button[aria-label="Open sidebar"]'); await p.click('button[aria-label="Settings"]'); await p.waitForSelector('#push-row'); return p; };
  const devices = (p) => p.evaluate(async () => (await (await fetch('/api/push', { headers: { 'X-Token': 'tok123' } })).json()).devices);
  // 1. turn on -> subscribed with the server's public key, then test, then off
  let p = await mk(FAKE_PUSH);
  await p.waitForSelector('text=Turn on notifications');
  await p.click('text=Turn on notifications'); await p.waitForSelector('text=Notifications are on for this device');
  if ((await devices(p)) !== 1) errs.push('server did not record the device');
  const keyLen = await p.evaluate(() => window.__opts.applicationServerKey.length); if (keyLen !== 65) errs.push('applicationServerKey is ' + keyLen + ' bytes, expected 65');
  await p.click('text=Send a test'); await p.waitForSelector('#toast:has-text("Sent")');
  await p.click('text=Turn off'); await p.waitForSelector('text=Turn on notifications');
  if ((await devices(p)) !== 0) errs.push('device not removed');
  await p.context().close();
  // 2. blocked permission gives a human message and subscribes nothing
  p = await mk("window.__deny = true;" + FAKE_PUSH);
  await p.click('text=Turn on notifications'); await p.waitForSelector('#toast.err');
  if (!/blocked/i.test(await p.textContent('#toast'))) errs.push('blocked message: ' + await p.textContent('#toast'));
  if ((await devices(p)) !== 0) errs.push('subscribed despite refusal');
  await p.context().close();
  // 3. iPhone in a normal browser tab is told to add the app to the Home Screen first
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1' });
  await ctx.addInitScript(FAKE_PUSH);
  p = await ctx.newPage(); await p.goto(BASE + '/#token=tok123'); await p.waitForSelector('.sys');
  await p.click('#topbar button[aria-label="Open sidebar"]'); await p.click('button[aria-label="Settings"]');
  await p.waitForSelector('text=add the app to your Home Screen');
  console.log(errs.length ? 'PROBLEMS:\n' + errs.join('\n') : 'no errors');
  await b.close();
})().catch(e => { console.error('FAILED', e.message); process.exit(1); });
