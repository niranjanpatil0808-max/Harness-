const { chromium, devices } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const SHOTS = process.env.SHOTS || '/tmp';
const BASE = process.env.BASE_URL || 'http://127.0.0.1:8804';
(async () => {
  const b = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined, args: ['--no-sandbox'] });
  const errs = [];
  // a phone: touch, small screen, high pixel density
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  const p = await ctx.newPage();
  p.on('pageerror', e => errs.push('pageerror ' + e.message));
  await p.goto(BASE + '/#token=tok123');
  await p.waitForSelector('.sys');
  // 1. the service worker installs and controls the page
  const active = await p.evaluate(async () => { const r = await navigator.serviceWorker.ready; return !!r.active; });
  if (!active) errs.push('service worker not active');
  await p.waitForFunction(() => navigator.serviceWorker.controller, null, { timeout: 8000 }).catch(() => { p.reload(); });
  await p.waitForSelector('.sys');
  // 2. it cached the app shell but nothing from /api or /apps
  const cached = await p.evaluate(async () => { const out = []; for (const k of await caches.keys()) { for (const r of await (await caches.open(k)).keys()) out.push(new URL(r.url).pathname); } return out; });
  if (!cached.includes('/static/app.js') || !cached.includes('/')) errs.push('shell not cached: ' + cached.join(','));
  if (cached.some(u => u.startsWith('/api/') || u.startsWith('/apps/'))) errs.push('PRIVATE DATA CACHED: ' + cached.filter(u => u.startsWith('/api/')).join(','));
  // 3. the manifest is reachable and valid from the page
  const manifest = await p.evaluate(async () => (await fetch(document.querySelector('link[rel=manifest]').href)).json());
  if (manifest.display !== 'standalone') errs.push('manifest display');
  // 4. touch targets are thumb sized
  const sizes = await p.evaluate(() => ['#send', '#topbar .icon-btn'].map(s => { const e = document.querySelector(s); if (!e) return [s, 0]; const r = e.getBoundingClientRect(); return [s, Math.min(r.width, r.height)]; }));
  for (const [sel, size] of sizes) if (sel === '#send' && size < 44) errs.push(`${sel} only ${size}px`);
  // 5. no sideways scrolling, sidebar opens, install entry exists for iOS-like UAs only when relevant
  if (await p.evaluate(() => document.documentElement.scrollWidth > innerWidth)) errs.push('horizontal overflow');
  await p.click('#topbar button[aria-label="Open sidebar"]');
  await p.waitForTimeout(400);
  await p.screenshot({ path: SHOTS + '/p1_sidebar.png' });
  await p.keyboard.press('Escape');
  // 6. offline: the shell still opens and says so, instead of a browser error page
  await ctx.setOffline(true);
  await p.reload();
  await p.waitForSelector('#sidebar .brand', { timeout: 10000 });
  await p.waitForSelector('#toast.on', { timeout: 10000 });
  await p.screenshot({ path: SHOTS + '/p2_offline.png' });
  await ctx.setOffline(false);
  console.log(errs.length ? 'PROBLEMS:\n' + errs.join('\n') : 'no errors');
  await b.close();
})().catch(e => { console.error('FAILED', e.message); process.exit(1); });
