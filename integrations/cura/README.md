# Cura integration: read-only post-processing evidence

This integration uses Cura's existing `PostProcessingPlugin` script contract. It
records a content-addressed JSON manifest and returns Cura's `data` list unchanged.
It does **not** upload G-code, alter temperatures, change motion commands, start a
print, infer quality, or claim that the later saved file has identical bytes.

Upstream references checked on 17 September 2026:

- `Ultimaker/Cura` is the canonical active repository and uses `main`.
- `plugins/PostProcessingPlugin/Script.py` defines `execute(data: List[str])` as
  receiving a list of G-code strings and returning a list.
- Current bundled scripts use `getSettingDataString()` with JSON settings.
- Cura's CONTRIBUTING guide accepts focused source pull requests, but this
  integration remains in KlipperLearn until native Cura acceptance is tested.

## Install for a source/development Cura checkout

Copy `KlipperLearnEvidence.py` into Cura's
`plugins/PostProcessingPlugin/scripts/` directory, then restart Cura. Open
**Extensions → Post Processing → Modify G-Code**, add
**KlipperLearn Evidence (No G-code Changes)**, and choose an evidence directory
or leave it empty for `~/KlipperLearn/cura-slice-manifests`.

The exact per-user installation mechanism varies across packaged Cura releases.
This round does not claim Marketplace packaging or GUI installation acceptance.

## Evidence semantics

The SHA-256 is calculated over `"".join(data).encode("utf-8")` at the point Cura
invokes the post-processing script. The manifest deliberately contains no G-code,
source path, model name, machine address or user-selected output path. It records
segment count and `;LAYER:` marker count only as structural diagnostics.

Cura may subsequently serialize or transform the returned strings. Therefore the
manifest field `final_saved_file_verified` is always `false`. For byte identity of
the final saved file, use a file-based post-processing helper after the output is
written. Do not compare this in-memory hash directly with a final-file hash and
call a mismatch corruption without accounting for Cura's writer behavior.

If evidence writing fails, the script logs a generic error and still returns the
original list object unchanged. Existing conflicting manifests are never replaced.
The 512 MiB in-memory evidence limit is a defensive bound, not a Cura file-size
limit.

## Validation scope

`tests/test_cura_integration.py` stubs only the minimal Cura `Script` and `Logger`
interfaces. It verifies exact UTF-8 hashing, absence of G-code/path content in the
manifest, unchanged list identity and contents, fail-open printing behavior,
conflict refusal and valid settings JSON. These tests are not a native Cura GUI,
Marketplace, slicing-engine or physical-printer test.
