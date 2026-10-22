// Team task board (give a task, follow it to Done, jump to the result) and sharing a message into another room.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const SHOTS = process.env.SHOTS || '/tmp';
const BASE = process.env.BASE_URL || 'http://127.0.0.1:8804';
(async () => {
  const b = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined, args: ['--no-sandbox'] });
  const errs = [];
  for (const [label, viewport] of [['desktop', { width: 1100, height: 800 }], ['phone', { width: 390, height: 844 }]]) {
    const p = await (await b.newContext({ viewport, isMobile: label === 'phone', hasTouch: label === 'phone' })).newPage();
    p.on('pageerror', e => errs.push(label + ' pageerror ' + e.message));
    p.on('console', m => { if (m.type() === 'error') errs.push(label + ' console ' + m.text()); });
    await p.goto(BASE + '/#token=tok123'); await p.waitForSelector('#msg', { state: 'attached' }); await p.waitForTimeout(800);
    // 1. give a task from the board
    await p.evaluate(() => tasksDialog());
    await p.waitForSelector('.tasks-dialog select[aria-label="Room"]');
    await p.selectOption('select[aria-label="Room"]', 'team');
    await p.selectOption('select[aria-label="Agent"]', 'alice');
    const title = label + ' draft the launch note';
    await p.fill('textarea[aria-label="Task"]', title);
    await p.click('.tasks-dialog .btn.primary:has-text("Give task")');
    await p.waitForSelector(`.task-card:has-text("${title}") .task-chip.st-done`, { timeout: 20000 }).catch(() => errs.push(label + ': task never reached Done'));
    await p.screenshot({ path: SHOTS + `/t1_tasks_${label}.png` });
    // 2. the sidebar shows no open tasks now; jump to the result
    await p.click(`.task-card:has-text("${title}") >> text=See the result`);
    await p.waitForFunction(() => !document.querySelector('.tasks-dialog'));
    await p.waitForSelector('.row[data-mid]', { timeout: 8000 }).catch(() => {});
    await p.waitForSelector('.row:has-text("Task #")', { timeout: 8000 }).catch(() => {});
    const mid = await p.evaluate(() => [...document.querySelectorAll('.row[data-mid]')].pop()?.dataset.mid);
    if (!mid) errs.push(label + ': no message rows carry their id');
    // 3. a task message is visible in the room for everyone
    if (!(await p.locator(`.row:has-text("Task #")`).count())) errs.push(label + ': the task message is not in the room');
    if (label === 'desktop') {
      // 4. share alice's reply into another room
      await p.evaluate(() => fetch('/api/rooms', { method: 'POST', headers: { 'X-Token': 'tok123', 'Content-Type': 'application/json' }, body: JSON.stringify({ name: 'launch', members: ['alice'] }) }));
      await p.evaluate(() => poll(true)); await p.waitForTimeout(500);
      const reply = p.locator('.row:not(.me):has(.who-line:has-text("alice"))').last();
      await reply.hover();
      await reply.locator('button[aria-label="Share this message to a room"]').click();
      await p.selectOption('select[aria-label="Share to room"]', 'launch');
      await p.click('.dialog .btn.primary:has-text("Share")');
      await p.waitForSelector('#toast.on:has-text("Shared to #launch")');
      await p.click('#sidebar .item:has-text("launch")');
      await p.waitForSelector('.row:has-text("Shared by you from #team")', { timeout: 8000 }).catch(() => errs.push('shared message not in the target room'));
      await p.screenshot({ path: SHOTS + '/t2_shared.png' });
      // 5. the switcher offers Team tasks
      await p.keyboard.press('Control+k'); await p.keyboard.type('tasks');
      await p.waitForSelector('.sw-item:has-text("Team tasks")'); await p.keyboard.press('Escape');
    }
    await p.context().close();
  }
  console.log(errs.length ? 'PROBLEMS:\n' + errs.join('\n') : 'no errors');
  await b.close();
})().catch(e => { console.error('FAILED', e.message); process.exit(1); });
