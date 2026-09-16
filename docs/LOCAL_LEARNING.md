# Local evidence and bounded learning

## Evidence, not an unrestricted printer agent

The application associates print context, source-file hashes, telemetry intervals,
phone features, camera views and human ratings with durable trial records. Motion,
orientation and aggregated acoustic features are evidence only; their availability
does not mean lost steps or exact carriage position can be measured reliably.

The model and optimizer do not replace Klipper's safety protections. The manual
calibration adapter previews proposals, verifies current bounds, requires separate
confirmation to apply or restore, records readback, and does not blindly retry an
ambiguous physical operation. Automatic trial preparation is explicitly opt-in.

## Comparison protocol

Keep the same geometry, layer settings, material, nozzle, mounting and observation
conditions when comparing a change. Establish repeatable baselines. Change one
parameter at a time within configured bounds; record failures as failures rather
than replacing them with favourable estimates. Six zones on one bed are a screening
session, not six independent validation sessions.

The bounded quadratic optimizer requires reviewed observations and at least three
distinct parameter values. It may abstain, explore a nearby permitted value, or
propose a clipped local vertex. None of these outcomes establishes a global optimum.
Unverified macros or unresolved slicer overrides can invalidate an assumed change.

## Small local model

The lightweight model uses engineered image/sensor features and ridge regression.
It evaluates held-out sessions before marking a fitted model eligible within the
software workflow. This is not a CNN, a universal detector, or independent evidence
of dimensional quality. A model score learned from human ratings is an estimate,
not an objective physical measurement. Corrupt models, non-finite coefficients,
invalid feature shapes and out-of-distribution inputs cause abstention.

The optional MobileNet tools train a separate image classifier from trusted,
labelled data. Inference uses CPU execution, checks model metadata and output
finiteness, and requires PyTorch >= 2.10.0. No random or untrained weights should be
presented as a validated quality model. No pretrained checkpoint ships in this repo.

## Captures and persistence

Private evidence is kept in local SQLite storage and controlled asset directories.
Browser queues retain sensor chunks across reloads/network failures. Raw audio is
not retained by the aggregate collector. Paired photographs require actual device
support for controllable lighting; missing or insufficient images remain explicit.
Live snapshots expire after five seconds; old cached images are not served as live.

Backups contain private material and must not be uploaded wholesale. The SQLite
snapshot and asset reads are not a transactionally atomic snapshot of the entire
filesystem. Consult the backup manifest before interpreting a changing experiment.

## Explicit limits

There is no independent unattended safety observer, robotic removal of completed
parts, verified native Android host, or automatic cloud advisor in this release.
Do not run another physical trial until bed clearance, current settings and prior
restoration have been checked. A human operator remains responsible for physical safety.
