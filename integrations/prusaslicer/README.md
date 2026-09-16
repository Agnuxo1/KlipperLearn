# PrusaSlicer: read-only slice evidence

This is an external post-processing integration, not a PrusaSlicer fork or a
feature accepted by its maintainers. It reuses the canonical, independently
maintained [slice-manifest helper](../orca/klipperlearn_manifest.py); there is no
second copy of the hashing code and no printer connection.

## Use the existing helper

Keep the helper on your own computer and use an existing Python 3.8+ interpreter.
No KlipperLearn server, phone, API key or Python package installation is needed.
In PrusaSlicer, open **Print Settings -> Output options -> Post-processing scripts**.
Add one command line that invokes the helper. Use actual local absolute paths.
For example, on Windows:

```text
"C:\Python312\python.exe" "C:\KlipperLearn\integrations\orca\klipperlearn_manifest.py" --output-dir "C:\KlipperLearn\slice-manifests"
```

On Linux, the equivalent command is:

```text
/usr/bin/python3 /opt/KlipperLearn/integrations/orca/klipperlearn_manifest.py --output-dir /home/user/KlipperLearn/slice-manifests
```

These example paths are not installers. PrusaSlicer appends the absolute temporary
G-code path as the last argument; do not add your own model path to that setting.

## Evidence, not an optimization claim

The helper reads the file passed by the slicer and writes a content-addressed JSON
sidecar in the selected output directory. It does not alter the file, rename its
output, infer print settings, query a printer, upload anything or call an AI API.
It ignores `SLIC3R_PP_HOST` and `SLIC3R_PP_OUTPUT_NAME`; private names and network
addresses from that environment do not enter the manifest.

Place it last in a post-processing chain to fingerprint the bytes after earlier
scripts. This still does not certify the final delivered file: another export,
conversion or upload step can change it. Fingerprint the saved/transferred artifact
separately when exact final-file identity matters. No binary G-code conversion is
performed or claimed. A failed helper exits nonzero rather than fabricating a hash.

Keep original photos and observed layer settings separate. The sidecar identifies
a byte stream, not a physical print, an STL geometry, a validated profile or quality.
PrusaSlicer-native Quality/Standard/Speed preset import is not implemented by this
helper; do not import Orca JSON files as if they were PrusaSlicer presets.

## Verification and contribution route

`tests/test_prusaslicer_integration.py` exercises the appended-file contract with
spaces, Unicode, temporary names, a preceding simulated postprocessor, idempotence,
and no edits to G-code or `.output_name`. These are local contract tests, not an
installed-PrusaSlicer GUI test. Native UI acceptance remains to be performed.

Upstream references, checked 17 September 2026:
- https://help.prusa3d.com/article/post-processing-scripts_283913
- https://github.com/prusa3d/PrusaSlicer/blob/master/.github/CONTRIBUTING.md

PrusaSlicer's issue tracker is for reproducible bugs, not promotion. Keep this
external helper here unless a specific, tested upstream improvement is warranted.
