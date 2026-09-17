# Klipper: read-only compatibility and readiness review

KlipperLearn remains outside the firmware. Use an existing authorized connection
to capture `GET /printer/objects/query?webhooks&print_stats&toolhead&configfile`
through Moonraker, then review the saved JSON without further network activity:

```sh
python -m klipperlearn.ecosystem_evidence status --input status.json --output readiness.json
```

The dependency-free core or standalone ecosystem toolkit provides this command.
It distinguishes a parsed server response from Klipper readiness and an MCU
connection error. It extracts only configured kinematics, axis limits, nozzle
size and motion limits; macros and free-text error content are not copied.
Configured limits describe the supplied configuration, not measured hardware
capability or tuning recommendations. Missing values stay unknown.

The report always has `commands_allowed=false`, `freshness_verified=false` and
`safe_to_print_certified=false`. A saved ready state must never authorize a later
movement or heating operation. Existing guarded controllers still need current
state, explicit review and the ordinary printer safeguards.

Use `examples/ecosystem-status.json` as a synthetic, offline exercise. The actual
Flashforge Benchy tests were operator-plus-ChatGPT work, not the Anycubic
KlipperLearn chart/cube cohort; keep that distinction when reviewing evidence.

Official contracts:
- https://www.klipper3d.org/Status_Reference.html
- https://www.klipper3d.org/CONTRIBUTING.html

Klipper excludes experimental core changes and recommends Discourse for sharing
such work. This release does not submit a firmware patch or a DCO assertion.

## Scope and contribution status

This is an independently maintained KlipperLearn integration. It is not an
upstream merge, official listing, endorsement, or physical-printer validation.
All new commands below run locally on supplied files and do not start a print.
No firmware, operating-system service or existing preset is modified.
