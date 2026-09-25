/* Real browser, static files, simulated Marlin printer; no external network or hardware. */
const {chromium} = require('playwright');
const fs = require('node:fs/promises'), path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '../docs');
const TYPES = {'.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.svg': 'image/svg+xml', '.webmanifest': 'application/manifest+json'};

(async () => {
  const browser = await chromium.launch({headless: true, ...(process.env.KL_TEST_BROWSER_CHANNEL ? {channel: process.env.KL_TEST_BROWSER_CHANNEL} : {})});
  try {
    for (const width of [390, 1280]) {
      const context = await browser.newContext({viewport: {width, height: 900}, serviceWorkers: 'block', locale: 'es-ES'});
      const page = await context.newPage(), errors = [], external = [];
      page.on('pageerror', e => errors.push(e.message));
      page.on('dialog', d => d.accept());
      await page.route('**/*', async route => {
        const url = new URL(route.request().url());
        if (url.hostname !== 'launch.test') { external.push(url.hostname); return route.abort(); }
        const name = url.pathname.endsWith('/') ? url.pathname.slice(1) + 'index.html' : url.pathname.slice(1);
        const target = path.resolve(root, name);
        if (!target.startsWith(root + path.sep)) return route.abort();
        try { return route.fulfill({body: await fs.readFile(target), contentType: TYPES[path.extname(target)] || 'text/plain'}); }
        catch { return route.fulfill({status: 404}); }
      });
      await page.goto('https://launch.test/app/', {waitUntil: 'networkidle'});
      assert.equal(await page.locator('#estop').isVisible(), false, 'stop button hidden while disconnected');
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'no horizontal overflow');

      await page.locator('#btn-sim').click();
      await page.locator('#status.ok').waitFor({timeout: 10000});
      assert.match(await page.locator('#fw-info').innerText(), /Marlin 2\.1\.2\.1/);
      assert(await page.locator('#estop').isVisible());

      // Standard trial part, 1 mm tall, printed on the simulator.
      await page.locator('.tabs [data-tab=calibrate]').click();
      const item = page.locator('.cal-item').last();
      await item.locator('input').first().fill('1');
      await item.locator('button').click();
      await page.locator('#btn-start').click();
      await page.locator('#tab-learn.active').waitFor({timeout: 30000});

      // Rate with stringing and expect exactly one bounded parameter change first.
      await page.locator('input[name=defect_stringing]').fill('2');
      await page.locator('#rating-form button.primary').click();
      await page.locator('#rec-card:not([hidden])').waitFor();
      assert.match(await page.locator('.rec').first().innerText(), /Retracci/);
      assert.equal(await page.locator('#history tbody tr').count(), 1);
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'no horizontal overflow after a trial');
      assert.deepEqual(errors, []); assert.deepEqual(external, []);
      await context.close();
    }
    console.log('Phone app: PASS (mobile/desktop, simulator connect, generated trial, rating, one-change recommendation, no external requests).');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
