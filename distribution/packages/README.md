# Free-channel packages

These files are reproducible with `python tools/build_distribution.py`.
Verify `SHA256SUMS` before using a download. Store review and signatures are not
implied by a ZIP file. Source and limitations are in [the distribution guide](../README.md).

| Package | Purpose | Current boundary |
| --- | --- | --- |
| [Firefox candidate](KlipperLearn-Calibration-Review-Firefox-1.0.0.zip) | Local file reviewer, temporary-load tested | Unsigned; AMO login, submission, review and signing pending. |
| [Chromium candidate](KlipperLearn-Calibration-Review-Chromium-1.0.0.zip) | Same reviewer, native Edge tested | Not listed in Edge Add-ons or Chrome Web Store. |
| [Web app](KlipperLearn-Calibration-Review-Web-1.0.0.zip) | Static HTTPS application with optional offline shell | Not an APK or a Microsoft Store package. |
| [Printable model kit](KlipperLearn-Calibration-Card-Community-Kit.zip) | Original STL, license, instructions and empty worksheet | No exact-asset physical test/photo or model-site submission claimed. |

The reviewer uses the original MIT reference engine, not the full Python mode
optimizer or a visual neural model. It never connects to a printer. The model
retains GPL-3.0-or-later. No dependency on a paid AI API is introduced.

For end users, open the hosted web version instead of trying to install an
unsigned Firefox package permanently. Offline use is optional: enable it in the
app first; the browser's own install/add-to-home-screen menu varies by platform.
No selected session, photograph, credential or account is cached by the app.
