"""Optional native MV3 smoke test for an authorized, unrestricted test browser.

Do not change enterprise policies. No existing profile, store account or printer
is accessed. This test is included but has NOT passed in the delivery sandbox.
SPDX-License-Identifier: GPL-3.0-or-later
"""
from pathlib import Path
import argparse
import json
import tempfile
import zipfile
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('--chromium-path',required=True)
args=parser.parse_args()
with tempfile.TemporaryDirectory(prefix='klipperlearn-native-') as temporary,sync_playwright() as p:
    extension=ROOT/'extension'
    context=p.chromium.launch_persistent_context(temporary,executable_path=args.chromium_path,
        headless=False,ignore_default_args=['--disable-extensions'],
        args=[f'--disable-extensions-except={extension}',f'--load-extension={extension}'],
        accept_downloads=True,viewport={'width':1280,'height':800})
    outbound=[]
    def block(route):outbound.append(route.request.url);route.abort()
    context.route('http://**/*',block);context.route('https://**/*',block)
    try:
        workers=context.service_workers
        worker=workers[0] if workers else context.wait_for_event('serviceworker',timeout=15000)
        extension_id=worker.url.split('/')[2]
        page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(f'chrome-extension://{extension_id}/index.html')
        page.locator('#demo').click()
        page.wait_for_function("document.querySelector('#export-profiles').disabled===false")
        with page.expect_download() as output:page.locator('#export-profiles').click()
        with zipfile.ZipFile(output.value.path()) as archive:
            assert archive.testzip() is None and len(archive.namelist())==8
            assert 'DEMO' in json.loads(archive.read('klipperlearn_quality_process.json'))['name']
        assert not errors and not outbound
        print(json.dumps({'native_extension_smoke':'passed','printer_contacted':False,'outbound_requests':outbound}))
    finally:
        context.close()
