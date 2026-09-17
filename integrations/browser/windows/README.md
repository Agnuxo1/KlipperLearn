# Microsoft Store package

This is a Windows 10/11 Desktop PWA package of KlipperLearn Slicer Review.
The hosted application version is 0.1.0; the initial Windows package version is
1.0.0.0. No additional AI subscription, publisher account or paid certificate is
required. This package does not include a printer control service.

`product-identity.json` records the real identity assigned by Microsoft Partner
Center, not a sample identity. `pwabuilder-request.json` contains only public
application URLs and package metadata. No signing keys or access tokens are stored.

The package was generated with the official PWABuilder Microsoft Store packaging
service. Its nested manifest name and publisher were checked against Partner
Center. The generated ZIP was checked for archive integrity. The unsigned
sideload diagnostic package is not included or intended for Store submission.

`build-verification.json` records exact package bytes and SHA-256. Submission and
certification are separate from generation: see the current store-status ledger.
No native MSIX installation or physical printer test is claimed here.

The application is served from the project's `docs/slicer-review` source and
uses Microsoft Edge's PWA host. GitHub and Microsoft process their own hosting,
Store and browser requests independently. User-selected calibration evidence is
processed locally, not uploaded by the application. See the public
[Windows privacy notice](../../../docs/windows-privacy.html).

Official packaging source: https://github.com/pwa-builder/PWABuilder/tree/main/apps/pwabuilder-microsoft-store
