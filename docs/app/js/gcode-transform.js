// SPDX-License-Identifier: GPL-3.0-or-later
// Apply a trial's parameters to an already-sliced G-code program while streaming it,
// so each trial can change one variable without re-slicing. Pure functions (testable).
//
// Trial parameters (all optional; null/undefined = leave the file as sliced):
//   speed_factor_pct, flow_percent, accel_mm_s2, junction_deviation_mm, jerk_mm_s,
//   pressure_advance, shaper_freq_x, shaper_freq_y, hotend_temp_c, bed_temp_c,
//   fan_percent, retract_mm

const num = (cmd, letter) => { const m = cmd.match(new RegExp(`(?:^|\\s)${letter}(-?\\d*\\.?\\d+)`)); return m ? parseFloat(m[1]) : null; };
const setParam = (line, letter, value) => {
  const re = new RegExp(`((?:^|\\s)${letter})(-?\\d*\\.?\\d+)`);
  return re.test(line) ? line.replace(re, `$1${value}`) : `${line} ${letter}${value}`;
};
const code = line => { const i = line.indexOf(';'); return (i >= 0 ? line.slice(0, i) : line).trim(); };
const fmt = (v, d = 5) => String(Number(v.toFixed(d)));

// Most frequent non-zero value of a parameter for a family of commands: the file's "main" setting.
export function dominantValue(lines, regex, letter = 'S') {
  const counts = new Map();
  for (const l of lines) {
    const c = code(l);
    if (!regex.test(c)) continue;
    const v = num(c, letter);
    if (v !== null && v > 0) counts.set(v, (counts.get(v) || 0) + 1);
  }
  let best = null, bestN = 0;
  for (const [v, n] of counts) if (n > bestN || (n === bestN && v > best)) { best = v; bestN = n; }
  return best;
}

// Most common length of E-only retractions, to scale retraction proportionally.
export function detectRetraction(lines) {
  let relative = false, lastE = 0;
  const counts = new Map();
  for (const l of lines) {
    const c = code(l);
    if (/^M83\b/.test(c)) relative = true;
    else if (/^M82\b/.test(c)) relative = false;
    else if (/^G92\b/.test(c)) { const e = num(c, 'E'); if (e !== null) lastE = e; }
    else if (/^G[01]\b/.test(c)) {
      const e = num(c, 'E');
      if (e === null) continue;
      const delta = relative ? e : e - lastE;
      if (!relative) lastE = e;
      if (delta < 0 && !/\s[XYZ]-?\d/.test(' ' + c.slice(2))) {
        const r = Math.round(-delta * 100) / 100;
        counts.set(r, (counts.get(r) || 0) + 1);
      }
    }
  }
  let best = null, n = 0;
  for (const [r, k] of counts) if (k > n) { best = r; n = k; }
  return best;
}

// Values a sliced file already uses, so trial parameters start from the file itself.
export function fileValues(lines) {
  const fan = dominantValue(lines, /^M106\b/);
  return {
    hotend_temp_c: dominantValue(lines, /^M10[49]\b/),
    bed_temp_c: dominantValue(lines, /^M1(40|90)\b/),
    fan_percent: fan === null ? null : Math.round(fan / 2.55),
    retract_mm: detectRetraction(lines),
  };
}

// Klipper (through Moonraker) takes its own commands for accel, corner velocity, pressure
// advance and input shaping; speed/flow factors (M220/M221) are the same as Marlin.
export function klipperHeader(p) {
  const out = [];
  if (p.speed_factor_pct != null) out.push(`M220 S${Math.round(p.speed_factor_pct)}`);
  if (p.flow_percent != null) out.push(`M221 S${Math.round(p.flow_percent)}`);
  const lim = [];
  if (p.accel_mm_s2 != null) lim.push(`ACCEL=${Math.round(p.accel_mm_s2)}`);
  if (p.square_corner_velocity != null) lim.push(`SQUARE_CORNER_VELOCITY=${fmt(p.square_corner_velocity, 1)}`);
  if (lim.length) out.push('SET_VELOCITY_LIMIT ' + lim.join(' '));
  if (p.pressure_advance != null) out.push(`SET_PRESSURE_ADVANCE ADVANCE=${fmt(p.pressure_advance, 3)}`);
  const sh = ['x', 'y'].filter(a => p['shaper_freq_' + a] != null).map(a => `SHAPER_FREQ_${a.toUpperCase()}=${fmt(p['shaper_freq_' + a], 1)}`);
  if (sh.length) out.push('SET_INPUT_SHAPER ' + sh.join(' '));
  if (p.retract_mm != null) out.push(`SET_RETRACTION RETRACT_LENGTH=${fmt(p.retract_mm, 2)}`);
  const warn = [];
  if (p.jerk_mm_s != null || p.junction_deviation_mm != null) warn.push('Klipper uses square_corner_velocity; jerk/junction deviation ignored.');
  return {commands: out, warnings: warn};
}

export function klipperRestore(k = {}) {
  const out = ['M220 S100', 'M221 S100'];
  const lim = [];
  if (k.max_accel != null) lim.push(`ACCEL=${Math.round(k.max_accel)}`);
  if (k.square_corner_velocity != null) lim.push(`SQUARE_CORNER_VELOCITY=${fmt(k.square_corner_velocity, 1)}`);
  if (lim.length) out.push('SET_VELOCITY_LIMIT ' + lim.join(' '));
  if (k.pressure_advance != null) out.push(`SET_PRESSURE_ADVANCE ADVANCE=${fmt(k.pressure_advance, 3)}`);
  return out;
}

export function headerCommands(p, features = {}) {
  if (features.klipper) return klipperHeader(p);
  const out = [];
  const warn = [];
  if (p.speed_factor_pct != null) out.push(`M220 S${Math.round(p.speed_factor_pct)}`);
  if (p.flow_percent != null) out.push(`M221 S${Math.round(p.flow_percent)}`);
  if (p.accel_mm_s2 != null) out.push(features.accelStyle === 'S' ? `M204 S${Math.round(p.accel_mm_s2)}` : `M204 P${Math.round(p.accel_mm_s2)}`);
  if (p.junction_deviation_mm != null) {
    if (features.jerkStyle === 'classic') warn.push('Firmware uses classic jerk; junction deviation ignored.');
    else out.push(`M205 J${fmt(p.junction_deviation_mm, 3)}`);
  }
  if (p.jerk_mm_s != null) {
    if (features.jerkStyle === 'junction') warn.push('Firmware uses junction deviation; classic jerk ignored.');
    else out.push(`M205 X${fmt(p.jerk_mm_s, 1)} Y${fmt(p.jerk_mm_s, 1)}`);
  }
  if (p.pressure_advance != null) {
    if (features.linearAdvance === false) warn.push('Firmware did not report Linear Advance (M900); K ignored.');
    else out.push(`M900 K${fmt(p.pressure_advance, 3)}`);
  }
  for (const ax of ['x', 'y']) {
    const f = p['shaper_freq_' + ax];
    if (f == null) continue;
    if (features.inputShaping === false) warn.push('Firmware did not report input shaping (M593); shaper ignored.');
    else out.push(`M593 ${ax.toUpperCase()} F${fmt(f, 1)}`);
  }
  if (p.retract_mm != null) out.push(`M207 S${fmt(p.retract_mm, 2)}`); // firmware retraction (G10) if used
  return {commands: out, warnings: [...new Set(warn)]};
}

export function restoreCommands(baseline = {}, features = {}) {
  if (features.klipper) return klipperRestore(baseline.klipper);
  const out = ['M220 S100', 'M221 S100'];
  const a = baseline.M204;
  if (a) out.push(features.accelStyle === 'S' ? `M204 S${a.S ?? a.P}` : `M204 P${a.P ?? a.S}`);
  const j = baseline.M205;
  if (j && j.J != null) out.push(`M205 J${j.J}`);
  else if (j && j.X != null) out.push(`M205 X${j.X} Y${j.Y ?? j.X}`);
  if (baseline.M900 && baseline.M900.K != null) out.push(`M900 K${baseline.M900.K}`);
  if (baseline.M593) for (const ax of ['X', 'Y']) if (baseline.M593[ax]?.F != null) out.push(`M593 ${ax} F${baseline.M593[ax].F}`);
  if (baseline.M207 && baseline.M207.S != null) out.push(`M207 S${baseline.M207.S}`);
  return out;
}

export function applyTrial(lines, p = {}, {features = {}, baseline = {}, limits = {}} = {}) {
  const maxHot = limits.max_hotend_c ?? 260, maxBed = limits.max_bed_c ?? 110;
  const report = {changed: 0, warnings: []};
  const header = headerCommands(p, features);
  report.warnings.push(...header.warnings);

  const mainHot = p.hotend_temp_c != null ? dominantValue(lines, /^M10[49]\b/) : null;
  const mainBed = p.bed_temp_c != null ? dominantValue(lines, /^M1(40|90)\b/) : null;
  const mainFan = p.fan_percent != null ? dominantValue(lines, /^M106\b/) : null;
  const baseRetract = p.retract_mm != null ? detectRetraction(lines) : null;
  const k = baseRetract ? p.retract_mm / baseRetract : 1;
  if (p.retract_mm != null && !baseRetract) report.warnings.push('No retraction moves found; only firmware retraction (M207) will change.');

  const out = [];
  let inserted = false;
  let relative = false, lastOrig = 0, lastNew = 0, retracted = 0;
  const insertHeader = () => {
    if (inserted) return;
    out.push('; KlipperLearn trial settings', ...header.commands);
    inserted = true;
  };

  for (const line of lines) {
    const c = code(line);
    let l = line;
    if (/^;\s*(LAYER:0\b|LAYER_CHANGE)/i.test(line)) { out.push(line); insertHeader(); continue; }

    if (/^M10[49]\b/.test(c) && mainHot) {
      const s = num(c, 'S');
      if (s > 0) { l = setParam(c, 'S', Math.min(maxHot, Math.round(s + p.hotend_temp_c - mainHot))); report.changed++; }
    } else if (/^M1(40|90)\b/.test(c) && mainBed) {
      const s = num(c, 'S');
      if (s > 0) { l = setParam(c, 'S', Math.min(maxBed, Math.round(s + p.bed_temp_c - mainBed))); report.changed++; }
    } else if (/^M106\b/.test(c) && mainFan) {
      const s = num(c, 'S') ?? 255;
      l = setParam(c, 'S', Math.max(0, Math.min(255, Math.round(s * (p.fan_percent / 100) * 255 / mainFan)))); report.changed++;
    } else if (/^M220\b/.test(c) && p.speed_factor_pct != null && num(c, 'S') !== null) {
      l = setParam(c, 'S', Math.round(p.speed_factor_pct)); report.changed++;
    } else if (/^M221\b/.test(c) && p.flow_percent != null && num(c, 'S') !== null) {
      l = setParam(c, 'S', Math.round(p.flow_percent)); report.changed++;
    } else if (features.klipper && /^SET_VELOCITY_LIMIT\b/i.test(c) && p.accel_mm_s2 != null && /\bACCEL=/i.test(c)) {
      l = c.replace(/\bACCEL=[\d.]+/i, `ACCEL=${Math.round(p.accel_mm_s2)}`); report.changed++;
    } else if (features.klipper && /^SET_PRESSURE_ADVANCE\b/i.test(c) && p.pressure_advance != null && /\bADVANCE=/i.test(c)) {
      l = c.replace(/\bADVANCE=[\d.]+/i, `ADVANCE=${fmt(p.pressure_advance, 3)}`); report.changed++;
    } else if (/^M204\b/.test(c) && p.accel_mm_s2 != null) {
      l = c;
      for (const letter of ['P', 'S']) if (num(l, letter) !== null) l = setParam(l, letter, Math.round(p.accel_mm_s2));
      if (l !== c) report.changed++;
    } else if (/^M900\b/.test(c) && p.pressure_advance != null && features.linearAdvance !== false) {
      l = setParam(c, 'K', fmt(p.pressure_advance, 3)); report.changed++;
    } else if (/^M205\b/.test(c) && p.junction_deviation_mm != null && num(c, 'J') !== null) {
      l = setParam(c, 'J', fmt(p.junction_deviation_mm, 3)); report.changed++;
    } else if (/^M83\b/.test(c)) relative = true;
    else if (/^M82\b/.test(c)) relative = false;
    else if (/^G92\b/.test(c)) {
      const e = num(c, 'E');
      if (e !== null) { lastOrig = e; lastNew = e; }
    } else if (/^G[01]\b/.test(c)) {
      const e = num(c, 'E');
      const hasXYZ = /\s[XYZ]-?\d/.test(' ' + c.slice(2));
      if (e !== null && baseRetract) {
        const deltaOrig = relative ? e : e - lastOrig;
        let deltaNew = deltaOrig;
        if (deltaOrig < 0) { deltaNew = deltaOrig * k; retracted += -deltaOrig; }
        else if (deltaOrig > 0 && retracted > 0) { deltaNew = deltaOrig + (k - 1) * retracted; retracted = 0; }
        if (!relative) { lastOrig = e; lastNew += deltaNew; }
        if (deltaNew !== deltaOrig || (!relative && Math.abs(lastNew - lastOrig) > 1e-9)) {
          l = setParam(c, 'E', fmt(relative ? deltaNew : lastNew));
          if (deltaNew !== deltaOrig) report.changed++;
        }
      }
      // No layer marker before the first extrusion: insert the settings right before it.
      if (!inserted && e !== null && e > 0 && hasXYZ) insertHeader();
    }
    out.push(l);
  }
  if (!inserted) insertHeader();
  out.push('; KlipperLearn restore', ...restoreCommands(baseline, features));
  return {lines: out, report};
}
