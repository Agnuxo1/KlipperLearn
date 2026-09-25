// SPDX-License-Identifier: GPL-3.0-or-later
// Optional external advisor (e.g. JEV behind the KlipperLearn host service).
// The public app never holds provider credentials: it only POSTs a compact state and the
// bounded candidates the local advisor already built, and accepts one of those candidates.
import {jevCandidate} from './advisor.js';

export function buildAdvisorRequest({trial, history, candidates, goal, features}) {
  const compact = t => ({id: t.id, parent: t.parentId || null, changed: t.changed || null,
    params: t.params, measured: t.measured || {}, human: t.human || {}, score: t.score || null});
  return {
    schema: 'klipperlearn.advisor-request/v1',
    goal,
    firmware: features ? {firmware: features.firmware, linearAdvance: features.linearAdvance, inputShaping: features.inputShaping} : null,
    weights: {measured: 0.4, human: 0.6},
    last: compact(trial),
    history: history.filter(t => t.source?.hash === trial.source?.hash).slice(-12).map(compact),
    candidates: candidates.map(jevCandidate),
  };
}

// Accept the answer only if it names one of the candidates we sent.
export function parseAdvisorResponse(response, candidates) {
  const id = response?.candidate_id ?? response?.decision?.candidate_id ?? response?.choice;
  const chosen = candidates.find(c => c.id === id);
  if (!chosen) throw new Error('Advisor chose an unknown candidate');
  return {candidate: chosen, confidence: Number(response.confidence ?? response.decision?.confidence ?? 0),
    provenance: String(response.provenance ?? 'unknown')};
}

export async function askAdvisor(endpoint, request, {timeoutMs = 20000} = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(endpoint, {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(request), signal: ctrl.signal, credentials: 'omit', referrerPolicy: 'no-referrer'});
    if (!res.ok) throw new Error(`Advisor HTTP ${res.status}`);
    return await res.json();
  } finally { clearTimeout(timer); }
}
