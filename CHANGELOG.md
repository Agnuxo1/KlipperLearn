# Changelog

## Unreleased — KlipperLearn Phone (preview)

- Add a training dataset recorder (klipperlearn-dataset/v1): printer telemetry, accelerometer, audio features, knock and jam events with WAV clips, photos per layer/mid/final, human labels, ZIP export with manifest.jsonl.
- Add a Klipper/Moonraker mode: same-origin connection when the app is served on the Klipper machine, trial upload and start, recording of jobs started elsewhere, Klipper-native trial commands with restore.
- Add tools/migrate_bed_trials_to_dataset.py and a read-only Termux check (tools/android/phone_host_check.sh) for the phone-as-host route.
- Add a static, installable phone web app at `docs/app/` (GitHub Pages `/app/`).
- Control Marlin-compatible printers directly over WebUSB (CDC-ACM, CH340/CH341, CP210x, FTDI) or Web Serial.
- Add a browser G-code host with line numbers, checksums, resends, temperatures, pause, cancel and M112.
- Apply per-trial settings by rewriting the streamed G-code; restore firmware values after every job.
- Add slicer-free calibration generators and an experimental accelerometer resonance sweep.
- Add camera, microphone and accelerometer indicators, a 40/60 measured/human score and a one-change advisor.
- Add an optional external advisor (JEV) contract that can only choose among the app's bounded candidates.
- Validated with a simulated printer and headless Chromium only; physical Android USB acceptance is pending.

## 0.6.0 — File-first Printer Optimizer

- Add a portable skills-only plugin, repository marketplace and optional read-only MCP tools.
- Select three whole tested process/filament configurations with strict evidence gates.
- Preserve layer settings, geometry, temperatures, G-code and original presets.
- Validate one-variable AI proposals against exact session identities and declared limits.
- Add private-LAN API discovery with explicit consent, allowlisting and bounded requests.
- Add an original STL calibration coupon and a local file-review/export interface.
- Do not automatically print, call a paid model, install presets or register a public plugin.

## 0.5.2 — Linux host independence

- Document a persistent Linux backend, private-state migration and camera proxy removal.
- Expose a configured printer instance name and version in health/status.
- Distinguish a reachable server from an unready Klipper MCU; retain disabled controls.
- Permit dashboard access during an MCU error without repeating sensor onboarding.
- Gate persisted restoration commands behind explicit automatic-controller enablement.
- Add eight Python cases and an MCU-error browser scenario, all without hardware traffic.
- Clarify the logged Benchy timing and different layer counts separately from artwork.

## 0.5.1 — reviewed source release

- Import the original 0.5.0 application, browser companion and full test suites;
  preserve GPL-3.0-or-later and the separate MIT reference tools.
- Translate application messages and the touch interface into English; publish
  consolidated English guides and versioned, metadata-stripped artwork.
- Reject stale/cached live camera frames, malformed JSON, duplicate authentication
  headers, oversized request bodies, non-finite settings and invalid model outputs.
- Authenticate private session routes, disable their caching, validate read-only
  HTTP URLs and bound responses without following redirects.
- Block known-vulnerable optional checkpoint runtimes below PyTorch 2.10.0.
- Add exclusive private token-file creation and portable browser-test tooling.
- Extend tests, packaging and CI. No live printer actuation or service replacement
  is part of this publication. Phone-only Android hosting remains a development target.

## 0.1.0 — 2026-09-16

Initial research publication after a README-only repository.

Added a standalone advisory HTML reviewer; deterministic, bounded comparisons;
manual external-advisor exchange and validation; read-only workspace/history
export; exact sliced-file manifests for Orca post-processing; schemas, offline
tests, contribution templates and a documented safety boundary.

Explicitly not a release of the original workstation application, Android host,
trained CNN or automatic printer controller. Hardware and upstream acceptance
remain unverified. No historical performance figure is promoted as a release benchmark.
