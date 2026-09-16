# Session contract

Use `scripts/optimizer.py` as the executable validation authority. The example
`synthetic-session.json` is test data only, never a preset recommendation.

A `klipperlearn.slicer-session/v1` object has exactly:

- `printer`: brand, model, preset, nozzle_mm, firmware.
- `material`: the particular material being compared, as a non-empty string.
- `benchmark`: sha256 of the original model bytes, layer_height_mm, layer_count.
- `base_process` and `base_filament`: original sanitized exported Orca JSON objects.
- `limits`: fully qualified supported keys, each with min, max, max_step.
- `candidates`: id, process numerical overrides, filament numerical overrides.
  Include `baseline` with both override objects empty.
- `trials`: id, session_id, candidate_id, configuration_sha256, benchmark_sha256,
  layer_height_mm, layer_count, completed, full_model, print_seconds,
  total_seconds, surface_score, geometry_score, photo_sha256, human_reviewed.
- `policy`: minimum_repeats (2–10), quality_floor (1–5), maximum_time_cv (0–0.5).
- `synthetic`: boolean. Use true for examples, simulations and software fixtures.

The two quality scores are 0–5 (or null if not reviewed). Photos are arrays of
actual SHA-256 digests, not image analysis. Trial session IDs identify independent
physical jobs. Configurations are bound using `configuration_sha256(session,
candidate)` before printing, including bases, printer, material and benchmark.
Unknown historical bindings must remain in a separate unverified report; do not
invent a valid digest so that a historical result passes the gates.

Supported numerical overrides are listed in `PARAMETERS`: wall/infill/top/bridge
speeds, selected accelerations, filament volumetric cap, flow ratio and already
enabled Klipper pressure advance. The broad hard ceilings are input-rejection
limits, **not safe defaults or recommended values**. Supply machine-specific
bounds separately. Geometry, layer height, temperatures and G-code are locked.

An AI proposal has exactly schema (`klipperlearn.slicer-proposal/v1`),
session_sha256, anchor_candidate_id, parameter, value, evidence_trial_ids and
rationale. A valid response is an unprinted candidate; it does not add a completed
trial, install a profile or authorize physical actions.

The profile ZIP holds six named JSON files and a review report. Native import and
reslicing must be verified in the installed slicer. Original presets must remain
available for rollback. A synthetic session always produces conspicuous DEMO names.
