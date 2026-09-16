# External integrations

No integration described here means acceptance into an upstream repository.
The current tools do not require upstream code changes.

## Klipper and Moonraker

Use the existing Moonraker server's documented
[`GET /server/history/list`](https://moonraker.readthedocs.io/en/latest/external_api/history/)
endpoint. `tools/exporter/export_workspace.py` paginates with a cutoff, checks
unique job IDs and preserves incomplete results on failures. It is GET-only,
refuses redirects and environment proxies, and accepts literal private/loopback IPs.

Example on the same Linux host:

```sh
python tools/exporter/export_workspace.py --root ./existing-workspace --moonraker-url http://127.0.0.1:7125
```

A `401` or `403` is reported; authentication is not bypassed. Authenticated export
is not implemented. Use an approved export path from the existing interface rather
than weakening Moonraker authorization. TLS verification is never disabled.
The tools do not perform a transactional database backup or infer quality from status.

## Mainsail

Mainsail's history view and this exporter consume Moonraker data; the HTML `/history`
page is not the JSON endpoint. No scraping, replacement UI, injected browser extension
or patch to Mainsail is required for history export. The historical Samsung stream
must be recovered with its actual code and credentials; no sample endpoint is
advertised as an installed camera in this publication.

## OrcaSlicer

Use `integrations/orca/klipperlearn_manifest.py` through the documented
[post-processing scripts](https://github.com/OrcaSlicer/OrcaSlicer/wiki/others_settings_post_processing_scripts)
setting. This is a post-processing adapter, **not** the newer native Python plugin API.
Python 3.8+ is required. The script accepts the generated file as its positional
argument; Orca appends it when invoking the post-processing command.

For a development checkout in `C:\KlipperLearn` with a Python executable at
`C:\Python\python.exe`, a configured command is:

```text
"C:\Python\python.exe" "C:\KlipperLearn\integrations\orca\klipperlearn_manifest.py" --output-dir "C:\KlipperLearnEvidence\slice-manifests"
```

Paths in this example describe the installation, not hard-coded source settings.
Select the actual interpreter and checkout paths in the slicer's UI. Install the
adapter last if other post-processors alter G-code; the manifest identifies bytes
at the time this adapter ran, not later transformations or proof of actual printing.
Orca may use a temporary file, so the manifest goes into an explicit persistent
output directory rather than beside that temporary file.

The adapter never changes source bytes or inferred temperatures/speeds. Existing
conflicting manifests are not overwritten. Test with a non-printing fixture first;
CLI tests are not a claim of a completed Orca desktop integration test.

## Voron and other compatible machines

Treat each machine as a separate capability/configuration profile. Do not publish
unmeasured universal acceleration, pressure advance or temperature presets. A Voron
profile and supporting evidence can be contributed here without modifying Voron's
firmware or claiming support for every Voron build.
