const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const BASE = process.env.BASE_URL || 'http://127.0.0.1:8804';
const OWNER = 'tok123';
(async () => {
  const b = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined, args: ['--no-sandbox'] });
  const errs = [];
  const owner = await (await b.newContext({ viewport: { width: 1100, height: 800 } })).newPage();
  owner.on('pageerror', e => errs.push('owner pageerror: ' + e.message));
  await owner.goto(BASE + '/#token=' + OWNER);
  await owner.waitForSelector('#sidebar .item:has-text("alice")');
  // a second room the invited person must NOT see
  await owner.evaluate(async () => { await fetch('/api/rooms', { method: 'POST', headers: { 'X-Token': 'tok123', 'Content-Type': 'application/json' }, body: JSON.stringify({ name: 'board-room', members: ['alice'] }) }); });
  // the owner creates an invite link in Settings > Team
  await owner.click('button[aria-label="Settings"]'); await owner.click('.set-item:has-text("Team")');
  await owner.waitForSelector('text=Invite someone');
  await owner.click('text=Create invite link');
  await owner.waitForSelector('text=Invite link ready');
  const link = await owner.inputValue('input[aria-label="Invite link"]');
  if (!link.includes('#invite=ki_')) errs.push('no invite link: ' + link);
  // a second browser opens it, picks a name and is signed in as a member
  const member = await (await b.newContext({ viewport: { width: 390, height: 780 }, isMobile: true, hasTouch: true })).newPage();
  member.on('pageerror', e => errs.push('member pageerror: ' + e.message));
  await member.goto(link);
  await member.waitForSelector('input[aria-label="Your name"]');
  await member.fill('input[aria-label="Your name"]', 'you');
  await member.click('.btn.primary:has-text("Join")');
  await member.waitForSelector('text=taken or reserved');  // the owner's name is reserved
  await member.fill('input[aria-label="Your name"]', 'sam');
  await member.click('.btn.primary:has-text("Join")');
  await member.waitForSelector('#topbar .title:has-text("# team")');
  // the member sees their room, not the private one, and none of the admin controls
  await member.click('#topbar button >> nth=0');
  await member.waitForSelector('#sidebar .side-foot:has-text("sam")');
  const side = await member.innerText('#sidebar');
  if (side.includes('board-room')) errs.push('member can see a room they are not in');
  if (side.includes('New agent')) errs.push('member sees New agent');
  if (!side.includes('member')) errs.push('role not shown');
  await member.click('button[aria-label="Settings"]');
  const tabs = await member.locator('.dialog .set-item').allInnerTexts();
  if (tabs.join(',') !== 'General') errs.push('member sees settings tabs: ' + tabs.join(','));
  await member.click('.dialog .btn.primary:has-text("Done")');
  await member.waitForTimeout(500);
  if (!(await member.locator('#sidebar .item:has-text("team")').isVisible())) { await member.click('#topbar button[aria-label="Open sidebar"]'); await member.waitForTimeout(400); }
  // the member talks; the owner sees it under the member's name
  await member.click('#sidebar .item:has-text("team")');
  await member.fill('#msg', '@alice hello from sam'); await member.keyboard.press('Enter');
  await owner.keyboard.press('Escape'); await owner.keyboard.press('Escape');
  await owner.click('#sidebar .item:has-text("team")');
  await owner.waitForSelector('.row:not(.me) .who-line:has-text("sam")', { timeout: 15000 }).catch(() => errs.push('owner does not see the message under sam'));
  // an invite link cannot be used twice
  const again = await (await b.newContext()).newPage();
  await again.goto(link);
  await again.waitForSelector('input[aria-label="Your name"]');
  await again.fill('input[aria-label="Your name"]', 'kim'); await again.click('.btn.primary:has-text("Join")');
  await again.waitForSelector('text=not valid any more');
  // the owner can remove sam, who is then locked out
  await owner.click('button[aria-label="Settings"]'); await owner.click('.set-item:has-text("Team")');
  await owner.waitForSelector('strong:has-text("sam")');
  // reset sam's sign-in: the old token stops, the new link works
  await owner.click('.card:has-text("sam") .btn:has-text("Reset sign-in")'); await owner.click('.overlay:last-child .btn.primary');
  const fresh = await owner.inputValue('input[aria-label="Sign-in link"]');
  await owner.click('.overlay:last-child .btn.primary:has-text("Done")');
  await member.reload();
  await member.waitForSelector('input[aria-label="Access token"]', { timeout: 8000 }).catch(() => errs.push('old sign-in still works after reset'));
  const sam2 = await (await b.newContext()).newPage();
  await sam2.goto(fresh); await sam2.waitForSelector('#sidebar .brand', { state: 'attached' });
  await sam2.waitForSelector('#sidebar .item:has-text("team")', { state: 'attached', timeout: 8000 }).catch(() => errs.push('new sign-in link does not load the workspace'));
  if (await sam2.locator('input[aria-label="Access token"]').count()) errs.push('new sign-in link does not work');
  await owner.click('.card:has-text("sam") .btn.danger:has-text("Remove")'); await owner.click('.overlay:last-child .btn.primary');
  await owner.waitForSelector('text=sam removed', { timeout: 6000 }).catch(() => {});
  await sam2.reload();
  await sam2.waitForSelector('input[aria-label="Access token"]', { timeout: 8000 }).catch(() => errs.push('a removed person is still signed in'));
  console.log(errs.length ? 'PROBLEMS:\n' + errs.join('\n') : 'no errors');
  await b.close();
})().catch(e => { console.error('FAILED', e.message); process.exit(1); });
