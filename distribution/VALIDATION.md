# Free-channel delivery review — 17 September 2026

## Delivered scope

Calibration Review 1.0.0 is a standalone local reviewer built around the canonical
MIT 0.1.0 reference engine. It is not the 0.6.0 Python three-mode preset generator,
a trained visual model, a printer driver or a public store listing. The engine
is bundled without changes, with its license. This release adds a strict JSON
reader, bounded file handling, stale-session clearing, local exports and optional
shell-only offline caching. The extension requests no browser or host permissions.

Four reproducible archives contain the Firefox candidate, Chromium candidate,
web application and the unchanged original STL plus community documentation.
No APK, MSIX, signed XPI, account credential, model API or private history is included.
The printable kit is GPL-3.0-or-later and non-exclusive; it does not contain a
matching real photograph or a verified physical print of that exact asset.

## Completed checks

- 514 Python tests and 185 subtests passed in the full local regression suite.
- All 14 JavaScript test programs passed, including the new local reviewer and
  real service-worker installation, offline reload/analysis and removal tests.
- Mozilla web-ext 10.6.0 reported zero errors, zero notices and zero warnings.
- The unpacked extension was temporarily installed in native Firefox using
  web-ext and a disposable profile; no public signing or AMO upload took place.
- Native Edge 153.0.4234.32 loaded the extension in an isolated temporary profile.
  Its background worker started, bundled UI analysed synthetic data, permissions
  and origins were empty, and the app made zero external requests in that test.
  The profile was closed and removed. A real screenshot records that synthetic UI.

Two existing third-party deprecation warnings remain in Python tests. An initial
browser test confused a native Request.url property with Playwright's url()
method; the test was corrected and the full browser suite rerun successfully.
Firefox for Android's minimum was set to 142 to match its built-in no-data
collection declaration. Desktop minimum remains 140. Mobile extension installation
and native Android/Windows Store packaging are not claimed as tested.

## Publication and account gates

The official Mozilla submission route displayed the owner's sign-in page; no
publisher session or listing was created. Printables displayed Login; no model
was uploaded. MakerWorld's policy page returned 403 through available fetching,
which was not bypassed or interpreted as a payment requirement. Its current
upload, photograph and licensing rules still require final account-side review.

Microsoft's documented new individual registration flow and Edge Add-ons have
no registration fee, but their accounts and review processes remain separate.
A new Google Play account requires USD 25 and Chrome Web Store registration also
requires a fee: neither paid registration was attempted. No fee exemption or
universal native compatibility is invented. Additional destinations are candidates,
not verified free accounts or accepted listings.

The HTML/PWA release can be hosted on the existing GitHub Pages site without a
publisher registration payment. Its build is not a Microsoft Store submission.
Only completed public deployment checks may set a public URL in the ledger.
No printer, production Linux service, private certificate or API billing changed.
No automated mass posting, exclusivity, fabricated print photos or mirrored
upstream adoption claims were used. See channels.json and the referenced official
policies for per-platform scope and remaining gates.
