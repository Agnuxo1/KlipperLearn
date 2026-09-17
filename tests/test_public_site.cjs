/* Real browser, static fixtures; no external network or hardware. */
const {chromium} = require('playwright');
const fs = require('node:fs/promises'), path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '../docs');
(async () => {
  const browser = await chromium.launch({headless:true, ...(process.env.KL_TEST_BROWSER_CHANNEL ? {channel:process.env.KL_TEST_BROWSER_CHANNEL} : {})});
  try {
    for (const width of [1280, 390]) {
      const page = await browser.newPage({viewport:{width,height:900}}), errors=[], external=[];
      page.on('pageerror', e=>errors.push(e.message));
      await page.route('**/*', async route=>{
        const url = new URL(route.request().url());
        if(url.hostname !== 'launch.test'){external.push(url.hostname);return route.abort();}
        const name = url.pathname === '/' ? 'index.html' : url.pathname.slice(1);
        const target = path.resolve(root,name);
        if(!target.startsWith(root+path.sep))return route.abort();
        try {return route.fulfill({body:await fs.readFile(target),contentType:({'.html':'text/html','.css':'text/css','.webp':'image/webp','.svg':'image/svg+xml'})[path.extname(target)]||'text/plain'});}
        catch {return route.fulfill({status:404});}
      });
      await page.goto('https://launch.test/',{waitUntil:'networkidle'});
      assert.equal(await page.locator('h1').count(),1);
      assert.equal(await page.locator('.integration-list a').count(),10);
      assert(await page.locator('figure img').evaluate(i=>i.complete&&i.naturalWidth>0));
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
      assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
      await page.keyboard.press('Tab');
      assert.equal(await page.locator(':focus').textContent(),'Skip to content');
      if(process.env.KL_SITE_SCREENSHOT_DIR){
        const destination=path.join(process.env.KL_SITE_SCREENSHOT_DIR,`site-${width}.png`);
        await page.locator("h1").click();
        await page.screenshot({path:destination,fullPage:true});
      }
      await page.goto("https://launch.test/demo/index.html",{waitUntil:"networkidle"});
      await page.locator("#demo").click();
      assert.match(await page.locator("#session-summary").innerText(), /SYNTHETIC EXAMPLE/);
      await page.locator("#analyze").click();
      assert((await page.locator("#output").innerText()).length > 50);
      assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
      await page.close();
    }
    console.log('Public site: PASS (desktop/mobile, no horizontal overflow, local images, keyboard entry, no external requests).');
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
