// SPDX-License-Identifier: GPL-3.0-or-later
// Klipper through Moonraker. Intended setup: the old phone runs the Klipper host and
// Moonraker, and this app is served from the same phone (http://localhost is a secure
// context, so camera, microphone and accelerometer work without keys or pairing).
// Moonraker trusts local clients, so no credentials are involved.
//
// MoonrakerPrinter mirrors the Printer interface used by the UI (handshake, runJob, pause,
// resume, cancel, emergencyStop, send, temps, on/emit) so the rest of the app is unchanged.

const sleep = ms => new Promise(r => setTimeout(r, ms));

export function defaultMoonrakerUrl(loc = typeof location !== 'undefined' ? location : null) {
  if (!loc) return 'http://127.0.0.1:7125';
  const local = /^(localhost|127\.0\.0\.1|\[::1\])$/.test(loc.hostname) || /\.local$/.test(loc.hostname);
  return local && loc.protocol.startsWith('http') ? loc.origin : 'http://127.0.0.1:7125';
}

// JSON-RPC 2.0 over Moonraker's websocket, plus the HTTP upload endpoint.
export class MoonrakerClient {
  constructor(baseUrl, {WebSocketImpl = globalThis.WebSocket, fetchImpl = globalThis.fetch?.bind(globalThis)} = {}) {
    this.base = baseUrl.replace(/\/+$/, '');
    this.WS = WebSocketImpl; this.fetch = fetchImpl;
    this.id = 1; this.pending = new Map(); this.onNotify = () => {}; this.onClose = () => {};
  }
  open(timeoutMs = 8000) {
    const url = this.base.replace(/^http/, 'ws') + '/websocket';
    return new Promise((resolve, reject) => {
      const ws = this.ws = new this.WS(url);
      const timer = setTimeout(() => { reject(new Error('Moonraker did not answer at ' + this.base)); try { ws.close(); } catch (_) {} }, timeoutMs);
      ws.onopen = () => { clearTimeout(timer); resolve(); };
      ws.onerror = () => { clearTimeout(timer); reject(new Error('Cannot reach Moonraker at ' + this.base)); };
      ws.onclose = () => { for (const p of this.pending.values()) p.reject(new Error('Moonraker closed')); this.pending.clear(); this.onClose(); };
      ws.onmessage = e => this.handle(typeof e.data === 'string' ? e.data : String(e.data));
    });
  }
  handle(text) {
    let msg; try { msg = JSON.parse(text); } catch (_) { return; }
    if (msg.id != null && this.pending.has(msg.id)) {
      const p = this.pending.get(msg.id); this.pending.delete(msg.id);
      if (msg.error) p.reject(new Error(msg.error.message || 'Moonraker error')); else p.resolve(msg.result);
    } else if (msg.method) this.onNotify(msg.method, msg.params || []);
  }
  call(method, params = {}, timeoutMs = 30000) {
    const id = this.id++;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error(method + ' timed out')); }, timeoutMs);
      this.pending.set(id, {resolve: v => { clearTimeout(timer); resolve(v); }, reject: e => { clearTimeout(timer); reject(e); }});
      this.ws.send(JSON.stringify({jsonrpc: '2.0', method, params, id}));
    });
  }
  async upload(path, text) {
    const form = new FormData();
    form.append('root', 'gcodes');
    form.append('file', new Blob([text], {type: 'text/plain'}), path);
    const res = await this.fetch(this.base + '/server/files/upload', {method: 'POST', body: form, credentials: 'omit'});
    if (!res.ok) throw new Error(`Upload failed: HTTP ${res.status}`);
    return res.json();
  }
  close() { try { this.ws?.close(); } catch (_) {} }
}

export const SUBSCRIBE = {
  extruder: ['temperature', 'target', 'power', 'pressure_advance'],
  heater_bed: ['temperature', 'target', 'power'],
  toolhead: ['position', 'homed_axes', 'max_accel', 'max_velocity', 'square_corner_velocity'],
  gcode_move: ['speed', 'speed_factor', 'extrude_factor', 'gcode_position'],
  print_stats: ['state', 'filename', 'print_duration', 'filament_used', 'info', 'message'],
  virtual_sdcard: ['progress', 'is_active'],
  display_status: ['progress'],
  webhooks: ['state', 'state_message'],
};

// Merge a partial status notification into the full status object (Moonraker sends diffs).
export function mergeStatus(status, diff) {
  for (const [obj, fields] of Object.entries(diff || {})) status[obj] = {...(status[obj] || {}), ...fields};
  return status;
}

// One printer.csv row from a Moonraker status snapshot.
export function statusRow(st, layer = null) {
  const e = st.extruder || {}, b = st.heater_bed || {}, g = st.gcode_move || {}, th = st.toolhead || {};
  const pos = g.gcode_position || th.position || [];
  return {hotend: e.temperature, hotend_target: e.target, hotend_power: e.power, bed: b.temperature, bed_target: b.target,
    bed_power: b.power, x: pos[0], y: pos[1], z: pos[2], speed_mm_s: g.speed != null ? g.speed / 60 : null,
    speed_factor: g.speed_factor, progress: st.virtual_sdcard?.progress ?? st.display_status?.progress,
    layer: st.print_stats?.info?.current_layer ?? layer, state: st.print_stats?.state};
}

export class MoonrakerPrinter {
  constructor(client, {log = () => {}, uploadDir = 'klipperlearn'} = {}) {
    this.client = client; this.log = log; this.uploadDir = uploadDir;
    this.listeners = {}; this.status = {}; this.temps = {}; this.job = null;
    this.info = null; this.settings = {}; this.features = null;
    this.conn = {label: 'Klipper · Moonraker ' + client.base, isOpen: false};
    client.onNotify = (method, params) => this.onNotify(method, params);
    client.onClose = () => { this.conn.isOpen = false; this.emit('close'); };
  }
  on(evt, fn) { (this.listeners[evt] = this.listeners[evt] || []).push(fn); return this; }
  emit(evt, data) { for (const fn of this.listeners[evt] || []) fn(data); }

  onNotify(method, params) {
    if (method === 'notify_status_update') this.applyStatus(params[0]);
    else if (method === 'notify_gcode_response') { const line = String(params[0] ?? ''); this.log('<', line); if (/^!!/.test(line)) this.emit('error', line); }
    else if (method === 'notify_klippy_shutdown') this.emit('abort', 'Klipper shutdown');
    else if (method === 'notify_klippy_disconnected') this.emit('abort', 'Klipper disconnected');
  }

  applyStatus(diff) {
    mergeStatus(this.status, diff);
    const e = this.status.extruder, b = this.status.heater_bed;
    if (diff?.extruder || diff?.heater_bed) {
      if (e) this.temps.hotend = {current: e.temperature, target: e.target, power: e.power};
      if (b) this.temps.bed = {current: b.temperature, target: b.target, power: b.power};
      this.emit('temps', this.temps);
    }
    this.emit('status', this.status);
  }

  async open() { await this.client.open(); this.conn.isOpen = true; }

  async handshake() {
    const info = await this.client.call('printer.info');
    if (info.state !== 'ready') throw new Error(`Klipper is ${info.state}: ${info.state_message || ''}`.trim());
    this.info = {name: 'Klipper', version: info.software_version, machine: info.hostname, caps: {}};
    const sub = await this.client.call('printer.objects.subscribe', {objects: SUBSCRIBE});
    this.applyStatus(sub.status);
    const th = this.status.toolhead || {};
    // Baseline for restore: the values Klipper runs with before the trial.
    this.settings = {klipper: {max_accel: th.max_accel, max_velocity: th.max_velocity,
      square_corner_velocity: th.square_corner_velocity, pressure_advance: this.status.extruder?.pressure_advance}};
    this.features = {firmware: `Klipper ${info.software_version || ''}`.trim(), klipper: true, accelStyle: 'S', jerkStyle: 'junction',
      linearAdvance: true, inputShaping: true, eeprom: false, autoReportTemp: true, host: 'moonraker'};
    this.emit('ready', {info: this.info, settings: this.settings, features: this.features});
    return this.features;
  }

  async send(cmd) {
    this.log('>', cmd);
    await this.client.call('printer.gcode.script', {script: cmd}, 600000);
    return [];
  }

  // Upload the (already transformed) program, start it and follow it until it ends.
  async runJob(lines, {onProgress = () => {}, onLayer = () => {}, name = 'trial'} = {}) {
    if (this.job) throw new Error('A job is already running');
    const file = `${this.uploadDir}/${name.replace(/[^\w.-]+/g, '_').replace(/\.gcode$/i, '')}-${Date.now().toString(36)}.gcode`;
    await this.client.upload(file, lines.join('\n') + '\n');
    await this.client.call('printer.print.start', {filename: file});
    return this.followJob({onProgress, onLayer, file});
  }

  // Follow the current print (started here or from Mainsail/Fluidd) until it finishes.
  async followJob({onProgress = () => {}, onLayer = () => {}, file = null} = {}) {
    const job = this.job = {paused: false, cancelled: false, startedAt: Date.now(), layer: 0, file, z: null};
    let seenPrinting = false, lastZ = null;
    const done = new Promise(resolve => {
      const onStatus = st => {
        const ps = st.print_stats || {};
        if (ps.state === 'printing' || ps.state === 'paused') seenPrinting = true;
        job.paused = ps.state === 'paused';
        const progress = st.virtual_sdcard?.progress ?? st.display_status?.progress;
        if (progress != null) onProgress(progress, job);
        const cur = ps.info?.current_layer;
        const z = (st.gcode_move?.gcode_position || [])[2];
        let layer = job.layer;
        if (cur != null) layer = cur;
        else if (ps.state === 'printing' && z != null && (lastZ === null || z > lastZ + 0.05) && z < 1000) { if (lastZ !== null) layer = job.layer + 1; lastZ = z; }
        job.z = z ?? job.z;
        if (layer !== job.layer) { job.layer = layer; onLayer(layer, job.z); }
        if (seenPrinting && ['complete', 'cancelled', 'error', 'standby'].includes(ps.state)) { off(); resolve(ps.state); }
      };
      const onAbort = () => { off(); resolve('error'); };
      const off = () => { this.listeners.status = (this.listeners.status || []).filter(f => f !== onStatus); this.listeners.abort = (this.listeners.abort || []).filter(f => f !== onAbort); };
      this.on('status', onStatus).on('abort', onAbort);
      onStatus(this.status);
    });
    const state = await done;
    job.state = state;
    job.cancelled = state !== 'complete';
    this.job = null;
    this.emit('jobEnd', {cancelled: job.cancelled, state, seconds: (Date.now() - job.startedAt) / 1000, layers: job.layer});
    return state === 'complete';
  }

  async pause() { await this.client.call('printer.print.pause'); }
  async resume() { await this.client.call('printer.print.resume'); }
  cancel() { this.client.call('printer.print.cancel').catch(e => this.log('!', e.message)); }
  async emergencyStop() { await this.client.call('printer.emergency_stop'); this.emit('abort', 'Emergency stop'); }
  async close() { this.client.close(); this.conn.isOpen = false; }
}

export async function waitFor(pred, ms = 5000, step = 50) {
  const t0 = Date.now();
  while (!pred()) { if (Date.now() - t0 > ms) throw new Error('timeout'); await sleep(step); }
}
