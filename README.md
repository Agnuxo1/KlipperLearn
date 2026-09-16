<p align="center">
  <img src="https://github.com/user-attachments/assets/122cfb10-01cd-4fd9-9c8f-4e0828812500" width="1200" alt="KlipperLearn concept: an older phone alongside a legacy 3D printer, with a camera and sensor dashboard." />
</p>

# KlipperLearn

**Same printer. More possibilities.**

Modernize a compatible legacy 3D printer with an older Android phone: a touchscreen,
Wi-Fi connectivity, camera and sensor evidence, and repeatable calibration trials.
The goal is to use the phone as the Klipper host over USB, without a Raspberry Pi,
and improve print quality and speed through measured comparisons.

**Current release: 0.1.0 research preview — advisory tools, not a complete printer controller.**
The original workstation application has not yet been imported. This public release
provides a working offline reviewer and integration utilities; it does not yet ship
a phone-host installer, live sensor capture, a trained visual model or autonomous
printing. See the [implementation status](docs/STATUS.md).

[Quick start](#quick-start) · [Two modes](#two-advisor-modes) ·
[Calibration loop](#the-3d-calibration-chart) · [Integration tools](#integration-tools) ·
[Workshop progress](#workshop-progress) · [Contribute](CONTRIBUTING.md)

> **About the images:** the header and diagrams are AI-generated concept illustrations,
> not screenshots or compatibility evidence. The workshop poster is an AI-retouched
> presentation of a supplied photograph. Values and apparent surface finish in these
> images are not verified measurements or recommended printer settings.

## Two advisor modes

Both modes aim to run on the same phone-host architecture. They differ in who
analyzes the evidence, not in the safety limits or permission to operate the printer.

| Mode | Product goal | Available in this release |
| --- | --- | --- |
| **1. Local** | Phone-local sensor fusion, visual analysis and a small validated model, with no mandatory cloud service. | A dependency-free HTML/JavaScript reviewer with deterministic, one-variable comparisons and evidence gates. No trained CNN is included. |
| **2. External advisor** | Optional multimodal review by ChatGPT or another capable model. | Export a structured request and validate manually returned JSON. No API call, credential or paid service is required by the reference tools. |

<p align="center">
  <img src="https://github.com/user-attachments/assets/82527f6a-5a08-4163-8390-742567cbb2d2" width="1100" alt="Concept comparison of local analysis and an external multimodal advisor using the same evidence and bounded proposal contract." />
</p>

*Concept illustration: local and external analysis share an evidence format.
The illustrated automatic analysis and printer-configuration controls are product
ideas, not functions shipped in this preview.*

An advisor proposes a change. A separately validated controller would decide
whether an explicitly approved action is permitted. That controller is not shipped
here; the current reviewer cannot move, heat or start a printer.

## Quick start

Run the existing reference reviewer locally:

```sh
python -m http.server 8080 --bind 127.0.0.1 --directory reference
```

Open `http://127.0.0.1:8080`, select **Load synthetic example**, then choose
**Analyze locally** or **Export advisor request**.

The example uses invented measurements for software testing, not a printer profile.
Import real JSON sessions using the [evidence contract](docs/EVIDENCE_CONTRACT.md).
The UI does not upload your files, contact a printer or download model weights.
Its content security policy disables network API connections.

Python serves the development page; this command does **not** install Klipper on
Android. See [validation](docs/VALIDATION.md) for the environments actually tested.

## Phone-first architecture

The intended system separates four responsibilities: the phone's user interface
and evidence collection, a real Klipper host runtime, the printer MCU, and the
slicing workflow. **An HTML page alone does not provide the Klipper host or native
USB access.** The [Android host design](docs/ANDROID_HOST.md) documents that boundary.

<p align="center">
  <img src="https://github.com/user-attachments/assets/d558722d-72fd-4b23-b44f-ed0d2bf19cfd" width="1100" alt="High-level concept diagram linking the phone, printer, slicing tools and experiment evidence store." />
</p>

*Conceptual data flow, not a deployment or wiring diagram. In the phone-only goal,
Klipper's host process and Moonraker run in a compatible phone runtime; the printer
MCU runs its firmware. The illustration's grouping of software under the printer
must not be read as placing all those services on the printer board.*

The historical companion arrangement must not be presented as a demonstrated
phone-only replacement for a Raspberry Pi. Phone/OS compatibility, USB transport,
charging, process lifetime and recovery still require documented tests.

## The 3D calibration chart

The **3D calibration chart** is the project's repeatable test-and-compare workflow:
print a known artifact, collect evidence, review the outcome, propose a bounded
change and compare the next trial against the baseline.

<p align="center">
  <img src="https://github.com/user-attachments/assets/42c81d3e-e645-4c4e-b94a-3b75909cc326" width="1100" alt="Concept loop: prepare a calibration artifact, print, capture evidence, review, propose an adjustment and compare the next trial." />
</p>

*Target workflow. The preview does not automate slicing, photography, bed clearing
or printer operation. Illustrated scores and parameter changes are synthetic;
multiple changes shown together are not the one-variable trial protocol.*

Comparisons need the same artifact and documented print settings. A shorter print
time is not enough: quality, failed trials, repeatability and missing evidence must
remain visible. Proposals stay within an operator-defined budget and limits; a
failure or an uncertain result must not be silently recorded as an improvement.

Read the [calibration protocol](docs/CALIBRATION_PROTOCOL.md),
[model card](docs/MODEL_CARD.md) and [safety case](docs/SAFETY.md).

## Integration tools

### Klipper, Moonraker and Mainsail

The GET-only history reader and conservative workspace exporter live in
`tools/exporter/`. They preserve source bytes, report exclusions, refuse redirects
and public-IP destinations, and retain partial history without claiming a complete
transactional snapshot.

```sh
python tools/exporter/export_workspace.py --root /path/to/existing/KlipperLearn --offline
python tools/exporter/export_workspace.py --root /path/to/existing/KlipperLearn --moonraker-url http://127.0.0.1:7125
```

The result is a **private review package**, not an archive to publish wholesale.
A Moonraker job marked `completed` records job completion, not a quality assessment.

### OrcaSlicer

The post-processing adapter records a content-addressed slice manifest without
changing the G-code or contacting a printer:

```sh
python integrations/orca/klipperlearn_manifest.py --output-dir ./slice-manifests model.gcode
```

See [integration instructions](docs/INTEGRATIONS.md) for scope and verification.
These are external tools; no incorporation into or endorsement by Klipper,
Moonraker, Mainsail, OrcaSlicer or Voron is claimed.

## Workshop progress

The project author reports iterative trials with the official 3DBenchy on a stock
Flashforge Creator Pro more than 12 years old, reaching an approximately
**20-minute print judged acceptable by the author, without reducing the layer count**.
This is a report about the historical workshop prototype, not a benchmark achieved
by the public reference reviewer.

<p align="center">
  <img src="https://github.com/user-attachments/assets/c2355c51-6cf1-4714-b0f1-a45a55a27c42" width="720" alt="AI-retouched presentation based on the author's workshop photograph of successive turquoise Benchy trials, illustrating reported progress toward a 20-minute print." />
</p>

*AI-retouched presentation based on a real workshop photograph supplied by the
author. The setting, labels and visible surfaces have been generated or altered;
this is not an unmodified experimental photograph. The report above is not
independently verified. Original photographs, G-code, logs and the layer-count
comparison are needed for a reproducible performance claim; the poster alone
cannot establish print quality, duration or unchanged geometry.*

## Develop and test

Python 3.8+ and Node.js 18+ are sufficient for the offline unit tests. These tools
require no third-party production Python or JavaScript packages.

```sh
python -m unittest discover -s tools/exporter/tests -v
python -m unittest discover -s tests -p 'test_*.py' -v
node --test tests/core.test.js
python tools/check_repository.py
```

The [validation record](docs/VALIDATION.md) distinguishes software checks from
hardware and model validation. Passing unit tests is not evidence of mechanical
safety or successful phone-only operation.

## Publication, privacy and contributions

The original application will be reviewed in a separate staging copy: preserve the
working installation, exclude credentials and private records, inspect licensing,
and reproduce its tests before merging. See the [source-import procedure](docs/SOURCE_IMPORT.md)
and [privacy policy](docs/PRIVACY.md). Adding a file to `.gitignore` does not remove
an already committed copy or sanitize Git history.

[Contributions](CONTRIBUTING.md) should be focused, tested and supported by evidence.
The [community plan](docs/COMMUNITY.md) avoids promotional issues, duplicate messages
and premature printer-control patches.

## License and attribution

MIT applies to the newly published source and documentation. Existing workstation
source and third-party materials retain their applicable licenses when imported.
No upstream firmware, slicer source, STL models or trained weights are bundled.
Illustrations reference product names but do not establish affiliation or endorsement.
See [third-party and visual notices](THIRD_PARTY_NOTICES.md).

Created by **Francisco Angulo de Lafuente**.
