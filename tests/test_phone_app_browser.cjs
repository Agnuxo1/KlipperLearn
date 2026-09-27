/* Real browser, static files, simulated Marlin printer; no external network or hardware. */
const {chromium} = require('playwright');
const fs = require('node:fs/promises'), path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '../docs');
const TYPES = {'.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.svg': 'image/svg+xml', '.webmanifest': 'application/manifest+json'};

(async () => {
  const browser = await chromium.launch({headless: true, args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'], ...(process.env.KL_TEST_BROWSER_CHANNEL ? {channel: process.env.KL_TEST_BROWSER_CHANNEL} : {})});
  try {
    for (const width of [390, 1280]) {
      const context = await browser.newContext({viewport: {width, height: 900}, serviceWorkers: 'block', locale: 'es-ES', acceptDownloads: true, permissions: ['camera', 'microphone']});
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
      assert.match(await page.locator('#measured-summary').innerText(), /Dataset/, 'recorder summary shown');

      // Export the training dataset and check the klipperlearn-dataset/v1 layout.
      const [dl] = await Promise.all([page.waitForEvent('download'), page.locator('#btn-export-dataset').click()]);
      const zip = new Uint8Array(await fs.readFile(await dl.path()));
      const {unzipStore} = await import(require('node:url').pathToFileURL(path.join(root, 'app/js/dataset.js')).href);
      const files = unzipStore(zip), names = Object.keys(files);
      const m = JSON.parse(new TextDecoder().decode(files['dataset/manifest.jsonl']).trim());
      assert.equal(m.schema, 'klipperlearn-dataset/v1');
      const dir = `dataset/trials/${m.trial_id}/`;
      for (const n of ['meta.json', 'labels.json', 'gcode_params.json', 'printer.csv', 'accel.csv', 'audio_features.csv', 'events.jsonl', 'photos/final.jpg'])
        assert.ok(names.includes(dir + n), 'missing ' + n + ' in ' + names.join(' '));
      const rows = name => new TextDecoder().decode(files[dir + name]).trim().split(String.fromCharCode(10));
      const printerRows = rows('printer.csv');
      assert.ok(printerRows.length >= 2, 'printer telemetry rows');
      const audioRows = rows('audio_features.csv');
      assert.ok(audioRows.length >= 2, 'audio feature rows from the (fake) microphone');
      assert.equal(JSON.parse(new TextDecoder().decode(files[dir + 'labels.json'])).labeled_by, 'human');
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'no horizontal overflow after a trial');
      assert.deepEqual(errors, []); assert.deepEqual(external, []);
      await context.close();
    }
    console.log('Phone app: PASS (mobile/desktop, simulator connect, generated trial with dataset recording, rating, one-change recommendation, dataset ZIP export, no external requests).');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
