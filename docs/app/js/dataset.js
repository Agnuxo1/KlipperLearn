// SPDX-License-Identifier: GPL-3.0-or-later
// Training dataset recorder (klipperlearn-dataset/v1). Every trial becomes one folder with
// the printer telemetry, phone sensor streams, detected events, photos and human labels,
// plus one line in manifest.jsonl. Pure logic: no DOM, so it runs in Node tests as well.
//
//   dataset/manifest.jsonl
//   dataset/trials/<trial_id>/{meta.json, gcode_params.json, printer.csv, accel.csv,
//     audio_features.csv, audio_events/*.wav, photos/*.jpg, events.jsonl, labels.json}
import {fft} from './analysis.js';

export const DATASET_SCHEMA = 'klipperlearn-dataset/v1';
export const AUDIO_BANDS_HZ = [0, 500, 2000, 6000, Infinity];
const CLIP_RATE = 16000;

// ---------------------------------------------------------------- encoders
const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; }
  return t;
})();

export function crc32(bytes) {
  let c = 0xffffffff;
  for (let i = 0; i < bytes.length; i++) c = CRC_TABLE[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

const enc = new TextEncoder();
const asBytes = d => (typeof d === 'string' ? enc.encode(d) : d instanceof Uint8Array ? d : new Uint8Array(d));

// Uncompressed ("stored") ZIP: photos and WAV clips barely compress, and a store-only writer
// stays small, dependency-free and readable by every unzip tool and datasets library.
export function zipStore(files, date = new Date()) {
  const dosTime = (date.getHours() << 11) | (date.getMinutes() << 5) | (date.getSeconds() >> 1);
  const dosDate = ((date.getFullYear() - 1980) << 9) | ((date.getMonth() + 1) << 5) | date.getDate();
  const locals = [], centrals = [];
  let offset = 0;
  for (const f of files) {
    const name = enc.encode(f.path), data = asBytes(f.data), crc = crc32(data);
    const head = new DataView(new ArrayBuffer(30));
    head.setUint32(0, 0x04034b50, true); head.setUint16(4, 20, true); head.setUint16(6, 0x0800, true);
    head.setUint16(8, 0, true); head.setUint16(10, dosTime, true); head.setUint16(12, dosDate, true);
    head.setUint32(14, crc, true); head.setUint32(18, data.length, true); head.setUint32(22, data.length, true);
    head.setUint16(26, name.length, true); head.setUint16(28, 0, true);
    locals.push(new Uint8Array(head.buffer), name, data);
    const cen = new DataView(new ArrayBuffer(46));
    cen.setUint32(0, 0x02014b50, true); cen.setUint16(4, 20, true); cen.setUint16(6, 20, true); cen.setUint16(8, 0x0800, true);
    cen.setUint16(10, 0, true); cen.setUint16(12, dosTime, true); cen.setUint16(14, dosDate, true);
    cen.setUint32(16, crc, true); cen.setUint32(20, data.length, true); cen.setUint32(24, data.length, true);
    cen.setUint16(28, name.length, true); cen.setUint32(42, offset, true);
    centrals.push(new Uint8Array(cen.buffer), name);
    offset += 30 + name.length + data.length;
  }
  const cenSize = centrals.reduce((s, b) => s + b.length, 0);
  const end = new DataView(new ArrayBuffer(22));
  end.setUint32(0, 0x06054b50, true); end.setUint16(8, files.length, true); end.setUint16(10, files.length, true);
  end.setUint32(12, cenSize, true); end.setUint32(16, offset, true);
  const parts = [...locals, ...centrals, new Uint8Array(end.buffer)];
  const out = new Uint8Array(parts.reduce((s, b) => s + b.length, 0));
  let p = 0;
  for (const b of parts) { out.set(b, p); p += b.length; }
  return out;
}

// Read back a stored ZIP (tests and re-import).
export function unzipStore(bytes) {
  const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const files = {};
  let p = 0;
  const dec = new TextDecoder();
  while (p + 30 <= bytes.length && dv.getUint32(p, true) === 0x04034b50) {
    const size = dv.getUint32(p + 18, true), nameLen = dv.getUint16(p + 26, true), extra = dv.getUint16(p + 28, true);
    const name = dec.decode(bytes.subarray(p + 30, p + 30 + nameLen));
    const start = p + 30 + nameLen + extra;
    files[name] = bytes.slice(start, start + size);
    if (crc32(files[name]) !== dv.getUint32(p + 14, true)) throw new Error('CRC mismatch: ' + name);
    p = start + size;
  }
  return files;
}

export function encodeWav(samples, sampleRate) {
  const dv = new DataView(new ArrayBuffer(44 + samples.length * 2));
  const str = (o, s) => { for (let i = 0; i < s.length; i++) dv.setUint8(o + i, s.charCodeAt(i)); };
  str(0, 'RIFF'); dv.setUint32(4, 36 + samples.length * 2, true); str(8, 'WAVE'); str(12, 'fmt ');
  dv.setUint32(16, 16, true); dv.setUint16(20, 1, true); dv.setUint16(22, 1, true);
  dv.setUint32(24, sampleRate, true); dv.setUint32(28, sampleRate * 2, true); dv.setUint16(32, 2, true); dv.setUint16(34, 16, true);
  str(36, 'data'); dv.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) dv.setInt16(44 + i * 2, Math.round(Math.max(-1, Math.min(1, samples[i])) * 32767), true);
  return new Uint8Array(dv.buffer);
}

// Linear-interpolation resampler for short clips (anti-aliasing by block averaging).
export function resample(x, from, to) {
  if (from === to) return Float32Array.from(x);
  const ratio = from / to, n = Math.floor(x.length / ratio), out = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const a = i * ratio, b = Math.min(x.length, a + ratio);
    let s = 0, c = 0;
    for (let j = Math.floor(a); j < b; j++) { s += x[j]; c++; }
    out[i] = c ? s / c : 0;
  }
  return out;
}

const csvCell = v => (v == null || (typeof v === 'number' && !Number.isFinite(v)) ? '' : typeof v === 'number' ? String(Math.round(v * 1e5) / 1e5) : String(v));
export function toCsv(columns, rows) {
  return [columns.join(','), ...rows.map(r => columns.map(c => csvCell(r[c])).join(','))].join('\n') + '\n';
}

// ---------------------------------------------------------------- features & detectors
// One audio frame (~100 ms) -> loudness, peak, spectral centroid and 4 band energies.
export function audioFrameFeatures(frame, sampleRate) {
  let s = 0, peak = 0;
  for (const v of frame) { s += v * v; const a = Math.abs(v); if (a > peak) peak = a; }
  const rms = Math.sqrt(s / (frame.length || 1));
  let n = 1; while (n * 2 <= frame.length && n < 4096) n *= 2;
  const re = new Float64Array(n), im = new Float64Array(n);
  for (let i = 0; i < n; i++) re[i] = frame[i] * (0.5 - 0.5 * Math.cos(2 * Math.PI * i / (n - 1)));
  fft(re, im);
  const bands = new Array(AUDIO_BANDS_HZ.length - 1).fill(0);
  let pw = 0, pf = 0;
  for (let k = 1; k < n / 2; k++) {
    const f = k * sampleRate / n, p = re[k] ** 2 + im[k] ** 2;
    pw += p; pf += p * f;
    for (let b = 0; b < bands.length; b++) if (f >= AUDIO_BANDS_HZ[b] && f < AUDIO_BANDS_HZ[b + 1]) { bands[b] += p; break; }
  }
  return {rms, peak, crest: rms > 0 ? peak / rms : 0, centroid_hz: pw > 0 ? pf / pw : 0,
    band_0_500: bands[0] / n, band_500_2k: bands[1] / n, band_2k_6k: bands[2] / n, band_6k_up: bands[3] / n};
}

// Spike detector over a positive signal: slow baseline (EMA of level and of absolute
// deviation); an event fires when the value exceeds baseline + k·deviation and a minimum
// absolute rise, with a refractory period. Spikes barely move the baseline.
export class SpikeDetector {
  constructor({k = 6, minRise = 0, refractory = 0.25, warmup = 20, alpha = 0.02} = {}) {
    Object.assign(this, {k, minRise, refractory, warmup, alpha});
    this.mean = null; this.dev = 0; this.count = 0; this.last = -Infinity;
  }
  push(t, v) {
    if (this.mean === null) { this.mean = v; this.count = 1; return null; }
    const thr = this.mean + Math.max(this.k * this.dev, this.minRise);
    const hit = this.count >= this.warmup && v > thr && t - this.last >= this.refractory;
    const clipped = Math.min(v, this.mean + 3 * (this.dev || Math.abs(v - this.mean)));
    this.mean += this.alpha * (clipped - this.mean);
    this.dev += this.alpha * (Math.abs(clipped - this.mean) - this.dev);
    this.count++;
    if (!hit) return null;
    this.last = t;
    return {t, value: v, baseline: this.mean, ratio: this.dev > 0 ? (v - this.mean) / this.dev : null};
  }
}

// Extruder skipping during a jam produces clicks at a steady rhythm; frame knocks during
// fast reversals are irregular. Flag a suspected jam when >= minCount audio transients in
// the window are nearly periodic (coefficient of variation of the intervals < maxCv).
export class JamDetector {
  constructor({window = 6, minCount = 5, maxCv = 0.35, minInterval = 0.12, maxInterval = 1.5, refractory = 20} = {}) {
    Object.assign(this, {window, minCount, maxCv, minInterval, maxInterval, refractory});
    this.times = []; this.last = -Infinity;
  }
  push(t) {
    this.times.push(t);
    while (this.times.length && t - this.times[0] > this.window) this.times.shift();
    if (this.times.length < this.minCount || t - this.last < this.refractory) return null;
    const iv = this.times.slice(1).map((v, i) => v - this.times[i]);
    const mean = iv.reduce((a, b) => a + b, 0) / iv.length;
    if (mean < this.minInterval || mean > this.maxInterval) return null;
    const sd = Math.sqrt(iv.reduce((a, b) => a + (b - mean) ** 2, 0) / iv.length);
    if (sd / mean > this.maxCv) return null;
    this.last = t;
    return {t, count: this.times.length, period_s: mean, cv: sd / mean};
  }
}

// ---------------------------------------------------------------- recorder
export const PRINTER_COLUMNS = ['t', 'hotend', 'hotend_target', 'hotend_power', 'bed', 'bed_target', 'bed_power',
  'x', 'y', 'z', 'speed_mm_s', 'speed_factor', 'progress', 'layer', 'state'];
export const ACCEL_COLUMNS = ['t', 'ax', 'ay', 'az'];
export const AUDIO_COLUMNS = ['t', 'rms', 'peak', 'crest', 'centroid_hz', 'band_0_500', 'band_500_2k', 'band_2k_6k', 'band_6k_up'];

export class TrialRecorder {
  // t0: the clock origin (performance.now() in the page). All times are seconds from t0.
  constructor({t0 = 0, frameSeconds = 0.1, clipPre = 1, clipPost = 1, maxClips = 150, maxAccelRows = 720000} = {}) {
    Object.assign(this, {t0, frameSeconds, clipPre, clipPost, maxClips, maxAccelRows});
    this.printer = []; this.accel = []; this.audio = []; this.events = []; this.clips = []; this.photos = [];
    this.accelKnock = new SpikeDetector({k: 8, minRise: 0.8, refractory: 0.3, warmup: 50, alpha: 0.01});
    this.audioKnock = new SpikeDetector({k: 8, minRise: 0.02, refractory: 0.15, warmup: 20, alpha: 0.02});
    this.jam = new JamDetector();
    this.gravity = null; this.frame = []; this.frameStart = null;
    this.ring = new Float32Array(CLIP_RATE * (clipPre + clipPost + 1)); this.ringPos = 0; this.ringTotal = 0;
    this.pendingClips = [];
    this.dropped = {accel: 0, clips: 0};
  }
  rel(ms) { return (ms - this.t0) / 1000; }

  addPrinter(ms, s) { this.printer.push({t: this.rel(ms), ...s}); }

  addMotion(ms, x, y, z) {
    const t = this.rel(ms);
    if (this.accel.length < this.maxAccelRows) this.accel.push({t, ax: x, ay: y, az: z});
    else this.dropped.accel++;
    // Remove gravity/tilt with a slow per-axis average, then detect jolts on the magnitude.
    const g = this.gravity || (this.gravity = {x, y, z});
    g.x += 0.02 * (x - g.x); g.y += 0.02 * (y - g.y); g.z += 0.02 * (z - g.z);
    const mag = Math.hypot(x - g.x, y - g.y, z - g.z);
    const hit = this.accelKnock.push(t, mag);
    if (hit) this.addEvent(ms, 'knock', {source: 'accel', magnitude: hit.value, baseline: hit.baseline, ratio: hit.ratio});
  }

  // Raw microphone samples (mono float, any sample rate), in arrival order.
  addAudio(ms, block, sampleRate) {
    const t = this.rel(ms);
    const clip = resample(block, sampleRate, CLIP_RATE);
    for (const v of clip) { this.ring[this.ringPos] = v; this.ringPos = (this.ringPos + 1) % this.ring.length; }
    this.ringTotal += clip.length;
    if (this.frameStart === null) this.frameStart = t - block.length / sampleRate;
    for (const v of block) this.frame.push(v);
    const need = Math.round(this.frameSeconds * sampleRate);
    while (this.frame.length >= need) {
      const f = this.frame.splice(0, need);
      const ft = this.frameStart; this.frameStart += this.frameSeconds;
      const feat = audioFrameFeatures(f, sampleRate);
      this.audio.push({t: ft, ...feat});
      const hit = this.audioKnock.push(ft, feat.peak);
      if (hit) {
        this.addEvent(this.t0 + ft * 1000, 'knock', {source: 'audio', peak: feat.peak, baseline: hit.baseline, ratio: hit.ratio, centroid_hz: feat.centroid_hz});
        const jam = this.jam.push(ft);
        if (jam) this.addEvent(this.t0 + ft * 1000, 'jam_suspect', {source: 'audio', ...jam});
      }
    }
    this.flushClips();
  }

  addEvent(ms, type, data = {}) {
    const t = this.rel(ms);
    const ev = {t, type, ...data};
    this.events.push(ev);
    if ((type === 'knock' && data.source === 'audio') || type === 'jam_suspect') this.requestClip(ev);
    return ev;
  }

  requestClip(ev) {
    if (this.pendingClips.some(c => Math.abs(c.t - ev.t) < this.clipPost) || this.clips.some(c => Math.abs(c.t - ev.t) < this.clipPost)) return;
    if (this.clips.length + this.pendingClips.length >= this.maxClips) { this.dropped.clips++; return; }
    this.pendingClips.push({t: ev.t, type: ev.type, total: this.ringTotal, ev});
  }

  // force: the recording ended, cut pending clips with whatever audio followed the event.
  flushClips(force = false) {
    const post = this.clipPost * CLIP_RATE, pre = this.clipPre * CLIP_RATE;
    this.pendingClips = this.pendingClips.filter(c => {
      if (this.ringTotal - c.total < post && !force) return true;
      const end = Math.min(c.total + post, this.ringTotal);
      const len = Math.min(pre + (end - c.total), end, this.ring.length);
      const startAbs = end - len, samples = new Float32Array(len);
      for (let i = 0; i < len; i++) {
        const back = this.ringTotal - (startAbs + i);   // samples ago
        samples[i] = this.ring[((this.ringPos - back) % this.ring.length + this.ring.length) % this.ring.length];
      }
      const name = `audio_events/${String(this.clips.length).padStart(3, '0')}_${c.type}_${c.t.toFixed(2)}s.wav`;
      this.clips.push({t: c.t, name, wav: encodeWav(samples, CLIP_RATE)});
      c.ev.clip = name;
      return false;
    });
  }

  addPhoto(ms, name) { this.photos.push({t: this.rel(ms), name}); }

  summary() {
    const dur = this.accel.length > 1 ? this.accel.at(-1).t - this.accel[0].t : 0;
    const count = type => this.events.filter(e => e.type === type).length;
    return {accel_rows: this.accel.length, accel_rate_hz: dur > 0 ? (this.accel.length - 1) / dur : null,
      audio_frames: this.audio.length, printer_rows: this.printer.length, photos: this.photos.length,
      knocks_accel: this.events.filter(e => e.type === 'knock' && e.source === 'accel').length,
      knocks_audio: this.events.filter(e => e.type === 'knock' && e.source === 'audio').length,
      jam_suspects: count('jam_suspect'), clips: this.clips.length, dropped: this.dropped};
  }

  // Text/binary parts of the trial folder produced by the recorder itself.
  parts() {
    this.flushClips(true);
    const files = {
      'printer.csv': toCsv(PRINTER_COLUMNS, this.printer),
      'accel.csv': toCsv(ACCEL_COLUMNS, this.accel),
      'audio_features.csv': toCsv(AUDIO_COLUMNS, this.audio),
      'events.jsonl': this.events.map(e => JSON.stringify(e)).join('\n') + (this.events.length ? '\n' : ''),
    };
    for (const c of this.clips) files[c.name] = c.wav;
    return files;
  }
}

// ---------------------------------------------------------------- trial folder & manifest
// outcome: explicit human label wins; otherwise infer only the obvious failure (not completed).
export function labelsFromTrial(tr) {
  const h = tr.human || {};
  let outcome = h.outcome || null;
  if (!outcome) outcome = tr.measured?.completed === false ? 'failure' : h.overall != null ? (h.overall >= 3 ? 'success' : 'failure') : 'unknown';
  return {outcome, overall: h.overall ?? null, surface: h.surface ?? null, dimensions: h.dimensions ?? null,
    defects: h.defects || {}, notes: h.notes || '', labeled_by: h.labeled_by || (tr.human ? 'human' : null),
    labeled_at: h.labeled_at || null};
}

export function trialMeta(tr, {app = 'klipperlearn-phone', appVersion = null, profile = null, recorderSummary = null} = {}) {
  return {schema: DATASET_SCHEMA, trial_id: tr.id, created_at: new Date(tr.createdAt).toISOString(),
    printer_id: tr.printerId, printer: profile ? {name: profile.name, bed_x: profile.bed_x, bed_y: profile.bed_y, nozzle_mm: profile.nozzle_mm} : null,
    firmware: tr.firmware || null, host: tr.host || null, source: tr.source || null, parent_id: tr.parentId || null,
    changed: tr.changed || null, measured: tr.measured || {}, sensors: tr.sensors || recorderSummary || null,
    app: {name: app, version: appVersion}};
}

// All files of one trial, relative to dataset root. `extra` holds recorder parts and photos
// ({'printer.csv': '...', 'photos/L10.jpg': Uint8Array, ...}).
export function trialFiles(tr, extra = {}, opts = {}) {
  const dir = `trials/${tr.id}/`;
  const files = [
    {path: dir + 'meta.json', data: JSON.stringify(trialMeta(tr, opts), null, 2)},
    {path: dir + 'gcode_params.json', data: JSON.stringify(tr.params || {}, null, 2)},
    {path: dir + 'labels.json', data: JSON.stringify(labelsFromTrial(tr), null, 2)},
  ];
  for (const [name, data] of Object.entries(extra)) files.push({path: dir + name, data});
  return files;
}

export function manifestEntry(tr, paths, provenance = 'klipperlearn-phone') {
  const labels = labelsFromTrial(tr);
  return {trial_id: tr.id, schema: DATASET_SCHEMA, printer_id: tr.printerId, created_at: new Date(tr.createdAt).toISOString(),
    source_hash: tr.source?.hash || null, params: tr.params || {}, outcome: labels.outcome, labels,
    paths: paths.map(p => p.replace(`trials/${tr.id}/`, '')), provenance};
}

// Build the whole dataset as a ZIP. `trials` are [{trial, extra}] with extra as in trialFiles.
export function buildDatasetZip(trials, opts = {}) {
  const files = [], manifest = [];
  for (const {trial, extra, profile} of trials) {
    const tf = trialFiles(trial, extra, {...opts, profile});
    files.push(...tf);
    manifest.push(JSON.stringify(manifestEntry(trial, tf.map(f => f.path), opts.provenance)));
  }
  files.unshift({path: 'manifest.jsonl', data: manifest.join('\n') + (manifest.length ? '\n' : '')},
    {path: 'README.md', data: DATASET_README});
  return zipStore(files.map(f => ({...f, path: 'dataset/' + f.path})));
}

export const DATASET_README = `# KlipperLearn dataset (klipperlearn-dataset/v1)

One folder per trial under trials/, one line per trial in manifest.jsonl.
Times are seconds from the start of the trial. Units: mm, mm/s, °C, m/s² (phone accelerometer),
audio amplitude in full scale (-1..1). Heater power 0..1. Photos are JPEG from the phone camera.
events.jsonl: knock (source accel|audio), jam_suspect (periodic audio clicks), pause, resume,
cancel, error. Detections are hints; labels.json (human) is the ground truth.
Recorded locally on the user's phone; nothing is uploaded unless the user shares this file.
`;
