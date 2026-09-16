(() => {
  'use strict';
  let busy = false;
  let actionBusy=false;
  function token() { return localStorage.getItem('klipperlearn-token') || sessionStorage.getItem('klipperlearn-token') || ''; }
  async function api(path,options={}) {
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),90000);
    try {
      const response=await fetch('/mobile/api/'+path,{...options,cache:'no-store',signal:controller.signal,
        headers:{'X-KlipperLearn-Token':token(),'Content-Type':'application/json'}});
      if (!response.ok) {
        const data=await response.json().catch(()=>({}));
        throw Error(typeof data.detail==='string'?data.detail:"The operation could not be completed.");
      }
      return path==='learning/export'?response.blob():(await response.json()).result;
    } finally {clearTimeout(timer);}
  }
  async function refresh() {
    const output = document.getElementById('learningStatus');
    if (!output || busy || document.hidden) return;
    let token = '';
    try { token = localStorage.getItem('klipperlearn-token') || sessionStorage.getItem('klipperlearn-token') || ''; }
    catch (_) { return; }
    if (!token) return;
    busy = true;
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch('/mobile/api/learning/status', {cache: 'no-store', signal: controller.signal,
        headers: {'X-KlipperLearn-Token': token}});
      if (!response.ok) throw Error('unavailable');
      const {result} = await response.json(), summary = result.summary || {}, operation = result.automatic_print;
      const toggle=document.getElementById('automaticEnabled');
      if(toggle&&!actionBusy){toggle.disabled=false;toggle.checked=Boolean(result.automatic_enabled);}
      const zones=document.getElementById('sixZoneResults');
      if(zones&&result.latest_batch){
        zones.replaceChildren();
        result.latest_batch.zones.forEach((zone,index)=>{
          const button=document.createElement('button');button.type='button';button.className='button';
          const label=zone.score==null?(zone.rated?"insufficient photograph":"awaiting rating"):Number(zone.score).toFixed(0)+'/100';
          button.textContent=`Zona ${index+1} · ${zone.rate} mm³/s · ${label}`;
          button.addEventListener('click',()=>window.dispatchEvent(new CustomEvent('klipperlearn-review-pending',
            {detail:{trial_id:zone.trial_id,force:true}})));
          zones.appendChild(button);
        });
      }
      const collecting = ['printing', 'paused'].includes(result.phase);
      output.textContent = collecting ? "Learning from this print: collecting telemetry and available sensors." :
        `History: ${summary.trials || 0} pruebas · ${summary.rated || 0} valoradas · ${summary.validated_models || 0} modelos validados.`;
      if (!summary.validated_models) output.textContent += " An improvement has not been demonstrated yet.";
      if (operation?.decision?.reason) output.textContent += ' ' + operation.decision.reason;
      if (operation?.phase?.startsWith('restore_')) output.textContent += " Restoration must be verified before another trial can start.";
      if (result.review_pending?.trial_id && !collecting) {
        window.dispatchEvent(new CustomEvent('klipperlearn-review-pending', {detail: result.review_pending}));
      }
    } catch (_) {
      output.textContent = "Learning is temporarily unavailable. Printer controls remain independent.";
    } finally { clearTimeout(timer); busy = false; }
  }
  setInterval(refresh, 10000);
  document.addEventListener('visibilitychange', refresh);
  document.getElementById('automaticEnabled')?.addEventListener('change',async event=>{
    actionBusy=true;event.target.disabled=true;
    try {await api('learning/settings',{method:'POST',body:JSON.stringify({enabled:event.target.checked})});}
    catch(error){document.getElementById('settingsStatus').textContent=error.message;}
    finally {actionBusy=false;refresh();}
  });
  document.getElementById('evidenceExport')?.addEventListener('click',async event=>{
    event.target.disabled=true;
    try {const blob=await api('learning/export'),url=URL.createObjectURL(blob),link=document.createElement('a');
      link.href=url;link.download='klipperlearn-private-evidence.zip';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
    catch(error){document.getElementById('settingsStatus').textContent=error.message;}
    finally {event.target.disabled=false;}
  });
  document.getElementById('sixZonePrepare')?.addEventListener('click',async event=>{
    if(actionBusy)return;
    actionBusy=true;event.target.disabled=true;
    const output=document.getElementById('sixZoneStatus');
    try {
      output.textContent="Preparing six charts from the reference G-code settings…";
      const prepared=await api('learning/six-zone/prepare',{method:'POST',body:'{}'});
      output.textContent='Preparadas: '+prepared.zones.map(z=>z.id+' '+z.rate+' mm³/s').join(' · ');
      if(!await ConsoleShell.confirm("Print the six charts? The bed must be empty. The printer will home once."))return;
      await api('printer/start',{method:'POST',body:JSON.stringify({filename:prepared.filename})});
      output.textContent="Batch started. Evidence and results will be saved in history.";
      document.querySelector('[data-view="printer"]').click();
    } catch(error){output.textContent=error.message+" Do not start again without checking the state.";}
    finally {actionBusy=false;event.target.disabled=false;}
  });
  refresh();
})();
