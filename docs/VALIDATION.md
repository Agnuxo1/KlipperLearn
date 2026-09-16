# Validation record — 2026-09-16

Scope: the new 0.1.0 research preview in this repository, not the historical
workstation application and not a physical printer installation.

## Executed locally

Environment: Linux container, Python 3.13.5, Node.js 22.16.0.

| Suite | Result | What it establishes |
| --- | --- | --- |
| Workspace exporter / history reader | 25 passed | Selected byte preservation, exclusions, bounded paginated GET requests, partial failures, redirect refusal and malformed-response handling. |
| Orca post-processing manifest | 9 passed | Exact SHA-256, unchanged source bytes, no private source path in output, idempotency, conflict refusal and invalid-file rejection. |
| JavaScript advisory core | 47 passed | Evidence gates, comparison logic, bounded non-executable proposals, schema export, stale proposals and unsupported-field rejection. |

**81 unit tests passed.** Fixtures are synthetic; HTTP servers in these tests are
local simulations. These results do not prove physical safety, reliable Android
USB, printed quality or the accuracy of a neural model.

## UI inspection

A Chromium in-memory DOM harness exercised loading four synthetic records, local
analysis, external-request download, proposal acceptance/rejection and a 390-pixel
mobile viewport. There were no JavaScript page errors or network requests in that
harness and no horizontal page overflow. Desktop and mobile layouts were visually
inspected. The returned proposal remained explicitly non-executable.

Browser navigation in this validation environment was blocked by an administrator
policy. No policy was changed. The harness injected the actual local HTML, CSS and
JavaScript into an in-memory page; its CSP meta element was omitted in memory to
allow that test injection. Consequently this is **not a deployed-page, CSP,
static-asset-loading or real-phone test**. The shipped HTML retains its restrictive
CSP. The standalone unit tests do not require this harness.

## Not executed

- Android application build, USB-host installation, long-duration phone operation,
  simultaneous OTG charging or phone sensor capture.
- Desktop OrcaSlicer UI installation or an actual slicer-triggered adapter run.
  The adapter was exercised as a CLI, including file preservation.
- Live Moonraker, Mainsail, Klipper, camera or printer interactions.
- A trained visual model, calibrated probabilities or comparative printed trials.
- Any motion, heating, firmware change or unattended calibration.

CI configuration covers offline tests on Python 3.10 and 3.13, with Node.js 22.
The presence of a workflow file is not evidence that a remote run has passed;
consult the actual GitHub Actions result for the commit being reviewed.

## Reproduce

From the repository root:

```sh
python -m unittest discover -s tools/exporter/tests -v
python -m unittest discover -s tests -p 'test_*.py' -v
node --test tests/core.test.js
python tools/check_repository.py
```

Do not reuse historical test counts from conversation logs as results of this
publication. Re-run the original application tests after a reviewed source import.
