# KlipperLearn

**A smarter future for an older 3D printer — powered by an older phone.**

Phone-first, open-source calibration research for compatible Klipper printers.
Use camera and sensor evidence to compare a **3D calibration chart**, propose a
bounded adjustment, and evaluate the next trial without confusing speed with quality.

**Version 0.1.0 · research preview · advisory-only reference implementation.**
This publication is not the complete historical workstation application. That
source has not yet been imported. It does not ship a working Android Klipper host,
a trained CNN, sensor capture, or an unattended printer controller. See
[status and acceptance gates](docs/STATUS.md) before connecting any hardware.

## Two advisor modes, one project

| Mode | Intended product | Implemented in this publication |
| --- | --- | --- |
| **1. Local** | Phone-local sensor fusion, visual analysis and a small validated model, with no mandatory cloud service. | A dependency-free HTML/JavaScript reviewer with deterministic, one-variable comparisons and strict evidence gates. |
| **2. External advisor** | Optional multimodal review by ChatGPT or another capable model, through the same bounded proposal contract. | Local request export and validation of manually returned JSON. No API request, credential or paid service is required. |

Both modes share the same intended phone-host deployment. Advisor choice must not
change heater protections, device permissions, evidence requirements or operator control.
An advisor proposes; a separately validated controller would decide whether a
specific, explicitly approved action is permitted. That controller is not shipped here.

## Try the working reference reviewer

Python is only a convenient development server here, not a claim of Android hosting:

```sh
python -m http.server 8080 --bind 127.0.0.1 --directory reference
```

Open `http://127.0.0.1:8080`, select **Load synthetic example**, then choose
**Analyze locally** or **Export advisor request**. The example contains invented
measurements for software testing; its settings are **not a printer profile**.
To review real records, import a JSON session following the
[evidence contract](docs/EVIDENCE_CONTRACT.md). No files are uploaded by the UI.

The browser page has no network API, G-code field, printer connection, tracking,
external fonts or downloaded model weights. Its content security policy disables
network connections. Browser serving and permissions must still be tested on each
supported phone; the UI test environment is documented in [validation](docs/VALIDATION.md).

## Working integration tools

**Moonraker / Klipper / Mainsail:** a GET-only history reader and conservative
workspace exporter are included in `tools/exporter/`. It preserves source bytes,
reports exclusions, refuses redirects and public IP destinations, and retains
partial history without claiming a complete transactional snapshot.

```sh
python tools/exporter/export_workspace.py --root /path/to/existing/KlipperLearn --offline
python tools/exporter/export_workspace.py --root /path/to/existing/KlipperLearn --moonraker-url http://127.0.0.1:7125
```

The result is a **private review package**, not a ZIP to publish wholesale.

**OrcaSlicer:** a post-processing adapter records a content-addressed slice
manifest without changing a byte of G-code or contacting a printer:

```sh
python integrations/orca/klipperlearn_manifest.py --output-dir ./slice-manifests model.gcode
```

See [integration instructions](docs/INTEGRATIONS.md) for scope and verification.
These are external integrations, not features merged into or endorsed by upstream projects.

## Architecture and safety

The phone-only goal requires a real Klipper host runtime and reliable USB access
on the phone. **An HTML page alone does not provide that runtime.** The
[Android host design](docs/ANDROID_HOST.md) distinguishes the web interface,
native/OS service, USB bridge and printer MCU. The existing companion deployment
must not be presented as a validated replacement for a Raspberry Pi.

Read the [architecture](docs/ARCHITECTURE.md), [calibration protocol](docs/CALIBRATION_PROTOCOL.md),
[safety case](docs/SAFETY.md), [model card](docs/MODEL_CARD.md) and [privacy policy](docs/PRIVACY.md).
A `completed` job, a valid JSON file or a passing unit test is not evidence of good
print quality, mechanical safety or successful phone-only operation.

## Develop and test

Python 3.8+ and Node.js 18+ are sufficient for the offline unit tests. No production
Python or JavaScript dependencies are installed by these tools.

```sh
python -m unittest discover -s tools/exporter/tests -v
python -m unittest discover -s tests -p 'test_*.py' -v
node --test tests/core.test.js
python tools/check_repository.py
```

[Contributions](CONTRIBUTING.md) should be small, tested and supported by evidence.
The [upstream collaboration plan](docs/COMMUNITY.md) explicitly avoids promotional
issues, duplicate messages and unvalidated printer-control patches.

## License and attribution

MIT for the newly published material in this repository. Existing workstation
source and third-party assets must retain their own applicable licenses when
imported. No Klipper, Moonraker, Mainsail, OrcaSlicer, Voron or 3DBenchy code,
models, logos or trained weights are bundled. See [third-party notices](THIRD_PARTY_NOTICES.md).

Created by **Francisco Angulo de Lafuente**. Independent project; no upstream affiliation is claimed.
