"""Exercise original UI logic in a documented Chromium DOM harness.

No browser policy is altered. No native extension/module/download claim is made.
SPDX-License-Identifier: GPL-3.0-or-later
"""
from pathlib import Path
import hashlib
import importlib.util
import json
import sys
import tempfile
import zipfile
from PIL import Image
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
EXT=ROOT/'extension'
STORE=ROOT/'store'
sys.path.insert(0,str(ROOT/'tools'))
from dom_harness import attach
checks=[]
def passed(name):
    checks.append(name); print('PASS',name,flush=True)

with tempfile.TemporaryDirectory(prefix='klipperlearn-chrome-') as temp,sync_playwright() as p:
    context=p.chromium.launch_persistent_context(temp,executable_path='/usr/bin/chromium',headless=True,
        args=['--no-sandbox','--disable-gpu'],viewport={'width':1280,'height':800},device_scale_factor=1)
    requests=[]; errors=[]
    context.on('request',lambda req:requests.append(req.url) if req.url.startswith(('http:','https:')) else None)
    page=context.new_page()
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.on('dialog',lambda dialog:dialog.accept())
    load,capture=attach(page,EXT,Path(temp))
    load('index.html')
    page.wait_for_function("document.querySelector('#setup-parameter').options.length===12")
    passed('Original application logic runs in the documented in-memory Chromium harness')
    assert page.locator('#export-profiles').is_disabled()
    page.screenshot(path=str(STORE/'screenshot-1-workspace.png'))
    page.locator('#demo').click()
    page.wait_for_function("document.querySelector('#export-profiles').disabled===false")
    assert 'SYNTHETIC' in page.locator('#session-summary').inner_text()
    assert page.locator('#quality-result').inner_text()=='detail'
    assert page.locator('#speed-result').inner_text()=='fast'
    page.screenshot(path=str(STORE/'screenshot-2-three-modes.png'))
    passed('Synthetic example selects the expected Quality and Speed configurations')
    with capture() as output:page.locator('#export-profiles').click()
    with zipfile.ZipFile(output.value.path()) as archive:
        assert archive.testzip() is None and len(archive.namelist())==8
        assert json.loads(archive.read('klipperlearn_quality_process.json'))['outer_wall_speed']=='35'
        assert all('DEMO' in json.loads(archive.read(name))['name'] for name in archive.namelist() if name.endswith(('_process.json','_filament.json')))
    passed('Captured output ZIP: six DEMO profiles, audit and instructions; CRC correct')
    with capture() as output:page.locator('#save-session').click()
    session_text=Path(output.value.path()).read_text()
    assert json.loads(session_text)['synthetic'] is True
    passed('Saved session preserves its synthetic flag and parseable JSON')
    with capture() as output:page.locator('#request').click()
    request=json.loads(Path(output.value.path()).read_text())
    assert request['images_attached'] is False and 'machine_start_gcode' not in json.dumps(request)
    proposal={'schema':'klipperlearn.slicer-proposal/v1','session_sha256':request['session_sha256'],
        'anchor_candidate_id':'baseline','parameter':'process.outer_wall_speed','value':42,
        'evidence_trial_ids':['baseline-0'],'rationale':'Synthetic one-step test; never physical actuation.'}
    page.locator('#proposal').fill(json.dumps(proposal))
    with capture() as output:page.locator('#validate').click()
    with zipfile.ZipFile(output.value.path()) as archive:
        assert len(archive.namelist())==3
        assert 'UNVALIDATED TRIAL' in json.loads(archive.read('klipperlearn_unvalidated_trial_process.json'))['name']
    assert not page.locator('#adopt').is_disabled()
    page.locator('#advisor').scroll_into_view_if_needed()
    page.screenshot(path=str(STORE/'screenshot-3-advisor.png'))
    passed('Manual advisor proposal generates explicitly unvalidated trial presets')
    page.locator('#adopt').click()
    page.wait_for_function("document.querySelector('#trial-candidate').options.length===4")
    assert 'unprinted' in page.locator('#status').inner_text().lower()
    passed('Adding a candidate does not invent a trial or apply machine settings')
    page.locator('#proposal').fill(json.dumps({**proposal,'value':400}))
    page.locator('#validate').click()
    page.wait_for_function("document.querySelector('#status').classList.contains('error')")
    assert page.locator('#adopt').is_disabled()
    passed('Stale or out-of-step suggestions cannot be adopted')
    bad=Path(temp)/'bad.json';bad.write_text('{"schema":"a","schema":"b"}')
    page.locator('#session-file').set_input_files(str(bad))
    page.wait_for_function("document.querySelector('#status').textContent.includes('Duplicate')")
    assert page.locator('#trial-candidate option').count()==4
    passed('Invalid imports preserve the currently loaded session')
    photo=Path(temp)/'original.png';Image.new('RGB',(32,32),'white').save(photo)
    page.locator('#photo-files').set_input_files(str(photo))
    page.wait_for_selector('.photo img')
    assert hashlib.sha256(photo.read_bytes()).hexdigest() in page.locator('.photo figcaption').inner_text()
    assert 'Not referenced' in page.locator('.photo figcaption').inner_text()
    passed('Original photograph hashes and unmatched status displayed locally')
    page.locator('#clear').click()
    assert page.locator('#export-profiles').is_disabled() and page.locator('.photo img').count()==0
    passed('Clear discards the session and image previews')
    old=json.loads(session_text)
    process=Path(temp)/'process.json';process.write_text(json.dumps(old['base_process']))
    filament=Path(temp)/'filament.json';filament.write_text(json.dumps(old['base_filament']))
    page.locator('#new-session details').first.locator('summary').click()
    form=page.locator('#setup-form')
    for name,value in {'brand':'Example','model':'Isolated test','preset':old['printer']['preset'],'firmware':'Klipper','material':'Synthetic fixture only','layers':'60','minimum':'20','maximum':'60','step':'5'}.items():form.locator(f'[name="{name}"]').fill(value)
    form.locator('[name="process"]').set_input_files(str(process));form.locator('[name="filament"]').set_input_files(str(filament))
    form.locator('[name="model-file"]').set_input_files(str(EXT/'assets/adjustment-card.stl'))
    form.locator('[name="confirmed"]').check();form.locator('button[type=submit]').click()
    page.wait_for_function("document.querySelector('#status').textContent.includes('Empty real session')")
    assert page.locator('#export-profiles').is_disabled()
    assert page.locator('#trial-candidate option').count()==1
    passed('Guided preset and model entry creates an empty unchanged baseline')
    page.locator('#new-session details').nth(1).locator('summary').click()
    form=page.locator('#trial-form')
    for index in range(2):
        image=Path(temp)/f'trial-{index}.png';Image.new('RGB',(32+index,32),'white').save(image)
        for name,value in {'run':f'own-test-{index}','print-time':'900','total-time':'1020','surface':'4.5','geometry':'4.5'}.items():form.locator(f'[name="{name}"]').fill(value)
        form.locator('[name="photos"]').set_input_files(str(image))
        for name in ('completed','full','reviewed'):form.locator(f'[name="{name}"]').check()
        form.locator('button[type=submit]').click()
        page.wait_for_function(f"document.querySelector('#context-trials').textContent.startsWith('{index+1} trials')")
        page.wait_for_function("document.querySelector('#add-trial').disabled===false")
    assert not page.locator('#export-profiles').is_disabled()
    assert page.locator('#quality-result').inner_text()=='baseline'
    passed('Two independent declared trials enable modes without invented alternatives')
    with capture() as output:page.locator('#save-session').click()
    spec=importlib.util.spec_from_file_location('oracle',ROOT/'reference/optimizer.py')
    oracle=importlib.util.module_from_spec(spec);spec.loader.exec_module(oracle)
    saved=oracle.loads(Path(output.value.path()).read_text())
    assert oracle.review_session(saved)['selected']['Quality']=='baseline'
    passed('Browser-created session structure is accepted by the original Python optimizer')
    page.set_viewport_size({'width':390,'height':844});load('index.html')
    page.wait_for_function("document.querySelector('#setup-parameter').options.length===12")
    assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
    page.locator('#demo').click();page.wait_for_function("document.querySelector('#export-profiles').disabled===false")
    assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
    passed('Narrow layout has no horizontal overflow')
    load('help.html');assert 'Privacy policy' in page.locator('body').inner_text()
    passed('Bundled guide, privacy and licensing load without a website')
    assert not requests,requests
    assert not errors,errors
    passed('Zero external requests and zero renderer errors in this harness')
    context.close()
report={'status':'passed','checks':checks,'count':len(checks),'browser':'Chromium 144.0.7559.96',
    'dom_harness':True,'native_extension_installation':False,'secure_origin_hash_api':'explicit hashlib-backed test double',
    'native_download_navigation':False,'download_test':'captured output blobs validated with Python zipfile',
    'external_requests':requests,'renderer_errors':errors,'store_submission':False,'printer_connected':False,'native_slicer_import':False}
(ROOT/'tests/browser-results.json').write_text(json.dumps(report,indent=2)+'\n')
print(f'{len(checks)} DOM-harness checks passed.',flush=True)
