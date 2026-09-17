/* Synthetic software fixture only; not a printer profile or measured benchmark. */
(function (root) {
  'use strict';
  const sample = {
    schema: 'klipperlearn.session.v1', session_id: 'synthetic-demo', synthetic: true,
    context: {printer_id: 'demo-printer', material_id: 'demo-material', geometry_id: 'demo-chart',
      mount_id: 'demo-fixed-mount', slicer_profile_id: 'demo-only',
      nozzle_mm: 0.4, layer_height_mm: 0.2, line_width_mm: 0.45},
    policy: {parameter: 'accel_mm_s2', min: 500, max: 1500, step: 100, direction: 'increase',
      minimum_quality: 0.8, quality_tolerance: 0.02, min_repeats: 2, max_trials: 12},
    trials: [
      {id: 'demo-a1', value: 1000, status: 'completed', duration_s: 100, quality_score: 0.85,
        quality_source: 'human', evidence_ids: ['synthetic-photo-a1'], safety_events: [], sensor_sync_valid: true},
      {id: 'demo-a2', value: 1000, status: 'completed', duration_s: 102, quality_score: 0.86,
        quality_source: 'human', evidence_ids: ['synthetic-photo-a2'], safety_events: [], sensor_sync_valid: true},
      {id: 'demo-b1', value: 1100, status: 'completed', duration_s: 95, quality_score: 0.86,
        quality_source: 'human', evidence_ids: ['synthetic-photo-b1'], safety_events: [], sensor_sync_valid: true},
      {id: 'demo-b2', value: 1100, status: 'completed', duration_s: 96, quality_score: 0.87,
        quality_source: 'human', evidence_ids: ['synthetic-photo-b2'], safety_events: [], sensor_sync_valid: true}
    ]
  };
  if (typeof module === 'object' && module.exports) module.exports = sample;
  else root.KlipperLearnDemo = sample;
}(typeof globalThis !== 'undefined' ? globalThis : this));
