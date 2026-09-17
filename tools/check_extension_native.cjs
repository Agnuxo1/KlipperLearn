/* SPDX-License-Identifier: MIT. Explicit temporary-profile extension check. */
const fs=require('node:fs/promises'), path=require('node:path'), os=require('node:os');
const assert=require('node:assert/strict');
const {chromium}=require('playwright');
(async()=>{
 const directory=path.resolve(process.argv[2]||'');
 if(!process.argv[2])throw Error('Pass the directory of a reviewed, unpacked extension.');
 const manifest=JSON.parse(await fs.readFile(path.join(directory,'manifest.json'),'utf8'));
 assert.equal(manifest.name,'KlipperLearn Calibration Review');
 assert.equal(manifest.manifest_version,3);assert.deepEqual(manifest.permissions,[]);
 const profile=await fs.mkdtemp(path.join(os.tmpdir(),'klipperlearn-extension-check-'));
 let context;
 try{
  context=await chromium.launchPersistentContext(profile,{headless:true,
   ...(process.env.KL_TEST_BROWSER_CHANNEL?{channel:process.env.KL_TEST_BROWSER_CHANNEL}:{}),
   args:[`--disable-extensions-except=${directory}`,`--load-extension=${directory}`]});
  let [worker]=context.serviceWorkers();
  if(!worker)worker=await context.waitForEvent('serviceworker',{timeout:15000});
  const id=new URL(worker.url()).host,page=await context.newPage(),errors=[],outside=[];
  page.on('pageerror',error=>errors.push(error.message));
  page.on('request',request=>{if(!request.url().startsWith(`chrome-extension://${id}/`))outside.push(request.url());});
  await page.goto(`chrome-extension://${id}/index.html`);
  await page.locator('#demo').click();await page.locator('#analyze').click();
  assert.equal(JSON.parse(await page.locator('#output').innerText()).executable,false);
  assert.equal(await page.locator('#offline-section').isHidden(),true);
  const perms=await worker.evaluate(()=>chrome.permissions.getAll());
  assert.deepEqual(perms.permissions,[]);assert.deepEqual(perms.origins,[]);
  assert.deepEqual(errors,[]);assert.deepEqual(outside,[]);
  if(process.env.KL_REVIEW_SCREENSHOT){
   await page.setViewportSize({width:1280,height:960});
   await page.screenshot({path:process.env.KL_REVIEW_SCREENSHOT,fullPage:true});
  }
  console.log(JSON.stringify({status:'passed',browser:process.env.KL_TEST_BROWSER_CHANNEL||'chromium',
   version:context.browser()?.version()||'persistent-context',temporary_extension:true,
   local_synthetic_analysis:true,extension_permissions:perms.permissions,
   host_permissions:perms.origins,app_external_requests:outside.length,printer_connected:false}));
 }finally{
  if(context)await context.close();
  await fs.rm(profile,{recursive:true,force:true,maxRetries:5,retryDelay:200});
 }
})().catch(error=>{console.error(error);process.exitCode=1;});
