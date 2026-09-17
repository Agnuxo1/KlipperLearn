/* SPDX-License-Identifier: MIT. Real localhost service-worker lifecycle, no printer. */
const assert=require('node:assert/strict');
const fs=require('node:fs/promises'),path=require('node:path'),http=require('node:http');
const {chromium}=require('playwright');
(async()=>{
 const root=path.resolve(__dirname,'../docs/review');
 const server=http.createServer(async(req,res)=>{
  const u=new URL(req.url,'http://localhost');
  if(!u.pathname.startsWith('/review/')){res.writeHead(404);res.end();return;}
  let relative=decodeURIComponent(u.pathname.slice('/review/'.length));if(!relative)relative='index.html';
  const file=path.resolve(root,relative);
  if(!file.startsWith(root+path.sep)){res.writeHead(403);res.end();return;}
  try{const raw=await fs.readFile(file);res.writeHead(200,{'Content-Type':({'.html':'text/html','.js':'application/javascript','.css':'text/css','.png':'image/png','.webmanifest':'application/manifest+json'})[path.extname(file)]||'text/plain','Cache-Control':'no-store'});res.end(raw);}catch{res.writeHead(404);res.end();}
 });
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const origin='http://127.0.0.1:'+server.address().port;
 const browser=await chromium.launch({headless:true,...(process.env.KL_TEST_BROWSER_CHANNEL?{channel:process.env.KL_TEST_BROWSER_CHANNEL}:{})});
 try{
  const context=await browser.newContext(),page=await context.newPage(),errors=[],outside=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('request',req=>{if(!req.url().startsWith(origin+'/'))outside.push(req.url());});
  await page.goto(origin+'/review/index.html');
  assert.equal(await page.evaluate(async()=> (await navigator.serviceWorker.getRegistrations()).length),0);
  await page.locator('#offline-enable').click();
  await page.waitForFunction(()=>document.querySelector('#offline-status').textContent.startsWith('Offline shell ready'),{},{timeout:20000});
  await page.waitForFunction(()=>Boolean(navigator.serviceWorker.controller));
  const cached=await page.evaluate(async()=>{const output=[];for(const key of await caches.keys()){for(const req of await (await caches.open(key)).keys())output.push(req.url);}return output;});
  assert(cached.length>=13);assert(cached.every(u=>u.startsWith(origin+'/review/')));assert(!cached.some(u=>u.endsWith('session.json')));
  await page.locator('#demo').click();await page.locator('#analyze').click();
  await context.setOffline(true);await page.reload();await page.locator('#demo').click();await page.locator('#analyze').click();
  assert.equal(JSON.parse(await page.locator('#output').innerText()).executable,false);
  assert.equal(await page.evaluate(()=>localStorage.length),0);
  await context.setOffline(false);await page.locator('#offline-disable').click();
  await page.waitForFunction(()=>document.querySelector('#offline-status').textContent.startsWith('Offline copy removed'));
  assert.equal(await page.evaluate(async()=> (await navigator.serviceWorker.getRegistrations()).length),0);
  assert.equal(await page.evaluate(async()=> (await caches.keys()).filter(k=>k.startsWith('klipperlearn-review-shell-')).length),0);
  assert.deepEqual(errors,[]);assert.deepEqual(outside,[]);await context.close();
  console.log('Review PWA: PASS (explicit opt-in, scope-bounded shell cache, offline reload/analysis, no session persistence, complete unregister).');
 }finally{await browser.close();await new Promise(resolve=>server.close(resolve));}
})().catch(error=>{console.error(error);process.exitCode=1;});
