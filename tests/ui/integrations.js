const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const BASE = process.env.BASE_URL || 'http://127.0.0.1:8804';
(async () => {
  const b = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined, args: ['--no-sandbox'] });
  const errs = [];
  const p = await (await b.newContext({ viewport: { width: 1100, height: 900 } })).newPage();
  p.on('pageerror', e => errs.push('pageerror: ' + e.message));
  await p.goto(BASE + '/#token=tok123');
  await p.waitForSelector('#sidebar .item:has-text("alice")');
  await p.click('button[aria-label="Settings"]'); await p.click('.set-item:has-text("Integrations")');
  await p.waitForSelector('strong:has-text("GitHub")');
  for (const n of ['GitHub', 'Slack', 'Calendar', 'Gmail']) if (!(await p.locator('strong:has-text("' + n + '")').count())) errs.push('missing card ' + n);
  // a bad allow-list is explained; nothing is saved
  await p.fill('input[aria-label="GitHub token"]', 'github_pat_UI_SECRET_VALUE');
  await p.fill('textarea[aria-label="GitHub allow-list"]', 'not a repo');
  await p.click('.card:has-text("GitHub") .btn.primary:has-text("Save")');
  await p.waitForSelector('#toast:has-text("owner/name")', { timeout: 5000 }).catch(() => errs.push('no readable error for a bad repo list'));
  // a good one is saved, shows Connected, can be switched on for an agent, and the token is never on the page
  await p.fill('textarea[aria-label="GitHub allow-list"]', 'acme/*');
  await p.click('.card:has-text("GitHub") .btn.primary:has-text("Save")');
  await p.waitForSelector('.card:has-text("GitHub") >> text=Connected');
  if ((await p.content()).includes('github_pat_UI_SECRET_VALUE')) errs.push('TOKEN VISIBLE');
  await p.click('.card:has-text("GitHub") .chip:has-text("alice")');
  await p.waitForSelector('.card:has-text("GitHub") .chip.on:has-text("alice")');
  if (await p.locator('.card:has-text("GitHub") .chip.on:has-text("bob")').count()) errs.push('bob must stay off');
  // remove cleans up
  await p.click('.card:has-text("GitHub") .btn.danger:has-text("Remove")'); await p.click('.overlay:last-child .btn.primary');
  await p.waitForSelector('.card:has-text("GitHub") >> text=Not set up');
  console.log(errs.length ? 'PROBLEMS:\n' + errs.join('\n') : 'no errors');
  await b.close();
})().catch(e => { console.error('FAILED', e.message); process.exit(1); });
