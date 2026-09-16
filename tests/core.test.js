/* Synthetic-only tests; never contact hardware. */
'use strict';
const test = require('node:test'), assert = require('node:assert/strict');
const core = require('../reference/core.js');
const sample = require('../reference/demo.js');
const fresh = () => JSON.parse(JSON.stringify(sample));
function proposal(s) {
  return {schema: 'klipperlearn.proposal.v1', session_id: s.session_id,
    baseline_trial_id: s.trials.at(-1).id, parameter: s.policy.parameter,
    from: 1100, to: 1200, reason: 'Synthetic comparison, not physical validation.',
    evidence_ids: [s.trials.at(-1).evidence_ids[0]]};
}
test('the synthetic example proposes a bounded step', () => {
  const r = core.advise(fresh()); assert.equal(r.proposed_value, 1200);
  assert.equal(r.action, 'propose_trial'); assert.equal(r.executable, false);
  assert.equal(r.trained_model_used, false); assert.equal(r.synthetic, true);
});
test('input is never mutated', () => {
  const s = fresh(), before = JSON.stringify(s); core.advise(s); core.advisorRequest(s);
  assert.equal(JSON.stringify(s), before);
});
test('empty session requires a baseline', () => {
  const s = fresh(); s.trials = []; assert.equal(core.advise(s).action, 'collect_baseline');
});
test('a single sample requires a repeat', () => {
  const s = fresh(); s.trials.pop(); assert.equal(core.advise(s).action, 'repeat');
});
test('missing historical repeat blocks comparison', () => {
  const s = fresh(); s.trials.shift(); assert.equal(core.advise(s).action, 'review_evidence');
});
test('quality degradation retains the previous setting', () => {
  const s = fresh(); s.trials[2].quality_score = s.trials[3].quality_score = 0.81;
  const r = core.advise(s); assert.equal(r.action, 'retain_previous'); assert.equal(r.proposed_value, 1000);
});
test('slower equal-quality trials do not count as improvement', () => {
  const s = fresh(); s.trials[2].duration_s = s.trials[3].duration_s = 120;
  assert.equal(core.advise(s).action, 'retain_previous');
});
test('quality floor is a hard gate', () => {
  const s = fresh(); s.trials[2].quality_score = s.trials[3].quality_score = 0.5;
  assert.equal(core.advise(s).action, 'inspect');
});
test('a bad baseline is not a reference', () => {
  const s = fresh(); s.trials[0].quality_score = s.trials[1].quality_score = 0.5;
  assert.equal(core.advise(s).action, 'inspect');
});
test('trial budget stops exploration', () => {
  const s = fresh(); s.policy.max_trials = 4; assert.equal(core.advise(s).action, 'budget_exhausted');
});
test('interval boundary is not a global-optimum claim', () => {
  const s = fresh(); s.policy.max = 1100; assert.equal(core.advise(s).action, 'envelope_reached');
});
test('decreasing search follows its declared direction', () => {
  const s = fresh(); s.policy.direction = 'decrease'; assert.equal(core.advise(s).proposed_value, 1000);
});
for (const status of ['failed', 'cancelled', 'interrupted']) {
  test(status + ' requires inspection, not retry', () => {
    const s = fresh(); s.trials[0].status = status; assert.equal(core.advise(s).action, 'inspect');
    assert.throws(() => core.validateProposal(s, proposal(s)));
  });
}
for (const [field, value] of [['quality_score', null], ['quality_source', 'unreviewed'],
  ['sensor_sync_valid', false], ['evidence_ids', []], ['duration_s', 0]]) {
  test('missing evidence gate: ' + field, () => {
    const s = fresh(); s.trials[0][field] = value; assert.equal(core.advise(s).action, 'review_evidence');
  });
}
for (const value of [NaN, Infinity, -1, '1100', true, null]) {
  test('reject nonnumeric/out-of-range parameter ' + String(value), () => {
    const s = fresh(); s.trials[0].value = value; assert.throws(() => core.advise(s));
  });
}
test('events are preserved and stop tuning', () => {
  const s = fresh(); s.trials[0].safety_events.push('layer_shift'); assert.equal(core.advise(s).action, 'inspect');
});
test('duplicate trial identifiers are rejected', () => {
  const s = fresh(); s.trials[1].id = s.trials[0].id; assert.throws(() => core.advise(s));
});
test('unvalidated neural scores cannot masquerade as human review', () => {
  const s = fresh(); s.trials[0].quality_source = 'CNN'; assert.throws(() => core.advise(s));
});
for (const field of ['script', 'gcode', '__proto__']) {
  test('unknown session field rejected: ' + field, () => {
    const s = fresh(); Object.defineProperty(s, field, {value: 'untrusted', enumerable: true});
    assert.throws(() => core.advise(s));
  });
}
test('external proposal is only a non-executable record', () => {
  const s = fresh(), r = core.validateProposal(s, proposal(s));
  assert.equal(r.executable, false); assert.equal(r.requires_human_approval, true);
});
for (const [key, value] of [['session_id', 'wrong'], ['baseline_trial_id', 'stale'],
  ['parameter', 'temperature_c'], ['from', 1000], ['to', 1501], ['to', 1300],
  ['to', 1100], ['to', '1200'], ['reason', ''], ['evidence_ids', ['invented']]]) {
  test('external proposal rejects ' + key + '=' + value, () => {
    const s = fresh(), p = proposal(s); p[key] = value; assert.throws(() => core.validateProposal(s, p));
  });
}
test('external proposal cannot smuggle G-code', () => {
  const s = fresh(), p = proposal(s); p.gcode = 'G28'; assert.throws(() => core.validateProposal(s, p));
});
test('request explains missing images and does not use a provider API', () => {
  const request = core.advisorRequest(fresh());
  assert.match(request.instructions, /not photographs/);
  assert.equal(request.schema, 'klipperlearn.advisor-request.v1');
});
test('all supported parameters share numeric validation', () => {
  for (const parameter of core.PARAMETERS) {
    const s = fresh(); s.policy.parameter = parameter; assert.equal(core.advise(s).parameter, parameter);
  }
});

test('advisor export includes a machine-readable closed response schema', () => {
  const schema = core.advisorRequest(fresh()).proposal_schema;
  assert.equal(schema.type, 'object'); assert.equal(schema.additionalProperties, false);
  assert.equal(schema.properties.to.type, 'number');
  assert.equal(schema.properties.session_id.const, sample.session_id);
  assert.equal(schema.required.length, 8);
});
