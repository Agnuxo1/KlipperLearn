/* No hardware traffic. Every API call is intercepted. */
const {chromium}=require('playwright');
const fs=require('node:fs/promises'), path=require('node:path'), assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../src/klipperlearn/mobile_app');
const token='test_one_click_token_1234567890';
const status={result:{status:{webhooks:{state:'ready'},print_stats:{state:'standby',filename:''},extruder:{temperature:25,target:0},heater_bed:{temperature:25,target:0},virtual_sdcard:{progress:0}}}};
(async()=>{
 const browser=await chromium.launch({headless:true,
  ...(process.env.KL_TEST_BROWSER_CHANNEL ? {channel:process.env.KL_TEST_BROWSER_CHANNEL} : {})});
 try {
  for (const permissions of ['denied','pending','ownership-unavailable']) {
   const context=await browser.newContext(), page=await context.newPage();
   const errors=[],writes=[]; let connects=0,offline=false;
   page.on('pageerror',e=>errors.push(e.message));
   await page.addInitScript(mode=>{
    // A stale token must be replaced by the same single button.
    localStorage.setItem('klipperlearn-token','expired_token_12345678901234567890');
    Object.defineProperty(navigator,'mediaDevices',{value:{getUserMedia:()=>mode==='pending'
      ? new Promise(()=>{}) : Promise.reject(new DOMException('Denied','NotAllowedError'))}});
   },permissions);
   await page.route('**/*',async route=>{
    const req=route.request(),url=new URL(req.url());
    if(url.hostname!=='console.test') return route.abort();
    if(url.pathname.startsWith('/mobile/api/')){
     if(url.pathname.endsWith('/connect')){ connects++; return route.fulfill({json:{result:{token}}}); }
     if(req.headers()['x-klipperlearn-token']!==token) return route.fulfill({status:401,json:{detail:'invalid token'}});
     if(req.method()!=='GET') writes.push(url.pathname);
     if(offline) return route.fulfill({status:503,json:{detail:'offline'}});
     if(url.pathname.endsWith('/printer/status')) return route.fulfill({json:status});
     if(url.pathname.endsWith('/printer/capabilities')) return route.fulfill({json:{result:{connected:true,features:{},limits:{}}}});
     return route.fulfill({json:{result:null}});
    }
    const name=path.basename(url.pathname);
    if(name==='device-owner.js' && permissions==='ownership-unavailable') {
     return route.fulfill({body:'/* optional device coordinator unavailable */',contentType:'application/javascript'});
    }
    try{return route.fulfill({body:await fs.readFile(path.join(root,name)),contentType:({'.html':'text/html','.css':'text/css','.js':'application/javascript','.svg':'image/svg+xml'})[path.extname(name)]||'text/plain'});}catch{return route.fulfill({status:404});}
   });
   await page.goto('https://console.test/mobile/console.html');
   await page.locator('#enterWelcome').click();
   await page.waitForFunction(()=>document.getElementById('onboardingCard').hidden && !document.getElementById('home').disabled,{},{timeout:5000});
   assert.equal(connects,1);
   assert.equal(await page.evaluate(()=>localStorage.getItem('klipperlearn-token')),token);
   assert.equal(await page.locator('#connectionBadge').innerText(),"Connected");
   offline=true;
   await page.waitForFunction(()=>document.getElementById('home').disabled,{},{timeout:6000});
   offline=false;
   await page.waitForFunction(()=>!document.getElementById('home').disabled && document.getElementById('onboardingCard').hidden,{},{timeout:6000});
   assert.deepEqual(writes,[]); assert.deepEqual(errors,[]);
   await context.close();
  }
  console.log('one-click: PASS (fresh page, stale token, denied/pending media, automatic network recovery, no printer writes)');
 } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1;});
