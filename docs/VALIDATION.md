# Validation of the 0.5.1 source release

## Scope and reproducible commands

This review used the real workstation source identified as 0.5.0, copied into a
separate release directory and revised as 0.5.1. It did not connect tests to the
printer, change firmware, restart the existing service, or alter private evidence.

The original selected source snapshot contained 140 files. Its SHA-256 inventory
was checked after editing the publication copy; all originals remained unchanged.

| Check | Result on the review workstation |
| --- | --- |
| Original source baseline | 215 Python tests and 185 subtests passed. |
| Reviewed application | 275 Python tests and 185 subtests passed; zero failures. |
| Read-only exporter | 25 unittest tests passed against simulated endpoints. |
| JavaScript application programs | All 10 programs passed, including four real headless-browser suites using simulated devices/APIs. |
| Separate reference advisor | All 47 Node test cases passed. |
| Ruff E9/F source and test checks | No findings. |
| Source syntax | All imported and new Python modules parsed. |
| Runtime dependency audit | 19 resolved packages; no known vulnerabilities reported by pip-audit at review time. |
| Bandit | Two reviewed alerts: a rejected wildcard-listener literal and XML escaping, not XML parsing. No high-severity findings. |

The final Python run took 11.88 seconds on the review workstation. Subtests are
reported separately and are not counted again as independent top-level tests.
There were two third-party deprecation warnings from the Starlette HTTPX test
adapter and its AnyIO portal alias; neither was suppressed or treated as a pass
for a failed test.

## Environment

- Python 3.12.14 on Windows; Node.js 22.18.0.
- Headless Microsoft Edge through Playwright 1.63.0; fresh isolated browser contexts.
- FastAPI 0.141.1, Starlette 1.6.0, Uvicorn 0.52.4, HTTPX 0.28.1.
- Pydantic 2.13.5, Pillow 12.3.0, NumPy 2.5.3, OpenCV 5.0.0.93.
- Optional local model tests used PyTorch 2.14.0+cpu and torchvision 0.29.0+cpu.

These are observed review versions, not claims of compatibility with every version
allowed by dependency ranges. The optional training stack is not installed by the
standard Linux CI job; optional tests may be skipped there and must be interpreted
separately from the full Windows review.

## Commands

```sh
python tools/run_offline_tests.py
python -m unittest discover -s tools/exporter/tests -v
node scripts/run-node-tests.cjs
node --test tests/core.test.js
python -m ruff check src tests --select E9,F
python tools/check_repository.py
python -m build
```

Python source tests block outbound socket connections. The only exemption is the
internal Windows asyncio wake-up socket pair. Exporter tests use an isolated local
HTTP test server. Browser tests intercept requests and simulate camera frames,
permissions, uploads, connection failures and illumination; they send no printer
commands to real hardware.

## Continuous integration and artifacts

The GitHub workflow runs Python 3.11 and 3.13 with Node.js 22 on Linux, installs
Playwright Chromium, and checks source, packaging, Python and browser tests. Check
the commit-specific Actions result: a workflow file alone is not a passing run.
Wheel and source distribution builds are part of release validation. The source
distribution includes source, tests, documentation, licenses and approved images.

## What the tests do not establish

No native Android Klipper host, physical USB connection, new printer speed/quality
measurement, trained universal defect detector, automatic cloud advisor or
unattended safety guarantee was validated in this review. Historical workshop
reports are attributed to the author, not relabelled as measurements of this
release. Read [release review](RELEASE_REVIEW_0.5.1.md) and [status](STATUS.md).
