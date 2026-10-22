// Get-started checklist, deleting your own message, repeating tasks, the retry button on a failed answer.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const BASE = process.env.BASE_URL || 'http://127.0.0.1:8804';
(async () => {
  const b = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined, args: ['--no-sandbox'] });
  const errs = [];
  const p = await (await b.newContext({ viewport: { width: 1100, height: 800 } })).newPage();
  p.on('pageerror', e => errs.push('pageerror ' + e.message));
  p.on('console', m => { if (m.type() === 'error') errs.push('console ' + m.text()); });
  await p.goto(BASE + '/#token=tok123'); await p.waitForSelector('#msg', { state: 'attached' }); await p.waitForTimeout(900);
  // 1. the checklist shows what is done and what is not, and its buttons work
  await p.waitForSelector('.start-btn');
  const before = await p.locator('.start-btn .badge').innerText();
  await p.click('.start-btn');
  await p.waitForSelector('.dialog:has-text("Get started") .check');
  if ((await p.locator('.check.done').count()) < 1) errs.push('connect-your-AI should be done already');
  await p.click('.dialog .check:has-text("Give your team a task") .btn');
  await p.waitForSelector('.tasks-dialog');
  // 2. a repeating task: it is given now and also appears as an automation
  await p.selectOption('select[aria-label="Repeat"]', 'weekdays');
  await p.fill('textarea[aria-label="Task"]', 'polish weekly status note');
  await p.click('.tasks-dialog .btn.primary:has-text("Give task")');
  await p.waitForSelector('.task-card:has-text("polish weekly status note")', { timeout: 15000 });
  await p.keyboard.press('Escape');
  const jobs = await p.evaluate(async () => (await api('/api/automations')).jobs || (await api('/api/state')).jobs);
  if (!JSON.stringify(jobs).includes('polish weekly status note')) errs.push('the repeating task did not create a schedule');
  // 3. delete my own message (tap the bubble, then Delete)
  await p.fill('#msg', 'delete me please'); await p.keyboard.press('Enter');
  await p.waitForSelector('.row.me .bubble:has-text("delete me please")');
  await p.click('.row.me .bubble:has-text("delete me please")');
  await p.click('.row.me.open .me-actions button:has-text("Delete")');
  await p.click('.overlay:last-child .btn.primary:has-text("Delete")');
  await p.waitForFunction(() => ![...document.querySelectorAll('.row.me .bubble')].some(b => b.textContent.includes('delete me please')), null, { timeout: 8000 }).catch(() => errs.push('the message was not removed'));
  // 4. the checklist moved on (messaged + tasked + the AI)
  await p.waitForTimeout(1500);
  const after = await p.locator('.start-btn .badge').innerText().catch(() => 'gone');
  if (after === before) errs.push('checklist progress did not change: ' + before + ' -> ' + after);
  // 5. a failed answer offers Try again
  const retry = await p.evaluate(() => { S.lastSent = {[S.room]: 'x'}; const n = bodyOf({id: 9999, sender: 'system', text: 'alice could not answer: the AI provider did not accept your API key.', ts: 1, room: S.room}); return !!n.querySelector('.retry'); });
  if (!retry) errs.push('no Try again button on a failed answer notice');
  // 6. the live preview shows what an agent is writing right now (and nothing when there is nothing)
  const live = await p.evaluate(() => { S.state.busy = ['alice']; S.state.drafts = { alice: 'Here is the start of my answer' }; S.sig.inline = null; renderInline(); return document.querySelector('#inline .draft')?.textContent || ''; });
  if (!live.includes('Here is the start of my answer')) errs.push('no live preview: ' + live);
  // 7. the owner can switch it off in Settings > Models
  await p.evaluate(() => settingsDialog('models')); await p.waitForSelector('input[aria-label="Show answers as they are written"]');
  await p.uncheck('input[aria-label="Show answers as they are written"]'); await p.waitForSelector('#toast.on:has-text("when finished")');
  console.log(errs.length ? 'PROBLEMS:\n' + errs.join('\n') : 'no errors');
  await b.close();
})().catch(e => { console.error('FAILED', e.message); process.exit(1); });
