"""Static source/package checks; not native browser or store acceptance.
SPDX-License-Identifier: GPL-3.0-or-later
"""
from pathlib import Path
import hashlib
import json
import re
import struct
import subprocess
ROOT=Path(__file__).resolve().parents[1]
EXT=ROOT/'extension'
manifest=json.loads((EXT/'manifest.json').read_text())
assert manifest['manifest_version']==3 and manifest['version']=='0.1.0'
assert len(manifest['description'])<=132
for key in ('permissions','host_permissions','optional_permissions','optional_host_permissions','content_scripts','externally_connectable'):
    assert not manifest.get(key),key
csp=manifest['content_security_policy']['extension_pages']
assert "script-src 'self'" in csp and "connect-src 'none'" in csp and "object-src 'none'" in csp
assert 'unsafe-eval' not in csp and 'https:' not in csp
for name in ('engine.mjs','app.mjs','sample.mjs','background.js'):
    subprocess.run(['node','--check',str(EXT/name)],check=True)
    assert not re.search(r'\b(?:fetch|eval)\s*\(|new\s+(?:Function|WebSocket)|XMLHttpRequest|sendBeacon',(EXT/name).read_text())
for file in EXT.glob('*.html'):
    text=file.read_text()
    assert not re.search(r'<script(?![^>]*\bsrc=)[^>]*>\s*\S',text)
    for target in re.findall(r'\b(?:src|href)="([^"]+)"',text):
        if target.startswith(('https://','#')):continue
        assert (file.parent/target).resolve().is_relative_to(EXT.resolve())
        assert (file.parent/target).exists(),target
for size,path in manifest['icons'].items():
    data=(EXT/path).read_bytes()
    assert data[:8]==b'\x89PNG\r\n\x1a\n'
    assert struct.unpack('>II',data[16:24])==(int(size),int(size))
for file in (ROOT/'store').glob('screenshot-*.png'):
    assert struct.unpack('>II',file.read_bytes()[16:24])==(1280,800)
assert 'GNU GENERAL PUBLIC LICENSE' in (EXT/'COPYING').read_text()
raw=(ROOT/'reference/optimizer.py').read_bytes()
assert hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()=='6386f0f1eec53f276aec213234888c12c37d1096'
records=[]
for path in sorted(EXT.rglob('*')):
    if not path.is_file():continue
    assert not path.is_symlink() and path.stat().st_size<=2*1024*1024
    if path.suffix in {'.html','.css','.mjs','.js','.json'}:
        data=path.read_text()
        assert not re.search(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|github_pat_[A-Za-z0-9_]{25,}|ghp_[A-Za-z0-9]{25,}',data)
        assert not any(t in data for t in ('192.168.0.15','192.168.0.16','lareliquia.angulo@','MODELOS-3D'))
    records.append({'path':path.relative_to(EXT).as_posix(),'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
(ROOT/'tests/package-checks.json').write_text(json.dumps({'status':'passed','scope':'static manifest, module syntax, local resources, source sizes, known secret patterns and original Python oracle identity','files':records,'native_installation':False,'store_submission':False},indent=2)+'\n')
print(f'Static checks passed for {len(records)} extension files. No privileged permissions or remote code.')
