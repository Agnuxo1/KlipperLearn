# Moonraker history evidence adapter

Use the documented history API or the existing read-only exporter to obtain a
local JSON `result.jobs` or `jobs` document. This adapter normalizes that document
without contacting Moonraker. Do not pass a website URL or Mainsail's HTML page.

From a source checkout, install only the dependency-free core in an isolated
Python 3.11+ environment (`python -m pip install .`), or unpack the standalone
**ecosystem toolkit** in `integrations/packages` and run from its directory:

```sh
python -m klipperlearn.ecosystem_evidence history --input history.json --printer-id printer-one --workflow operator_chatgpt --output history-review.json
```

The explicit workflow is one of `operator_chatgpt`, `klipperlearn`, `manual` or
`unknown`. Keep different physical printers and workflows in separate reports.
The program cannot derive that attribution from a model name or success status.

It preserves print and total duration separately; the difference is **nonprinting
time**, not automatically heating time. It rejects non-finite numbers, invalid
identifiers, reversed timestamps and duplicate IDs as timing evidence. Unknown
statuses never become completed prints. `exists` is kept as Moonraker's report,
not as independently verified file identity. It omits filenames, users, arbitrary
metadata and free-text errors. No normalized entry receives a quality score,
full-geometry approval or benchmark eligibility automatically. Even a completed
job can be a partial model or have poor quality. A page's `count` does not prove
the whole database was exported.

An example is `examples/ecosystem-history.json`; it is synthetic. Original print
logs remain private. If an output exists, the tool refuses to overwrite it.

Official contract: https://moonraker.readthedocs.io/en/latest/external_api/history/

## Scope and contribution status

This is an independently maintained KlipperLearn integration. It is not an
upstream merge, official listing, endorsement, or physical-printer validation.
All new commands below run locally on supplied files and do not start a print.
No firmware, operating-system service or existing preset is modified.
