/* Real browser lifecycle, simulated camera; all network calls intercepted. */
const {chromium} = require('playwright');
const fs = require('node:fs/promises'), path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '../src/klipperlearn/mobile_app');
const token = 'test_photo_queue_token_1234567890';
const job = {id: '00000000-0000-4000-8000-000000000025', trial_id: 'a'.repeat(32), status: 'running'};
const status = {result: {status: {webhooks: {state: 'ready'},
  print_stats: {state: 'complete', filename: 'test.gcode'},
  extruder: {temperature: 25, target: 0}, heater_bed: {temperature: 25, target: 0},
  virtual_sdcard: {progress: 1}}}};
(async () => {
  const browser = await chromium.launch({headless: true,
    ...(process.env.KL_TEST_BROWSER_CHANNEL ? {channel: process.env.KL_TEST_BROWSER_CHANNEL} : {})});
  try {
    const context = await browser.newContext(), page = await context.newPage();
    let frames = 0, claims = 0, completed = false;
    const errors = [], writes = [], uploads = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.addInitScript(() => {
      Object.defineProperty(navigator, 'mediaDevices', {value: {getUserMedia: constraints => {
        // A pending microphone prompt must not suppress camera-only work.
        if (!constraints.video) return new Promise(() => {});
        const canvas = document.createElement('canvas');
        canvas.width = 640; canvas.height = 360;
        let torch = false;
        const draw = () => {const ctx = canvas.getContext('2d'); ctx.fillStyle = torch ? '#eee' : '#123'; ctx.fillRect(0, 0, 640, 360);};
        draw(); setInterval(draw, 100);
        const stream = canvas.captureStream(5), track = stream.getVideoTracks()[0];
        track.getCapabilities = () => ({torch: true});
        track.getSettings = () => ({torch});
        track.applyConstraints = async constraints => {torch = Boolean(constraints.advanced?.[0]?.torch ?? constraints.torch); draw();};
        return Promise.resolve(stream);
      }}});
    });
    await page.route('**/*', async route => {
      const req = route.request(), url = new URL(req.url());
      if (url.hostname !== 'console.test') return route.abort();
      if (url.pathname.startsWith('/mobile/api/')) {
        if (url.pathname.endsWith('/connect')) return route.fulfill({json: {result: {token}}});
        if (req.headers()['x-klipperlearn-token'] !== token) return route.fulfill({status: 401});
        if (url.pathname.endsWith('/live/frame')) {frames++; return route.fulfill({json: {received: true}});}
        if (url.pathname.endsWith('/photos')) {
          const body = req.postDataBuffer();
          assert(body.length > 100 && body[0] === 255 && body[1] === 216);
          uploads.push({name: req.headers()['x-klipperlearn-filename'], body});
          return route.fulfill({json: {ok: true}});
        }
        if (url.pathname.endsWith('/complete')) {
          assert.deepEqual(req.postDataJSON(), {});
          completed = true;
          return route.fulfill({json: {result: {...job, status: 'complete', error: null}}});
        }
        if (req.method() !== 'GET') writes.push(url.pathname);
        if (url.pathname.endsWith('/printer/status')) return route.fulfill({json: status});
        if (url.pathname.endsWith('/printer/capabilities')) return route.fulfill({json: {result: {connected: true, features: {}, limits: {}}}});
        if (url.pathname.endsWith('/photo-pairs/next')) {
          claims++;
          return route.fulfill({json: {result: claims === 1 ? job : null}});
        }
        return route.fulfill({json: {result: null}});
      }
      const name = path.basename(url.pathname);
      try {return route.fulfill({body: await fs.readFile(path.join(root, name)),
        contentType: ({'.html': 'text/html', '.css': 'text/css', '.js': 'application/javascript', '.svg': 'image/svg+xml'})[path.extname(name)] || 'text/plain'});
      } catch {return route.fulfill({status: 404});}
    });
    await page.goto('https://console.test/mobile/console.html');
    await page.locator('#enterWelcome').click();
    await page.waitForFunction(() => document.getElementById('cameraStatus').textContent.includes('Streaming'), {}, {timeout: 8000});
    // Before the microphone timeout, while no active telemetry trial exists.
    await assert.doesNotReject(async () => {
      const until = Date.now() + 7000;
      while (!claims && Date.now() < until) await new Promise(resolve => setTimeout(resolve, 100));
      const diagnostic = await page.evaluate(() => Object.fromEntries(
        ['photoPairStatus', 'sensorStatus', 'connection', 'cameraStatus'].map(id => [id, document.getElementById(id)?.textContent])));
      assert(claims > 0, `Live frames=${frames}, queue not polled: ${JSON.stringify({diagnostic, errors})}`);
    });
    assert(frames > 0);
    const until = Date.now() + 10000;
    while (!completed && Date.now() < until) await new Promise(resolve => setTimeout(resolve, 100));
    assert(completed, 'Pair must upload both images and acknowledge completion');
    assert.deepEqual(uploads.map(item => item.name), ['torch-off', 'torch-on'].map(mode => `${job.id}-${mode}.jpg`));
    assert(!uploads[0].body.equals(uploads[1].body), 'Controlled illumination must produce two different images');
    await page.waitForFunction(() => document.getElementById('cameraStatus').textContent.includes('Streaming'), {}, {timeout: 5000});
    assert.deepEqual(errors, []);
    assert.deepEqual(writes, []);
    await context.close();
    console.log('photo queue browser: PASS (native fetch, two JPEG uploads, illumination, completion, live resume, pending microphone, no hardware traffic)');
  } finally {await browser.close();}
})().catch(error => {console.error(error); process.exitCode = 1;});
