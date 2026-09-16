(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  let selected = null, offset = 0, busy = false;
  const pairPattern = /^[A-Za-z0-9_-]{24,128}$/;
  function currentToken() {
    const pair = new URLSearchParams(location.hash.slice(1)).get('pair');
    let token = '';
    try { token = pairPattern.test(pair || '') ? pair : localStorage.getItem('klipperlearn-token') || sessionStorage.getItem('klipperlearn-token') || ''; } catch (_) {}
    if (pairPattern.test(pair || '')) {
      try { localStorage.setItem('klipperlearn-token', pair); sessionStorage.setItem('klipperlearn-token', pair); } catch (_) {}
      history.replaceState(null, '', location.pathname + location.search);
    }
    return token;
  }
  const message = text => { $('status').textContent = text; };
  async function api(path = '', body, base = '/mobile/api/experiments') {
    const token = currentToken();
    if (!token) throw Error("Tap Connect printer in the console to pair this session.");
    const abort = new AbortController(), timer = setTimeout(() => abort.abort(), 15000);
    try {
      const response = await fetch(base + path, {method: body ? 'POST' : 'GET', cache:'no-store',signal:abort.signal,headers:{'X-KlipperLearn-Token':token,'Content-Type':'application/json'}, ...(body ? {body:JSON.stringify(body)} : {})});
      if (!response.ok) throw Error(response.status === 401 ? "Invalid pairing. Reopen the pairing link." : "The operation could not be completed. Check the data or connection.");
      return path === '/export/jsonl' ? response.blob() : (await response.json()).result;
    } finally { clearTimeout(timer); }
  }
  async function run(action) {
    if (busy) return;
    busy = true;
    try { await action(); } catch (error) { message(error.name === 'AbortError' ? "Request timed out: check history before saving again." : error.message); }
    finally { busy = false; }
  }
  function show(record) {
    selected = record.id; $('detail').hidden = false;
    $('summary').textContent = `${record.context.material} · ${record.context.nozzle_mm} mm · Result: ${record.score === null ? "pending" : record.score.toFixed(1) + '/100'}`;
    $('record').textContent = JSON.stringify(record, null, 2);
    $('rating').reset();
    $('comment').value = record.revisions.length ? record.revisions[record.revisions.length-1].comment : '';
    for (const key of ['speed','surface','geometry']) {
      const value=record.ratings?.[key];
      if(Number.isInteger(value) && value>=0 && value<=5) document.querySelector(`input[name="${key}"][value="${value}"]`).checked=true;
    }
  }
  async function refresh() {
    const records = await api(`?limit=20&offset=${offset}`); $('list').replaceChildren();
    for (const record of records) {
      const button = document.createElement('button');
      button.textContent = `${record.timestamp_utc.slice(0,16)} · ${record.context.material} · ${record.score === null ? "Pending" : record.score.toFixed(1) + '/100'}`;
      button.onclick = () => run(async () => show(await api('/' + encodeURIComponent(record.id))));
      $('list').append(button);
    }
    $('previous').disabled = offset === 0; $('next').disabled = records.length < 20;
    message(records.length ? "History is stored on the local server." : "No trials on this page.");
  }
  for (const [key,label] of [['speed',"Speed"],['surface',"Surface and layers"],['geometry',"Geometry, corners and curves"]]) {
    const field = document.createElement('fieldset'), legend = document.createElement('legend'); legend.textContent = label; field.append(legend);
    for (let value=0; value<=5; value++) { const node=document.createElement('label'), radio=document.createElement('input'); radio.type='radio';radio.name=key;radio.value=value;radio.required=true;radio.setAttribute('aria-label',`${label}: ${value} out of 5 stars`);node.append(radio,document.createTextNode(value + ' ★'));field.append(node); }
    $('stars').append(field);
  }
  $('rating').onsubmit = event => {event.preventDefault();run(async () => {
    if (!selected) return;
    const ratings={},form=new FormData($('rating'));for(const key of ['speed','surface','geometry']) { if(form.get(key)===null) throw Error("Rate all three categories.");ratings[key]=Number(form.get(key)); }
    let record=await api('/'+selected+'/ratings',{ratings,comment:$('comment').value});
    const photo=$('resultPhoto').files[0];
    if(photo){
      if(photo.type!=='image/jpeg' || photo.size>8*1024*1024) throw Error("The photograph must be JPEG and no larger than 8 MiB.");
      const token=currentToken();
      const response=await fetch('/mobile/api/experiments/'+selected+'/photos',{method:'PUT',headers:{'X-KlipperLearn-Token':token,'Content-Type':'image/jpeg','X-KlipperLearn-Filename':photo.name},body:photo});
      if(!response.ok) throw Error("The rating was saved, but the photograph could not be saved. Select it again to retry.");
      record=(await response.json()).result;
    }
    show(record);await refresh();message("Rating saved. Revisions and photographs are preserved.");window.location.assign('console.html?ui=8');
  });};
  $('create').onsubmit = event => {event.preventDefault();run(async () => {
    const file=$('model').files[0]; if (!file || file.size>50*1024*1024) throw Error("Select a file no larger than 50 MiB.");
    const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',await file.arrayBuffer())),b=>b.toString(16).padStart(2,'0')).join('');
    const parameters=JSON.parse($('parameters').value);
    show(await api('',{context:{printer_id:$('printer').value,session_id:$('session').value,model_sha256:hash,material:$('material').value,nozzle_mm:Number($('nozzle').value)},parameters,objective_score:$('objective').value===''?null:Number($('objective').value),evidence:{filename:file.name,source:'manual'}}));
    await refresh();message("Manual trial saved; its data have not been validated yet.");
  });};
  $('refresh').onclick=()=>run(refresh);
  $('readContext').onclick=()=>run(async()=>{
    const context=await api('',null,'/mobile/api/printer/print-context');
    $('contextInfo').textContent=JSON.stringify(context,null,2);
    if(typeof context.material==='string') $('material').value=context.material;
    if(typeof context.nozzle_mm==='number') $('nozzle').value=context.nozzle_mm;
    if(context.parameters) $('parameters').value=JSON.stringify(context.parameters,null,2);
    message("Context retrieved. Review discrepancies and complete unknown fields; this does not verify the physical installation.");
  });
  $('suggest').onsubmit=event=>{event.preventDefault();run(async()=>{
    if(!selected) throw Error("Select a print from history.");
    const result=await api('/suggest',{anchor_id:selected,parameter:$('suggestParameter').value,current:Number($('suggestCurrent').value),bounds:[Number($('suggestMin').value),Number($('suggestMax').value)],maximum_step:Number($('suggestStep').value)});
    $('suggestResult').textContent=JSON.stringify(result,null,2);
    message("Experimental analysis. No adjustment has been sent to the printer.");
  });};
  $('previous').onclick=()=>run(async()=>{offset=Math.max(0,offset-20);await refresh();});
  $('next').onclick=()=>run(async()=>{offset+=20;await refresh();});
  $('export').onclick=()=>run(async()=>{const blob=await api('/export/jsonl'),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='experiments.jsonl';document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);});
  run(refresh);
})();
