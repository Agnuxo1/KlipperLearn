// SPDX-License-Identifier: GPL-3.0-or-later
// A small Marlin 2.1 imitation for demos and tests. It validates line numbers and
// checksums, can inject resend requests, simulates heaters and reports temperatures.
// It does not model motion; it only answers the serial protocol.

export class MarlinSimulator {
  constructor({version = '2.1.2.1', autoReport = true, inputShaping = true, linearAdvance = true,
    corruptEvery = 0, heatRate = 40, lineDelayMs = 0, ignoreFirst = 0} = {}) {
    Object.assign(this, {version, autoReport, inputShaping, linearAdvance, corruptEvery, heatRate, lineDelayMs, ignoreFirst});
    this.emit = () => {};
    this.expected = 0;
    this.count = 0;
    this.hotend = {current: 22, target: 0};
    this.bed = {current: 22, target: 0};
    this.settings = {M204: {P: 500, R: 500, T: 1000}, M205: {J: 0.08}, M203: {X: 300, Y: 300, Z: 5, E: 25},
      M220: {S: 100}, M221: {S: 100}, M900: {K: 0}, M593: {X: {F: 0, D: 0.1}, Y: {F: 0, D: 0.1}}, M207: {S: 4}};
    this.received = [];
    this.timer = null;
  }

  boot() {
    this.emit('start');
    this.emit(`echo:Marlin ${this.version}`);
    if (this.autoReport) this.timer = null;
  }

  stop() { clearInterval(this.timer); this.timer = null; }

  tick(seconds) {
    for (const h of [this.hotend, this.bed]) {
      const d = h.target - h.current;
      const step = Math.sign(d) * Math.min(Math.abs(d), this.heatRate * seconds * (h === this.bed ? 0.25 : 1));
      h.current = h.target === 0 ? Math.max(22, h.current - 5 * seconds) : h.current + step;
    }
  }

  tempLine() {
    const f = v => v.toFixed(2);
    return `T:${f(this.hotend.current)} /${f(this.hotend.target)} B:${f(this.bed.current)} /${f(this.bed.target)} @:0 B@:0`;
  }

  receive(line) {
    line = line.trim();
    if (line === 'M112') { this.emit('Error:Printer halted. kill() called!'); this.halted = true; return; }
    if (this.halted) return;
    if (this.ignoreFirst > 0) { this.ignoreFirst--; return; }   // still booting: bytes are lost
    let cmd = line;
    const numbered = line.match(/^N(\d+)\s+(.*?)\*(\d+)$/);
    if (numbered) {
      const [, nStr, body, csStr] = numbered;
      const n = parseInt(nStr, 10);
      let cs = 0;
      const payload = `N${nStr} ${body}`;
      for (let i = 0; i < payload.length; i++) cs ^= payload.charCodeAt(i);
      this.count++;
      const corrupt = this.corruptEvery && this.count % this.corruptEvery === 0;
      if (cs !== parseInt(csStr, 10) || corrupt) {
        this.emit(`Error:checksum mismatch, Last Line: ${this.expected - 1}`);
        this.emit(`Resend: ${n}`); this.emit('ok'); return;
      }
      if (!/^M110\b/.test(body) && n !== this.expected) {
        this.emit(`Error:Line Number is not Last Line Number+1, Last Line: ${this.expected - 1}`);
        this.emit(`Resend: ${this.expected}`); this.emit('ok'); return;
      }
      this.expected = /^M110\b/.test(body) ? (parseInt((body.match(/N(\d+)/) || [0, n])[1], 10) + 1) : n + 1;
      cmd = body;
    }
    this.received.push(cmd);
    this.execute(cmd);
  }

  execute(cmd) {
    const word = cmd.split(/\s+/)[0].toUpperCase();
    const num = (letter, fallback = 0) => { const m = cmd.match(new RegExp(`\\b${letter}(-?[\\d.]+)`)); return m ? parseFloat(m[1]) : fallback; };
    switch (word) {
      case 'M115':
        this.emit(`FIRMWARE_NAME:Marlin ${this.version} (Github) SOURCE_CODE_URL:github.com/MarlinFirmware/Marlin PROTOCOL_VERSION:1.0 MACHINE_TYPE:KlipperLearn Simulator EXTRUDER_COUNT:1 UUID:00000000-0000-0000-0000-000000000000`);
        this.emit(`Cap:AUTOREPORT_TEMP:${this.autoReport ? 1 : 0}`);
        this.emit('Cap:EEPROM:1'); this.emit('Cap:EMERGENCY_PARSER:1');
        break;
      case 'M503': {
        const s = this.settings;
        this.emit('echo:; Acceleration (units/s2) (P<print-accel> R<retract-accel> T<travel-accel>):');
        this.emit(`echo:  M204 P${s.M204.P.toFixed(2)} R${s.M204.R.toFixed(2)} T${s.M204.T.toFixed(2)}`);
        this.emit(`echo:  M205 B20000.00 S0.00 T0.00 J${s.M205.J.toFixed(3)}`);
        this.emit(`echo:  M203 X${s.M203.X} Y${s.M203.Y} Z${s.M203.Z} E${s.M203.E}`);
        if (this.linearAdvance) this.emit(`echo:  M900 K${s.M900.K.toFixed(2)}`);
        if (this.inputShaping) { this.emit(`echo:  M593 X F${s.M593.X.F.toFixed(2)} D${s.M593.X.D.toFixed(2)}`); this.emit(`echo:  M593 Y F${s.M593.Y.F.toFixed(2)} D${s.M593.Y.D.toFixed(2)}`); }
        break;
      }
      case 'M105': this.emit('ok ' + this.tempLine()); return;
      case 'M104': this.hotend.target = num('S'); break;
      case 'M140': this.bed.target = num('S'); break;
      case 'M109': this.hotend.target = num('S', this.hotend.target); this.hotend.current = this.hotend.target; this.emit(this.tempLine()); break;
      case 'M190': this.bed.target = num('S', this.bed.target); this.bed.current = this.bed.target; this.emit(this.tempLine()); break;
      case 'M155':
        clearInterval(this.timer);
        if (num('S') > 0 && typeof setInterval !== 'undefined') this.timer = setInterval(() => { this.tick(num('S')); this.emit(' ' + this.tempLine()); }, num('S') * 1000);
        break;
      case 'M204': for (const k of 'PRTS') if (cmd.includes(k)) this.settings.M204[k === 'S' ? 'P' : k] = num(k); break;
      case 'M205': if (/J/.test(cmd)) this.settings.M205.J = num('J'); break;
      case 'M900': if (!this.linearAdvance) { this.emit('echo:Unknown command: "M900"'); break; } this.settings.M900.K = num('K'); break;
      case 'M593':
        if (!this.inputShaping) { this.emit('echo:Unknown command: "M593"'); break; }
        for (const ax of ['X', 'Y']) if (new RegExp(`\\b${ax}\\b`).test(cmd) || !/\b[XY]\b/.test(cmd)) this.settings.M593[ax].F = num('F', this.settings.M593[ax].F);
        break;
      case 'M114': this.emit('X:0.00 Y:0.00 Z:0.00 E:0.00 Count X:0 Y:0 Z:0'); break;
      case 'G0': case 'G1':
        if (this.lineDelayMs) { setTimeout(() => this.emit('ok'), this.lineDelayMs); return; }
        break;
      default: break;
    }
    this.emit('ok');
  }
}
