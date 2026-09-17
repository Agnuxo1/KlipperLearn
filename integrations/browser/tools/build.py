"""Build deterministic extension and source/store ZIPs without publishing.
SPDX-License-Identifier: GPL-3.0-or-later
"""
from pathlib import Path
import hashlib
import json
import zipfile
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT.parent

def archive(filename,items):
    destination=OUT/filename
    with zipfile.ZipFile(destination,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for source,relative in sorted(items,key=lambda item:item[1]):
            if source.is_symlink():raise ValueError('Linked package input rejected')
            info=zipfile.ZipInfo(relative,date_time=(2026,9,17,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=0o100644<<16
            z.writestr(info,source.read_bytes())
    with zipfile.ZipFile(destination) as z:assert z.testzip() is None
    return {'file':filename,'bytes':destination.stat().st_size,'sha256':hashlib.sha256(destination.read_bytes()).hexdigest()}

extension=ROOT/'extension'
results=[archive('KlipperLearn-Chrome-0.1.0.zip',[(p,p.relative_to(extension).as_posix()) for p in extension.rglob('*') if p.is_file()])]
items=[]
for path in ROOT.rglob('*'):
    if not path.is_file() or any(part in ('__pycache__','.git','node_modules') for part in path.parts):continue
    if path.name=='test-output.zip' or path.suffix=='.pyc':continue
    if path.suffix.lower() not in {'.js','.mjs','.py','.html','.css','.png','.svg','.json','.md','.txt','.stl'} and path.name!='COPYING':continue
    items.append((path,path.relative_to(ROOT).as_posix()))
results.append(archive('KlipperLearn-Chrome-0.1.0-Source-and-Store.zip',items))
(OUT/'KlipperLearn-Chrome-0.1.0-SHA256SUMS.txt').write_text(''.join(r['sha256']+'  '+r['file']+'\n' for r in results))
print(json.dumps(results,indent=2))
