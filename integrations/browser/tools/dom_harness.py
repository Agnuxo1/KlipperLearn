"""In-memory DOM harness, not native extension installation.

The sandbox's extension and URL policies are not changed. Only locally authored
content is rendered. Secure-origin hashing and download navigation are explicit
test doubles. Independent Node/Python tests check numeric and output correctness.
SPDX-License-Identifier: GPL-3.0-or-later
"""
from pathlib import Path
from contextlib import contextmanager
from types import SimpleNamespace
import base64
import hashlib
import re


def attach(page, extension: Path, temporary: Path):
    page.expose_function('_digestForTest',lambda data:list(hashlib.sha256(bytes(data)).digest()))
    def load(name):
        source=(extension/name).read_text()
        source=re.sub(r'<script\b[^>]*>.*?</script>','',source,flags=re.S)
        source=re.sub(r'<link\b[^>]*>','',source)
        for image in (extension/'icons').glob('*.png'):
            source=source.replace('src="icons/'+image.name+'"','src="data:image/png;base64,'+base64.b64encode(image.read_bytes()).decode()+'"')
        page.set_content(source)
        page.add_style_tag(content=(extension/'style.css').read_text())
        if name!='index.html':return
        page.add_script_tag(content='''(()=>{
          window.__downloads=[];window.__blobs=new Map();
          const original=URL.createObjectURL.bind(URL);
          URL.createObjectURL=function(blob){const url=original(blob);window.__blobs.set(url,blob);return url;};
          Object.defineProperty(crypto,'subtle',{configurable:true,value:{digest:async(algorithm,data)=>{
            if(algorithm!=='SHA-256')throw new Error('Unexpected hash API');
            return Uint8Array.from(await window._digestForTest(Array.from(new Uint8Array(data)))).buffer;
          }}});
          document.addEventListener('click',event=>{
            const link=event.target.closest('a');
            if(link&&link.download){event.preventDefault();const blob=window.__blobs.get(link.href);
              if(blob)window.__downloads.push({name:link.download,blob});}
          },true);
        })();''')
        core=(extension/'engine.mjs').read_text().replace('export ','')
        names='loads,stringify,clone,number,sha256,validateSession,reviewSession,buildProfiles,advisorRequest,validateProposal,configurationHash,zipFiles,PARAMETERS,SCHEMA,MAX_BYTES'
        page.add_script_tag(content='(()=>{'+core+';window.__engine={'+names+'};})();')
        page.add_script_tag(content=(extension/'sample.mjs').read_text().replace('export const sampleText','window.sampleText'))
        app=(extension/'app.mjs').read_text()
        app=re.sub(r"import \{[\s\S]*?\}\s*from './engine.mjs';",'const {'+names+'}=window.__engine;',app,count=1)
        app=re.sub(r"import \{\s*sampleText\s*\}\s*from './sample.mjs';",'const sampleText=window.sampleText;',app)
        page.add_script_tag(content='(()=>{'+app+'})();')
    @contextmanager
    def capture_download():
        count=page.evaluate('window.__downloads.length')
        result=SimpleNamespace(value=None)
        yield result
        page.wait_for_function(f'window.__downloads.length>{count}')
        value=page.evaluate(f'async()=>({{name:window.__downloads[{count}].name,bytes:Array.from(new Uint8Array(await window.__downloads[{count}].blob.arrayBuffer()))}})')
        output=temporary/f'captured-{count}-{value["name"]}'
        output.write_bytes(bytes(value['bytes']))
        result.value=SimpleNamespace(path=lambda:str(output))
    return load,capture_download
