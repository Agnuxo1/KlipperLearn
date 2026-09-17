# Direct ecosystem delivery — 17 September 2026

## Execution and baseline

The owner requested active work rather than continued scheduling. Two scheduled
rounds had already delivered Cura and OctoPrint adapters; pending rounds were then
disabled. This direct review started from main at
`0233f7d6dc2b921537137428bd7ad1e19ab7adcb`, with no active repository work lock.
All implementation and validation took place in isolated working environments.

## Concrete deliverables

Seven further project-specific paths now have runnable external tooling: Klipper
status diagnostics, Moonraker history normalization, Orca preset-bundle auditing,
Mainsail and Fluidd camera-proxy generation, KIAUH host preflight and Voron
physical-evidence consistency checks. Existing Cura, OctoPrint and PrusaSlicer
integrations have separate source distributions rather than visibility-only forks.
The [package index](../packages/README.md) provides four independent downloads.

The OctoPrint plugin is now 0.1.1. This review corrected unbounded file hashing,
acceptance of non-finite or boolean timing metrics, unrestricted failure-message
content and stale shutdown queues. It detects changed input files, restricts
record size, sanitizes failure reasons, and avoids logging private source paths.
Safe relative file names remain local evidence and may still need redaction.

The tools do not infer measured quality from job completion, treat different
layer counts as an unchanged comparison, or combine different printer/workflow
cohorts. The Flashforge Benchy series remains operator-plus-ChatGPT evidence;
the Anycubic 4Max Pro charts and cubes remain the separate KlipperLearn setup.

## Validation performed

- Complete local Python suite: **503 passed and 185 subtests passed**.
- JavaScript: **11 of 11 test programs passed**, including simulated-device
  execution in actual browser processes.
- Exporter: **25 tests passed**. Separate reference core: **47 tests passed**.
- Ruff E9/F and repository link/consistency checks passed.
- The four ZIP packages match their canonical sources and recorded hashes.
- The standalone toolkit executed with Python `-I -S`, without site-packages,
  using only synthetic fixtures and local files. It generated and audited six
  DEMO presets without network access or printer control.
- The independent OctoPrint 0.1.1 ZIP successfully built a wheel using pip.
- Actual Nginx 1.26.3 and a disposable loopback TLS backend passed seven groups
  of checks: verified TLS/header isolation, exact stream routing, forbidden
  writes/routes/query credentials, unavailable-camera behavior, redirect refusal,
  incorrect certificate identity, and network allowlist enforcement. See the
  [runtime result](validation/nginx-runtime.json). Temporary services were stopped.

Two pre-existing third-party deprecation warnings remain. These tests are not a
security certification, measured print-quality improvement or native GUI import.
GitHub Actions on the published commit is the authority for remote CI status.

## Unchanged boundaries

No printer movement, heating, firmware change, LAN scan, live Linux configuration
change, paid resource, upstream contact or identity-verification action occurred.
No official inclusion in ten repositories is claimed. Native Cura/OctoPrint/Orca
and frontend acceptance, physical Voron testing, competent human maintenance and
applicable upstream contribution requirements remain separate outstanding gates.
