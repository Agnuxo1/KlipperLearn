// SPDX-License-Identifier: GPL-3.0-or-later
// KlipperLearn Phone: user interface wiring. Everything runs in this page; no server.
import {t, localized, setLanguage, detectLanguage, applyTranslations, getLanguage} from './i18n.js';
import {createConnection, transportSupport} from './connection.js';
import {Printer} from './printer.js';
import {MarlinSimulator} from './simulator.js';
import {applyTrial, fileValues, restoreCommands} from './gcode-transform.js';
import {CALIBRATIONS, DEFAULT_PROFILE, estimateSeconds, ringingFrequency, resonanceSweep} from './calibration.js';
import {analyzeAudio, analyzeMotion, analyzeRinging, resonanceFromSweep, sharpness} from './analysis.js';
import {parameterSpace, DEFECTS, recommend, nextParams, baselineParams, scoreTrial} from './advisor.js';
import {openStore, newId, hashText} from './store.js';
import {buildAdvisorRequest, parseAdvisorResponse, askAdvisor} from './jev-client.js';
import {Camera, Microphone, MotionRecorder, WakeLock, sensorSupport} from './sensors.js';
import {TrialRecorder, buildDatasetZip} from './dataset.js';
import {MoonrakerClient, MoonrakerPrinter, defaultMoonrakerUrl, statusRow} from './moonraker.js';

const APP_VERSION = '0.7.0-dataset';

const $ = sel => document.querySelector(sel);
const $$ = sel => [...document.querySelectorAll(sel)];

// Parameters a calibration print sets by itself; the trial transform must not override them.
const CAL_EXCLUDES = {
  temperature: ['hotend_temp_c'], ringing: ['accel_mm_s2', 'shaper_freq_x', 'shaper_freq_y', 'pressure_advance'],
  speed: ['speed_factor_pct'], retraction: ['retract_mm'], pressure_advance: ['pressure_advance'],
};

const S = {
  store: null, profiles: [], profile: null, printer: null, features: null, settings: {},
  params: null, program: null, goal: 'balanced', advisorUrl: '', measuredShaper: {},
  camera: null, measureCamera: null, mic: null, motion: null, wake: new WakeLock(),
  currentTrial: null, rec: null, chosen: null, logLines: [], installPrompt: null, moonrakerUrl: '',
  recorder: null, jobProgress: null,
};

// ---------------------------------------------------------------- helpers
function toast(msg, ms = 3500) {
  const el = $('#toast');
  el.textContent = msg; el.hidden = false;
  clearTimeout(toast.timer); toast.timer = setTimeout(() => { el.hidden = true; }, ms);
}
const fmtTime = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
const fmtNum = (v, d = 2) => (v == null || Number.isNaN(v) ? '–' : Number(v).toFixed(d));
const kvSet = (k, v) => S.store.setKv(k, v).catch(() => {});

function showTab(name) {
  $$('.tab').forEach(s => s.classList.toggle('active', s.id === 'tab-' + name));
  $$('.tabs button').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
  if (name === 'learn') renderLearn();
  window.scrollTo(0, 0);
}

function log(dir, line) {
  if (S.printer?.job && (dir === '>' && /^G[01]\b/.test(line) || line === 'ok')) return;
  if (dir === '<' && /^\s*(ok )?T:[\d.]+ \//.test(line)) return;       // temperature reports
  S.logLines.push(`${dir} ${line}`);
  if (S.logLines.length > 300) S.logLines.splice(0, S.logLines.length - 300);
  if (!log.pending) {
    log.pending = true;
    requestAnimationFrame(() => {
      log.pending = false;
      const el = $('#log');
      if (el.closest('details').open) { el.textContent = S.logLines.join('\n'); el.scrollTop = el.scrollHeight; }
    });
  }
}

function setStatus(kind) {
  const pill = $('#status');
  pill.className = 'pill' + (kind === 'connected' ? ' ok' : kind === 'printing' ? ' busy' : '');
  pill.textContent = t(kind);
  const connected = kind !== 'disconnected';
  $('#estop').hidden = !connected;
  $('#controls').hidden = !connected;
  $('#btn-connect').hidden = connected; $('#btn-sim').hidden = connected; $('#btn-disconnect').hidden = !connected;
  $('#btn-klipper').disabled = connected;
  $('#btn-start').disabled = !connected || !S.program || kind === 'printing';
  $('#btn-record-current').hidden = !(S.printer?.features?.klipper) || kind !== 'connected';
  $('#btn-sweep').disabled = !connected || kind === 'printing';
}

// ---------------------------------------------------------------- profiles
async function loadProfiles() {
  S.profiles = await S.store.profiles();
  if (!S.profiles.length) {
    const p = {...DEFAULT_PROFILE, id: newId('printer')};
    await S.store.saveProfile(p);
    S.profiles = [p];
  }
  const savedId = await S.store.kv('profileId');
  S.profile = S.profiles.find(p => p.id === savedId) || S.profiles[0];
}

function renderProfile() {
  const sel = $('#profile-select');
  sel.innerHTML = '';
  for (const p of S.profiles) sel.append(new Option(p.name, p.id, false, p.id === S.profile.id));
  const form = $('#profile-form');
  for (const el of form.elements) if (el.name) el.value = S.profile[el.name] ?? DEFAULT_PROFILE[el.name] ?? '';
}

async function saveProfileFromForm(e) {
  e.preventDefault();
  const form = $('#profile-form');
  const p = {...S.profile};
  for (const el of form.elements) {
    if (!el.name) continue;
    p[el.name] = el.type === 'number' ? parseFloat(el.value) : el.value;
  }
  S.profile = p;
  await S.store.saveProfile(p);
  S.profiles = await S.store.profiles();
  renderProfile(); renderParams();
  toast('✓ ' + p.name);
}

async function selectProfile(id) {
  S.profile = S.profiles.find(p => p.id === id) || S.profile;
  await kvSet('profileId', S.profile.id);
  await loadParams();
  renderProfile(); renderParams(); renderLearn();
}

// ---------------------------------------------------------------- trial parameters
async function loadParams() {
  const saved = await S.store.kv('params:' + S.profile.id);
  const base = baselineParams(S.profile, S.settings, S.features || {});
  S.params = {...base};
  if (saved) for (const k of Object.keys(base)) if (saved[k] != null) S.params[k] = saved[k];
}
const saveParams = () => kvSet('params:' + S.profile.id, S.params);

function renderParams() {
  const box = $('#param-editor');
  box.innerHTML = '';
  const space = parameterSpace(S.profile, S.features || {});
  const excluded = S.program?.calId ? CAL_EXCLUDES[S.program.calId] || [] : [];
  for (const [key, def] of Object.entries(space)) {
    if (S.params[key] == null) continue;
    const label = document.createElement('label');
    const span = document.createElement('span');
    span.textContent = localized(def.label) + (excluded.includes(key) ? ' ⨯' : '');
    const input = document.createElement('input');
    Object.assign(input, {type: 'number', min: def.min, max: def.max, step: def.step, value: S.params[key], disabled: excluded.includes(key)});
    if (key.startsWith('shaper_freq')) input.min = 0;
    input.addEventListener('change', () => {
      const v = parseFloat(input.value);
      if (Number.isFinite(v)) { S.params[key] = Math.min(def.max, Math.max(key.startsWith('shaper') && v === 0 ? 0 : def.min, v)); input.value = S.params[key]; saveParams(); }
    });
    label.append(span, input);
    box.append(label);
  }
}

// Parameters actually applied to the current program.
function paramsForProgram() {
  const p = {...S.params};
  for (const k of (S.program?.calId ? CAL_EXCLUDES[S.program.calId] || [] : [])) delete p[k];
  for (const ax of ['x', 'y']) if (!p['shaper_freq_' + ax]) delete p['shaper_freq_' + ax]; // 0 = leave firmware value
  return p;
}

// ---------------------------------------------------------------- connection
async function connect(kind) {
  if (!transportSupport().secure) { toast(t('insecure')); return; }
  try {
    const sim = kind === 'sim' ? new MarlinSimulator({lineDelayMs: 3}) : null;
    const conn = createConnection(kind, sim);
    const printer = wirePrinter(new Printer(conn, {log}));
    await conn.open(parseInt($('#baud').value, 10));
    await finishConnect(printer);
  } catch (e) {
    if (e.name === 'NotFoundError') return;                      // user closed the device picker
    toast('⚠ ' + e.message, 7000);
    try { await S.printer?.close(); } catch (_) {}
    S.printer = null; setStatus('disconnected');
  }
}

function wirePrinter(printer) {
  printer.on('temps', temps => {
    const f = h => h ? `${fmtNum(h.current, 1)} / ${fmtNum(h.target, 0)} °C` : '–';
    $('#t-hotend').textContent = f(temps.hotend); $('#t-bed').textContent = f(temps.bed);
  });
  printer.on('close', () => { S.printer = null; setStatus('disconnected'); });
  printer.on('abort', reason => { toast('⚠ ' + reason, 6000); S.recorder?.addEvent(performance.now(), 'error', {message: reason}); });
  printer.on('error', line => { log('!', line); S.recorder?.addEvent(performance.now(), 'error', {message: line}); });
  return printer;
}

async function finishConnect(printer) {
  S.printer = printer;
  toast(printer.conn.label + '…');
  S.features = await printer.handshake();
  S.settings = printer.settings;
  renderFirmware(printer);
  await loadParams(); renderParams();
  setStatus('connected');
}

// Klipper host on the same phone (or on the LAN when the page itself is served from there).
async function connectKlipper() {
  S.moonrakerUrl = $('#moonraker-url').value.trim() || defaultMoonrakerUrl();
  kvSet('moonrakerUrl', $('#moonraker-url').value.trim());
  try {
    const printer = wirePrinter(new MoonrakerPrinter(new MoonrakerClient(S.moonrakerUrl), {log}));
    await printer.open();
    await finishConnect(printer);
  } catch (e) {
    toast('⚠ ' + e.message, 7000);
    try { await S.printer?.close(); } catch (_) {}
    S.printer = null; setStatus('disconnected');
  }
}

function renderFirmware(printer) {
  const f = printer.features, dl = $('#fw-info');
  const yes = v => (v ? '✓' : '✗');
  const rows = [
    [t('firmware'), f.firmware + (printer.info?.machine ? ` · ${printer.info.machine}` : '')],
    [f.klipper ? 'Host' : 'USB', printer.conn.label],
    ...(f.klipper ? [
      ['max_accel', fmtNum(printer.settings.klipper?.max_accel, 0)],
      ['max_velocity', fmtNum(printer.settings.klipper?.max_velocity, 0)],
      ['square_corner_velocity', fmtNum(printer.settings.klipper?.square_corner_velocity, 1)],
      ['pressure_advance', fmtNum(printer.settings.klipper?.pressure_advance, 3)],
    ] : [
      ['M204', f.accelStyle === 'PRT' ? 'P/R/T' : 'S'],
      ['M205', f.jerkStyle === 'junction' ? 'Junction deviation' : 'Jerk'],
      ['Linear Advance (M900)', yes(f.linearAdvance)],
      ['Input shaping (M593)', yes(f.inputShaping)],
      ['EEPROM', yes(f.eeprom)],
    ]),
  ];
  dl.innerHTML = '';
  for (const [k, v] of rows) { const dt = document.createElement('dt'); dt.textContent = k; const dd = document.createElement('dd'); dd.textContent = v; dl.append(dt, dd); }
  dl.hidden = false;
}

async function sendLines(text) {
  if (!S.printer) return;
  for (const line of text.split('\n')) if (line.trim()) await S.printer.send(line).catch(e => toast(e.message));
}

// ---------------------------------------------------------------- programs
async function setProgram(program) {
  program.hash = await hashText(program.lines.join('\n'));
  S.program = program;
  $('#program-name').textContent = program.name;
  $('#program-meta').textContent = `· ${program.lines.length} lines · ~${fmtTime(estimateSeconds(program.lines))}`;
  $('#btn-download').disabled = false;
  if (program.kind === 'file') {
    const trials = await S.store.trials(S.profile.id);
    if (!trials.some(tr => tr.source?.hash === program.hash)) {
      // First trial with this file: start from the file's own values.
      const fv = fileValues(program.lines);
      for (const [k, v] of Object.entries(fv)) if (v != null && k in S.params) S.params[k] = v;
      saveParams();
    }
  }
  renderParams();
  setStatus(S.printer ? 'connected' : 'disconnected');
}

async function loadFile(file) {
  const text = await file.text();
  await setProgram({kind: 'file', name: file.name, lines: text.split(/\r?\n/)});
}

function transformed() {
  return applyTrial(S.program.lines, paramsForProgram(),
    {features: S.features || {}, baseline: S.settings, limits: S.profile});
}

function download(name, text, type = 'text/plain') {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([text], {type}));
  a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}

// ---------------------------------------------------------------- printing a trial
function diffParams(parent, params) {
  if (!parent) return null;
  const changed = Object.keys(params).filter(k => parent.params?.[k] != null && params[k] !== parent.params[k]);
  return changed.length === 1 ? {param: changed[0], from: parent.params[changed[0]], to: params[changed[0]]} : changed.length ? {multiple: changed} : null;
}

// One printer.csv row: Moonraker gives the full status; the USB host knows temperatures,
// the last commanded position/feed rate and the stream progress.
function printerSample() {
  const p = S.printer;
  if (!p) return null;
  if (p.features?.klipper) return statusRow(p.status, p.job?.layer ?? null);
  const h = p.temps.hotend || {}, b = p.temps.bed || {}, pos = p.job?.pos || {};
  return {hotend: h.current, hotend_target: h.target, hotend_power: h.power, bed: b.current, bed_target: b.target, bed_power: b.power,
    x: pos.x, y: pos.y, z: pos.z, speed_mm_s: pos.f != null ? pos.f / 60 : null, progress: S.jobProgress,
    layer: p.job?.layer ?? null, state: p.job ? (p.job.paused ? 'paused' : 'printing') : 'standby'};
}

async function savePhoto(trial, name) {
  if (!S.camera) return;
  const blob = await S.camera.snapshot();
  if (!blob) return;
  const key = `${trial.id}/photos/${name}.jpg`;
  await S.store.saveMedia(key, blob);
  trial.media.push(key);
  S.recorder?.addPhoto(performance.now(), `photos/${name}.jpg`);
}

async function startTrial() {
  if (!S.printer || !S.program || S.printer.job) return;
  if (!confirm(t('confirm_start'))) return;
  await runTrial({attach: false});
}

// Record a print that is running (or about to start) on Klipper, e.g. launched from
// Mainsail/Fluidd or by the KlipperLearn bed-trial tool on a computer.
async function recordCurrentJob() {
  if (!S.printer?.features?.klipper || S.printer.job) return;
  await runTrial({attach: true});
}

async function startSensors(rec) {
  const record = !!rec;
  try {
    if ($('#use-camera').checked || record) { S.camera = new Camera($('#print-video')); await S.camera.start(); $('#print-video').hidden = false; }
  } catch (e) { S.camera = null; toast('⚠ ' + e.message); }
  try {
    if ($('#use-mic').checked || record) {
      S.mic = new Microphone(); await S.mic.start();
      if (rec) await S.mic.tap((block, rate, ms) => rec.addAudio(ms, block, rate));
    }
  } catch (e) { S.mic = null; toast('⚠ ' + e.message); }
  try {
    if (($('#use-motion').checked || record) && sensorSupport().motion) {
      S.motion = new MotionRecorder();
      if (rec) S.motion.onSample = (ms, x, y, z) => rec.addMotion(ms, x, y, z);
      await S.motion.start();
    }
  } catch (e) { S.motion = null; toast('⚠ ' + e.message); }
  await S.wake.acquire();
}

async function stopSensors(trial) {
  if (S.mic) {
    const a = analyzeAudio(S.mic.take(), S.mic.sampleRate);
    if (a.ok) Object.assign(trial.measured, {clicks_per_min: a.clicksPerMin, audio_rms: a.rms, audio_centroid_hz: a.centroidHz});
    S.mic.stop(); S.mic = null;
  }
  if (S.motion) {
    const m = analyzeMotion(S.motion.stop());
    if (m.ok) Object.assign(trial.measured, {motion_rate_hz: m.sampleRateHz,
      motion_peak_hz: {x: m.axes.x.peakHz, y: m.axes.y.peakHz, z: m.axes.z.peakHz}, motion_rms: m.axes.x.rms + m.axes.y.rms});
    S.motion = null;
  }
  if (S.camera) {
    const frame = S.camera.frame(640);
    if (frame) trial.measured.sharpness = sharpness(frame.getContext('2d').getImageData(0, 0, frame.width, frame.height));
    await savePhoto(trial, 'final');
    S.camera.stop(); S.camera = null; $('#print-video').hidden = true;
  }
  await S.wake.release();
}

async function runTrial({attach}) {
  const trials = await S.store.trials(S.profile.id);
  const program = attach ? {kind: 'external', name: S.printer.status?.print_stats?.filename || 'klipper-job', hash: null} : S.program;
  const parent = program.hash ? trials.filter(tr => tr.source?.hash === program.hash).at(-1) || null : null;
  const params = attach ? {} : paramsForProgram();
  const {lines, report} = attach ? {lines: null, report: {warnings: []}} : transformed();
  const trial = {
    id: newId('trial'), printerId: S.profile.id, createdAt: Date.now(),
    source: {kind: program.kind, name: program.name, hash: program.hash, calId: program.calId || null,
      values: program.values || null, param: program.param || null, speed: program.speed || null},
    params, parentId: parent?.id || null, changed: attach ? null : diffParams(parent, params), baseline: !attach && !parent,
    firmware: S.features?.firmware || null, host: S.features?.klipper ? 'moonraker' : 'usb',
    measured: {}, human: null, media: [],
  };
  const warn = $('#job-warnings');
  warn.hidden = !report.warnings.length; warn.textContent = report.warnings.join(' ');

  const rec = S.recorder = $('#use-dataset').checked ? new TrialRecorder({t0: performance.now()}) : null;
  await startSensors(rec);
  const every = Math.max(1, parseInt($('#camera-every').value, 10) || 10);

  setStatus('printing');
  $('#job').hidden = false; $('#btn-pause').hidden = false; $('#btn-cancel').hidden = false;
  $('#btn-pause').textContent = t('pause');
  $('#job-sensors').textContent = '';
  if (attach) toast(t('waiting_job'), 6000);
  const started = Date.now();
  S.jobProgress = 0;
  let midTaken = false, lastState = null;
  const sample = () => {
    const row = printerSample();
    if (row) {
      rec.addPrinter(performance.now(), row);
      if (row.state !== lastState && lastState && ['paused', 'printing'].includes(row.state)) rec.addEvent(performance.now(), row.state === 'paused' ? 'pause' : 'resume');
      lastState = row.state;
    }
    const sum = rec.summary();
    $('#job-sensors').textContent = `📈 ${sum.accel_rows} · 🔊 ${sum.audio_frames} · ${t('knocks')} ${sum.knocks_accel + sum.knocks_audio} · ${t('jams')} ${sum.jam_suspects} · 📷 ${sum.photos}`;
  };
  if (rec) sample();
  const sampler = rec ? setInterval(sample, 1000) : null;
  const clock = setInterval(() => { $('#job-time').textContent = fmtTime((Date.now() - started) / 1000); }, 1000);
  const hooks = {
    name: program.name,
    onProgress: (f) => {
      S.jobProgress = f;
      $('#job-progress').value = f; $('#job-pct').textContent = `${Math.floor(f * 100)} %`;
      if (!midTaken && f >= 0.5) { midTaken = true; savePhoto(trial, 'mid'); }
    },
    onLayer: async (n) => {
      $('#job-layer').textContent = n;
      if (S.camera && n > 0 && n % every === 0) await savePhoto(trial, `L${String(n).padStart(3, '0')}`);
    },
  };
  let completed = false;
  try {
    completed = attach ? await S.printer.followJob(hooks) : await S.printer.runJob(lines, hooks);
  } catch (e) { toast('⚠ ' + e.message, 6000); rec?.addEvent(performance.now(), 'error', {message: e.message}); }
  clearInterval(clock); clearInterval(sampler);
  if (rec) sample();
  if (!completed) rec?.addEvent(performance.now(), 'cancel', {});

  trial.measured.completed = completed;
  trial.measured.seconds = (Date.now() - started) / 1000;
  await stopSensors(trial);
  if (rec) {
    trial.sensors = rec.summary();
    Object.assign(trial.measured, {knocks: trial.sensors.knocks_accel + trial.sensors.knocks_audio, jam_suspects: trial.sensors.jam_suspects});
    await S.store.saveMedia(`${trial.id}/dataset`, {files: rec.parts()});
    trial.media.push(`${trial.id}/dataset`);
  }
  S.recorder = null; S.jobProgress = null;
  await S.store.saveTrial(trial);
  S.currentTrial = trial;
  await kvSet('lastTrial:' + S.profile.id, trial.id);
  $('#btn-pause').hidden = true; $('#btn-cancel').hidden = true;
  setStatus(S.printer ? 'connected' : 'disconnected');
  toast(completed ? '✓' : '✗ ' + t('cancel'));
  showTab('learn');
}

async function togglePause() {
  if (!S.printer?.job) return;
  if (S.printer.job.paused) { await S.printer.resume(); $('#btn-pause').textContent = t('pause'); }
  else { await S.printer.pause(); $('#btn-pause').textContent = t('resume'); }
}

// ---------------------------------------------------------------- calibrations
function renderCalibrations() {
  const list = $('#cal-list');
  list.innerHTML = '';
  for (const [id, cal] of Object.entries(CALIBRATIONS)) {
    const item = document.createElement('div');
    item.className = 'cal-item';
    const h = document.createElement('h3'); h.textContent = localized(cal.title);
    const p = document.createElement('p'); p.className = 'muted small'; p.textContent = localized(cal.help);
    const grid = document.createElement('div'); grid.className = 'grid';
    const opts = cal.defaults(S.profile);
    const inputs = {};
    for (const [k, v] of Object.entries(opts)) {
      const label = document.createElement('label');
      const span = document.createElement('span'); span.textContent = t(k) !== k ? t(k) : k;
      const input = document.createElement('input'); input.type = 'number'; input.step = 'any'; input.value = v;
      inputs[k] = input; label.append(span, input); grid.append(label);
    }
    const btn = document.createElement('button'); btn.className = 'primary'; btn.textContent = t('send_to_print');
    btn.addEventListener('click', async () => {
      const o = Object.fromEntries(Object.entries(inputs).map(([k, el]) => [k, parseFloat(el.value)]));
      const out = cal.generate(S.profile, o);
      await setProgram({kind: 'calibration', calId: id, name: localized(cal.title), lines: out.gcode, values: out.values,
        param: cal.param, speed: out.speed || o.speed || null});
      showTab('print');
    });
    item.append(h, p, grid, btn);
    list.append(item);
  }
}

async function applyBand() {
  const tr = S.currentTrial;
  const v = parseFloat($('#band-select').value);
  if (!tr || !Number.isFinite(v)) return;
  const param = tr.source.param;
  if (param === 'speed_mm_s') { S.profile.print_mm_s = v; await S.store.saveProfile(S.profile); renderProfile(); }
  else if (param && param in S.params) { S.params[param] = v; saveParams(); renderParams(); }
  tr.human = tr.human || {};
  tr.human.best_band = v;
  await S.store.saveTrial(tr);
  toast(`✓ ${param} = ${v}`);
}

// ---------------------------------------------------------------- measure tab
const roi = {start: null, rect: null};
function setupRoi() {
  const canvas = $('#roi-canvas'), video = $('#measure-video');
  const pos = e => { const r = canvas.getBoundingClientRect(); return {x: (e.clientX - r.left) / r.width, y: (e.clientY - r.top) / r.height}; };
  const draw = () => {
    canvas.width = canvas.clientWidth; canvas.height = canvas.clientHeight;
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (!roi.rect) return;
    ctx.strokeStyle = '#3cc7bf'; ctx.lineWidth = 2;
    ctx.strokeRect(roi.rect.x * canvas.width, roi.rect.y * canvas.height, roi.rect.w * canvas.width, roi.rect.h * canvas.height);
  };
  canvas.addEventListener('pointerdown', e => { roi.start = pos(e); canvas.setPointerCapture(e.pointerId); });
  canvas.addEventListener('pointermove', e => {
    if (!roi.start) return;
    const p = pos(e);
    roi.rect = {x: Math.min(p.x, roi.start.x), y: Math.min(p.y, roi.start.y), w: Math.abs(p.x - roi.start.x), h: Math.abs(p.y - roi.start.y)};
    draw();
  });
  canvas.addEventListener('pointerup', () => { roi.start = null; });
  video.addEventListener('loadedmetadata', draw);
}

async function toggleMeasureCamera() {
  if (S.measureCamera) { S.measureCamera.stop(); S.measureCamera = null; $('#btn-camera').textContent = t('start_camera'); $('#btn-torch').hidden = true; return; }
  try {
    S.measureCamera = new Camera($('#measure-video'));
    await S.measureCamera.start();
    $('#btn-camera').textContent = t('stop_camera');
    $('#btn-torch').hidden = !S.measureCamera.torchSupported;
  } catch (e) { S.measureCamera = null; toast('⚠ ' + e.message); }
}

function analyzeRoi() {
  if (!S.measureCamera || !roi.rect || roi.rect.w < 0.05) { toast('ROI?'); return; }
  const frame = S.measureCamera.frame(1280);
  const W = frame.width, H = frame.height;
  const r = {x: Math.round(roi.rect.x * W), y: Math.round(roi.rect.y * H), w: Math.max(16, Math.round(roi.rect.w * W)), h: Math.max(2, Math.round(roi.rect.h * H))};
  const img = frame.getContext('2d').getImageData(0, 0, W, H);
  const mm = parseFloat($('#roi-mm').value), v = parseFloat($('#roi-speed').value);
  const res = analyzeRinging(img, r, {mmPerPx: mm / r.w, speedMmS: v});
  const axis = $('#roi-axis').value;
  let text = `λ ≈ ${fmtNum(res.wavelengthMm)} mm · contraste ${fmtNum(res.contrast, 3)}`;
  if (res.frequencyHz) {
    text += ` · f ≈ ${fmtNum(res.frequencyHz, 1)} Hz (${Math.round(res.prominence * 100)} %)`;
    if (res.prominence > 0.15) { S.measuredShaper[axis] = res.frequencyHz; kvSet('shaper:' + S.profile.id, S.measuredShaper); }
  }
  $('#ringing-result').textContent = text;
}

function updateManual() {
  const f = ringingFrequency(parseFloat($('#mr-v').value), parseFloat($('#mr-n').value), parseFloat($('#mr-d').value));
  $('#manual-result').textContent = f ? `f = v·N/D ≈ ${fmtNum(f, 1)} Hz` : '–';
  return f;
}

function useManualShaper() {
  const f = updateManual();
  if (!f) return;
  const axis = $('#mr-axis').value;
  S.measuredShaper[axis] = f; kvSet('shaper:' + S.profile.id, S.measuredShaper);
  if (('shaper_freq_' + axis) in S.params) { S.params['shaper_freq_' + axis] = Math.round(f); saveParams(); renderParams(); }
  toast(`✓ ${axis.toUpperCase()}: ${fmtNum(f, 1)} Hz`);
}

async function runSweep() {
  if (!S.printer || S.printer.job) return;
  const axis = $('#sw-axis').value;
  const sweep = resonanceSweep(S.profile, {axis, fromHz: +$('#sw-from').value, toHz: +$('#sw-to').value, accel: +$('#sw-accel').value});
  if (!confirm(t('resonance_help'))) return;
  const motion = new MotionRecorder();
  try { await motion.start(); } catch (e) { toast('⚠ ' + e.message); return; }
  const segments = [];
  let mark = 0;
  setStatus('printing');
  try {
    await S.printer.runJob(sweep.gcode, {onMarker: line => {
      const m = line.match(/^;KL_FREQ(_END)? ([\d.]+)/);
      if (!m) return;
      if (!m[1]) mark = motion.mark();
      else segments.push({freq: parseFloat(m[2]), samples: motion.since(mark)});
    }});
    for (const c of restoreCommands({M204: S.settings.M204}, S.features)) await S.printer.send(c);
  } catch (e) { toast('⚠ ' + e.message); }
  const all = motion.stop();
  setStatus(S.printer ? 'connected' : 'disconnected');
  const res = resonanceFromSweep(segments);
  const rate = analyzeMotion(all);
  $('#motion-rate').textContent = rate.ok ? `${fmtNum(rate.sampleRateHz, 0)} Hz` : '–';
  if (!res.ok) { $('#sweep-result').textContent = '✗ ' + (rate.ok ? '' : t('motion_rate') + ' ?'); return; }
  $('#sweep-result').textContent = `${axis}: pico ≈ ${res.peakHz} Hz (×${fmtNum(res.peakRatio, 1)})`;
  if (res.peakRatio > 1.5) { S.measuredShaper[axis.toLowerCase()] = res.peakHz; kvSet('shaper:' + S.profile.id, S.measuredShaper); }
  drawChart($('#sweep-chart'), res.points);
}

function drawChart(canvas, points) {
  canvas.hidden = false;
  const ctx = canvas.getContext('2d'), W = canvas.width, H = canvas.height, pad = 24;
  const style = getComputedStyle(document.documentElement);
  ctx.clearRect(0, 0, W, H);
  const maxA = Math.max(...points.map(p => p.amplitude)) || 1;
  const minF = points[0].freq, maxF = points.at(-1).freq || minF + 1;
  const x = f => pad + (f - minF) / (maxF - minF || 1) * (W - 2 * pad), y = a => H - pad - a / maxA * (H - 2 * pad);
  ctx.strokeStyle = style.getPropertyValue('--accent'); ctx.lineWidth = 2; ctx.beginPath();
  points.forEach((p, i) => (i ? ctx.lineTo(x(p.freq), y(p.amplitude)) : ctx.moveTo(x(p.freq), y(p.amplitude))));
  ctx.stroke();
  ctx.fillStyle = style.getPropertyValue('--muted'); ctx.font = '12px system-ui';
  ctx.fillText(`${minF} Hz`, pad, H - 6); ctx.fillText(`${maxF} Hz`, W - pad - 40, H - 6);
}

// ---------------------------------------------------------------- learn tab
async function renderLearn() {
  const trials = await S.store.trials(S.profile.id);
  if (!S.currentTrial) {
    const lastId = await S.store.kv('lastTrial:' + S.profile.id);
    S.currentTrial = trials.find(tr => tr.id === lastId) || trials.at(-1) || null;
  }
  renderHistory(trials);
  const tr = S.currentTrial;
  const form = $('#rating-form');
  if (!tr) { $('#rate-target').textContent = t('no_trials'); form.hidden = true; $('#rec-card').hidden = true; return; }
  $('#rate-target').textContent = `${tr.source.name} · ${new Date(tr.createdAt).toLocaleString()}` +
    (tr.changed?.param ? ` · ${tr.changed.param}: ${tr.changed.from} → ${tr.changed.to}` : '');
  form.hidden = false;
  // ratings
  for (const k of ['overall', 'surface', 'dimensions']) { form.elements[k].value = tr.human?.[k] ?? 3; form.elements[k].nextElementSibling.value = form.elements[k].value; }
  form.elements.notes.value = tr.human?.notes || '';
  form.elements.outcome.value = tr.human?.outcome || '';
  const dl = $('#defect-list');
  dl.innerHTML = '';
  for (const [key, def] of Object.entries(DEFECTS)) {
    const label = document.createElement('label');
    const span = document.createElement('span'); span.textContent = localized(def.label);
    const input = Object.assign(document.createElement('input'), {type: 'range', min: 0, max: 3, value: tr.human?.defects?.[key] ?? 0, name: 'defect_' + key});
    const out = document.createElement('output'); out.value = input.value;
    input.addEventListener('input', () => { out.value = input.value; });
    label.append(span, input, out); dl.append(label);
  }
  // calibration band picker
  const values = tr.source.values || [];
  $('#band-pick').hidden = !values.length || !tr.source.param;
  const bs = $('#band-select'); bs.innerHTML = '';
  values.forEach((v, i) => bs.append(new Option(`${i + 1}: ${v}`, v, false, tr.human?.best_band === v)));
  // measured summary
  const m = tr.measured || {};
  const md = $('#measured-summary'); md.innerHTML = '';
  const rows = [['⏱', m.seconds ? fmtTime(m.seconds) : '–'], ['✓', m.completed ? '✓' : '✗'],
    ['🔊 clicks/min', fmtNum(m.clicks_per_min, 1)], ['📈 Hz', m.motion_peak_hz ? `x ${fmtNum(m.motion_peak_hz.x, 1)} · y ${fmtNum(m.motion_peak_hz.y, 1)} (${fmtNum(m.motion_rate_hz, 0)} Hz)` : '–'],
    ['📷', m.sharpness != null ? fmtNum(m.sharpness, 0) : '–']];
  if (tr.sensors) rows.push([t('ds_summary'), `${t('knocks')} ${tr.sensors.knocks_accel + tr.sensors.knocks_audio} · ${t('jams')} ${tr.sensors.jam_suspects} · ${t('clips')} ${tr.sensors.clips} · 📷 ${tr.sensors.photos}`]);
  for (const [k, v] of rows) { const dt = document.createElement('dt'); dt.textContent = k; const dd = document.createElement('dd'); dd.textContent = v; md.append(dt, dd); }
  if (tr.human) showRecommendation(tr, trials); else { $('#rec-card').hidden = true; }
}

function renderHistory(trials) {
  const tbody = $('#history tbody');
  tbody.innerHTML = '';
  const refs = {};
  trials.forEach((tr, i) => {
    const ref = refs[tr.source?.hash] || (refs[tr.source?.hash] = trials.find(x => x.source?.hash === tr.source?.hash && x.baseline) || tr);
    const s = tr.human ? scoreTrial(tr, ref, S.goal) : null;
    const row = document.createElement('tr');
    const delta = tr.changed?.param ? `${tr.changed.param} ${tr.changed.from}→${tr.changed.to}` : tr.changed?.multiple ? tr.changed.multiple.join(', ') : (tr.baseline ? 'base' : '');
    for (const v of [i + 1, tr.source?.name || '', delta, s ? fmtNum(s.measured) : '–', s?.human != null ? fmtNum(s.human) : '–', s?.total != null ? fmtNum(s.total) : '–']) {
      const td = document.createElement('td'); td.textContent = v; row.append(td);
    }
    row.addEventListener('click', () => { S.currentTrial = tr; renderLearn(); window.scrollTo(0, 0); });
    tbody.append(row);
  });
}

async function saveRating(e) {
  e.preventDefault();
  const tr = S.currentTrial;
  if (!tr) return;
  const form = $('#rating-form');
  const defects = {};
  for (const key of Object.keys(DEFECTS)) { const v = parseInt(form.elements['defect_' + key].value, 10); if (v) defects[key] = v; }
  tr.human = {...(tr.human || {}), overall: +form.elements.overall.value, surface: +form.elements.surface.value,
    dimensions: +form.elements.dimensions.value, defects, notes: form.elements.notes.value,
    outcome: form.elements.outcome.value || null, labeled_by: 'human', labeled_at: new Date().toISOString()};
  const trials = await S.store.trials(S.profile.id);
  const ref = trials.find(x => x.source?.hash === tr.source?.hash && x.baseline) || tr;
  tr.score = scoreTrial(tr, ref, S.goal);
  await S.store.saveTrial(tr);
  toast('✓ ' + t('score') + ' ' + fmtNum(tr.score.total));
  renderLearn();
}

function showRecommendation(tr, trials) {
  const rec = recommend({last: tr, history: trials, profile: S.profile, features: S.features || {}, goal: S.goal, measuredShaper: S.measuredShaper});
  S.rec = rec; S.chosen = rec.decision;
  $('#rec-card').hidden = false;
  $('#rec-reason').textContent = {revert: t('reason_revert'), fix_defect: t('reason_fix'), explore: t('reason_explore'), converged: t('converged')}[rec.reason] || '';
  const list = $('#rec-list'); list.innerHTML = '';
  const space = parameterSpace(S.profile, S.features || {});
  for (const c of rec.candidates) {
    const row = document.createElement('label'); row.className = 'rec' + (c === S.chosen ? ' chosen' : '');
    const radio = Object.assign(document.createElement('input'), {type: 'radio', name: 'cand', checked: c === S.chosen});
    radio.addEventListener('change', () => { S.chosen = c; $$('.rec').forEach(r => r.classList.remove('chosen')); row.classList.add('chosen'); });
    const text = document.createElement('span');
    text.textContent = c.parameter ? `${localized(space[c.parameter]?.label) || c.parameter}: ${tr.params?.[c.parameter] ?? '–'} → ${c.value}` : t('converged');
    if (getLanguage() === 'en' && c.parameter) {
      const small = document.createElement('small'); small.className = 'muted'; small.textContent = c.description;
      text.append(document.createElement('br'), small);
    }
    row.append(radio, text); list.append(row);
  }
  $('#btn-ask-jev').hidden = !S.advisorUrl;
  $('#jev-result').textContent = '';
}

async function askJev() {
  if (!S.rec || !S.currentTrial || !S.advisorUrl) return;
  $('#jev-result').textContent = '…';
  try {
    const trials = await S.store.trials(S.profile.id);
    const req = buildAdvisorRequest({trial: S.currentTrial, history: trials, candidates: S.rec.candidates, goal: S.goal, features: S.features});
    const res = parseAdvisorResponse(await askAdvisor(S.advisorUrl, req), S.rec.candidates);
    S.chosen = res.candidate;
    const idx = S.rec.candidates.indexOf(res.candidate);
    $$('.rec').forEach((r, i) => { r.classList.toggle('chosen', i === idx); r.querySelector('input').checked = i === idx; });
    $('#jev-result').textContent = `JEV → ${res.candidate.id} (${fmtNum(res.confidence)}; provenance=${res.provenance})`;
  } catch (e) { $('#jev-result').textContent = '⚠ ' + e.message; }
}

async function useNext() {
  if (!S.currentTrial || !S.chosen) return;
  S.params = {...S.params, ...nextParams(S.currentTrial.params, S.chosen)};
  saveParams(); renderParams();
  toast(S.chosen.parameter ? `✓ ${S.chosen.parameter} = ${S.chosen.value}` : '✓');
  showTab('print');
}

// ---------------------------------------------------------------- settings / data
async function exportData() {
  const data = await S.store.exportAll();
  download(`klipperlearn-${new Date().toISOString().slice(0, 10)}.json`, JSON.stringify(data, null, 2), 'application/json');
}
// Dataset ZIP (klipperlearn-dataset/v1): every trial of every profile with its recorded files.
async function exportDataset() {
  const trials = await S.store.trials();
  if (!trials.length) { toast(t('ds_empty')); return; }
  const profiles = Object.fromEntries(S.profiles.map(p => [p.id, p]));
  const items = [];
  for (const tr of trials) {
    const extra = {};
    for (const key of tr.media || []) {
      const v = await S.store.media(key);
      if (!v) continue;
      if (key.endsWith('/dataset')) Object.assign(extra, v.files || {});
      else if (v instanceof Blob) {
        const rel = key.slice(tr.id.length + 1);
        extra[rel.startsWith('photos/') ? rel : `photos/${rel}.jpg`] = new Uint8Array(await v.arrayBuffer());
      }
    }
    items.push({trial: tr, extra, profile: profiles[tr.printerId]});
  }
  const zip = buildDatasetZip(items, {appVersion: APP_VERSION});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([zip], {type: 'application/zip'}));
  a.download = `klipperlearn-dataset-${new Date().toISOString().slice(0, 10)}.zip`; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 10000);
  toast(`✓ ${items.length}`);
}

async function importData(file) {
  try { const r = await S.store.importAll(JSON.parse(await file.text())); toast(`✓ ${r.profiles} / ${r.trials}`); await loadProfiles(); renderProfile(); renderLearn(); }
  catch (e) { toast('⚠ ' + e.message); }
}

// ---------------------------------------------------------------- init
function bind() {
  $$('.tabs button').forEach(b => b.addEventListener('click', () => showTab(b.dataset.tab)));
  $('#btn-connect').addEventListener('click', () => connect('auto'));
  $('#btn-sim').addEventListener('click', () => connect('sim'));
  $('#btn-disconnect').addEventListener('click', async () => { await S.printer?.close(); S.printer = null; setStatus('disconnected'); });
  $('#estop').addEventListener('click', () => S.printer?.emergencyStop().then(() => toast('M112')));
  $$('[data-gcode]').forEach(b => b.addEventListener('click', () => sendLines(b.dataset.gcode)));
  $('[data-cmd-hotend]').addEventListener('click', () => sendLines(`M104 S${Math.min(+$('#set-hotend').value || 0, S.profile.max_hotend_c)}`));
  $('[data-cmd-bed]').addEventListener('click', () => sendLines(`M140 S${Math.min(+$('#set-bed').value || 0, S.profile.max_bed_c)}`));
  $('#term-form').addEventListener('submit', e => { e.preventDefault(); const v = $('#term-input').value; $('#term-input').value = ''; sendLines(v).then(() => { S.logLines.push(''); }); $('#log').closest('details').open = true; });
  $('#profile-form').addEventListener('submit', saveProfileFromForm);
  $('#profile-select').addEventListener('change', e => selectProfile(e.target.value));
  $('#btn-new-profile').addEventListener('click', async () => {
    const p = {...DEFAULT_PROFILE, id: newId('printer'), name: `${t('p_name')} ${S.profiles.length + 1}`};
    await S.store.saveProfile(p); S.profiles = await S.store.profiles(); await selectProfile(p.id);
  });
  $('#file-input').addEventListener('change', e => e.target.files[0] && loadFile(e.target.files[0]));
  $('#btn-download').addEventListener('click', () => S.program && download(S.program.name.replace(/\.[^.]*$/, '') + '-klipperlearn.gcode', transformed().lines.join('\n')));
  $('#btn-start').addEventListener('click', startTrial);
  $('#btn-record-current').addEventListener('click', recordCurrentJob);
  $('#btn-klipper').addEventListener('click', connectKlipper);
  $('#btn-export-dataset').addEventListener('click', exportDataset);
  $('#btn-pause').addEventListener('click', togglePause);
  $('#btn-cancel').addEventListener('click', () => S.printer?.cancel());
  $('#btn-camera').addEventListener('click', toggleMeasureCamera);
  let torch = false;
  $('#btn-torch').addEventListener('click', () => { torch = !torch; S.measureCamera?.torch(torch); });
  $('#btn-analyze').addEventListener('click', analyzeRoi);
  for (const id of ['#mr-n', '#mr-d', '#mr-v']) $(id).addEventListener('input', updateManual);
  $('#btn-manual-shaper').addEventListener('click', useManualShaper);
  $('#btn-sweep').addEventListener('click', runSweep);
  $('#rating-form').addEventListener('submit', saveRating);
  $$('#rating-form .stars input[type=range]').forEach(i => i.addEventListener('input', () => { i.nextElementSibling.value = i.value; }));
  $('#btn-apply-band').addEventListener('click', applyBand);
  $('#btn-ask-jev').addEventListener('click', askJev);
  $('#btn-use-next').addEventListener('click', useNext);
  $('#goal').addEventListener('change', e => { S.goal = e.target.value; kvSet('goal', S.goal); renderLearn(); });
  $('#lang').addEventListener('change', e => { setLanguage(e.target.value); kvSet('lang', e.target.value); applyTranslations(); renderCalibrations(); renderParams(); renderLearn(); setStatus(S.printer ? 'connected' : 'disconnected'); });
  $('#advisor-url').addEventListener('change', e => { S.advisorUrl = e.target.value.trim(); kvSet('advisorUrl', S.advisorUrl); $('#btn-ask-jev').hidden = !S.advisorUrl; });
  $('#btn-export').addEventListener('click', exportData);
  $('#import-input').addEventListener('change', e => e.target.files[0] && importData(e.target.files[0]));
  window.addEventListener('beforeinstallprompt', e => { e.preventDefault(); S.installPrompt = e; $('#btn-install').hidden = false; });
  $('#btn-install').addEventListener('click', () => S.installPrompt?.prompt());
  window.addEventListener('beforeunload', e => { if (S.printer?.job) { e.preventDefault(); e.returnValue = ''; } });
  setupRoi();
  setInterval(() => { if (S.mic) $('#mic-level').textContent = fmtNum(S.mic.level(), 3); }, 500);
}

async function init() {
  S.store = await openStore();
  setLanguage(detectLanguage(await S.store.kv('lang')));
  applyTranslations();
  $('#lang').value = getLanguage();
  S.goal = (await S.store.kv('goal')) || 'balanced'; $('#goal').value = S.goal;
  S.advisorUrl = (await S.store.kv('advisorUrl')) || ''; $('#advisor-url').value = S.advisorUrl;
  $('#moonraker-url').value = (await S.store.kv('moonrakerUrl')) || '';
  $('#moonraker-url').placeholder = defaultMoonrakerUrl();
  await loadProfiles();
  S.measuredShaper = (await S.store.kv('shaper:' + S.profile.id)) || {};
  await loadParams();
  const support = transportSupport();
  const warn = $('#transport-warning');
  if (!support.secure) { warn.textContent = t('insecure'); warn.hidden = false; }
  else if (!support.webSerial && !support.webUsb) { warn.textContent = t('no_transport'); warn.hidden = false; $('#btn-connect').disabled = true; }
  if (!sensorSupport().motion) $('#use-motion').disabled = true;
  bind();
  renderProfile(); renderParams(); renderCalibrations();
  setStatus('disconnected');
  if ('serviceWorker' in navigator && window.isSecureContext) navigator.serviceWorker.register('sw.js').catch(() => {});
  if (S.store.volatile) toast('⚠ IndexedDB');
}

init().catch(e => { console.error(e); toast('⚠ ' + e.message, 8000); });
