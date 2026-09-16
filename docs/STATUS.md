# Publication status

Status reviewed: 2026-09-16. Release scope: 0.1.0 research preview.

## Available and executable

- Local HTML/JavaScript session reviewer and deterministic comparison engine.
- Strict session validation; explicit synthetic-data labels; missing-evidence gates.
- External-advisor request export and bounded JSON proposal validation.
- Read-only Moonraker history export and filtered source-review packaging.
- OrcaSlicer-compatible post-processing CLI for exact sliced-file fingerprints.
- Offline tests, public schemas, contribution guidance and safety documentation.

## Not included or not established

- The historical workstation source, its tests, records and exact dependency versions.
- Android packaging, a Klipper host on a phone, native USB access or a tested installer.
- Live phone sensor capture, camera streaming, microphone analysis or sensor fusion.
- A trained visual model, a representative training set or measured detection accuracy.
- Automatic slicing, device actuation, bed clearing or unattended recursive calibration.
- A measured speed/quality improvement on hardware using this publication.
- Acceptance, endorsement or integration into an upstream project's own repository.

The project history describes a more advanced local prototype. Descriptions and
reported historical test counts are not substitutes for its source or repeatable
results. This publication adds separately named reference and integration tools;
it does not silently replace `src/klipperlearn` or invent missing files.

## Product acceptance gates

1. Import the actual workstation snapshot with provenance, licenses and secret review.
2. Reproduce its tests and document dependencies; reconcile rather than overwrite changes.
3. Demonstrate a phone-only host on a named phone/OS/USB configuration, including
   charging, thermal behavior, process lifetime, reconnection and recovery.
4. Bind real, timestamped sensor/photo evidence to a specific print and immutable artifacts.
5. Validate a local visual model on held-out printers, mounts and materials, with
   uncertainty, abstention and false-positive/false-negative reporting.
6. Demonstrate bounded trials, non-overlapping placement or acknowledged bed clearing,
   failure recovery, safe cancellation and independent firmware protections.
7. Obtain real installation and usability results before claiming a production release.

Passing software tests closes none of the hardware or model-validation gates by itself.
