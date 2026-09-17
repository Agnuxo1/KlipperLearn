# Browser and installable-web delivery — 17 September 2026

This directory imports the original 0.1.0 Chrome source/store bundle and adds
Firefox and installable-web builds. The Chrome runtime files are unchanged from
the delivered source. This is file-first calibration assistance, not printer
control, automatic AI inference or a universal native slicer integration.

## Completed verification

- 70 Node tests passed, including 30 differential tests against the published
  Python reference and preservation of numeric/configuration identities.
- A real temporary Chromium extension installation passed native module loading,
  demo review and the eight-file preset/audit download. Application page errors
  and external application requests were absent. Browser policies were unchanged.
- A real temporary Firefox 156.0 add-on installation passed and exported the
  same eight-file demo bundle. Testing used a disposable profile and Mozilla's
  documented browser-UI test flag on geckodriver, not the owner's Firefox profile.
- The installable web application passed actual service-worker registration,
  caching of exactly 16 static files, offline reload, offline preset export,
  help navigation and mobile/desktop layout checks in Chromium.
- No actual Android device or Microsoft Store installation was tested. Browser
  installability is different from Google Play or Microsoft Store publication.

## Store outcomes

Chrome Web Store accepted the ZIP and created a separate draft:
`heaekjehabdpkdflpaofimkmjcnepbph`. The English description, Tools category,
English language, icon, two screenshots, promotional tile and support/homepage
were saved. EnigmAgent was not modified. Submission and review are not complete.

Mozilla accepted the Firefox ZIP and its server-side validator reported zero
errors and zero warnings. The description form has been populated with English
copy, an explicit experimental label, GPL-3.0-or-later, privacy and reviewer notes.
Uploading and completing metadata do not by themselves establish submission or
public approval. The store-status ledger records later observed outcomes.

The Microsoft Store onboarding page subsequently reported that the individual
account was created and verified and offered its Partner Center dashboard.
No identity documents were accessed or supplied by this development process.
Account readiness is separate from a reserved app, package upload and certification.

## Free Android and Windows path

`docs/slicer-review/` is a complete installable-web application, not a redirect
or advertisement. It reviews sessions and exports profiles offline after the
operator enables caching. It can be added through a supporting browser on Android
or Windows without a paid app-store account. This does not create a Google Play
listing, Android APK/AAB or Microsoft Store entry. The existing paid Chrome Web
Store account is not evidence of Google Play developer registration.

No printer, firmware, production service, paid resource or existing EnigmAgent
item was changed. A tool safety gate blocked a Chrome privacy-page navigation;
that denied action was not retried through another path. Source publication and
independent store workflows continued without weakening any access restriction.
