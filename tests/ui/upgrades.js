// Settings page navigation, usage dashboard, quick switcher (Ctrl+K), starter teams, setup wizard screens.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const SHOTS = process.env.SHOTS || '/tmp';
const BASE = process.env.BASE_URL || 'http://127.0.0.1:8804';
(async () => {
  const b = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined, args: ['--no-sandbox'] });
  const errs = [];
  const p = await (await b.newContext({ viewport: { width: 1100, height: 800 } })).newPage();
  p.on('pageerror', e => errs.push('pageerror ' + e.message));
  p.on('console', m => { if (m.type() === 'error') errs.push('console ' + m.text()); });
  await p.goto(BASE + '/#token=tok123'); await p.waitForSelector('.sys');
  // 1. settings is a page with grouped sections; the owner sees every section including Usage
  await p.click('button[aria-label="Settings"]');
  await p.waitForSelector('.set-nav .set-item.on');
  const items = await p.locator('.set-nav .set-item').allInnerTexts();
  for (const want of ['General', 'Models', 'Usage', 'Team', 'Internet', 'Plugins', 'Backup']) if (!items.includes(want)) errs.push('settings missing ' + want + ': ' + items.join(','));
  if (!(await p.locator('.set-h:has-text("Connections")').count())) errs.push('no group headings');
  // 2. usage dashboard shows numbers and lets the owner set a price
  await p.click('.set-item:has-text("Usage")');
  await p.waitForSelector('.stats .stat');
  if ((await p.locator('#settings-body .set-title').count()) !== 1) errs.push('usage heading missing or doubled');
  await p.fill('input[aria-label="Model"]', 'mock-model');
  await p.fill('input[aria-label="Price per million input tokens"]', '1');
  await p.fill('input[aria-label="Price per million output tokens"]', '2');
  await p.click('text=Save price');
  await p.waitForSelector('text=mock-model ($1 in / $2 out)');
  if ((await p.locator('#settings-body .set-title').count()) !== 1) errs.push('heading doubled after refresh');
  await p.screenshot({ path: SHOTS + '/u1_usage.png' });
  // 3. a panel that refreshes itself keeps the heading (models)
  await p.click('.set-item:has-text("Models")');
  await p.waitForSelector('#settings-body .set-title:has-text("Models")');
  await p.click('.dialog .btn.primary:has-text("Done")');
  // 4. quick switcher: Ctrl+K, local results, message search, Enter opens
  await p.keyboard.press('Control+k');
  await p.waitForSelector('.switcher .sw-input');
  if (!(await p.evaluate(() => document.activeElement && document.activeElement.classList.contains('sw-input')))) errs.push('switcher input not focused');
  await p.keyboard.type('backup');
  await p.waitForSelector('.sw-item:has-text("Backup")');
  await p.keyboard.press('Enter');
  await p.waitForSelector('.set-title:has-text("Backup")');
  await p.keyboard.press('Escape');
  await p.keyboard.press('Control+k'); await p.waitForSelector('.switcher .sw-input');
  await p.keyboard.type('welcome');  // the system welcome message in the starter room
  await p.waitForTimeout(800);
  await p.screenshot({ path: SHOTS + '/u2_switcher.png' });
  await p.keyboard.press('Escape');
  if (await p.locator('.switcher').count()) errs.push('switcher did not close on Escape');
  // 4b. save the chat as Markdown from the switcher
  await p.keyboard.press('Control+k'); await p.waitForSelector('.switcher .sw-input');
  await p.keyboard.type('export');
  await p.waitForSelector('.sw-item:has-text("Save this chat")');
  const [dl] = await Promise.all([p.waitForEvent('download'), p.keyboard.press('Enter')]);
  const fs = require('fs'); const md = fs.readFileSync(await dl.path(), 'utf8');
  if (!md.startsWith('# #team')) errs.push('export title: ' + md.slice(0, 40));
  if (!/\*\*system\*\*/.test(md)) errs.push('export has no messages');
  // 5. starter teams from New chat
  await p.evaluate(() => newChatDialog());
  await p.click('text=Start from a team');
  await p.waitForSelector('.pcard');
  await p.locator('.pcard').first().click();
  await p.waitForSelector('#toast.on');
  await p.waitForFunction(() => !document.querySelector('#dialog-root .dialog'));
  // 6. setup wizard: provider cards, then the key step with Back
  await p.evaluate(() => setupWizard());
  await p.waitForSelector('.wizard .pcard');
  if ((await p.locator('.wizard .pcard').count()) < 3) errs.push('few provider cards');
  await p.locator('.wizard .pcard').first().click();
  await p.waitForSelector('.wizard input[aria-label="API key"]');
  await p.screenshot({ path: SHOTS + '/u3_wizard.png' });
  await p.click('.wizard button:has-text("Back")');
  await p.click('.wizard button:has-text("Skip for now")');
  await p.waitForFunction(() => !document.querySelector('#dialog-root .dialog'));
  if (await p.evaluate(() => document.querySelector('#app').inert)) errs.push('app still inert after dialogs closed');
  console.log(errs.length ? 'PROBLEMS:\n' + errs.join('\n') : 'no errors');
  await b.close();
})().catch(e => { console.error('FAILED', e.message); process.exit(1); });
