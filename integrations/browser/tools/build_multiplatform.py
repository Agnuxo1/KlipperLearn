"""Build Firefox and installable-web distributions from the reviewed Chrome source.
No publication, account setup, network access or printer command is performed.
SPDX-License-Identifier: GPL-3.0-or-later
"""
from pathlib import Path
import hashlib
import json
import shutil
import zipfile
from PIL import Image
ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
EXT = ROOT / 'extension'
OUT = ROOT / 'dist'
OUT.mkdir(exist_ok=True)
FIREFOX = ROOT / 'firefox'
PWA = REPO / 'docs/slicer-review'
for target in (FIREFOX, PWA):
    target.mkdir(parents=True, exist_ok=True)
    for path in EXT.rglob('*'):
        if path.is_file():
            dest = target / path.relative_to(EXT)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, dest)
manifest = json.loads((FIREFOX / 'manifest.json').read_text())
manifest.pop('minimum_chrome_version', None)
manifest['background'] = {'scripts': ['background.js']}
manifest['browser_specific_settings'] = {
    'gecko': {'id': 'slicer-review@klipperlearn.agnuxo1.github.io',
              'strict_min_version': '140.0',
              'data_collection_permissions': {'required': ['none']}},
    'gecko_android': {'strict_min_version': '142.0'}}
(FIREFOX / 'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
(FIREFOX / 'background.js').write_text(
    "// SPDX-License-Identifier: GPL-3.0-or-later\n"
    "browser.action.onClicked.addListener(() => {\n"
    "  browser.tabs.create({url: browser.runtime.getURL('index.html')});\n});\n", encoding='utf-8')
for name in ('help.html',):
    path = FIREFOX / name
    text = path.read_text(encoding='utf-8').replace('CHROME EXTENSION', 'FIREFOX EXTENSION')
    text = text.replace('Google may process', 'Mozilla may process')
    path.write_text(text, encoding='utf-8')
for name in ('manifest.json', 'background.js'):
    (PWA / name).unlink()
for size in (192, 512):
    with Image.open(EXT / 'icons/icon-128.png') as image:
        image.resize((size,size), Image.Resampling.LANCZOS).save(PWA/f'icons/icon-{size}.png')
pwa_manifest = {'id': './', 'name': 'KlipperLearn Slicer Review',
    'short_name': 'KlipperLearn', 'description': 'Local calibration evidence and reviewed slicer presets.',
    'lang':'en', 'start_url':'./index.html', 'scope':'./', 'display':'standalone',
    'background_color':'#0b1220', 'theme_color':'#0b1220',
    'icons':[{'src':f'icons/icon-{size}.png','sizes':f'{size}x{size}','type':'image/png'} for size in (192,512)]}
(PWA/'manifest.webmanifest').write_text(json.dumps(pwa_manifest, indent=2)+'\n', encoding='utf-8')
pwa_sources = ROOT / 'web-platform'
for name in ('service-worker.js', 'install.mjs'):
    shutil.copyfile(pwa_sources/name, PWA/name)
index = (PWA/'index.html').read_text(encoding='utf-8')
index = index.replace('<title>', '<meta name="theme-color" content="#0b1220"><link rel="manifest" href="manifest.webmanifest"><title>', 1)
index = index.replace('<title>', '<link rel="icon" href="icons/icon-32.png"><title>',1)
index = index.replace('</head>', '<script type="module" src="install.mjs"></script></head>', 1)
index = index.replace('<main>', '<main><section class="panel" aria-label="Offline installation"><button id="enable-offline">Enable offline app</button> <button id="install-app" hidden>Install app</button><p id="install-status" role="status">Works in a browser. Optional offline support caches only application files, never your sessions or photographs.</p></section>', 1)
index = index.replace('inside this extension', 'inside this app')
csp = "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' blob:; connect-src 'self'; worker-src 'self'; manifest-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'"
index = index.replace('<meta charset="utf-8">', '<meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="'+csp+'">', 1)
(PWA/'index.html').write_text(index, encoding='utf-8')
help_text = (PWA/'help.html').read_text(encoding='utf-8')
help_text = help_text.replace('CHROME EXTENSION', 'INSTALLABLE WEB APP').replace('extension', 'app').replace('Extension', 'App')
help_text = help_text.replace('</main>', '<section><h2>Hosted and offline app</h2><p>Initial loading retrieves these static application files from GitHub Pages. GitHub may keep hosting request logs under its own policies. The app does not upload your selected files. Offline support caches only the public application shell on this device. Sessions and photographs remain in memory; save before closing. Installing this web app is not a Google Play or Microsoft Store listing.</p></section></main>')
(PWA/'help.html').write_text(help_text, encoding='utf-8')
for module in PWA.glob("*.mjs"):
    text=module.read_text(encoding="utf-8").replace(".mjs",".js")
    module.with_suffix(".js").write_text(text,encoding="utf-8")
    module.unlink()
for textfile in (PWA/"index.html",PWA/"service-worker.js"):
    textfile.write_text(textfile.read_text(encoding="utf-8").replace(".mjs",".js"),encoding="utf-8")
records=[]
for folder, name in ((EXT,'KlipperLearn-Chrome-0.1.0.zip'), (FIREFOX,'KlipperLearn-Firefox-0.1.0.zip'), (PWA,'KlipperLearn-Installable-Web-App-0.1.0.zip')):
    path=OUT/name
    with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for source in sorted(folder.rglob('*')):
            if source.is_file():
                entry=zipfile.ZipInfo(source.relative_to(folder).as_posix(),date_time=(2026,9,17,0,0,0));entry.compress_type=zipfile.ZIP_DEFLATED;entry.external_attr=0o100644<<16
                archive.writestr(entry,source.read_bytes())
    records.append({'name':name,'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
(OUT/'SHA256SUMS').write_text(''.join(r['sha256']+'  '+r['name']+'\n' for r in records),encoding='utf-8')
print(json.dumps(records,indent=2))
