/* SPDX-License-Identifier: GPL-3.0-or-later
 * Explicit file workflow. No network, persistent storage or printer commands.
 */
import {loads, stringify, clone, number, sha256, validateSession, reviewSession,
  buildProfiles, advisorRequest, validateProposal, configurationHash, zipFiles,
  PARAMETERS, SCHEMA, MAX_BYTES} from './engine.js';
import {sampleText} from './sample.js';
const $ = id => document.getElementById(id);
let session = null, review = null, pending = null, busy = false, photoUrls = [];
const controlled = ['save-session','export-review','request','validate','add-trial'];
function show(message, error = false) {
  $('status').textContent = message;
  $('status').className = error ? 'error' : 'ok';
}
function formatTime(value) {
  if (value === null) return '—';
  const rounded = Math.round(value);
  return Math.floor(rounded / 60) + 'm ' + rounded % 60 + 's';
}
function updateButtons() {
  for (const id of controlled) $(id).disabled = !session || busy;
  $('export-profiles').disabled = !session || !Object.keys(review?.selected ?? {}).length || busy;
  $('adopt').disabled = !pending || busy;
}
/** Prevent a late asynchronous file read from restoring a cleared/replaced session. */
async function run(action) {
  if (busy) return;
  busy = true;
  const previous = new Map();
  document.querySelectorAll('button,input,select,textarea').forEach(element => {
    previous.set(element, element.disabled); element.disabled = true;
  });
  try { await action(); }
  catch (error) { show(error?.message || 'Operation failed. No settings were applied.', true); }
  finally {
    busy = false;
    for (const [element, disabled] of previous) element.disabled = disabled;
    updateButtons();
  }
}
function download(name, content) {
  const blob = content instanceof Blob ? content : new Blob([
    typeof content === 'string' ? content : stringify(content, true) + '\n'
  ], {type:'application/json'});
  const url = URL.createObjectURL(blob), link = document.createElement('a');
  link.href = url; link.download = name;
  document.body.append(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}
async function readJson(file) {
  if (!file || file.size > MAX_BYTES) throw new Error('Select a JSON file no larger than 2 MiB.');
  return loads(new TextDecoder('utf-8', {fatal:true}).decode(await file.arrayBuffer()));
}
function cell(row, value, style = '') {
  const element = document.createElement('td');
  element.textContent = value; element.className = style; row.append(element);
}
function clearPhotos() {
  photoUrls.forEach(url => URL.revokeObjectURL(url)); photoUrls = [];
  $('photo-gallery').replaceChildren();
}
function reset() {
  session = null; review = null; pending = null;
  clearPhotos();
  $('session-summary').textContent = 'No session loaded. Open a session, try the example, or create one below.';
  $('context-printer').textContent = 'Printer: —'; $('context-layers').textContent = 'Layers: —';
  $('context-trials').textContent = 'Trials: —'; $('results').replaceChildren();
  $('trial-candidate').replaceChildren(); $('excluded').textContent = 'No session loaded.';
  for (const mode of ['quality','standard','speed']) {
    $(mode + '-result').textContent = 'Evidence needed';
    $(mode + '-detail').textContent = 'No settings are invented.';
  }
  $('proposal').value = ''; $('proposal-result').textContent = 'No API calls or automatic printer actions.';
  $('proposal-result').className = ''; $('session-file').value = ''; $('photo-files').value = '';
  updateButtons();
}
async function loadSession(value) {
  validateSession(value);
  const result = await reviewSession(value);
  session = value; review = result; pending = null;
  $('proposal-result').textContent = 'No validated proposal for this session.';
  $('session-summary').textContent = value.synthetic ? 'SYNTHETIC DEMONSTRATION — NOT PRINTER RESULTS' :
    'USER-SUPPLIED EVIDENCE — NOT INDEPENDENTLY VERIFIED';
  $('context-printer').textContent = value.printer.brand + ' · ' + value.printer.model + ' · ' + value.material;
  $('context-layers').textContent = number(value.benchmark.layer_height_mm) + ' mm · ' + number(value.benchmark.layer_count) + ' layers';
  $('context-trials').textContent = value.trials.length + ' trials · ' + value.candidates.length + ' configurations';
  $('results').replaceChildren();
  for (const candidate of result.candidates) {
    const row = document.createElement('tr');
    cell(row, candidate.candidate_id); cell(row, candidate.repeats);
    cell(row, candidate.quality === null ? '—' : candidate.quality.toFixed(2));
    cell(row, formatTime(candidate.print_seconds));
    cell(row, candidate.eligible ? 'Eligible' : candidate.reasons.join('; ').replaceAll('_',' '),
      candidate.eligible ? 'eligible' : 'blocked');
    $('results').append(row);
  }
  $('excluded').replaceChildren();
  if (!result.excluded.length) $('excluded').textContent = 'No excluded trials.';
  else {
    const list = document.createElement('ul');
    for (const trial of result.excluded) {
      const item = document.createElement('li');
      item.textContent = trial.trial_id + ': ' + trial.reasons.join('; ').replaceAll('_',' ');
      list.append(item);
    }
    $('excluded').append(list);
  }
  for (const mode of ['Quality','Standard','Speed']) {
    const key = mode.toLowerCase(), selected = result.selected[mode];
    const candidate = result.candidates.find(c => c.candidate_id === selected);
    $(key + '-result').textContent = selected ?? 'Evidence needed';
    $(key + '-detail').textContent = candidate ? (value.synthetic ? 'DEMO · ' : '') +
      formatTime(candidate.print_seconds) + ' · score ' + candidate.quality.toFixed(2) + '/5 · ' + candidate.repeats + ' repeats' :
      'No accepted comparable baseline yet.';
  }
  $('trial-candidate').replaceChildren();
  for (const candidate of value.candidates) {
    const option = document.createElement('option'); option.value = candidate.id;
    option.textContent = candidate.id; $('trial-candidate').append(option);
  }
  show(Object.keys(result.selected).length ? 'Review ready. Three mode pairs are available for local export.' :
    'Session loaded. Record comparable reviewed trials to enable mode exports.');
  updateButtons();
}
$('demo').addEventListener('click', () => run(async () => {
  if (session && !session.synthetic && !confirm('Replace this session with a synthetic example? Save your session first.')) return;
  clearPhotos(); await loadSession(loads(sampleText));
}));
$('session-file').addEventListener('change', () => run(async () => {
  const file = $('session-file').files[0]; if (!file) return;
  const imported = await readJson(file); await loadSession(imported); clearPhotos();
}));
$('clear').addEventListener('click', () => {
  if (busy || (session && !confirm('Clear this tab? Unsaved session data and photos will be lost.'))) return;
  reset(); show('Workspace cleared. No persistent data was stored.');
});
$('save-session').addEventListener('click', () => run(async () => {
  if (!session) return;
  download(session.synthetic ? 'klipperlearn-DEMO-session.json' : 'klipperlearn-session.json', session);
  show('Session downloaded. Photographs are not embedded. Keep your originals separately.');
}));
$('export-review').addEventListener('click', () => run(async () => {
  if (!session) return; download('klipperlearn-review.json', review);
  show('Review downloaded. Supplied records are not independent certification.');
}));
$('export-profiles').addEventListener('click', () => run(async () => {
  if (!session) return;
  const bundle = await buildProfiles(session), {files, ...audit} = bundle;
  const instructions = 'KlipperLearn Slicer Review\n' +
    (session.synthetic ? 'SYNTHETIC DEMO. Not verified printer settings.\n' : 'User observations and ratings, not independent certification.\n') +
    'Review paired process and filament presets, inheritance and effective settings in OrcaSlicer before import. Reslice the actual model and supervise printing. Native import and physical performance are not certified. Custom G-code and temperatures are preserved, not audited. Never disable printer safeguards.\n';
  download(session.synthetic ? 'KlipperLearn-DEMO-modes.zip' : 'KlipperLearn-reviewed-modes.zip',
    zipFiles({...files, 'review.json':audit, 'README.txt':instructions}));
  show('ZIP created: six paired presets, review and instructions. Nothing was installed or sent to a printer.');
}));
$('request').addEventListener('click', () => run(async () => {
  if (!session) return; download('klipperlearn-advisor-request.json', await advisorRequest(session));
  show('Numerical request downloaded. Review it before manually sharing; attach original photographs separately.');
}));
$('proposal').addEventListener('input', () => {
  pending = null; $('adopt').disabled = true;
  $('proposal-result').textContent = 'Proposal changed; validation is required again.';
});
$('validate').addEventListener('click', () => run(async () => {
  if (!session) return; pending = null;
  try {
    const proposal = loads($('proposal').value); pending = await validateProposal(session, proposal);
    $('proposal-result').className = '';
    $('proposal-result').textContent = 'Accepted as an UNPRINTED experiment: ' + proposal.parameter + ' → ' +
      number(proposal.value) + '. No settings applied.\n' + proposal.rationale;
    const {files, ...audit} = pending;
    download('KlipperLearn-UNVALIDATED-TRIAL.zip', zipFiles({...files, 'trial-review.json':audit}));
    show('One-step proposal validated; trial ZIP created. It is not an accepted mode.');
  } catch (error) {
    $('proposal-result').className = 'error'; $('proposal-result').textContent = error.message; throw error;
  }
}));
$('adopt').addEventListener('click', () => run(async () => {
  if (!session || !pending) return;
  const next = clone(session), id = pending.candidate.id;
  next.candidates.push(clone(pending.candidate)); await loadSession(next); $('trial-candidate').value = id;
  show('Unprinted candidate added. No physical trial or score has been invented. Save your session.');
}));
for (const [parameter, range] of Object.entries(PARAMETERS)) {
  const option = document.createElement('option'); option.value = parameter;
  option.textContent = parameter + ' · ' + range[2]; $('setup-parameter').append(option);
}
$('setup-form').addEventListener('submit', event => {
  event.preventDefault();
  run(async () => {
    const field = name => event.target.elements.namedItem(name), value = name => field(name).value;
    const model = field('model-file').files[0];
    if (!model || !model.size || model.size > 32 * 1024 * 1024) throw new Error('Select an original STL no larger than 32 MiB.');
    const process = await readJson(field('process').files[0]), filament = await readJson(field('filament').files[0]);
    if (session && !confirm('Replace the current session? Save it first.')) return;
    const next = {schema:SCHEMA, synthetic:false,
      printer:{brand:value('brand').trim(), model:value('model').trim(), preset:value('preset').trim(),
        firmware:value('firmware').trim(), nozzle_mm:Number(value('nozzle'))}, material:value('material').trim(),
      benchmark:{sha256:await sha256(await model.arrayBuffer()), layer_height_mm:Number(value('layer')), layer_count:Number(value('layers'))},
      base_process:process, base_filament:filament,
      limits:{[value('parameter')]:{min:Number(value('minimum')), max:Number(value('maximum')), max_step:Number(value('step'))}},
      policy:{minimum_repeats:2, quality_floor:3.5, maximum_time_cv:0.1},
      candidates:[{id:'baseline', process:{}, filament:{}}], trials:[]};
    await loadSession(next); clearPhotos();
    show('Empty real session created. Nothing has been printed or optimized yet. Save this baseline.');
  });
});
/** Inspect dimensions before allowing a potentially large compressed photo to render. */
function imageDimensions(bytes) {
  const view = new DataView(bytes), data = new Uint8Array(bytes);
  const png = [137,80,78,71,13,10,26,10];
  if (png.every((byte,index) => data[index] === byte) && data.length >= 24) {
    return [view.getUint32(16), view.getUint32(20), 'image/png'];
  }
  if (data[0] === 255 && data[1] === 216) {
    let offset = 2;
    while (offset + 9 < data.length) {
      if (data[offset++] !== 255) throw new Error('Invalid JPEG markers.');
      let marker = data[offset++]; while (marker === 255) marker = data[offset++];
      if (marker === 217 || marker === 218) break;
      if (marker === 1 || (marker >= 208 && marker <= 215)) continue;
      const length = view.getUint16(offset);
      if (length < 2 || offset + length > data.length) break;
      if ([192,193,194,195,197,198,199,201,202,203,205,206,207].includes(marker)) {
        return [view.getUint16(offset + 5), view.getUint16(offset + 3), 'image/jpeg'];
      }
      offset += length;
    }
  }
  throw new Error('Select a valid JPEG or PNG photo.');
}
async function readPhoto(file) {
  if (!file || file.size < 24 || file.size > 8 * 1024 * 1024) throw new Error('Photos must be JPEG/PNG, at most 8 MiB each.');
  const bytes = await file.arrayBuffer(), [width, height, mime] = imageDimensions(bytes);
  if (width < 1 || height < 1 || width * height > 20000000) throw new Error('Photo dimensions exceed 20 megapixels.');
  return {hash:await sha256(bytes), bytes, mime, name:file.name};
}
async function showPhotos(files) {
  if (files.length > 8) throw new Error('Select at most eight photographs.');
  const records = []; for (const file of files) records.push(await readPhoto(file));
  clearPhotos();
  for (const record of records) {
    const figure = document.createElement('figure'), image = document.createElement('img'), caption = document.createElement('figcaption');
    figure.className = 'photo';
    const url = URL.createObjectURL(new Blob([record.bytes], {type:record.mime}));
    photoUrls.push(url); image.src = url; image.alt = 'Selected original calibration photograph';
    const matches = session ? session.trials.filter(t => t.photo_sha256.includes(record.hash)).map(t => t.id) : [];
    caption.textContent = record.name + ' · SHA-256 ' + record.hash + ' · ' +
      (matches.length ? 'Referenced by ' + matches.join(', ') : 'Not referenced in this session');
    figure.append(image, caption); $('photo-gallery').append(figure);
  }
  show('Photos opened locally. Hash matching does not verify image content or print quality.');
}
$('photo-files').addEventListener('change', () => run(() => showPhotos([...$('photo-files').files])));
$('trial-form').addEventListener('submit', event => {
  event.preventDefault();
  run(async () => {
    if (!session) throw new Error('Create or open a session first.');
    const form = event.target, field = name => form.elements.namedItem(name), value = name => field(name).value;
    const candidate = session.candidates.find(c => c.id === value('candidate'));
    const files = [...field('photos').files], photos = [];
    if (files.length > 8) throw new Error('At most eight photos per new trial.');
    for (const file of files) photos.push((await readPhoto(file)).hash);
    const next = clone(session), id = value('run').trim();
    next.trials.push({id, session_id:id, candidate_id:candidate.id,
      configuration_sha256:await configurationHash(next, candidate), benchmark_sha256:next.benchmark.sha256,
      layer_height_mm:next.benchmark.layer_height_mm, layer_count:next.benchmark.layer_count,
      completed:field('completed').checked, full_model:field('full').checked, human_reviewed:field('reviewed').checked,
      print_seconds:Number(value('print-time')), total_seconds:Number(value('total-time')),
      surface_score:value('surface') === '' ? null : Number(value('surface')),
      geometry_score:value('geometry') === '' ? null : Number(value('geometry')), photo_sha256:photos});
    await loadSession(next); form.reset();
    show('Trial recorded from your observations. Save your session to retain it. No evidence was uploaded.');
  });
});
window.addEventListener('pagehide', () => photoUrls.forEach(url => URL.revokeObjectURL(url)));
reset();
