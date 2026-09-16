# Changelog

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
