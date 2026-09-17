/* SPDX-License-Identifier: MIT. Strict parser and real browser file/UI tests. */
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const {chromium} = require('playwright');
const parser = require('../distribution/reviewer/strict-json.js');
for (const value of [null, true, false, 12, -4.2e-4, 'hello \\ " \n', '💡', [1,2,{a:'b'}], {nested:{empty:{}, list:[]}}]) {
  assert.equal(JSON.stringify(parser.parse(JSON.stringify(value))), JSON.stringify(value));
}
for (const input of ['{"a":1,"a":2}', '{"a":1,"\\u0061":2}', '{"__proto__":{}}', '1e999', 'NaN', '[1,]', '{"a":1,}', '01', '{}x', '"\\ud800"', '['.repeat(34)+'0'+']'.repeat(34), '']) assert.throws(() => parser.parse(input), undefined, input);
assert.throws(()=>parser.parse('123',2));
(async () => {
 const browser = await chromium.launch({headless:true,...(process.env.KL_TEST_BROWSER_CHANNEL ? {channel:process.env.KL_TEST_BROWSER_CHANNEL}: {})});
 try {
  const context=await browser.newContext({acceptDownloads:true,serviceWorkers:'block'}), page=await context.newPage();
  const errors=[],unexpected=[];page.on('pageerror',e=>errors.push(e.message));
  const root=path.resolve(__dirname,'../docs/review');
  await page.route('**/*',async route=>{
    const u=new URL(route.request().url());
    if(u.hostname!=='review.test' || !u.pathname.startsWith('/review/')) {unexpected.push(u.href);return route.abort();}
    const file=path.resolve(root,u.pathname.slice('/review/'.length)||'index.html');
    if(!file.startsWith(root+path.sep))return route.abort();
    try{return route.fulfill({body:await fs.readFile(file),contentType:({'.html':'text/html','.js':'application/javascript','.css':'text/css','.png':'image/png','.webmanifest':'application/manifest+json'})[path.extname(file)]||'text/plain'});}catch{return route.fulfill({status:404});}
  });
  await page.goto('https://review.test/review/index.html');
  await page.locator('#demo').click();
  await page.locator('#analyze').click();
  const result=JSON.parse(await page.locator('#output').innerText());
  assert.equal(result.synthetic,true);assert.equal(result.executable,false);assert.equal(result.requires_human_approval,true);
  const downloadPromise=page.waitForEvent('download');await page.locator('#save-decision').click();
  const download=await downloadPromise;assert.equal(download.suggestedFilename(),'klipperlearn-decision.json');
  assert.deepEqual(JSON.parse(await fs.readFile(await download.path(),'utf8')),result);
  await page.locator('#session-file').setInputFiles({name:'invalid.json',mimeType:'application/json',buffer:Buffer.from('{"schema":"a","schema":"b"}')});
  await page.waitForFunction(()=>document.querySelector('#message').textContent.includes('Duplicate'));
  assert(await page.locator('#analyze').isDisabled());assert(await page.locator('#save-decision').isDisabled());
  assert.equal(await page.locator('#trials tr').count(),0);
  await page.locator('#demo').click();
  const pending=page.waitForEvent('download');await page.locator('#save-session').click();const saved=await pending;
  const input=await fs.readFile(await saved.path());
  await page.locator('#session-file').setInputFiles({name:'session.json',mimeType:'application/json',buffer:input});
  await page.waitForFunction(()=>!document.querySelector('#analyze').disabled);
  await page.locator('#analyze').click();assert.equal(JSON.parse(await page.locator('#output').innerText()).session_id,result.session_id);
  await page.locator('#clear').click();assert(await page.locator('#analyze').isDisabled());assert.equal(await page.locator('#output').innerText(),'');
  for(const width of [390,1280]) {await page.setViewportSize({width,height:850});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));}
  assert.deepEqual(errors,[]);assert.deepEqual(unexpected,[]);await context.close();
  console.log('Calibration Review: PASS (strict JSON, bounded local files, real downloads, stale-state clearing, responsive layout, no outside requests).');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
