# Evidence and proposal contract v1

The executable reference validator is `reference/core.js`. JSON Schemas in
`schemas/` describe structure; runtime validation also enforces relationships,
repeat requirements, evidence gates, policy bounds and proposal freshness.

## Session

`klipperlearn.session.v1` contains `session_id`, an explicit `synthetic` flag,
a fixed `context`, a `policy` and ordered `trials`. IDs are short opaque identifiers;
use pseudonyms rather than names, IPs, absolute paths or account information.

Context keys: `printer_id`, `material_id`, `geometry_id`, `mount_id`,
`slicer_profile_id`, `nozzle_mm`, `layer_height_mm`, `line_width_mm`.
A context is a declaration; the current validator does not resolve files or verify
that all runs physically share those conditions.

Policy keys: `parameter`, `min`, `max`, `step`, `direction`, `minimum_quality`,
`quality_tolerance`, `min_repeats`, `max_trials`. Parameters are limited to
`speed_mm_s`, `accel_mm_s2`, `temperature_c`, `pressure_advance_s`, `flow_ratio`,
`fan_percent`. Bounds are operator declarations, not certified safe hardware limits.
The general numeric validator's range is an encoding limit, not an operating limit.

Each trial contains `id`, `value`, `status`, `duration_s`, `quality_score`,
`quality_source`, `evidence_ids`, `safety_events`, `sensor_sync_valid`.
Unknown scores are `null`. Only reviewed human scores are accepted for comparisons
in this release. Model scores require a future validated model contract, not
renaming an untrained network's output. `sensor_sync_valid` is also a declaration.

Consecutive repeats at one value form a comparison group. Safety events and failed,
cancelled or interrupted jobs stop suggestions. Missing reviews, durations,
references or synchronization block tuning. Quality regressions or slower equal-
quality results retain the previous setting for review. All decisions are
non-executable and need human approval. This is a transparent heuristic, not a
statistical confidence estimate or learned controller.

## External advisor

Export a `klipperlearn.advisor-request.v1` package manually. It contains the session
and instructions; no photographs are embedded. Inspect and attach the relevant
photos separately to the chosen advisor. A reference ID alone is not an image.

A returned `klipperlearn.proposal.v1` must contain exactly `schema`, `session_id`,
`baseline_trial_id`, `parameter`, numeric `from` and `to`, `reason`, `evidence_ids`.
It must refer to the latest trial, the same variable and existing evidence. The
change must be nonzero, within bounds and no larger than one permitted step.
Other fields, including G-code or shell commands, are rejected. The full evidence
gate must pass before a proposal can be accepted as a record. No command is sent.

Example fixtures generated from `reference/demo.js` are explicitly synthetic.
For real use, provide actual observations and independently reviewed limits.
