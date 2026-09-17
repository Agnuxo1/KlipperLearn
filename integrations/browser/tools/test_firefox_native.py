"""Use an isolated Firefox profile and supported temporary add-on installation.
SPDX-License-Identifier: GPL-3.0-or-later
"""
from pathlib import Path
import json, tempfile, time, zipfile
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
ROOT=Path(__file__).resolve().parents[1]
ADDON='slicer-review@klipperlearn.agnuxo1.github.io'
UUID='5c49dcd4-8278-44bc-af06-ce6444fd44cc'
with tempfile.TemporaryDirectory(prefix='klipperlearn-firefox-') as temporary:
    options=Options();options.add_argument('-headless')
    options.binary_location=r'C:\Program Files\Mozilla Firefox\firefox.exe'
    options.set_preference('extensions.webextensions.uuids',json.dumps({ADDON:UUID}))
    options.set_preference('browser.download.folderList',2)
    options.set_preference('browser.download.dir',temporary)
    options.set_preference('browser.download.useDownloadDir',True)
    options.set_preference('browser.helperApps.neverAsk.saveToDisk','application/zip,application/json,application/octet-stream')
    driver=webdriver.Firefox(options=options, service=Service(service_args=["--allow-system-access"]))
    try:
        installed=driver.install_addon(str(ROOT/'dist/KlipperLearn-Firefox-0.1.0.zip'),temporary=True)
        assert installed==ADDON
        driver.set_context('chrome')
        driver.execute_script("gBrowser.selectedTab = gBrowser.addTab(arguments[0], {triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal()});",f'moz-extension://{UUID}/index.html')
        driver.set_context('content')
        driver.switch_to.window(driver.window_handles[-1])
        driver.find_element(By.ID,'demo').click()
        WebDriverWait(driver,15).until(lambda d:d.find_element(By.ID,'export-profiles').is_enabled())
        driver.find_element(By.ID,'export-profiles').click()
        output=Path(temporary)/'KlipperLearn-DEMO-modes.zip'
        end=time.monotonic()+20
        while not output.exists() and time.monotonic()<end:time.sleep(0.2)
        with zipfile.ZipFile(output) as archive:
            assert len(archive.namelist())==8 and archive.testzip() is None
            assert 'DEMO' in json.loads(archive.read('klipperlearn_quality_process.json'))['name']
        assert driver.find_element(By.ID,'quality-result').text!='Evidence needed'
        print(json.dumps({'firefox_native':'passed','version':driver.capabilities['browserVersion'],
                          'temporary_installation':True,'profile':'disposable','exported_files':8,
                          'printer_contacted':False,'amo_submission':False}))
    finally:
        driver.quit()
