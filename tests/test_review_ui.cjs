const {chromium}=require('playwright');
const fs=require('node:fs/promises'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../src/klipperlearn/mobile_app');
const base={id:'0123456789abcdef0123456789abcdef',timestamp_utc:'2026-09-13T08:00:00Z',context:{material:"White PLA",nozzle_mm:.4},score:null,ratings:null,revisions:[]};
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.KL_TEST_BROWSER_CHANNEL ? {channel:process.env.KL_TEST_BROWSER_CHANNEL} : {})});
 try{
  const page=await browser.newPage(),writes=[];
  await page.route('**/*',async route=>{
   const request=route.request(),url=new URL(request.url());
   if(url.pathname.startsWith('/mobile/api/')){
    if(url.pathname.endsWith('/connect')) return route.fulfill({json:{result:{token:'offline_test_token_12345678901234'}}});
    if(url.pathname.includes('/experiments')) assert.equal(request.headers()['x-klipperlearn-token'],'offline_test_token_12345678901234');
    if(url.pathname==='/mobile/api/experiments/recent'&&request.method()==='GET') return route.fulfill({json:{result:[base]}});
    if(url.pathname.endsWith('/ratings')&&request.method()==='POST'){
      writes.push(JSON.parse(request.postData()));
      return route.fulfill({json:{result:{...base,ratings:writes[0].ratings,revisions:[{comment:writes[0].comment}],score:null}}});
    }
    if(url.pathname.endsWith('/printer/status')) return route.fulfill({json:{result:{status:{webhooks:{state:'ready'},print_stats:{state:'standby',filename:''},extruder:{temperature:25,target:0},heater_bed:{temperature:25,target:0},virtual_sdcard:{progress:0}}}}});
    if(url.pathname.endsWith('/printer/capabilities')) return route.fulfill({json:{result:{connected:true,printer_state:'standby',machine:{name:'Test'},limits:{extruder_max:275,bed_max:110,max_velocity:150,max_accel:3000},features:{}}}});
    return route.fulfill({json:{result:null}});
   }
   const name=path.basename(url.pathname);
   try{return route.fulfill({body:await fs.readFile(path.join(root,name)),contentType:({'.html':'text/html','.css':'text/css','.js':'application/javascript','.svg':'image/svg+xml'})[path.extname(name)]||'text/plain'});}catch{return route.fulfill({status:404});}
  });
  await page.goto('https://console.test/mobile/console.html#pair=offline_test_token_12345678901234');
   if(await page.locator('#welcomeDialog').isVisible()) await page.locator('#enterSilent').click();
   await page.waitForFunction(()=>document.getElementById('onboardingCard').hidden);
   await page.locator('[data-view="calibration"]').click();
   await page.locator('#reviewOpen').click();
  await page.waitForFunction(()=>document.querySelectorAll('#reviewTrial option').length===1);
  for(const key of ['speed','surface','geometry']) await page.locator(`input[name="review-${key}"][value="4"]`).check();
  await page.locator('#reviewComment').fill('Prueba integrada');
  await page.locator('#reviewSave').click();
  await page.waitForFunction(()=>!document.getElementById('reviewDialog').open);
  assert.deepEqual(writes,[{ratings:{speed:4,surface:4,geometry:4},comment:'Prueba integrada'}]);
  assert.equal(await page.locator('[data-view="printer"]').getAttribute('aria-current'),'page');
  console.log('integrated review: PASS');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
