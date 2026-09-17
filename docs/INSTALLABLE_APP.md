# KlipperLearn Slicer Review: browser apps

The Chrome and Firefox extension sources and the installable web application are
published under `integrations/browser/` and `docs/slicer-review/`. They share the
reviewed local trial-selection engine. Store upload is not store approval.
Current observed outcomes are recorded in
[the store ledger](../integrations/browser/store-status.json).

## Open the installable web app

Application URL: https://agnuxo1.github.io/KlipperLearn/slicer-review/index.html

1. Open the application in a compatible up-to-date browser.
2. To save the application shell on this device, select **Enable offline app**.
3. Once the offline-ready message appears, use **Install app** when offered, or
   the installation/add-to-home-screen option provided by your browser.
4. Save your calibration session explicitly before closing. Only public application
   files are cached; user photographs and active sessions are not persisted.

This is a free web-distribution option for Android and Windows. It is not an
Android APK/AAB, Google Play publication, MSIX package or Microsoft Store listing.
A real Android-device acceptance check and Windows installation check remain
separate from the successful Chromium offline tests. Initial hosting requests
are subject to GitHub's policies; the application does not upload selected files.

## Download packages and source

- [Chrome ZIP](../integrations/browser/dist/KlipperLearn-Chrome-0.1.0.zip)
- [Firefox ZIP](../integrations/browser/dist/KlipperLearn-Firefox-0.1.0.zip)
- [Installable-web ZIP](../integrations/browser/dist/KlipperLearn-Installable-Web-App-0.1.0.zip)
- [Package SHA-256 checksums](../integrations/browser/dist/SHA256SUMS)
- [Source, tests and store materials](../integrations/browser/)
- [Delivery scope and validation](../integrations/browser/STORE_DELIVERY.md)

The Firefox ZIP is unsigned until Mozilla completes its distribution/signing
process. A temporary developer installation used for testing is not a permanent
consumer install or a public Add-ons listing. Do not disable signing requirements.
The Chrome draft is separate from any existing extension in the publisher account.

## Functional boundaries

Use original model geometry, explicit machine/material limits and comparable
reviewed trial records. Quality, Standard and Speed presets are generated only
from eligible evidence. The demo is synthetic, not an optimized printer profile.
Review effective settings and reslice in your actual slicer before a supervised
physical trial. The application does not move, heat, connect to or start a printer.
AI requests are explicitly downloaded and shared by the user; no model API key,
publisher subscription or automatic cloud call is required by these browser apps.
