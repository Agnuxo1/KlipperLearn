# Store submission results — 17 September 2026

This record supersedes the earlier pre-submission snapshot in STORE_DELIVERY.md.
The publisher is Francisco Angulo de Lafuente. The project remains free and
GPL-3.0-or-later. A submission is not an approval or an installed consumer release.
The machine-readable status is [store-status.json](store-status.json).

## Chrome Web Store

Item: `heaekjehabdpkdflpaofimkmjcnepbph`, version 0.1.0.
The existing publisher account was used; no registration fee was paid again and
EnigmAgent was not modified. Privacy, local content-handling declarations, free
public distribution and reviewer instructions were completed and saved.

The final confirmation requested automatic publication after approval. The store
then displayed **Pending review** and confirmed the extension had been submitted.
Google approval and the public consumer-installation path remain unverified.
The declaration includes local image/content processing even though the extension
does not transmit selected evidence or inspect other web pages.

## Mozilla Add-ons

The full submission was completed, including the requested source archive.
Mozilla displayed **Submission complete**, and its official confirmation email
acknowledged receipt. The earlier validator reported zero errors and warnings.

The review source archive includes unminified application files, the Firefox
variant, build tools, GPL COPYING, and a standard-library rebuild program. Running
that program produced the exact submitted Firefox ZIP SHA-256:
`ef9361050aeb4bf7d02988f45604d52e96a66362218b8da350fb0424b127a870`.
The description correctly says Firefox rather than Chrome. The custom licence
notice preserves GPL-3.0-or-later and points to the full packaged COPYING.

Expected listing after approval:
https://addons.mozilla.org/firefox/addon/klipperlearn-slicer-review/
No approval, signed consumer XPI or public listing is claimed by this record.

## Microsoft Store

The product name **KlipperLearn Slicer Review** was reserved. Microsoft assigned
product ID `9P77SW6NX3NB` and submission ID `1152921505701918899`.
The official PWABuilder Microsoft Store service generated the Edge-hosted PWA
package using those real identifiers and public project URLs. No account tokens,
signing keys, paid certificate or private printer records were sent to the builder.

The nested manifest name and publisher were verified against Partner Center.
The resulting [MSIX bundle](windows/KlipperLearn-Slicer-Review-1.0.0.msixbundle)
was uploaded. The package section and Properties section both showed **Complete**.
The package version is 1.0.0.0; the hosted browser application remains 0.1.0.
Only Windows 10/11 Desktop was selected. The standard Edge PWA host's
`runFullTrust` capability requires Microsoft approval; it was not removed or
misrepresented to suppress that warning.

Zero was selected as the price in EUR with worldwide public availability, and the
save action completed. The IARC questionnaire was answered for the actual utility,
reviewed, and saved after the normal publisher consent. Final overview status for
those two sections has not been rechecked. The English listing text was entered,
but its final persistence and required screenshot upload are not complete.

A subsequent attempt to inspect the screenshot form was blocked by the execution
tool's safety assessment. No alternate route was used to retry the denied action.
Windows certification has **not** been submitted. The remaining steps are:

1. Confirm saved zero pricing and age-rating status in Submission 1.
2. Save the English listing and upload an actual application screenshot.
3. Explain the standard Edge PWA-host capability and provide reviewer instructions.
4. Submit for certification, then verify the resulting decision and installation.

The publicly hosted [Windows privacy notice](../../docs/windows-privacy.html)
explains initial GitHub requests, Microsoft/Edge services, local evidence
processing, optional static-file caching and manual external-advisor exchange.
It was fetched successfully over normal HTTPS before preparing the listing.

## Public web and Android route

The deployed web application was opened in a disposable Chromium through public
HTTPS. Its real WebCrypto implementation, synthetic-demo analysis and native
ZIP download succeeded. The archive contained the expected eight files, no
script errors were recorded, and no out-of-scope application request occurred.
A real screenshot was captured from that running application for the Windows kit.
This test is not a native MSIX installation or a physical Android-device test.

The [installable web app](https://agnuxo1.github.io/KlipperLearn/slicer-review/index.html)
is available independently of a store. The previously verified offline test caches
16 public application files, not user photographs or active calibration sessions.
There is still no Android APK/AAB or verified Google Play developer account in
this work. The existing Google registration is for Chrome Web Store. No new
Google Play payment or duplicate registration was made.

## Scope and preservation

The existing native Chromium/Firefox tests and 70 engine tests remain applicable
to unchanged browser code. The Windows-package source commit passed the project's
Python 3.11/3.13 checks and Browser distributions workflow. Check the final commit's
Actions for the latest CI result; testing does not establish physical print gains.

The two real printers, their methods and production installations remain separate
and unchanged. No printer movement, heating, print start, firmware restart, API
purchase, paid service, browser-policy bypass or mass outreach occurred.
