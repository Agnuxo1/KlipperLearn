# Ecosystem work log

## Initial preparation — 17 September 2026

- Confirmed public base commit 6bbc120 and used a separate source checkout.
- Confirmed canonical names, default branches and license metadata for ten targets.
- Read seven available project contribution files; reviewed the official VoronUsers
  submission rules separately. Root/.github/docs discovery is not exhaustive.
- Recorded OctoPrint AI restrictions, Mainsail contributor-vouch requirements,
  real DCO sign-offs, Klipper experimental exclusion and Voron physical testing.
- Created the ten-target ledger with distinct delivery/submission/acceptance states.
- Added a PrusaSlicer setup using the existing canonical fingerprint helper and
  five passing temporary-file contract tests; no helper duplication or G-code edits.
- Scheduled eight bounded rounds, 01:00–08:00 Europe/Madrid on 17 September.
- No upstream issue, PR, fork or promotional message was created in this round.
- No LAN scan, printer action, service update, payment or identity action occurred.

This preparation does not claim installed-PrusaSlicer acceptance, ten completed
integrations or upstream adoption. Subsequent rounds append exact artifacts, tests,
commit refs, submission URLs and blockers here. Preserve this log; do not replace
past test outcomes with a later aggregate that obscures what actually ran.

### Initial validation

The complete local suite passed 350 tests plus 185 subtests, including the five
new PrusaSlicer contract cases. Ruff E9/F and repository consistency passed.
Two pre-existing third-party deprecation warnings remain. The public-file scan
found no configured private host addresses, workstation paths or matched secret
formats in this change; this is a scoped scan, not a security certification.

## Round 1 — Cura read-only evidence adapter

- Re-read public `main` at `2004fd4`; no repository `AGENTS.md` exists.
- Rechecked canonical `Ultimaker/Cura`: active, default branch `main`, LGPL-3.0.
- Re-read current `CONTRIBUTING.md` and the current
  `plugins/PostProcessingPlugin/Script.py` contract before implementation.
- GitHub searches for the exact term `KlipperLearn` found 0 Cura issues and 0
  Cura pull requests. No upstream contact, fork or Marketplace action was made.
- Added `integrations/cura/KlipperLearnEvidence.py`, a Cura post-processing script
  that hashes the exact UTF-8 in-memory G-code stream, writes a content-addressed
  JSON manifest, and returns the original `data` list object unchanged.
- The manifest omits G-code, model names, source/output paths, LAN addresses and
  inferred settings. It explicitly does not claim identity with Cura's later
  serialized output file, geometry verification, quality assessment or printing.
- Added focused installation/semantics documentation and six contract tests.

### Round 1 validation

- `python -m pytest tests/test_cura_integration.py -q`: **6 passed**.
- `py_compile` passed for the adapter and its tests.
- A complete offline-suite attempt reached **353 passed, 1 skipped, 2 failed**.
  Both failures were existing real-inference smoke tests blocked because this clean
  runner has PyTorch `2.6.0+cu124`, while KlipperLearn intentionally requires a
  stable PyTorch `>=2.10.0` before loading checkpoints.
- Re-running the offline suite with only those two environment-gated smoke tests
  deselected produced **353 passed, 1 skipped, 2 deselected**.
- `tools/check_repository.py` passed after that regression run.
- `ruff` was not available in this clean Python environment; no Ruff result is
  claimed for this round. Python compilation and tests above are the recorded
  syntax/static fallback.

The adapter is **prepared and contract-tested in our repository only**. It is not
claimed as natively installed in Cura, accepted by Ultimaker, listed in Marketplace,
or verified against final saved-file bytes. No printer, slicer profile, Linux
service, LAN host, credential or physical hardware was changed.

### Round 1 publication

- Published commit 754e091 to the project repository after its branch CI passed on Python 3.11 and 3.13.
- CI run: https://github.com/Agnuxo1/KlipperLearn/actions/runs/35160751083
- main was advanced by fast-forward only; no force push was used.
- Cura upstream remains **not submitted / not accepted**; no fork or external message was created.


## Round 2 ? OctoPrint external evidence plugin

- Re-read public `main` at `3b6ec40`; the KlipperLearn repository still has no
  root `AGENTS.md`. The authoritative next priority was OctoPrint.
- Rechecked canonical `OctoPrint/OctoPrint` (`dev`) and current `CONTRIBUTING.md`
  plus `AGENTS.md`. Core AI-authored contributions are prohibited, so no OctoPrint
  core code, issue, PR description or reviewer message was generated or submitted.
- Rechecked the official Plugin Repository registration guide. It supports an
  `ai-developed` attribute but requires active maintainer responsibility and an
  understanding of the implementation without depending on generative AI.
- GitHub searches for the exact term `KlipperLearn` found 0 OctoPrint issues,
  0 OctoPrint pull requests and 0 plugin-repository pull requests.
- Added a separately maintained modern `pyproject.toml` OctoPrint plugin under
  `integrations/octoprint/plugin/`. It listens only to `FileAdded`, `PrintStarted`,
  `PrintDone`, `PrintFailed` and `PrintCancelled`.
- Event handling is bounded and non-blocking: the OctoPrint event callback only
  queues a task. One daemon worker hashes local files and writes manifests.
- Manifests exclude G-code bodies, absolute host paths, users/owners, connector
  identifiers, IP addresses and printer commands. Non-local files are ignored.
- Added a registration-readiness checklist instead of making an invalid or
  maintenance-unverified directory submission.

### Round 2 validation

- `python -m pytest tests/test_octoprint_integration.py -q`: **7 passed**.
- Full offline regression with the same two environment-gated PyTorch smoke tests
  deselected: **360 passed, 1 skipped, 2 deselected**.
- Ruff E9/F passed for the plugin and focused tests; Ruff formatting was applied.
- `pip wheel` produced `octoprint_klipperlearnevidence-0.1.0-py3-none-any.whl`;
  SHA-256: `3ffe943eb84ff3056a85a127f06035d9f7292251652a3996c8ed1653a9928a52`.
  Wheel inspection confirmed the `octoprint.plugin` entry point and bundled GPL
  license files. The wheel is a local validation artifact, not an official release.

The integration is **prepared and contract-tested in our repository only**. It is
not claimed as installed in a real OctoPrint instance, listed in the official
Plugin Repository, accepted by OctoPrint maintainers or physically printer-tested.
No printer, server, LAN host, firmware, credential or paid service was touched.

### Round 2 publication

- Published reviewed branch `integration/octoprint-evidence-20260917` at commit `2ba7ae9`.
- GitHub Actions run: https://github.com/Agnuxo1/KlipperLearn/actions/runs/35165372760
- Both Python 3.11 and 3.13 jobs passed the complete CI workflow, including source/package validation, outbound-blocked application tests, simulated exporter tests and browser/JavaScript tests.
- OctoPrint upstream and the official Plugin Repository remain **not submitted / not accepted**. No fork, issue, PR, directory entry or maintainer message was created.
