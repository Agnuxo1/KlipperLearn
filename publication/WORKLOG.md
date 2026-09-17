# Model-platform publication work log

## 2026-09-17T10:15:00.421419+00:00 - Direct owner request

Read main at `9e92d1e6173a87406dbeb2cfbe4e26d0ada2430f`, CONTRIBUTING.md and the ecosystem
state. No tracked AGENTS.md was present and no active ecosystem round was
recorded. This is a new direct request, not an extension of overnight automation.

Prepared an unchanged original 40 x 30 x 12 mm coupon with editable Python
exporter, complete-project links, GPL notices, geometry report, checksums, a
clearly labelled technical render and six platform-specific publication gates.
No unverified benchmark rankings, physical print tests or endorsements were added.

The native Printables session saved draft 1845028. The file-upload interaction
was denied by the tool safety check. The denied action was not retried through
an alternative interface. The saved draft contains no uploaded model files and
is not public. Do not create another draft when resuming.

Read MakerWorld's official model-upload rules in the native browser and verified
that an actual printed-object photo is required. The exact coupon has no such
verified photo. The unrelated Flashforge Benchy series is not suitable evidence.

Thingiverse, MyMiniFactory and Thangs displayed unauthenticated login controls.
Cults3D displayed a browser security challenge; no challenge was bypassed. The
current per-platform facts and remaining license/policy gates are in status.json.

Validation: 515 Python cases plus 194 subtests passed in the isolated environment;
4 optional cases were skipped, 2 dependency deprecations were reported. The 11
new packaging tests and Ruff E9/F checks passed. See validation.json. The first
global-environment test run had 2 unsupported-PyTorch failures; no safety guard
was relaxed to make the tests pass. No hardware, firmware, private network,
production service, account permission, payment or background task was touched.

AI assistance is disclosed. No DCO/CLA or human-review attestation was made.

Additional validation: all 12 JavaScript test programs passed using headless Edge
and synthetic endpoints; 47 reference-core tests and 25 exporter tests passed.
Repository consistency and whitespace checks passed.

Final code review found checkout-dependent line endings in the model archive.
Normalized distributed text to UTF-8/LF and added a regression that recreates a
CRLF checkout and requires byte-identical ZIP output. Final rerun: 516 cases,
194 subtests passed; 4 optional cases skipped; 2 dependency warnings. All 12
new packaging tests passed. Text file hashes use canonical UTF-8/LF so they
match Git blobs on Windows and Linux. Original coupon bytes are unchanged.
