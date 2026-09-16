/* SPDX-License-Identifier: MIT
 * Local reference UI. Deliberately contains no fetch, device or printer API.
 */
(function () {
  'use strict';
  const core = window.KlipperLearnCore;
  let session = null;
  const get = id => document.getElementById(id);
  function show(message, data) {
    get('message').textContent = message;
    get('output').textContent = data ? JSON.stringify(data, null, 2) : '';
  }
  function run(action) {
    try { action(); } catch (error) { show('Not accepted: ' + error.message); }
  }
  function load(data) {
    core.validateSession(data);
    session = data;
    get('session-summary').textContent = (data.synthetic ? 'SYNTHETIC EXAMPLE · ' : 'IMPORTED · ') +
      data.session_id + ' · ' + data.trials.length + ' trials · ' + data.policy.parameter;
    get('trials').textContent = '';
    data.trials.forEach(trial => {
      const row = document.createElement('tr');
      [trial.id, trial.value, trial.duration_s, trial.quality_score === null ? 'Unreviewed' : trial.quality_score].forEach(value => {
        const cell = document.createElement('td'); cell.textContent = String(value); row.appendChild(cell);
      });
      get('trials').appendChild(row);
    });
    ['analyze', 'export', 'validate'].forEach(id => { get(id).disabled = false; });
    get('proposal').value = '';
    show('Session loaded locally. No printer has been contacted.');
  }
  get('demo').addEventListener('click', () => run(() => load(JSON.parse(JSON.stringify(window.KlipperLearnDemo)))));
  get('session-file').addEventListener('change', event => {
    const file = event.target.files[0];
    if (!file) return;
    if (file.size > 2 * 1024 * 1024) { show('Not accepted: session file exceeds 2 MiB.'); return; }
    const reader = new FileReader();
    reader.onload = () => run(() => load(JSON.parse(reader.result)));
    reader.onerror = () => show('The selected file could not be read.');
    reader.readAsText(file);
  });
  get('analyze').addEventListener('click', () => run(() => {
    const decision = core.advise(session); show(decision.reason, decision);
  }));
  get('export').addEventListener('click', () => run(() => {
    const data = core.advisorRequest(session);
    const blob = new Blob([JSON.stringify(data, null, 2) + '\n'], {type: 'application/json'});
    const url = URL.createObjectURL(blob), link = document.createElement('a');
    link.href = url; link.download = 'klipperlearn-advisor-request.json';
    document.body.appendChild(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    show('Request saved locally. Inspect it before sharing; photos are not embedded.', data);
  }));
  get('validate').addEventListener('click', () => run(() => {
    if (get('proposal').value.length > 20000) throw new Error('Proposal exceeds the size limit.');
    const proposal = core.validateProposal(session, JSON.parse(get('proposal').value));
    show('Proposal format and evidence references accepted. This does not verify its physical safety or authorize printing.', proposal);
  }));
}());
