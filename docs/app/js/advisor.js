// SPDX-License-Identifier: GPL-3.0-or-later
// Local, deterministic trial advisor. It changes ONE parameter per trial, inside bounds,
// learns from comparable trials (same printer + same test part) and scores each trial as
// 40 % measured evidence + 60 % human rating. It also emits bounded candidates in the
// klipperlearn JEV candidate format so an external advisor (JEV) can choose among them.

export const WEIGHTS = {measured: 0.4, human: 0.6};

export function parameterSpace(profile = {}, features = {}) {
  const maxHot = profile.max_hotend_c ?? 260, maxBed = profile.max_bed_c ?? 110;
  const space = {
    speed_factor_pct: {min: 50, max: 250, step: 10, maxStep: 25, label: {es: 'Velocidad global (%)', en: 'Speed factor (%)'}},
    accel_mm_s2: {min: 200, max: 6000, step: 250, maxStep: 750, label: {es: 'Aceleración (mm/s²)', en: 'Acceleration (mm/s²)'}},
    hotend_temp_c: {min: 170, max: maxHot, step: 5, maxStep: 10, label: {es: 'Temperatura boquilla (°C)', en: 'Hotend temperature (°C)'}},
    bed_temp_c: {min: 0, max: maxBed, step: 5, maxStep: 10, label: {es: 'Temperatura cama (°C)', en: 'Bed temperature (°C)'}},
    fan_percent: {min: 0, max: 100, step: 10, maxStep: 30, label: {es: 'Ventilador de capa (%)', en: 'Part fan (%)'}},
    retract_mm: {min: 0.2, max: 8, step: 0.5, maxStep: 1.5, label: {es: 'Retracción (mm)', en: 'Retraction (mm)'}},
    flow_percent: {min: 85, max: 115, step: 2, maxStep: 5, label: {es: 'Flujo (%)', en: 'Flow (%)'}},
  };
  if (features.jerkStyle === 'classic') space.jerk_mm_s = {min: 4, max: 20, step: 1, maxStep: 3, label: {es: 'Jerk (mm/s)', en: 'Jerk (mm/s)'}};
  else space.junction_deviation_mm = {min: 0.01, max: 0.2, step: 0.01, maxStep: 0.03, label: {es: 'Desviación de unión (mm)', en: 'Junction deviation (mm)'}};
  if (features.linearAdvance !== false) space.pressure_advance = {min: 0, max: 1.5, step: 0.02, maxStep: 0.1, label: {es: 'Avance lineal K', en: 'Linear advance K'}};
  if (features.inputShaping !== false) {
    space.shaper_freq_x = {min: 15, max: 120, step: 2, maxStep: 20, label: {es: 'Input shaping X (Hz)', en: 'Input shaping X (Hz)'}};
    space.shaper_freq_y = {min: 15, max: 120, step: 2, maxStep: 20, label: {es: 'Input shaping Y (Hz)', en: 'Input shaping Y (Hz)'}};
  }
  return space;
}

// Defects the user rates 0 (none) to 3 (severe); each maps to ordered single-variable actions.
export const DEFECTS = {
  ringing: {label: {es: 'Ondas/vibraciones (ghosting)', en: 'Ringing / ghosting'}, actions: [['shaper', 0], ['accel_mm_s2', -1], ['speed_factor_pct', -1]]},
  stringing: {label: {es: 'Hilos', en: 'Stringing'}, actions: [['retract_mm', +1], ['hotend_temp_c', -1]]},
  corner_bulge: {label: {es: 'Esquinas abultadas / costura', en: 'Bulging corners / seam blobs'}, actions: [['pressure_advance', +1], ['junction_deviation_mm', -1], ['jerk_mm_s', -1], ['accel_mm_s2', -1]]},
  under_extrusion: {label: {es: 'Falta de material / huecos', en: 'Under-extrusion / gaps'}, actions: [['hotend_temp_c', +1], ['speed_factor_pct', -1], ['flow_percent', +1]]},
  over_extrusion: {label: {es: 'Exceso de material / grumos', en: 'Over-extrusion / blobs'}, actions: [['flow_percent', -1], ['pressure_advance', +1]]},
  layer_shift: {label: {es: 'Capas desplazadas / pasos perdidos', en: 'Layer shift / skipped steps'}, actions: [['accel_mm_s2', -1], ['speed_factor_pct', -1]]},
  weak_layers: {label: {es: 'Capas débiles / se separan', en: 'Weak layer bonding'}, actions: [['hotend_temp_c', +1], ['fan_percent', -1], ['speed_factor_pct', -1]]},
  curling: {label: {es: 'Voladizos curvados', en: 'Curling overhangs'}, actions: [['fan_percent', +1], ['hotend_temp_c', -1]]},
  warping: {label: {es: 'Despegue / warping', en: 'Warping / poor adhesion'}, actions: [['bed_temp_c', +1], ['fan_percent', -1]]},
  elephant_foot: {label: {es: 'Pie de elefante', en: 'Elephant foot'}, actions: [['bed_temp_c', -1]]},
};

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const roundTo = (v, step) => { const d = Math.max(0, -Math.floor(Math.log10(step)) + 1); return Number((Math.round(v / step) * step).toFixed(d)); };

export function humanScore(human = {}) {
  const ratings = ['overall', 'surface', 'dimensions'].map(k => human[k]).filter(v => v >= 1 && v <= 5);
  if (!ratings.length) return null;
  const base = (ratings.reduce((a, b) => a + b, 0) / ratings.length - 1) / 4;
  const defects = Object.values(human.defects || {}).reduce((a, b) => a + (b || 0), 0);
  return clamp(base - 0.03 * defects, 0, 1);
}

// Measured evidence relative to a reference trial of the same part. Every indicator is optional.
export function measuredScore(m = {}, ref = null, goal = 'balanced') {
  const parts = [];
  parts.push([m.completed === false ? 0 : 1, 0.3]);
  if (m.seconds && ref?.seconds) {
    const speedup = ref.seconds / m.seconds;              // > 1 means faster than reference
    parts.push([clamp(0.5 + (speedup - 1) * 1.5, 0, 1), goal === 'speed' ? 0.4 : goal === 'quality' ? 0.05 : 0.2]);
  }
  if (m.ringing_contrast != null && ref?.ringing_contrast) parts.push([clamp(0.5 - (m.ringing_contrast / ref.ringing_contrast - 1), 0, 1), 0.2]);
  if (m.clicks_per_min != null) parts.push([clamp(1 - m.clicks_per_min / 30, 0, 1), 0.15]);
  if (m.sharpness != null && ref?.sharpness) parts.push([clamp(0.5 + (m.sharpness / ref.sharpness - 1) * 0.5, 0, 1), 0.1]);
  const w = parts.reduce((a, [, wt]) => a + wt, 0);
  return parts.reduce((a, [v, wt]) => a + v * wt, 0) / w;
}

export function scoreTrial(trial, ref, goal) {
  const measured = measuredScore(trial.measured, ref?.measured, goal);
  const human = humanScore(trial.human);
  const total = human === null ? null : WEIGHTS.measured * measured + WEIGHTS.human * human;
  return {measured, human, total};
}

function comparable(history, trial) {
  return history.filter(t => t.printerId === trial.printerId && t.source?.hash === trial.source?.hash && t.human && humanScore(t.human) !== null);
}

function directionMemory(trials, ref, goal) {
  // For each param+direction: how did past single-variable changes do versus their parent?
  const mem = {};
  const byId = Object.fromEntries(trials.map(t => [t.id, t]));
  for (const t of trials) {
    if (!t.changed || !t.parentId || !byId[t.parentId]) continue;
    const dir = Math.sign(t.changed.to - t.changed.from);
    const key = `${t.changed.param}:${dir}`;
    const delta = scoreTrial(t, ref, goal).total - scoreTrial(byId[t.parentId], ref, goal).total;
    (mem[key] = mem[key] || []).push(delta);
  }
  return mem;
}

function makeCandidate(space, param, current, dir, factor, reason) {
  const s = space[param];
  if (!s) return null;
  const from = current[param] ?? null;
  if (from === null) return null;
  const delta = clamp(s.step * factor, s.step, s.maxStep) * dir;
  const to = roundTo(clamp(from + delta, s.min, s.max), s.step);
  if (to === from) return null;
  return {id: `${param}_${dir > 0 ? 'up' : 'down'}`, parameter: param, value: to, from,
    bounds: [s.min, s.max], maximum_step: s.maxStep, description: reason};
}

// Main entry. `last` = the most recently rated trial; `history` = all trials.
// Returns {decision, candidates, best, reason}.
export function recommend({last, history = [], profile = {}, features = {}, goal = 'balanced', measuredShaper = null}) {
  const space = parameterSpace(profile, features);
  const noChange = {id: 'no_change', parameter: null, value: null, bounds: null, maximum_step: 0,
    description: 'Keep current settings; evidence is insufficient or the part already meets the goal.'};
  if (!last) return {decision: noChange, candidates: [noChange], reason: 'no_trials'};
  const trials = comparable(history.concat(history.includes(last) ? [] : [last]), last);
  const ref = trials.find(t => t.baseline) || trials[0] || last;
  const scored = trials.map(t => ({t, s: scoreTrial(t, ref, goal).total})).filter(x => x.s !== null);
  const best = scored.reduce((a, b) => (b.s > a.s ? b : a), scored[0] || {t: last, s: 0});
  const lastScore = scoreTrial(last, ref, goal).total;
  const mem = directionMemory(trials, ref, goal);
  const current = {...(last.params || {})};
  const candidates = [];
  const seen = new Set();
  const add = c => { if (c && !seen.has(c.id)) { seen.add(c.id); candidates.push(c); } };

  // 1. The last single change made things worse: go back to the best parameters.
  const regressed = last.changed && best.t !== last && lastScore !== null && best.s - lastScore > 0.03;
  if (regressed) {
    const p = last.changed.param;
    add({id: `${p}_revert`, parameter: p, value: best.t.params?.[p] ?? last.changed.from, from: current[p],
      bounds: space[p] ? [space[p].min, space[p].max] : null, maximum_step: space[p]?.maxStep ?? 0,
      description: `Last change of ${p} lowered the score (${lastScore.toFixed(2)} vs best ${best.s.toFixed(2)}): revert.`});
  }

  // 2. Fix the worst rated defect with the first viable action.
  const defects = Object.entries(last.human?.defects || {}).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]);
  for (const [name, sev] of defects) {
    for (const [param, dir] of DEFECTS[name]?.actions || []) {
      if (param === 'shaper') {
        if (measuredShaper && space.shaper_freq_x) {
          for (const ax of ['x', 'y']) {
            const f = measuredShaper[ax];
            if (f && space['shaper_freq_' + ax]) add({id: `shaper_${ax}_set`, parameter: 'shaper_freq_' + ax, value: roundTo(clamp(f, 15, 120), 1),
              from: current['shaper_freq_' + ax] ?? 0, bounds: [15, 120], maximum_step: 120,
              description: `Ringing rated ${sev}/3 and a ${f.toFixed(1)} Hz resonance was measured on ${ax.toUpperCase()}: enable input shaping.`});
          }
        }
        continue;
      }
      const bad = (mem[`${param}:${dir}`] || []).some(d => d < -0.03);
      if (bad) continue;
      add(makeCandidate(space, param, current, dir, 1 + 0.5 * (sev - 1),
        `${DEFECTS[name].label.en} rated ${sev}/3: ${dir > 0 ? 'increase' : 'decrease'} ${param}.`));
    }
  }

  // 3. No significant defect: explore toward the goal (faster for speed/balanced).
  const maxSev = defects.length ? defects[0][1] : 0;
  if (maxSev <= 1 && goal !== 'quality') {
    for (const param of ['speed_factor_pct', 'accel_mm_s2']) {
      const past = mem[`${param}:1`] || [];
      if (past.some(d => d < -0.03)) continue;
      const streak = past.filter(d => d >= 0).length;
      add(makeCandidate(space, param, current, +1, 1 + 0.5 * streak, `No major defects: try faster ${param}.`));
    }
  }
  candidates.push(noChange);
  const decision = candidates[0];
  return {decision, candidates: candidates.slice(0, 64), best: best.t?.id, bestScore: best.s,
    lastScore, reason: regressed ? 'revert' : decision.id === 'no_change' ? 'converged' : maxSev > 1 ? 'fix_defect' : 'explore'};
}

// Starting values: firmware settings (M503), the profile and, for a sliced file, the
// values detected in that file (so temperature/fan/retraction offsets start at zero).
export function baselineParams(profile = {}, settings = {}, features = {}, fileValues = {}) {
  const p = {
    speed_factor_pct: 100, flow_percent: 100,
    accel_mm_s2: settings.M204?.P ?? settings.M204?.S ?? 500,
    hotend_temp_c: fileValues.hotend_temp_c ?? profile.hotend_c ?? 205,
    bed_temp_c: fileValues.bed_temp_c ?? profile.bed_c ?? 60,
    fan_percent: fileValues.fan_percent ?? profile.fan_percent ?? 100,
    retract_mm: fileValues.retract_mm ?? profile.retract_mm ?? 5,
  };
  if (features.jerkStyle === 'classic') p.jerk_mm_s = settings.M205?.X ?? 10;
  else p.junction_deviation_mm = settings.M205?.J ?? 0.08;
  if (features.linearAdvance !== false) p.pressure_advance = settings.M900?.K ?? 0;
  if (features.inputShaping !== false) { p.shaper_freq_x = settings.M593?.X?.F ?? 0; p.shaper_freq_y = settings.M593?.Y?.F ?? 0; }
  return p;
}

// Keep only the fields accepted by the klipperlearn JEV candidate contract.
export function jevCandidate(c) {
  return {id: c.id, parameter: c.parameter, value: c.value, bounds: c.bounds, maximum_step: c.maximum_step, description: c.description};
}

// Build the parameters of the next trial from a chosen candidate.
export function nextParams(current, candidate) {
  const p = {...current};
  if (candidate && candidate.parameter) p[candidate.parameter] = candidate.value;
  return p;
}
