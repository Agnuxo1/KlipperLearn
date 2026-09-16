(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const categories = [['speed', "Speed"], ['surface', "Surface and layers"], ['geometry', "Geometry, corners and curves"]];
  let records = [], selected = null, busy = false, previousPrintState = '', offset = 0;

  function token() {
    try { return (localStorage.getItem('klipperlearn-token') || sessionStorage.getItem('klipperlearn-token') || '').trim(); }
    catch (_) { return ''; }
  }
  function setStatus(message, error = false) {
    $('reviewStatus').textContent = message;
    $('reviewStatus').className = 'network-status' + (error ? ' error' : '');
  }
  async function request(path = '', options = {}) {
    const value = token();
    if (!value) throw Error("Connect the printer to view its history.");
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch('/mobile/api/experiments' + path, {
        ...options, cache: 'no-store', signal: controller.signal,
        headers: {...(options.headers || {}), 'X-KlipperLearn-Token': value}
      });
      if (!response.ok) throw Error(response.status === 401 ? "Invalid pairing." : "The operation could not be completed.");
      return path === '/export/jsonl' ? response.blob() : (await response.json()).result;
    } finally { clearTimeout(timer); }
  }
  function recordLabel(record) {
    const date = String(record.timestamp_utc || '').slice(0, 16).replace('T', ' ');
    const result = record.score === null ? "pending" : Number(record.score).toFixed(1) + '/100';
    const zone=record.evidence?.batch_zone;
    return `${date} · ${zone ? zone+' · '+record.parameters.volumetric_mm3_s+' mm³/s · ' : ''}${record.context?.material || 'Material'} · ${result}`;
  }
  function renderSelected() {
    selected = records.find(record => record.id === $('reviewTrial').value) || null;
    $('reviewForm').hidden = !selected;
    if (!selected) return;
    $('reviewRecord').textContent = JSON.stringify(selected, null, 2);
    $('reviewComment').value = selected.revisions?.at(-1)?.comment || '';
    categories.forEach(([key]) => {
      document.querySelectorAll(`input[name="review-${key}"]`).forEach(input => {
        input.checked = Number(input.value) === selected.ratings?.[key];
      });
    });
  }
  async function refresh(preferPending = false) {
    setStatus('Consultando historial…');
    records = await request('/recent?limit=30&offset=' + offset);
    $('reviewPrevious').disabled = offset === 0;
    $('reviewNext').disabled = records.length < 30;
    $('reviewTrial').replaceChildren(...records.map(record => {
      const option = document.createElement('option');
      option.value = record.id; option.textContent = recordLabel(record); return option;
    }));
    const preferred = preferPending && records.find(record => record.ratings === null);
    if (preferred) $('reviewTrial').value = preferred.id;
    renderSelected();
    setStatus(records.length ? "History is stored on this computer." : "No prints have been recorded yet.");
  }
  async function guarded(action) {
    if (busy) return;
    busy = true; $('reviewSave').disabled = true;
    try { await action(); }
    catch (error) { setStatus(error.name === 'AbortError' ? "Timed out; check the result before retrying." : error.message, true); }
    finally { busy = false; $('reviewSave').disabled = false; }
  }

  categories.forEach(([key, title]) => {
    const field = document.createElement('fieldset'), legend = document.createElement('legend'), row = document.createElement('div');
    legend.textContent = title; row.className = 'review-star-row'; field.append(legend, row);
    for (let value = 0; value <= 5; value++) {
      const label = document.createElement('label'), input = document.createElement('input');
      input.type = 'radio'; input.name = 'review-' + key; input.value = String(value); input.required = true;
      input.setAttribute('aria-label', `${title}: ${value} out of 5 stars`);
      label.append(input, document.createTextNode(value === 0 ? '0' : '★')); row.append(label);
    }
    $('reviewStars').append(field);
  });
  $('reviewOpen').addEventListener('click', () => guarded(() => { offset = 0; return refresh(false); }));
  $('reviewPrevious').addEventListener('click', () => guarded(() => { offset = Math.max(0, offset - 30); return refresh(false); }));
  $('reviewNext').addEventListener('click', () => guarded(() => { offset += 30; return refresh(false); }));
  $('reviewExport').addEventListener('click', () => guarded(async () => {
    const url = URL.createObjectURL(await request('/export/jsonl')), link = document.createElement('a');
    link.href = url; link.download = 'klipperlearn-experiments.jsonl';
    document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }));
  $('reviewTrial').addEventListener('change', renderSelected);
  $('reviewForm').addEventListener('submit', event => {
    event.preventDefault();
    guarded(async () => {
      if (!selected) throw Error("Select a print.");
      const form = new FormData($('reviewForm')), ratings = {};
      categories.forEach(([key]) => {
        const value = form.get('review-' + key);
        if (value === null) throw Error("Rate all three categories.");
        ratings[key] = Number(value);
      });
      const photo = $('reviewPhoto').files[0];
      if (photo && (photo.type !== 'image/jpeg' || photo.size > 8 * 1024 * 1024)) throw Error("The photograph must be JPEG and no larger than 8 MiB.");
      let record = await request('/' + encodeURIComponent(selected.id) + '/ratings', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ratings, comment: $('reviewComment').value})
      });
      if (photo) {
        record = await request('/' + encodeURIComponent(selected.id) + '/photos', {
          method: 'PUT', headers: {'Content-Type': 'image/jpeg', 'X-KlipperLearn-Filename': photo.name}, body: photo
        });
      }
      records = records.map(item => item.id === record.id ? record : item);
      setStatus("Rating saved.");
      $('reviewPhoto').value = '';
      ConsoleShell.closeDialog($('reviewDialog'));
      document.querySelector('[data-view="printer"]').click();
    });
  });

  const observer = new MutationObserver(() => {
    const state = $('printState').textContent;
    if (previousPrintState === "Printing" && state === "Completed") {
      guarded(async () => {
        offset = 0; await refresh(false);
        const filename = $('file').textContent;
        const matching = records.find(record => record.evidence?.filename === filename);
        if (!matching) return; // Never request a rating for an unrelated/failed trial.
        if (matching.evidence?.decision?.kind === 'six_zone_screen') return; // Wait for the six registered child records.
        $('reviewTrial').value = matching.id; renderSelected(); ConsoleShell.openDialog('reviewDialog');
      });
    }
    previousPrintState = state;
  });
  observer.observe($('printState'), {childList: true, characterData: true, subtree: true});
  previousPrintState = $('printState').textContent;
  let notifiedTrial = null;
  window.addEventListener('klipperlearn-review-pending', event => {
    const id = event.detail?.trial_id;
    if (!id || (!event.detail.force && notifiedTrial === id) || busy || document.querySelector('dialog[open]')) return;
    guarded(async () => {
      const record = await request('/' + encodeURIComponent(id));
      if (record.rating_revision > 0 && !event.detail.force) { notifiedTrial = id; return; }
      offset = 0; await refresh(false);
      if (!records.some(item => item.id === id)) records.unshift(record);
      const option = [...$('reviewTrial').options].find(item => item.value === id);
      if (!option) $('reviewTrial').add(new Option(recordLabel(record), id));
      $('reviewTrial').value = id; renderSelected();
      if (!document.querySelector('dialog[open]')) {
        notifiedTrial = id; ConsoleShell.openDialog('reviewDialog');
      }
    });
  });
})();
