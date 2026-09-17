/* SPDX-License-Identifier: MIT
 * Local-only UI. All downloads follow user gestures; nothing is uploaded.
 */
(function () {
  'use strict';
  const core = window.KlipperLearnCore, json = window.KlipperLearnJSON;
  const $ = id => document.getElementById(id);
  let session = null, decision = null, generation = 0;
  const limit = 2 * 1024 * 1024;
  function show(message, data = null) {
    $('message').textContent = message;
    $('output').textContent = data === null ? '' : JSON.stringify(data, null, 2);
    decision = data;
    $('save-decision').disabled = data === null;
  }
  function reset(message = 'No session loaded.') {
    generation++; session = null; decision = null;
    for (const id of ['analyze', 'export', 'validate', 'save-session', 'save-decision']) $(id).disabled = true;
    $('session-summary').textContent = message;
    $('trials').replaceChildren(); $('proposal').value = '';
    show(message);
  }
  function load(data) {
    core.validateSession(data); session = data;
    $('session-summary').textContent = (data.synthetic ? 'SYNTHETIC EXAMPLE · ' : 'IMPORTED · ') + data.session_id + ' · ' + data.trials.length + ' trials';
    for (const t of data.trials) {
      const row = document.createElement('tr');
      for (const item of [t.id, t.value, t.duration_s, t.quality_score ?? 'Unreviewed']) {
        const cell = document.createElement('td'); cell.textContent = String(item); row.appendChild(cell);
      }
      $('trials').appendChild(row);
    }
    for (const id of ['analyze', 'export', 'validate', 'save-session']) $(id).disabled = false;
    show('Session loaded locally. No printer has been contacted.');
  }
  function run(action) {
    try { action(); } catch (error) { show('Not accepted: ' + error.message); }
  }
  function save(name, data) {
    const blob = new Blob([JSON.stringify(data, null, 2) + '\n'], {type: 'application/json'});
    const url = URL.createObjectURL(blob), link = document.createElement('a');
    link.href = url; link.download = name; document.body.appendChild(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  }
  $('clear').addEventListener('click', () => { reset('Session cleared from this page.'); $('session-file').value = ''; });
  $('demo').addEventListener('click', () => { reset(); run(() => load(json.parse(JSON.stringify(window.KlipperLearnDemo)))); });
  $('session-file').addEventListener('change', async event => {
    reset(); const ticket = generation, file = event.target.files[0];
    if (!file) return;
    try {
      if (file.size > limit) throw new Error('Session file exceeds 2 MiB.');
      const bytes = await file.arrayBuffer();
      if (ticket !== generation) return;
      load(json.parse(new TextDecoder('utf-8', {fatal: true}).decode(bytes)));
    } catch (error) {
      if (ticket === generation) { reset(); show('Not accepted: ' + error.message); }
    }
  });
  $('analyze').addEventListener('click', () => run(() => { const result = core.advise(session); show(result.reason, result); }));
  $('export').addEventListener('click', () => run(() => { const result = core.advisorRequest(session); save('klipperlearn-advisor-request.json', result); show('Saved locally. Review before manually sharing; photographs are not embedded.', result); }));
  $('validate').addEventListener('click', () => run(() => { const result = core.validateProposal(session, json.parse($('proposal').value, 20000)); show('Format and evidence references accepted. This does not verify physical safety or authorize printing.', result); }));
  $('save-session').addEventListener('click', () => run(() => { if (session) save('klipperlearn-session.json', session); }));
  $('save-decision').addEventListener('click', () => run(() => { if (decision) save('klipperlearn-decision.json', decision); }));
}());
