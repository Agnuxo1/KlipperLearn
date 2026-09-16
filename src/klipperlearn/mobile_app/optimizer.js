/* File-first review only. No printer control, external inference or trackers. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  let session = null, proposal = null, proposalRaw = null, busy = false, ready = false;
  const urls = [];
  function currentToken() {
    try { return sessionStorage.getItem('klipperlearn-token') || localStorage.getItem('klipperlearn-token') || ''; }
    catch (_) { return ''; }
  }
  async function apiRaw(path, raw, timeout=20000) {
    const token = currentToken();
    if (!token) throw Error('Open the printer console and connect before using this page.');
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), timeout);
    try {
      const response = await fetch('/mobile/api/optimizer/' + path, {
        method: 'POST', cache: 'no-store', signal: controller.signal,
        headers: {'Content-Type':'application/json','X-KlipperLearn-Token':token}, body: raw
      });
      const body = await response.json();
      if (!response.ok) throw Error(typeof body.detail === 'string' ? body.detail : 'The supplied data could not be validated.');
      return body.result;
    } finally { clearTimeout(timer); }
  }
  function api(path, data, timeout=20000) { return apiRaw(path, JSON.stringify(data), timeout); }
  function buttons() {
    $('review').disabled = $('request').disabled = !session || busy;
    $('proposal').disabled = !session || !proposal || busy;
    $('discover').disabled = busy;
    $('profiles').disabled = !session || !ready || busy;
  }
  async function run(action) {
    if (busy) return;
    busy = true; buttons(); $('profiles').disabled = true;
    try { await action(); }
    catch (error) { $('status').textContent = error.name === 'AbortError' ? 'Timed out. No printer command was sent.' : error.message; }
    finally { busy = false; buttons(); }
  }
  function download(name, value) {
    const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], {type:'application/json'})); urls.push(url);
    const link = document.createElement('a'); link.href = url; link.download = name; link.className = 'button'; link.textContent = 'Download ' + name;
    $('downloads').append(link);
  }
  function clearDownloads() { while (urls.length) URL.revokeObjectURL(urls.pop()); $('downloads').replaceChildren(); }
  async function readFile(input) {
    const file = input.files[0];
    if (!file || file.size > 2*1024*1024) throw Error('Select a JSON file no larger than 2 MiB.');
    // Preserve raw JSON for strict duplicate-key validation before parsing in JS.
    const raw = await file.text();
    const token = currentToken();
    if (!token) throw Error('Connect using the printer console first.');
    return {raw, value:JSON.parse(raw)};
  }
  $('sessionFile').onchange = () => run(async () => {
    session = null; ready = false; clearDownloads(); $('profiles').disabled = true;
    const loaded = await readFile($('sessionFile'));
    const answer = {result:await apiRaw('review',loaded.raw)};
    session = loaded.value;
    $('brand').value = session.printer.brand; $('model').value = session.printer.model;
    $('brand').readOnly = $('model').readOnly = true;
    $('identity').textContent = session.printer.preset + ' · ' + session.material + ' · ' + session.benchmark.layer_count + ' layers. Identity is locked to the loaded evidence.';
    $('result').textContent = JSON.stringify(answer.result, null, 2);
    $('status').textContent = session.synthetic ? 'SYNTHETIC DEMONSTRATION — not a real printer profile.' : 'Session loaded. Review evidence and original photographs.';
    ready = answer.result.status === 'profiles_available';
  });
  $('review').onclick = () => run(async () => {
    const result = await api('review',session); $('result').textContent = JSON.stringify(result,null,2);
    $('status').textContent = result.status === 'profiles_available' ? 'Three modes can be exported from reviewed trial records.' : 'More comparable, complete and reviewed evidence is needed.';
    ready = result.status === 'profiles_available';
  });
  $('request').onclick = () => run(async () => {
    const result = await api('advisor-request',session); clearDownloads();
    download('klipperlearn-ai-review.json',{...result, reviewer_label:$('reviewer').value, model_label:$('modelLabel').value});
    $('status').textContent = 'Request prepared locally. Attach original photographs separately in your selected assistant. No model was called.';
  });
  $('profiles').onclick = () => run(async () => {
    const result = await api('profiles',session); clearDownloads();
    for (const [name,value] of Object.entries(result.files)) download(name,value);
    download('klipperlearn-mode-review.json',{...result, files:undefined});
    $('status').textContent = 'Profile pairs ready. Import into OrcaSlicer, select the matching process and filament, then reslice and inspect. Nothing was installed or printed.';
    $('result').textContent = JSON.stringify(result.review,null,2);
  });
  $('proposalFile').onchange = () => run(async () => {proposal = null; proposalRaw = null; const loaded = await readFile($('proposalFile')); proposal = loaded.value; proposalRaw = loaded.raw; $('status').textContent = 'Proposal loaded; validation is still required.';});
  $('proposal').onclick = () => run(async () => { const result=await apiRaw('check-proposal','{"session":'+JSON.stringify(session)+',"proposal":'+proposalRaw+'}'); $('result').textContent=JSON.stringify(result,null,2); clearDownloads(); for (const [name,value] of Object.entries(result.files || {})) download(name,value); download('klipperlearn-unprinted-candidate.json',result);$('status').textContent='Bounded candidate only. A new supervised trial and review are required.';});
  $('discover').onclick = () => run(async () => {
    if (!$('consent').checked) throw Error('Explicit consent is required for discovery.');
    $('status').textContent='Checking approved LAN API endpoints; this can take up to 75 seconds.';
    const result=await api('discover',{cidr:$('cidr').value.trim(),confirmed:true},85000);
    $('discoveryResult').textContent=JSON.stringify(result,null,2);
    $('status').textContent=result.complete ? 'Discovery complete. Confirm the printer identity manually.' : 'Partial discovery only; not all hosts completed.';
  });
  window.addEventListener('pagehide',clearDownloads);
})();
