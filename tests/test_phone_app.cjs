#!/usr/bin/env node
// Tests for the phone-first web app (docs/app): USB driver math, Marlin protocol over the
// simulator, G-code trial transforms, calibration generators, analysis and the advisor.
'use strict';
const assert = require('node:assert/strict');
const path = require('node:path');
const {pathToFileURL} = require('node:url');

const mod = name => import(pathToFileURL(path.join(__dirname, '..', 'docs', 'app', 'js', name)).href);
const tests = [];
const test = (name, fn) => tests.push({name, fn});

test('CH340 divisor produces baud rates within 2 %', async () => {
  const {ch341Divisor, ch341ActualBaud} = await mod('usb-drivers.js');
  for (const baud of [9600, 57600, 115200, 250000, 500000]) {
    const actual = ch341ActualBaud(ch341Divisor(baud));
    assert.ok(Math.abs(actual - baud) / baud < 0.02, `${baud} -> ${actual}`);
  }
});

test('FTDI divisor and status stripping', async () => {
  const {ftdiDivisor, stripFtdiStatus} = await mod('usb-drivers.js');
  assert.deepEqual(ftdiDivisor(250000), {value: 12, index: 0});
  const d = ftdiDivisor(115200);                      // 26.04 -> 26
  assert.equal(d.value & 0x3fff, 26);
  const raw = Uint8Array.from([0x01, 0x60, 111, 107, 10]);
  assert.deepEqual([...stripFtdiStatus(raw)], [111, 107, 10]);
});

test('CH340 driver sends the Linux ch341 init sequence to a fake device', async () => {
  const {Ch34xDriver, ch341Divisor} = await mod('usb-drivers.js');
  const calls = [];
  const device = {
    vendorId: 0x1a86, opened: false,
    configuration: {interfaces: [{interfaceNumber: 0, alternates: [{interfaceClass: 0xff, endpoints: [
      {type: 'bulk', direction: 'in', endpointNumber: 2, packetSize: 32}, {type: 'bulk', direction: 'out', endpointNumber: 2, packetSize: 32}]}]}]},
    async open() { this.opened = true; }, async claimInterface(n) { calls.push(['claim', n]); },
    async controlTransferIn(setup) { calls.push(['in', setup.request]); return {status: 'ok', data: new DataView(Uint8Array.from([0x31, 0]).buffer)}; },
    async controlTransferOut(setup) { calls.push(['out', setup.request, setup.value, setup.index]); return {status: 'ok'}; },
  };
  await new Ch34xDriver(device).open(250000);
  assert.deepEqual(calls[1], ['in', 0x5f]);
  assert.deepEqual(calls[2], ['out', 0xa1, 0, 0]);
  assert.deepEqual(calls[3], ['out', 0x9a, 0x1312, ch341Divisor(250000) | 0x80]);
  assert.deepEqual(calls[4], ['out', 0x9a, 0x2518, 0xc3]);
  assert.deepEqual(calls[5], ['out', 0xa4, 0xff9f, 0]);
});

test('line splitter handles CRLF and partial chunks', async () => {
  const {LineSplitter} = await mod('connection.js');
  const got = [];
  const s = new LineSplitter(l => got.push(l));
  s.push(new TextEncoder().encode('ok\r\nT:20'));
  s.push(new TextEncoder().encode('0.0 /0.0\nstart\n'));
  assert.deepEqual(got, ['ok', 'T:200.0 /0.0', 'start']);
});

test('parsers: temperatures, firmware, M503 settings', async () => {
  const p = await mod('printer.js');
  assert.equal(p.checksumLine(1, 'M115'), 'N1 M115*39');
  assert.equal(p.stripGcode('G1 X10 ; move'), 'G1 X10');
  const t = p.parseTemps('ok T:201.3 /205.0 B:59.9 /60.0 @:127 B@:0');
  assert.deepEqual(t.hotend, {current: 201.3, target: 205});
  assert.deepEqual(t.bed, {current: 59.9, target: 60});
  const info = p.parseFirmwareInfo(['FIRMWARE_NAME:Marlin 2.1.2.1 (Github) SOURCE_CODE_URL:x PROTOCOL_VERSION:1.0 MACHINE_TYPE:Ender-3 EXTRUDER_COUNT:1', 'Cap:AUTOREPORT_TEMP:1']);
  assert.equal(info.name, 'Marlin'); assert.equal(info.version, '2.1.2.1'); assert.equal(info.machine, 'Ender-3');
  assert.equal(info.caps.AUTOREPORT_TEMP, true);
  const s = p.parseSettings(['echo:  M204 P500.00 R500.00 T1000.00', 'echo:  M205 B20000.00 S0.00 T0.00 J0.080', 'echo:  M593 X F40.00 D0.10', 'echo:  M593 Y F35.50 D0.10']);
  assert.equal(s.M204.P, 500); assert.equal(s.M205.J, 0.08); assert.equal(s.M593.Y.F, 35.5);
  const f = p.describeFeatures(info, s);
  assert.equal(f.accelStyle, 'PRT'); assert.equal(f.jerkStyle, 'junction'); assert.equal(f.inputShaping, true);
  const old = p.describeFeatures({name: 'Marlin', version: '1.0.2', caps: {}}, {M204: {S: 800}, M205: {X: 10}});
  assert.equal(old.accelStyle, 'S'); assert.equal(old.jerkStyle, 'classic'); assert.equal(old.linearAdvance, false);
});

async function connectedPrinter(simOptions = {}) {
  const {MarlinSimulator} = await mod('simulator.js');
  const {SimulatedConnection} = await mod('connection.js');
  const {Printer} = await mod('printer.js');
  const sim = new MarlinSimulator({autoReport: false, ...simOptions});
  const conn = new SimulatedConnection(sim);
  await conn.open();
  const printer = new Printer(conn);
  const features = await printer.handshake();
  return {sim, conn, printer, features};
}

test('handshake over the simulator reads firmware and settings', async () => {
  const {printer, features} = await connectedPrinter();
  assert.equal(features.firmware, 'Marlin 2.1.2.1');
  assert.equal(features.linearAdvance, true);
  assert.equal(printer.settings.M204.P, 500);
  printer.stopTimers();
});

test('job streaming survives injected checksum errors (resend)', async () => {
  const {sim, printer} = await connectedPrinter({corruptEvery: 7});
  const lines = Array.from({length: 60}, (_, i) => `G1 X${i} Y${i} F3000`);
  const layers = [];
  const ok = await printer.runJob([';LAYER:0', ...lines, ';LAYER:1', 'G1 Z0.4'], {onLayer: n => layers.push(n)});
  assert.equal(ok, true);
  const moves = sim.received.filter(c => c.startsWith('G1 X'));
  assert.deepEqual(moves, lines, 'every line delivered exactly once, in order');
  assert.deepEqual(layers, [1, 2]);
  printer.stopTimers();
});

test('cancel runs the safe shutdown sequence', async () => {
  const {sim, printer} = await connectedPrinter({lineDelayMs: 1});
  const lines = Array.from({length: 2000}, (_, i) => `G1 X${i % 100} F3000`);
  const run = printer.runJob(lines);
  await new Promise(r => setTimeout(r, 30));
  printer.cancel();
  assert.equal(await run, false);
  assert.ok(sim.received.includes('M104 S0') && sim.received.includes('M140 S0'));
  printer.stopTimers();
});

test('trial transform rewrites temperatures, accel, retraction and restores settings', async () => {
  const {applyTrial, detectRetraction} = await mod('gcode-transform.js');
  const file = ['M140 S60', 'M104 S215', 'M190 S60', 'M109 S215', 'M82', 'G92 E0', 'M220 S100', ';LAYER:0',
    'M204 S1000', 'G1 X10 Y10 E1.0 F1800', 'G1 E-3 F2400', 'G0 X50 Y50', 'G1 E1.0 F2400', 'G1 X60 Y60 E2.0', 'M104 S210', 'M106 S255'];
  assert.equal(detectRetraction(file), 4);
  const {lines, report} = applyTrial(file, {hotend_temp_c: 205, accel_mm_s2: 1500, retract_mm: 2, speed_factor_pct: 120, fan_percent: 50},
    {features: {accelStyle: 'PRT', linearAdvance: true}, baseline: {M204: {P: 500}}});
  assert.ok(lines.includes('M104 S205') && lines.includes('M109 S205'), 'main temperature changed');
  assert.ok(lines.includes('M104 S200'), 'temperature offsets preserved (210 -> 200)');
  assert.ok(lines.includes('M204 S1500'));
  assert.ok(lines.includes('M220 S120'), 'slicer reset of M220 overridden');
  const iL0 = lines.indexOf(';LAYER:0');
  assert.equal(lines[iL0 + 1], '; KlipperLearn trial settings');
  assert.ok(lines.includes('G1 E-1 F2400'), 'retraction scaled 4 -> 2 mm (absolute E: 1 -> -1)');
  assert.ok(lines.includes('G1 E1 F2400'), 'unretraction returns to the same absolute E');
  assert.ok(lines.includes('G1 X60 Y60 E2.0'), 'later extrusion untouched: E is back in sync');
  assert.ok(lines.includes('M106 S128'));
  assert.equal(lines.at(-1), 'M204 P500');
  assert.ok(report.changed >= 6);
});

test('relative-E retraction scaling and firmware warnings', async () => {
  const {applyTrial} = await mod('gcode-transform.js');
  const file = ['M83', 'G1 X1 Y1 E0.5', 'G1 E-5 F2400', 'G0 X9', 'G1 E5.2 F2400', 'G1 X2 Y2 E0.4'];
  const {lines, report} = applyTrial(file, {retract_mm: 3, pressure_advance: 0.05}, {features: {linearAdvance: false}});
  assert.ok(lines.includes('G1 E-3 F2400'));
  assert.ok(lines.includes('G1 E3.2 F2400'), 'extra prime length kept');
  assert.ok(report.warnings.some(w => /M900/.test(w)));
  assert.ok(!lines.some(l => l.startsWith('M900')));
});

test('calibration generators produce bounded, well-formed G-code', async () => {
  const {CALIBRATIONS, DEFAULT_PROFILE, estimateSeconds, ringingFrequency, resonanceSweep} = await mod('calibration.js');
  const profile = {...DEFAULT_PROFILE};
  for (const [id, cal] of Object.entries(CALIBRATIONS)) {
    const out = cal.generate(profile, cal.defaults(profile));
    assert.ok(out.gcode.length > 50, id);
    let maxE = 0;
    for (const l of out.gcode) {
      const m = l.match(/^G[01] .*X(-?[\d.]+) Y(-?[\d.]+)/);
      if (m) { assert.ok(+m[1] >= 0 && +m[1] <= profile.bed_x && +m[2] >= 0 && +m[2] <= profile.bed_y, `${id} inside bed: ${l}`); }
      const e = l.match(/ E(-?[\d.]+)/); if (e) maxE = Math.max(maxE, +e[1]);
      assert.ok(!/NaN|undefined/.test(l), `${id}: ${l}`);
    }
    assert.ok(maxE < 12, `${id} no extreme extrusion (${maxE})`);
    if (cal.param) assert.equal(out.gcode.filter(l => l.startsWith(';KL_BAND')).length, out.values.length, id);
    assert.ok(estimateSeconds(out.gcode) > 10, id);
  }
  // 30 mm tube wall extrusion: E per mm matches the slic3r model for 0.45 x 0.2 mm on 1.75 mm filament.
  const tower = CALIBRATIONS.temperature.generate(profile, {start: 210, step: -5, count: 2}).gcode;
  assert.ok(tower.includes('M109 S210') && tower.includes('M109 S205'));
  assert.equal(ringingFrequency(100, 5, 10), 50);
  const sweep = resonanceSweep(profile, {fromHz: 20, toHz: 40, stepHz: 10});
  assert.deepEqual(sweep.freqs, [20, 30, 40]);
  assert.ok(!sweep.gcode.some(l => / E/.test(l)), 'sweep never extrudes');
});

test('FFT finds a known accelerometer frequency and ringing period', async () => {
  const a = await mod('analysis.js');
  const rate = 200, f0 = 42;
  const samples = Array.from({length: 1024}, (_, i) => ({t: i * 1000 / rate, x: Math.sin(2 * Math.PI * f0 * i / rate), y: 0.01, z: 9.81}));
  const m = a.analyzeMotion(samples);
  assert.ok(Math.abs(m.axes.x.peakHz - f0) < 0.5, String(m.axes.x.peakHz));
  assert.ok(Math.abs(m.sampleRateHz - rate) < 1e-6);
  const w = 256, h = 20, data = new Uint8ClampedArray(w * h * 4);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) { const v = 128 + 60 * Math.sin(2 * Math.PI * x / 16); data.set([v, v, v, 255], (y * w + x) * 4); }
  const r = a.analyzeRinging({width: w, height: h, data}, {x: 0, y: 0, w, h}, {mmPerPx: 0.1, speedMmS: 80});
  assert.ok(Math.abs(r.periodPx - 16) < 0.5, String(r.periodPx));
  assert.ok(Math.abs(r.frequencyHz - 50) < 2, String(r.frequencyHz));
  const sweep = a.resonanceFromSweep([20, 30, 40, 50].map(f => ({freq: f, samples: Array.from({length: 50}, (_, i) => ({x: (f === 40 ? 3 : 1) * Math.sin(i), y: 0, z: 0}))})));
  assert.equal(sweep.peakHz, 40);
});

test('advisor: one bounded change per trial, reverts regressions, JEV-shaped candidates', async () => {
  const adv = await mod('advisor.js');
  const {buildAdvisorRequest, parseAdvisorResponse} = await mod('jev-client.js');
  const features = {jerkStyle: 'junction', linearAdvance: true, inputShaping: true};
  const params = adv.baselineParams({hotend_c: 210}, {M204: {P: 500}, M205: {J: 0.08}, M900: {K: 0}}, features);
  assert.equal(params.accel_mm_s2, 500);
  const base = {id: 't1', printerId: 'p', source: {hash: 'h'}, params, baseline: true,
    measured: {completed: true, seconds: 600}, human: {overall: 3, surface: 3, defects: {stringing: 2}}};
  const r1 = adv.recommend({last: base, history: [base], features, goal: 'balanced'});
  assert.equal(r1.decision.parameter, 'retract_mm');
  assert.ok(r1.decision.value > params.retract_mm && r1.decision.value - params.retract_mm <= 1.5);
  assert.equal(r1.candidates.at(-1).id, 'no_change');
  // Next trial made it worse: advisor must revert.
  const t2 = {id: 't2', parentId: 't1', printerId: 'p', source: {hash: 'h'}, params: adv.nextParams(params, r1.decision),
    changed: {param: 'retract_mm', from: params.retract_mm, to: r1.decision.value},
    measured: {completed: true, seconds: 600}, human: {overall: 1, surface: 1, defects: {stringing: 3}}};
  const r2 = adv.recommend({last: t2, history: [base, t2], features, goal: 'balanced'});
  assert.equal(r2.reason, 'revert');
  assert.equal(r2.decision.value, params.retract_mm);
  // No defects + speed goal: explore faster.
  const good = {...base, id: 't3', human: {overall: 5, surface: 5, defects: {}}};
  const r3 = adv.recommend({last: good, history: [good], features, goal: 'speed'});
  assert.equal(r3.decision.parameter, 'speed_factor_pct');
  // Ringing with a measured resonance proposes input shaping.
  const ring = {...base, id: 't4', human: {overall: 3, defects: {ringing: 3}}};
  const r4 = adv.recommend({last: ring, history: [ring], features, measuredShaper: {x: 48.2, y: 36}});
  assert.equal(r4.decision.parameter, 'shaper_freq_x');
  // Score weights: 40 % measured + 60 % human.
  const s = adv.scoreTrial({measured: {completed: true}, human: {overall: 5}}, null, 'balanced');
  assert.equal(s.total, 1);
  const req = buildAdvisorRequest({trial: base, history: [base], candidates: r1.candidates, goal: 'balanced', features});
  for (const c of req.candidates) assert.deepEqual(Object.keys(c).sort(), ['bounds', 'description', 'id', 'maximum_step', 'parameter', 'value']);
  assert.equal(parseAdvisorResponse({candidate_id: 'no_change', confidence: 0.9, provenance: 'jev'}, r1.candidates).candidate.id, 'no_change');
  assert.throws(() => parseAdvisorResponse({candidate_id: 'rm -rf'}, r1.candidates));
});

test('memory store export/import round trip', async () => {
  const {openStore} = await mod('store.js');
  const store = await openStore();
  await store.saveProfile({id: 'p1', name: 'A'});
  await store.saveTrial({id: 't1', printerId: 'p1', createdAt: 1});
  const dump = await store.exportAll();
  const other = await openStore();
  assert.deepEqual(await other.importAll(dump), {profiles: 1, trials: 1});
});

(async () => {
  let failed = 0;
  for (const t of tests) {
    try { await t.fn(); console.log('ok   ' + t.name); }
    catch (e) { failed++; console.error('FAIL ' + t.name + '\n     ' + (e.stack || e)); }
  }
  console.log(`${tests.length - failed}/${tests.length} phone-app tests passed`);
  process.exit(failed ? 1 : 0);
})();
