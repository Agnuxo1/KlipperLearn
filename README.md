<p align="center"><img src="assets/hero.png" alt="KlipperLearn: a phone-first future for older 3D printers" width="100%"></p>

# KlipperLearn

**Keep the printer. Reuse the phone. Learn from real prints.**

[![Validation](https://github.com/Agnuxo1/KlipperLearn/actions/workflows/ci.yml/badge.svg)](https://github.com/Agnuxo1/KlipperLearn/actions/workflows/ci.yml)
[![License: GPL-3.0-or-later](https://img.shields.io/badge/core-GPL--3.0--or--later-blue)](LICENSE)

KlipperLearn combines a touch-friendly phone interface, local camera and sensor
evidence, reproducible calibration charts, and bounded tuning proposals for
compatible Klipper / Moonraker printers. Its purpose is to make existing machines
more useful rather than require a new printer.

**0.5.1 — reviewed source release.** This repository now contains the original
Python application and its HTML/JavaScript phone companion, not only the earlier
advisory demonstration. The original installation is not overwritten by this
publication. Read the [capability matrix](docs/STATUS.md) before connecting hardware.

> **Phone-only hosting is a development target, not a delivered Android installer.**
> The shipped deployment uses a Python host running beside Klipper/Moonraker and
> a phone browser as interface, camera and sensor source. An HTML page alone does
> not supply a native Klipper process or reliable USB access. No trained defect
> weights or universally validated automatic calibration profile are bundled.

## Two advisor modes

| Mode | Available now | Deliberate boundary |
| --- | --- | --- |
| **Local learning** | Local evidence storage, registered chart analysis, small ridge-model experiments, bounded parameter proposals, and optional MobileNet training/inference tools. | A fitted model is not proof of general print-quality accuracy. No pretrained defect model is bundled; low-quality or incomplete evidence must be rejected. |
| **External advisor** | An offline HTML reviewer exports a structured request and validates manually returned JSON from ChatGPT or another reviewer. | No cloud account, API key or automatic API call is built in. Returned text is not executable G-code and does not directly control a printer. |

![Two advisor modes — conceptual illustration](assets/advisor-modes-concept.png)
*Concept art: the diagrams describe the project direction, not a validated native-phone deployment.*

Both modes use explicit evidence and bounded proposals. Hardware protection stays
with Klipper and a qualified operator; neither mode may bypass thermal limits,
trusted configuration or confirmation requirements.

## What is in the application

- **Touch console:** printer status, temperatures, file selection, explicit manual
  controls, camera preview, history and human ratings.
- **Phone evidence:** motion, orientation, aggregated acoustic features, a durable
  upload queue, and controlled paired photographs when supported by the device.
  Raw microphone recordings are not saved by the sensor collector.
- **Calibration workflow:** chart generation and geometry checks, immutable file
  hashes, reviewed observations, one-variable proposals, and experimental six-zone
  screening. Specified limits are not a guarantee that a machine can safely reach them.
- **Integrations:** Moonraker APIs, camera registration/proxy interoperability with
  Mainsail, candidate Orca profile exports, and a source-preserving Orca slice manifest.
- **Privacy:** local storage by default, authenticated private routes, bounded request
  bodies, and no publication of the author's private keys, runtime data or old Git history.

## Install and open the console

Use Python **3.11 or newer** on a compatible host. These steps install the application,
not Klipper firmware, a native Android host, or printer-specific configuration.

```sh
git clone https://github.com/Agnuxo1/KlipperLearn.git
cd KlipperLearn
python -m venv .venv
```

Activate the environment with `.venv\Scripts\activate` on Windows or
`source .venv/bin/activate` on Linux, then:

```sh
python -m pip install -e ".[learning]"
python -m klipperlearn serve --host 127.0.0.1 --port 8765
```

Open **http://127.0.0.1:8765/mobile/console.html**. This default invocation does
**not** enable printer control or connect to a printer. For an authenticated phone
connection over HTTPS, follow the complete [installation guide](docs/INSTALLATION.md).
Do not expose Moonraker or this application directly to the public Internet.

For the separate, dependency-free external-advisor reviewer:

```sh
python -m http.server 8080 --bind 127.0.0.1 --directory reference
```

Open **http://127.0.0.1:8080**. Its clearly labelled synthetic example is for
software demonstration and is **not a printer profile**. The reference page has
no printer transport and its content security policy disables network API calls.

## The 3D calibration chart

![Calibration cycle — conceptual illustration](assets/calibration-cycle-concept.png)

The intended loop is **establish a baseline → collect synchronized evidence →
review → propose one bounded change → run an explicitly approved trial → compare
and repeat or stop**. A failed trial remains useful negative evidence; a `completed`
Moonraker job does not prove dimensional accuracy or acceptable surface quality.

Automatic trial preparation must be explicitly enabled. Starting a new physical
print still requires an explicit request and a clear bed; this release does not
implement robotic bed clearing or a validated unattended safety supervisor.
See the [calibration protocol](docs/CALIBRATION_PROTOCOL.md) and
[local learning guide](docs/LOCAL_LEARNING.md).

## Workshop progress

<p align="center"><img src="assets/benchy-workshop-retouched.png" alt="Editorial presentation of the author's Benchy tuning progression" width="620"></p>

*Author-reported workshop result: progressively tuned Benchy trials reached
approximately 20 minutes with an acceptable visual result, without reducing the
layer count, on a stock-mechanical Flashforge Creator Pro described by the author
as more than 12 years old. The image above is AI-retouched editorial artwork.
It is not an independently measured benchmark or evidence that this release runs
Klipper directly on an Android phone. The [unaltered source-photo pixels](assets/benchy-workshop-original.png)
and [image provenance notes](assets/README.md) are available separately. Reproducing
the timing and quality requires the original slicer settings, G-code and print logs.*

## Architecture and integration

![Phone-first architecture — conceptual illustration](assets/architecture-concept.png)

The current application separates the phone browser, Python companion, Moonraker,
Klipper host, and printer MCU. Keep those roles distinct when reporting results.
See [architecture](docs/ARCHITECTURE.md), [Android host requirements](docs/ANDROID_HOST.md),
[integration boundaries](docs/INTEGRATIONS.md), [model documentation](docs/MODEL_CARD.md),
[safety](docs/SAFETY.md), and [privacy](docs/PRIVACY.md).

These are **external integrations**, not changes accepted by Klipper, Moonraker,
Mainsail, OrcaSlicer or Voron. Contributions should solve a concrete problem and
follow the relevant project's process; see [community collaboration](docs/COMMUNITY.md).

## Development and validation

```sh
python -m pip install -e ".[learning,dev]"
npm ci
python tools/run_offline_tests.py
node scripts/run-node-tests.cjs
node --test tests/core.test.js
python -m unittest discover -s tools/exporter/tests -v
python tools/check_repository.py
```

Browser tests require Playwright Chromium: run `npx playwright install chromium`.
On Windows an already installed Edge can be selected with
`KL_TEST_BROWSER_CHANNEL=msedge`. All browser printer endpoints are simulated;
software tests never prove hardware safety. Details and measured results are in
[validation](docs/VALIDATION.md) and the [0.5.1 review](docs/RELEASE_REVIEW_0.5.1.md).

## License, provenance and attribution

The imported application is **GPL-3.0-or-later**; see [LICENSE](LICENSE) and
[COPYING](COPYING). The separately published 0.1.0 reference reviewer and integration
tools retain their MIT license in [LICENSES/MIT-reference.txt](LICENSES/MIT-reference.txt).
Third-party notices and the included Klipper logo are documented in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Created by **Francisco Angulo de Lafuente** and KlipperLearn contributors.
Independent project: no upstream affiliation, endorsement or hardware certification
is implied. [Source-import provenance](docs/SOURCE_IMPORT.md) explains what was
imported, revised, excluded and preserved privately.
