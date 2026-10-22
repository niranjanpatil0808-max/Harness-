// A fuller user journey, run on a desktop and on a phone: first look, chat, an approval, replies and their buttons, a private chat,
// the task board, a room brief, search, slash commands, an attachment, going offline and back, inviting a teammate who joins on a
// phone and talks, every Settings page, help, and theme. After each stage it checks the screen for sideways scrolling, text that
// runs out of its box, thumb-sized buttons (phone), console errors and failed requests. SHOTS=/dir keeps a screenshot per stage.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const BASE = process.env.BASE_URL || 'http://127.0.0.1:8804';
const SHOTS = process.env.SHOTS || '';
const fs = require('fs'), os = require('os'), path = require('path');
const problems = [];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function audit(p, label, stage, phone) {
  const found = await p.evaluate((phone) => {
    const out = [];
    const vw = innerWidth;
    if (document.documentElement.scrollWidth > vw + 1) out.push('sideways scroll (' + document.documentElement.scrollWidth + ' > ' + vw + ')');
    const visible = (e) => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && e.offsetParent !== null; };
    const name = (e) => (e.getAttribute('aria-label') || e.id || e.textContent.trim().slice(0, 24) || e.tagName).replace(/\s+/g, ' ');
    const inSidebarHidden = (e) => { const sb = e.closest('#sidebar'); return sb && sb.getBoundingClientRect().right <= 1; };
    for (const e of document.querySelectorAll('button, [role=button], select, input:not([type=hidden]):not([type=checkbox]):not([type=file]), textarea, .item, .set-item')) {
      if (!visible(e) || inSidebarHidden(e)) continue;
      const r = e.getBoundingClientRect();
      const scroller = (() => { for (let a = e.parentElement; a && a !== document.body; a = a.parentElement) { if (['auto', 'scroll'].includes(getComputedStyle(a).overflowX) && a.scrollWidth > a.clientWidth) return true; } return false; })();
      if ((r.right > vw + 1 || r.left < -1) && !scroller) out.push('off screen: ' + name(e));
      if (phone && (r.height < 30 || r.width < 30) && !e.closest('.msg-actions, .me-actions')) out.push('small touch target (' + Math.round(r.width) + 'x' + Math.round(r.height) + '): ' + name(e));
    }
    for (const e of document.querySelectorAll('button, .btn, .pill, .chip, .task-chip, h3, h4, h5, .title, .item, label')) {
      if (!visible(e) || inSidebarHidden(e)) continue;
      const s = getComputedStyle(e);
      if (e.scrollWidth > e.clientWidth + 2 && s.overflow !== 'visible' && s.textOverflow !== 'ellipsis' && !['auto', 'scroll'].includes(s.overflowX)) out.push('text clipped in: ' + name(e));
    }
    const dialogs = document.querySelectorAll('.dialog');
    for (const d of dialogs) { const r = d.getBoundingClientRect(); if (r.bottom > innerHeight + 1 || r.top < -1) out.push('dialog taller than the screen: ' + name(d.querySelector('h3,h2') || d)); }
    return [...new Set(out)];
  }, phone);
  for (const f of found) problems.push(`[${label}] ${stage}: ${f}`);
  if (SHOTS) await p.screenshot({ path: path.join(SHOTS, `${label}-${stage}.png`) }).catch(() => {});
}

async function step(label, name, fn) {
  try { await fn(); } catch (e) { problems.push(`[${label}] ${name}: ${String(e.message).split('\n').slice(0, 3).join(' | ')}`); }
}

async function journey(b, label, ctxOptions) {
  const phone = label === 'phone';
  const ctx = await b.newContext(ctxOptions);
  const p = await ctx.newPage();
  const net = [];
  p.on('pageerror', (e) => problems.push(`[${label}] pageerror ${e.message}`));
  p.on('console', (m) => { if (m.type() === 'error' && !/Failed to load resource.*(401|404)|ERR_INTERNET_DISCONNECTED/.test(m.text())) problems.push(`[${label}] console ${m.text().slice(0, 140)}`); });
  p.on('response', (r) => { if (r.status() >= 500) problems.push(`[${label}] server ${r.status()} ${r.url().replace(BASE, '')}`); });
  const openSidebar = async () => { if (phone && !(await p.locator('#sidebar .item:has-text("team")').isVisible())) { await p.click('#topbar button[aria-label="Open sidebar"]'); await sleep(400); } };
  const closeDialog = async () => { await p.keyboard.press('Escape'); await sleep(200); if (await p.locator('.dialog').count()) { await p.keyboard.press('Escape'); await sleep(200); } };

  await p.goto(BASE + '/#token=tok123'); await p.waitForSelector('.sys'); await sleep(700);
  await audit(p, label, '01-first-look', phone);

  await step(label, 'chat message', async () => {
    await p.fill('#msg', 'hello team'); await p.keyboard.press('Enter');
    await p.waitForSelector('.row.me:has-text("hello team")');
    await p.waitForSelector('.row:not(.me):has(.who-line:has-text("alice"))', { timeout: 15000 });
    await audit(p, label, '02-chat', phone);
  });

  await step(label, 'approval flow', async () => {
    await p.fill('#msg', '@alice work it out with python'); await p.keyboard.press('Enter');
    await p.waitForSelector('.perm', { timeout: 15000 });
    await audit(p, label, '03-approval', phone);
    await p.click('.perm .btn.primary:has-text("Allow once")');
    await p.waitForSelector('.perm', { state: 'detached', timeout: 20000 });
    await p.waitForFunction(() => !document.querySelector('.working'), null, { timeout: 20000 });
    await audit(p, label, '04-after-approval', phone);
  });

  await step(label, 'reply buttons', async () => {
    const reply = p.locator('.row:not(.me):has(.who-line:has-text("alice"))').last();
    if (!phone) await reply.hover();  // on a phone the buttons are always shown
    for (const a of ['Copy', 'Ask again', 'Share', 'Helpful', 'Not helpful']) {
      const n = await reply.locator(`button[aria-label*="${a}"], button[title*="${a}"]`).count();
      if (!n) problems.push(`[${label}] reply is missing the "${a}" button`);
    }
    await reply.locator('button[aria-label*="Helpful"], button[title*="Helpful"]').first().click().catch(() => {});
    const mine = p.locator('.row.me').last();
    if (phone) { await mine.locator('.bubble, .text, .msg-text').first().tap().catch(() => {}); }
    await audit(p, label, '05-reply-buttons', phone);
  });

  await step(label, 'private chat', async () => {
    await openSidebar();
    await p.click('#sidebar .item:has-text("bob")'); await sleep(500);
    await p.fill('#msg', 'hi bob, just us'); await p.keyboard.press('Enter');
    await p.waitForSelector('.row:not(.me):has(.who-line:has-text("bob"))', { timeout: 15000 });
    await audit(p, label, '06-private-chat', phone);
  });

  await step(label, 'task board', async () => {
    await p.evaluate(() => tasksDialog());
    await p.waitForSelector('.tasks-dialog select[aria-label="Room"]');
    await audit(p, label, '07-tasks-empty', phone);
    await p.selectOption('select[aria-label="Room"]', 'team'); await p.selectOption('select[aria-label="Agent"]', 'alice');
    await p.fill('textarea[aria-label="Task"]', label + ' write the launch note');
    await p.click('.tasks-dialog .btn.primary:has-text("Give task")');
    await p.waitForSelector(`.task-card:has-text("${label} write the launch note") .task-chip.st-done`, { timeout: 25000 });
    await audit(p, label, '08-tasks-done', phone);
    await closeDialog();
  });

  await step(label, 'room brief', async () => {
    await openSidebar(); await p.click('#sidebar .item:has-text("team")'); await sleep(400);
    if (phone) await closeSidebarIfOpen(p);
    await p.click('button:has-text("Add a room brief"), button:has-text("Edit")');
    await p.waitForSelector('.dialog textarea');
    await p.fill('.dialog textarea', 'We are launching the app on Friday. Keep answers short.');
    await audit(p, label, '09-brief-dialog', phone);
    await p.click('.dialog .btn.primary');
    await p.waitForSelector('text=launching the app on Friday');
    await audit(p, label, '10-brief-shown', phone);
  });

  await step(label, 'search and slash', async () => {
    if (phone) { await openSidebar(); await p.click('#sidebar [aria-label*="Search"], #sidebar .item:has-text("Search")'); } else await p.keyboard.press('Control+k');
    await p.waitForSelector('.switcher .sw-input'); await p.keyboard.type('python');
    await sleep(900);
    await audit(p, label, '11-search', phone);
    await p.keyboard.press('Escape'); await sleep(200);
    await p.fill('#msg', '/'); await sleep(300);
    await audit(p, label, '12-slash', phone);
    await p.fill('#msg', '');
  });

  await step(label, 'attachment', async () => {
    const f = path.join(os.tmpdir(), 'notes.txt'); fs.writeFileSync(f, 'meeting notes\n');
    await p.setInputFiles('input[type=file]', f);
    await sleep(1200);
    await audit(p, label, '13-attachment', phone);
  });

  await step(label, 'offline outbox', async () => {
    await ctx.setOffline(true);
    const offlineText = 'sent while offline ' + Date.now();
    await p.fill('#msg', offlineText); await p.keyboard.press('Enter');
    await p.waitForSelector('#outbox .queued, .queued', { timeout: 8000 });
    await audit(p, label, '14-offline', phone);
    await ctx.setOffline(false);
    await p.waitForSelector(`.row.me:has-text("${offlineText}")`, { timeout: 30000 });
    await sleep(2500);
    if (await p.locator(`.row.me:has-text("${offlineText}")`).count() !== 1) problems.push(`[${label}] the offline message was sent more than once`);
  });

  await step(label, 'settings pages', async () => {
    for (const tab of ['general', 'models', 'usage', 'team', 'internet', 'integrations', 'plugins', 'search', 'improve', 'approvals', 'backup']) {
      await p.evaluate((t) => settingsDialog(t), tab); await sleep(450);
      await audit(p, label, '15-settings-' + tab, phone);
      await closeDialog();
    }
  });

  await step(label, 'help, checklist, new chat, theme', async () => {
    await p.evaluate(() => helpDialog()); await sleep(300); await audit(p, label, '16-help', phone); await closeDialog();
    await p.evaluate(() => newChatDialog()); await sleep(300); await audit(p, label, '17-new-chat', phone); await closeDialog();
    await p.evaluate(() => onboardingDialog && onboardingDialog()); await sleep(300); await audit(p, label, '18-getstarted', phone); await closeDialog();
    await p.evaluate(() => document.querySelector('button[aria-label="Change theme"]')?.click()); await sleep(300);
    await audit(p, label, '19-theme', phone);
    await p.evaluate(() => document.querySelector('button[aria-label="Change theme"]')?.click());
  });

  // invite a teammate, who joins on a phone and talks; the owner sees it
  await step(label, 'invite a teammate', async () => {
    await p.evaluate(() => settingsDialog('team')); await p.waitForSelector('text=Invite someone');
    await p.click('text=Create invite link'); await p.waitForSelector('text=Invite link ready');
    const link = await p.inputValue('input[aria-label="Invite link"]');
    await audit(p, label, '20-invite-link', phone);
    await closeDialog(); await closeDialog();
    const who = 'sam' + label + (Date.now() % 100000);
    const mctx = await b.newContext({ viewport: { width: 390, height: 780 }, isMobile: true, hasTouch: true });
    const m = await mctx.newPage();
    m.on('pageerror', (e) => problems.push(`[${label}/teammate] pageerror ${e.message}`));
    await m.goto(link); await m.waitForSelector('input[aria-label="Your name"]');
    await audit(m, label + '-teammate', '21-join', true);
    await m.fill('input[aria-label="Your name"]', who); await m.click('.btn.primary:has-text("Join")');
    await m.waitForSelector('#topbar .title:has-text("# team")'); await sleep(500);
    await audit(m, label + '-teammate', '22-joined', true);
    await m.fill('#msg', '@alice hello from ' + who); await m.keyboard.press('Enter');
    await m.waitForSelector('.row.me:has-text("hello from")');
    await m.waitForSelector('.row:not(.me):has(.who-line:has-text("alice"))', { timeout: 15000 });
    await audit(m, label + '-teammate', '23-teammate-chat', true);
    await m.evaluate(() => helpDialog()); await sleep(300); await audit(m, label + '-teammate', '24-teammate-help', true); await m.keyboard.press('Escape');
    await m.evaluate(() => settingsDialog('general')); await sleep(500); await audit(m, label + '-teammate', '25-teammate-settings', true);
    await openSidebar(); await p.click('#sidebar .item:has-text("team")').catch(() => {}); await sleep(600);
    if (!(await p.locator('.row:not(.me) .who-line:has-text("' + who + '")').count())) problems.push(`[${label}] the owner does not see the teammate's message`);
    await mctx.close();
  });
  await ctx.close();
}

async function closeSidebarIfOpen(p) { if (await p.locator('#sidebar .item:has-text("team")').isVisible().catch(() => false)) { await p.keyboard.press('Escape'); await sleep(300); } }

(async () => {
  const b = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined, args: ['--no-sandbox'] });
  const only = process.env.ONLY;
  if (!only || only === 'pc') await journey(b, 'pc', { viewport: { width: 1280, height: 800 } });
  if (!only || only === 'phone') await journey(b, 'phone', { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  console.log(problems.length ? 'PROBLEMS:\n' + problems.join('\n') : 'no errors');
  await b.close();
})().catch((e) => { console.error('FAILED', e.message); process.exit(1); });
