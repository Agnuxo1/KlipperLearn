"""Exercise the actual app and service worker with no printer or LAN access.
SPDX-License-Identifier: GPL-3.0-or-later
"""
from pathlib import Path
from functools import partial
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
import threading, json, tempfile, zipfile, os
from playwright.sync_api import sync_playwright, expect
ROOT=Path(__file__).resolve().parents[1]
DOCS=ROOT.parents[1]/'docs'
class Quiet(SimpleHTTPRequestHandler):
    def log_message(self,*args): pass
server=ThreadingHTTPServer(('127.0.0.1',0),partial(Quiet,directory=str(DOCS)))
thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
try:
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True, executable_path=os.environ.get("KL_CHROMIUM_PATH"))
        context=browser.new_context(accept_downloads=True)
        page=context.new_page();errors=[];external=[]
        page.on('pageerror',lambda err:errors.append(str(err)))
        page.on('request',lambda req:external.append(req.url) if req.url.startswith(('http:','https:')) and not req.url.startswith('http://127.0.0.1:') else None)
        url=f'http://127.0.0.1:{server.server_port}/slicer-review/index.html'
        page.on('console',lambda m:print('BROWSER_CONSOLE',m.type,m.text) if m.type=='error' else None)
        page.goto(url);page.locator('#demo').click();page.wait_for_timeout(500);print('APP_STATUS',page.locator('#status').inner_text(),'ERRORS',errors)
        expect(page.locator("#export-profiles")).to_be_enabled()
        with page.expect_download() as capture:page.locator('#export-profiles').click()
        with zipfile.ZipFile(capture.value.path()) as z:assert len(z.namelist())==8 and z.testzip() is None
        page.locator('#enable-offline').click()
        expect(page.locator("#install-status")).to_contain_text("Offline application files are ready",timeout=30000)
        entries=page.evaluate("async()=>{const c=await caches.open('klipperlearn-slicer-review-shell-0.1.0');return (await c.keys()).map(r=>r.url)}")
        assert len(entries)==16 and all('/slicer-review/' in item for item in entries)
        context.set_offline(True);page.reload(wait_until='load')
        page.locator('#demo').click();expect(page.locator("#export-profiles")).to_be_enabled()
        with page.expect_download() as capture:page.locator('#export-profiles').click()
        with zipfile.ZipFile(capture.value.path()) as z:
            assert len(z.namelist())==8
            assert 'DEMO' in json.loads(z.read('klipperlearn_quality_process.json'))['name']
        for width in (390,1280):
            page.set_viewport_size({'width':width,'height':800})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
        page.locator('a[href="help.html"]').first.click()
        assert page.locator('body').inner_text().find('Hosted and offline app')>=0
        assert not errors and not external,(errors,external)
        print(json.dumps({'pwa_test':'passed','native_service_worker':True,'offline_reload_and_export':True,'cached_static_files':len(entries),'external_app_requests':len(external),'android_device_test':False,'windows_store_install':False}))
        browser.close()
finally:
    server.shutdown();server.server_close();thread.join(timeout=3)
