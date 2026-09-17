# Voron: physical-evidence review packet, not an untested user mod

No Voron has been physically tested for this release. The Flashforge and Anycubic
tests are not evidence of Voron compatibility. Do not submit an untested user mod
or relabel data from another printer as a Voron test.

The local packet checker helps an actual Voron owner assemble review evidence:

```sh
python -m klipperlearn.voron_review --packet voron-packet.json --assets-root ./original-photos --output review.json
```

The packet contract has `schema=klipperlearn.voron-evidence/v1`, `printer_id`,
`voron_model` (V0, Trident, V2.4, Switchwire or Legacy), `configuration_sha256`,
`benchmark_sha256`, `declarations` and `trials`. Start from
`examples/voron-packet.template.json`. Its false declarations and empty trial
list intentionally cannot pass; replace them only with actual evidence, never
as a way to satisfy software checks. No fabricated passing Voron example ships.

Declarations: `physical_printer_tested`, `operator_reviewed`, `license_reviewed`,
`mount_clearance_checked`, `thermal_limits_checked`. Each trial records distinct
`trial_id` and `session_id`, matching configuration/benchmark hashes, boolean
`completed`, unchanged `layer_height_mm` and `layer_count`, a safe relative
`photo` filename and its `photo_sha256`.

Two independent repeat sessions, consistent geometry/configuration and distinct
matching JPEG/PNG files are required for a packet ready for **human review**.
Linked files, path traversal, oversized files, mismatched hashes and mixed layer
settings are blocked. Matching bytes do not prove original photography, image
quality, machine identity, adequate safety or truthful declarations. Those
require inspection by the operator/reviewer. No result approves a VoronUsers
submission. A real CAD/STL modification must also meet that project's separate
licensing, attribution and source-file rules.

This tool never modifies the packet or photographs. No firmware settings,
motion commands, temperatures, untested mounts or universal speed profiles are
included. The workflow is useful before any community submission, not a
substitute for actually testing the modification on the target machine.

Official project: https://github.com/VoronDesign/VoronUsers

## Scope and contribution status

This is an independently maintained KlipperLearn integration. It is not an
upstream merge, official listing, endorsement, or physical-printer validation.
All new commands below run locally on supplied files and do not start a print.
No firmware, operating-system service or existing preset is modified.
