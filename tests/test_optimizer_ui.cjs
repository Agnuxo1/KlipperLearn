/* Browser-only workflow with all API calls intercepted. Never controls a printer. */
(async () => {
  const {chromium} = await import('playwright');
  const fs = await import('node:fs/promises');
  const path = await import('node:path');
  const assert = await import('node:assert/strict');
  const root = path.resolve(__dirname, '../src/klipperlearn/mobile_app');
  const browser = await chromium.launch({headless:true,
    ...(process.env.KL_TEST_BROWSER_CHANNEL ? {channel:process.env.KL_TEST_BROWSER_CHANNEL} : {})});
  try {
    const page = await browser.newPage(), writes = [], errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.addInitScript(() => sessionStorage.setItem('klipperlearn-token','test-optimizer-browser-token'));
    await page.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url());
      assert.equal(url.hostname, 'optimizer.test');
      if (url.pathname.startsWith('/mobile/api/optimizer/')) {
        assert.equal(request.headers()['x-klipperlearn-token'],'test-optimizer-browser-token');
        writes.push({path:url.pathname,body:request.postData()});
        if (url.pathname.endsWith('/review')) return route.fulfill({json:{result:{status:'profiles_available',synthetic:true,selected:{Quality:'detail',Standard:'baseline',Speed:'fast'}}}});
        if (url.pathname.endsWith('/advisor-request')) return route.fulfill({json:{result:{schema:'test-request',images_attached:false}}});
        if (url.pathname.endsWith('/check-proposal')) return route.fulfill({status:422,json:{detail:'Duplicate JSON key'}});
        if (url.pathname.endsWith('/profiles')) {
          const files = {};
          for (const mode of ['quality','standard','speed']) for (const kind of ['process','filament']) files[`${mode}_${kind}.json`] = {name:mode,type:kind};
          return route.fulfill({json:{result:{files,review:{synthetic:true}}}});
        }
        throw Error('Unexpected optimizer API');
      }
      assert.equal(request.method(),'GET');
      const name = path.basename(url.pathname);
      try { await route.fulfill({body:await fs.readFile(path.join(root,name)),contentType:({'.html':'text/html','.css':'text/css','.js':'application/javascript'})[path.extname(name)] || 'application/octet-stream'}); }
      catch (_) { await route.fulfill({status:404}); }
    });
    await page.goto('https://optimizer.test/mobile/optimizer.html');
    await page.locator('#reviewer').selectOption('Other AI');
    assert.equal(writes.length,0);
    await page.locator('#sessionFile').setInputFiles(path.resolve(__dirname,'../examples/synthetic-slicer-session.json'));
    await page.waitForFunction(() => !document.getElementById('profiles').disabled);
    assert.equal(await page.locator('#brand').inputValue(),'Example');
    assert.equal(await page.locator('#brand').getAttribute('readonly'),'');
    await page.locator('#request').click();
    await page.waitForFunction(() => document.querySelectorAll('#downloads a').length === 1);
    assert.equal(await page.locator('#profiles').isDisabled(),false);
    await page.locator('#profiles').click();
    await page.waitForFunction(() => document.querySelectorAll('#downloads a').length === 7);
    assert.match(await page.locator('#status').innerText(),/Nothing was installed or printed/);
    const before = writes.length;
    await page.locator('summary').click();
    await page.locator('#discover').click();
    await page.waitForFunction(() => document.getElementById('status').textContent.includes('consent'));
    assert.equal(writes.length,before);
    await page.locator('#proposalFile').setInputFiles({name:'proposal.json',mimeType:'application/json',buffer:Buffer.from('{"value":41,"value":42}')});
    await page.waitForFunction(() => !document.getElementById('proposal').disabled);
    await page.locator('#proposal').click();
    await page.waitForFunction(() => document.getElementById('status').textContent.includes('Duplicate'));
    assert.equal((writes.at(-1).body.match(/"value"/g)||[]).length,2);
    assert.deepEqual(errors,[]);
    assert.ok(writes.every(r=>r.path.startsWith('/mobile/api/optimizer/')));
    console.log('optimizer UI: PASS (file review, reviewer label, six presets, raw proposal validation, consent, no printer commands)');
  } finally { await browser.close(); }
})().catch(error => {console.error(error);process.exitCode=1;});
