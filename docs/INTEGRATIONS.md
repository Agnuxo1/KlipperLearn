# External integrations

## Klipper and Moonraker

The companion uses Moonraker APIs for status, files, camera information and explicit
bounded controls. The default server is evidence-only; enabling `--moonraker`
installs the companion adapter. Read [installation](INSTALLATION.md) and
[safety](SAFETY.md) before configuring live access. Local pairing is a trusted-LAN
feature and must not be exposed as Internet authentication.

The read-only observer disables redirects and environment proxies and bounds HTTP
responses. The separate `tools/exporter/` utility retrieves paginated history and
prepares a filtered private review archive. Its output is not a ZIP to publish
wholesale. Neither a history status nor the absence of firmware errors establishes
physical print quality.

## Mainsail and cameras

KlipperLearn remains an external application. A deployment can expose its authenticated
snapshot/MJPEG endpoints through a restricted local proxy and register that camera
in Moonraker for Mainsail. Preserve existing cameras and verify proxy TLS and viewer
permissions. The camera must be active; snapshots expire after five seconds.
Do not reuse a full control token as a publicly exposed viewing URL.

Phone capture, torch control, wake locks and Wi-Fi recovery depend on the actual
browser and hardware. The release's camera tests use simulated devices, not a new
validation of the author's original Mainsail installation.

## OrcaSlicer

`orca_export.py` generates candidate overrides from reviewed values and existing
profiles. It preserves source profiles and does not silently edit the user's Orca
configuration. Re-slice and inspect the effective settings: inherited values and
G-code commands may override assumptions, especially acceleration and flow.

The separate post-processing adapter fingerprints an already-sliced file without
changing any G-code bytes:

```sh
python integrations/orca/klipperlearn_manifest.py --output-dir ./slice-manifests model.gcode
```

This establishes artifact identity, not a safe or optimal profile. The local Python
source tests verify the adapter; actual Orca UI installation must be checked in the
chosen environment.

## External models

The `reference/` reviewer exports a structured request and validates a manually
returned JSON proposal. It has no API key or printer transport. This release does
not automatically send application photographs to a cloud model. Keep manual
review and local action limits separate from model-generated recommendations.

## Upstream projects

No changes have been merged into Klipper, Moonraker, Mainsail, OrcaSlicer or Voron by
this publication. There is no upstream endorsement. Follow each community's
contribution process with a narrow, tested change rather than promotional issues.
