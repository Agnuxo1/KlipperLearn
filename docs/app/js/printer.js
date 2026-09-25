// SPDX-License-Identifier: GPL-3.0-or-later
// Minimal G-code host for Marlin-family firmware (and compatible RepRap firmwares) that
// runs in the browser: numbered lines with checksums, resend handling, temperature
// reports, capability probing (M115/M503) and job streaming with pause/resume/cancel.

export function checksumLine(n, cmd) {
  const body = `N${n} ${cmd}`;
  let cs = 0;
  for (let i = 0; i < body.length; i++) cs ^= body.charCodeAt(i);
  return `${body}*${cs}`;
}

export function stripGcode(line) {
  const i = line.indexOf(';');
  return (i >= 0 ? line.slice(0, i) : line).replace(/\(.*?\)/g, '').trim();
}

export function parseTemps(line) {
  const out = {};
  const re = /\b(T\d?|B|C)\s*:\s*(-?[\d.]+)\s*(?:\/\s*(-?[\d.]+))?/g;
  let m;
  while ((m = re.exec(line))) {
    const key = m[1] === 'B' ? 'bed' : m[1] === 'C' ? 'chamber' : (m[1] === 'T' || m[1] === 'T0') ? 'hotend' : 'hotend' + m[1].slice(1);
    if (!(key in out)) out[key] = {current: parseFloat(m[2]), target: m[3] === undefined ? null : parseFloat(m[3])};
  }
  return Object.keys(out).length ? out : null;
}

export function parseFirmwareInfo(lines) {
  const info = {name: null, version: null, machine: null, caps: {}};
  for (const line of lines) {
    const fw = line.match(/FIRMWARE_NAME:\s*([^\s(]+)\s*([^\s(]*)/);
    if (fw) { info.name = fw[1]; info.version = fw[2] || null; }
    const mt = line.match(/MACHINE_TYPE:\s*(.+?)(?:\s+[A-Z_]+:|$)/);
    if (mt) info.machine = mt[1].trim();
    const cap = line.match(/^Cap:([A-Z0-9_]+):(\d)/);
    if (cap) info.caps[cap[1]] = cap[2] === '1';
  }
  return info;
}

// Parse the echo lines of M503 into {M204: {P: 500, ...}, M593: {X: {F, D}, Y: {...}}, ...}.
export function parseSettings(lines) {
  const s = {};
  for (let raw of lines) {
    raw = raw.replace(/^echo:\s*/, '').trim();
    const m = raw.match(/^(M\d+)\s*(.*)$/);
    if (!m) continue;
    const cmd = m[1];
    const params = {};
    let axisFlag = null;
    for (const tok of m[2].split(/\s+/)) {
      const t = tok.match(/^([A-Z])(-?[\d.]*)$/);
      if (!t) continue;
      if (t[2] === '') { axisFlag = t[1]; continue; }
      params[t[1]] = parseFloat(t[2]);
    }
    if (cmd === 'M593' && axisFlag) { s.M593 = s.M593 || {}; s.M593[axisFlag] = params; }
    else s[cmd] = {...(s[cmd] || {}), ...params};
  }
  return s;
}

export function describeFeatures(info, settings) {
  const accel = settings.M204 || {};
  const jerk = settings.M205 || {};
  const major = parseInt((info.version || '0').split('.')[0], 10) || 0;
  const minor = parseInt((info.version || '0.0').split('.')[1], 10) || 0;
  return {
    firmware: info.name ? `${info.name} ${info.version || ''}`.trim() : 'unknown',
    accelStyle: 'P' in accel ? 'PRT' : 'S' in accel ? 'S' : (major >= 2 || (major === 1 && minor >= 1)) ? 'PRT' : 'S',
    jerkStyle: 'J' in jerk ? 'junction' : 'classic',
    linearAdvance: 'M900' in settings,
    inputShaping: 'M593' in settings,
    autoReportTemp: !!info.caps.AUTOREPORT_TEMP,
    eeprom: !!info.caps.EEPROM,
    emergencyParser: !!info.caps.EMERGENCY_PARSER,
  };
}

const sleep = ms => new Promise(r => setTimeout(r, ms));

export class Printer {
  constructor(conn, {log = () => {}, timeoutMs = 15000} = {}) {
    this.conn = conn;
    this.log = log;
    this.timeoutMs = timeoutMs;
    this.listeners = {};
    this.lineNo = 0;
    this.history = new Map();
    this.queue = [];
    this.inflight = null;
    this.replay = [];
    this.pendingResend = null;
    this.lastRx = Date.now();
    this.temps = {};
    this.info = null; this.settings = {}; this.features = null;
    this.job = null;
    conn.onLine = line => this.handleLine(line);
    conn.onClose = () => this.emit('close');
  }

  on(evt, fn) { (this.listeners[evt] = this.listeners[evt] || []).push(fn); return this; }
  emit(evt, data) { for (const fn of this.listeners[evt] || []) fn(data); }

  handleLine(line) {
    this.lastRx = Date.now();
    this.log('<', line);
    const temps = parseTemps(line);
    if (temps && /(^ok)?\s*T\d?:|B:/.test(line)) { Object.assign(this.temps, temps); this.emit('temps', this.temps); }
    const rs = line.match(/^(?:Resend|rs)\s*:?\s*N?(\d+)/i);
    if (rs) { this.pendingResend = parseInt(rs[1], 10); return; }
    if (/^start\b/.test(line)) { this.emit('reset'); return; }
    if (/^Error:/i.test(line)) {
      this.emit('error', line);
      if (/Printer halted|kill\(\) called|Thermal Runaway|MINTEMP|MAXTEMP/i.test(line)) this.abortAll('Firmware halted: ' + line);
      return;
    }
    if (/^ok\b/.test(line)) { this.onOk(line); return; }
    if (this.inflight) this.inflight.response.push(line);
  }

  onOk(line) {
    const cur = this.inflight;
    if (this.pendingResend !== null) {
      // Replay history from the requested line, including the one that failed.
      const from = this.pendingResend; this.pendingResend = null;
      const upTo = cur ? cur.n : this.lineNo - 1;
      const again = [];
      for (let n = from; n <= upTo; n++) if (this.history.has(n)) again.push(n);
      if (!again.length) { this.log('!', `Resend N${from} outside history`); return this.finishInflight(line); }
      this.replay = again.slice(1);
      this.writeNumbered(again[0]);
      return;
    }
    if (this.replay.length) { this.writeNumbered(this.replay.shift()); return; }
    this.finishInflight(line);
  }

  finishInflight(line) {
    const cur = this.inflight;
    this.inflight = null;
    if (cur) { if (line.length > 2) cur.response.push(line); cur.resolve(cur.response); }
    this.pump();
  }

  writeNumbered(n) {
    this.conn.writeLine(checksumLine(n, this.history.get(n))).catch(e => this.abortAll(e.message));
  }

  // Queue a G-code command; resolves with the response lines when the firmware says ok.
  send(cmd) {
    const clean = stripGcode(cmd);
    if (!clean) return Promise.resolve([]);
    return new Promise((resolve, reject) => { this.queue.push({cmd: clean, resolve, reject, response: []}); this.pump(); });
  }

  pump() {
    if (this.inflight || !this.queue.length || !this.conn.isOpen) return;
    const item = this.queue.shift();
    const n = this.lineNo++;
    item.n = n;
    this.history.set(n, item.cmd);
    if (this.history.size > 256) this.history.delete(n - 256);
    this.inflight = item;
    this.sentAt = Date.now();
    this.log('>', item.cmd);
    this.writeNumbered(n);
  }

  // Emergency stop bypasses the queue (Marlin's emergency parser acts immediately).
  async emergencyStop() {
    await this.conn.writeLine('M112');
    this.abortAll('Emergency stop');
  }

  dropPending(err) {
    if (this.inflight) { this.inflight.reject(err); this.inflight = null; }
    for (const q of this.queue.splice(0)) q.reject(err);
    this.replay = []; this.pendingResend = null;
  }

  abortAll(reason) {
    if (this.job) this.job.cancelled = true;
    this.dropPending(new Error(reason));
    this.emit('abort', reason);
  }

  // Watchdog: a lost "ok" would stall the queue; M105 provokes a fresh ok.
  startWatchdog() {
    clearInterval(this.watchdog);
    this.watchdog = setInterval(() => {
      if (!this.inflight) return;
      const heating = /^(M109|M190|M191|G28|G29|M303|G4|M400)\b/.test(this.inflight.cmd);
      if (!heating && Date.now() - this.lastRx > this.timeoutMs) {
        this.log('!', 'No response, requesting status');
        this.lastRx = Date.now();
        this.conn.writeLine('M105').catch(() => {});
      }
    }, 2000);
  }

  async handshake() {
    // Opening the port resets many 8-bit boards (DTR). Wait for their "start" banner, or
    // up to 3 s for boards that don't reset, then give the firmware a moment to settle.
    const sim = this.conn.label === 'Simulator';
    let started = false;
    this.on('reset', () => { started = true; });
    const t0 = Date.now();
    while (!sim && !started && Date.now() - t0 < 3000) await sleep(100);
    await sleep(sim ? 50 : started ? 1500 : 200);
    this.startWatchdog();
    const withTimeout = (p, ms, what) => Promise.race([p, sleep(ms).then(() => { throw new Error(what); })]);
    try {
      let answered = false;
      for (let attempt = 0; attempt < 3 && !answered; attempt++) {
        try { await withTimeout(this.send('M110 N0'), 4000, 'timeout'); answered = true; }
        catch (_) { this.dropPending(new Error('M110 retry')); }
      }
      if (!answered) throw new Error('No G-code firmware answered. Check the baud rate (115200/250000). A board flashed with Klipper firmware needs a Klipper host instead.');
      this.lineNo = 1; this.history.clear();
      const m115 = await withTimeout(this.send('M115'), 8000, 'M115 timed out');
      this.info = parseFirmwareInfo(m115);
    } catch (e) { this.abortAll(e.message); this.stopTimers(); throw e; }
    try { this.settings = parseSettings(await withTimeout(this.send('M503'), 8000, 'M503 timed out')); }
    catch (_) { this.settings = {}; }
    this.features = describeFeatures(this.info, this.settings);
    if (this.features.autoReportTemp) await this.send('M155 S2');
    else this.startTempPolling();
    this.emit('ready', {info: this.info, settings: this.settings, features: this.features});
    return this.features;
  }

  startTempPolling() {
    clearInterval(this.tempPoll);
    this.tempPoll = setInterval(() => { if (!this.inflight && !this.queue.length) this.send('M105').catch(() => {}); }, 3000);
  }

  stopTimers() { clearInterval(this.watchdog); clearInterval(this.tempPoll); }

  // Stream a G-code program. `lines` is an array of strings; `transform` may rewrite them.
  async runJob(lines, {transform = null, onProgress = () => {}, onLayer = () => {}, onMarker = () => {}} = {}) {
    if (this.job) throw new Error('A job is already running');
    const job = this.job = {paused: false, cancelled: false, relativeE: false, startedAt: Date.now(), layer: 0, z: null};
    const program = transform ? transform(lines) : lines;
    const total = program.length;
    try {
      for (let i = 0; i < total; i++) {
        while (job.paused && !job.cancelled) await sleep(200);
        if (job.cancelled) break;
        const raw = program[i];
        if (/^;\s*(LAYER:|LAYER_CHANGE|layer num)/i.test(raw)) { job.layer++; onLayer(job.layer, job.z); }
        if (/^;KL_/.test(raw)) onMarker(raw);
        const cmd = stripGcode(raw);
        if (!cmd) continue;
        if (/^M83\b/.test(cmd)) job.relativeE = true;
        if (/^M82\b/.test(cmd)) job.relativeE = false;
        const z = cmd.match(/^G[01]\b.*\bZ(-?[\d.]+)/);
        if (z) job.z = parseFloat(z[1]);
        await this.send(cmd);
        if (i % 25 === 0 || i === total - 1) onProgress((i + 1) / total, job);
      }
    } finally {
      const cancelled = job.cancelled;
      this.job = null;
      if (cancelled) await this.safeShutdown().catch(() => {});
      this.emit('jobEnd', {cancelled, seconds: (Date.now() - job.startedAt) / 1000, layers: job.layer});
    }
    return !job.cancelled;
  }

  async pause() {
    if (!this.job || this.job.paused) return;
    this.job.paused = true;
    const restoreE = this.job.relativeE ? 'M83' : 'M82';
    for (const c of ['G91', 'G1 E-2 F2400', 'G1 Z5 F600', 'G90', restoreE]) await this.send(c);
  }

  async resume() {
    if (!this.job || !this.job.paused) return;
    const restoreE = this.job.relativeE ? 'M83' : 'M82';
    for (const c of ['G91', 'G1 Z-5 F600', 'G1 E2 F2400', 'G90', restoreE]) await this.send(c);
    this.job.paused = false;
  }

  cancel() { if (this.job) { this.job.cancelled = true; this.job.paused = false; } }

  async safeShutdown() {
    for (const c of ['M104 S0', 'M140 S0', 'M106 S0', 'G91', 'G1 Z10 F600', 'G90', 'M84']) await this.send(c);
  }

  async close() { this.stopTimers(); this.cancel(); await this.conn.close(); }
}
