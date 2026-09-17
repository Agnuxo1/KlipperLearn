# KlipperLearn Slicer Review — Chrome extension 0.1.0

Free, open-source local calibration review and paired OrcaSlicer mode exports.
The extension contains its own interface, validation engine, selection policy and
ZIP writer. It is not an APK, a ChatGPT skills package or a website launcher.

## Delivery status

**Prepared, with engine and DOM-harness validation. Not uploaded or submitted to
Chrome Web Store. No store item ID exists.** No GitHub write occurred for this
extension. Existing EnigmAgent and live printer installations remain untouched.
No additional developer registration, payment or paid API was used.

The connected PC and GitHub tools in this session exposed read operations only;
command execution, browser control and file/repository writes were unavailable.
That prevented account-side native installation and store submission. The existing
Chrome Web Store publisher registration should be reused, not Google Play or a new
paid account. Do not interpret an authorization message as proof of tool capability.

## Features

- Import a `klipperlearn.slicer-session/v1` session or create one with a guided form,
  actual machine/material context, current Orca presets and an unchanged STL model.
- Record physical job identities, actual timings, human ratings and original photo
  hashes, including failures. No trial or performance claim is prefilled.
- Compare whole configurations in Quality, Standard and Speed modes, retaining
  geometry/layer-count context and excluding reused or inadequate evidence.
- Export six paired Orca JSON presets, an audit and instructions in one ZIP.
- Export a numerical advisor request; manually review with ChatGPT or another
  assistant, then validate one bounded change and export UNVALIDATED TRIAL presets.
- Add an unprinted candidate and collect new supervised evidence before adoption.
- Preview original JPEG/PNG photos locally and match their SHA-256 identities.
- Download the original 40 x 30 x 12 mm calibration card, not official 3DBenchy.

The local tool needs no Python installation, account or API key. It makes no
network request and requests no extension/host permission. It has no content
scripts, page/history access, tracking, camera/microphone access or printer control.
Sessions are not persisted automatically; save before closing or clearing the tab.

## Limits

This is not automatic visual grading, autonomous printing, native Android Klipper
hosting, a universal printer driver or an automatic ChatGPT API integration.
Photographs and ratings remain user-supplied evidence, not independent certification.
Several modes can legitimately select the same settings. Preserving temperatures,
custom scripts and other settings in copied profiles is not a safety audit of them.
Inspect effective settings and inheritance in Orca, reslice and supervise printing.
Native slicer import and physical performance have not been validated here.

## Installation acceptance test

1. Extract the package ZIP into an empty folder.
2. In an authorized test Chrome profile, open `chrome://extensions`.
3. Enable Developer mode, select **Load unpacked**, and choose the folder with
   `manifest.json`. Click the extension toolbar icon to open the workspace.
4. Complete `store/REVIEWER_INSTRUCTIONS.txt` before requesting store review.

Do not change enterprise/browser security policies to bypass restrictions. Native
installation must be tested where the owner is allowed to install extensions.

## Validation actually performed

- **70 Node tests passed**, including 30 differential scenarios against the exact
  original Python optimizer: session/configuration IDs, exclusions, selected modes,
  paired presets, numeric spelling, and one-setting proposals.
- **16 Chromium DOM-harness checks passed**, covering data entry, results, generated
  ZIPs, saving/reopening structure, proposal validation, photographs, error recovery,
  layout and privacy. No external request occurred during these tests.
- Module syntax, manifest, resources, original license, no-network code patterns,
  known secret patterns, package contents and ZIP CRC are checked separately.

**Native installation is not validated.** The validation sandbox disallows
extension installation and URL navigation by administrator policy; none of those
policies was modified. The UI tests render self-authored content in a blank document,
replace the unavailable secure-origin hash interface with a hashlib-backed test
double and capture download blobs. They do not exercise native module loading under
`chrome-extension://`, store installation or actual browser download navigation.

Screenshots show the real UI logic running in this documented harness with synthetic
observations. They are not AI-generated imagery or evidence of physical printing.
Re-capture in installed Chrome before submitting the definitive store listing.

## Reproduce tests and packages

The engine tests require Node 22 and Python 3.11 or later (standard library only).
The DOM harness additionally uses Playwright, Pillow and a local Chromium binary.
These development dependencies are not bundled or required by the extension.

```sh
python tools/oracle_cases.py
node --test tests/engine.test.mjs
python tests/browser_test.py
python tools/check_package.py
python tools/build.py
```

## Source provenance and licensing

The reference Python file matches `src/klipperlearn/slicer_optimizer.py` in
Agnuxo1/KlipperLearn commit `9e92d1e6173a87406dbeb2cfbe4e26d0ada2430f`, with Git blob
SHA-1 `6386f0f1eec53f276aec213234888c12c37d1096`. The browser code is a new port, not a
claim that every historical repository test was rerun. Imported numeric spellings
are retained to protect Python-exported hashes; manually changing 40.0 to 40 or
other noncanonical spellings can invalidate identities. Historical trial IDs are
not silently repaired to force acceptance.

GPL-3.0-or-later is preserved for the source and original calibration model. The
project's existing icon is reused; no Google/OpenAI/printer-company logo is used.
No font files, credentials, cookies, private logs or model weights are included.

## Store material

`store/listing.json`, `DESCRIPTION.txt` and `REVIEWER_INSTRUCTIONS.txt` contain the
English listing, privacy explanations and test steps. `store/PRIVACY.html` must be
hosted at a verified public URL before submission; the intended URL is NOT yet live.
The package contains three 1280 x 800 UI captures, an icon and a 440 x 280 promotional
tile. Upload the extension-only ZIP, not the source/development archive.

The complete source directory can be added as `extensions/chrome/` in the existing
repository with tests and provenance intact. Do not overwrite EnigmAgent. The
repository import and Web Store submission have not occurred in this delivery.
