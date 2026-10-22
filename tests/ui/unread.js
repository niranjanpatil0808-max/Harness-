const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const BASE = process.env.BASE_URL || 'http://127.0.0.1:8804';
(async () => {
  const b = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined, args: ['--no-sandbox'] });
  const errs = [];
  const p = await (await b.newContext({ viewport: { width: 1100, height: 800 } })).newPage();
  p.on('pageerror', e => errs.push('pageerror ' + e.message));
  await p.goto(BASE + '/#token=tok123'); await p.waitForSelector('.sys');   // we are looking at the "team" room
  const api = (path, body) => p.evaluate(async ([path, body]) => { const r = await fetch(path, { method: 'POST', headers: { 'X-Token': 'tok123', 'Content-Type': 'application/json' }, body: JSON.stringify(body) }); return r.json(); }, [path, body]);
  // an agent answers in a different chat while we are elsewhere
  const dm = await api('/api/dm', { a: 'you', b: 'alice' });
  await api('/api/say', { room: dm.room, text: 'hi alice' });
  await p.waitForFunction(() => document.title.startsWith('(1)'), null, { timeout: 15000 });
  const row = p.locator('#sidebar .room-item, #sidebar .item', { hasText: 'alice' }).first();
  if (!(await p.locator('#sidebar .item:has-text("alice") .dot').count())) errs.push('no unread dot on the chat with news');
  if ((await p.locator('#sidebar .item:has-text("team") .dot').count()) !== 0) errs.push('the room we are in shows as unread');
  // opening it clears the marker and the title
  await p.click('#sidebar .item:has-text("alice")');
  await p.waitForFunction(() => document.title === 'Kintsugi', null, { timeout: 8000 });
  if ((await p.locator('#sidebar .item:has-text("alice") .dot').count()) !== 0) errs.push('dot did not clear');
  // our own message never marks a chat unread
  await p.fill('#msg', 'thanks'); await p.keyboard.press('Enter'); await p.waitForSelector('.row:not(.me) .body');
  await p.click('#sidebar .item:has-text("team")');
  await p.waitForTimeout(2500);
  if (await p.evaluate(() => document.title) !== 'Kintsugi') errs.push('title shows unread after our own message: ' + await p.evaluate(() => document.title));
  console.log(errs.length ? 'PROBLEMS:\n' + errs.join('\n') : 'no errors');
  await b.close();
})().catch(e => { console.error('FAILED', e.message); process.exit(1); });
