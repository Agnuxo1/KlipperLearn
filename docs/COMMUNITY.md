# Community preview and responsible distribution

KlipperLearn is free, independently maintained and experimental. We seek useful
feedback and reproducible compatibility reports, not endorsements obtained by
creating empty forks, repeated advertisements or artificial repository activity.

## Public entry points

- Project website: https://agnuxo1.github.io/KlipperLearn/
- Source and issues: https://github.com/Agnuxo1/KlipperLearn
- Preview release: https://github.com/Agnuxo1/KlipperLearn/releases/tag/community-preview-20260917
- Getting started: [START_HERE.md](START_HERE.md)
- Integration status: [the evidence ledger](../integrations/ecosystem/status.json)

The site is static, has no publisher analytics or advertising, and provides an
optional in-browser reference demonstration. That demo is the original 0.1.0
reference evaluator, not the current host application or the three-mode Python
optimizer. Files selected there stay in the browser; the demo does not connect
to a printer. Hosting-provider request logs remain governed by GitHub's policies.

## What was checked before this preview

The OctoPrint 0.1.1 package was installed with OctoPrint 1.11.8 in a disposable
Windows Python environment. The actual plugin manager discovered and initialized
it; the native event manager dispatched synthetic file and completion events.
The expected two manifests were written without changing G-code or leaking the
fixture path. Both workers terminated. This is native framework testing, not
web-UI acceptance, real serial communication or physical printing.

An OrcaSlicer CLI acceptance attempt using only disposable configuration and
bundled public DEMO presets returned an error before producing sliced output.
Native Orca import/slicing acceptance therefore remains unverified. No production
profile was edited and no G-code was sent to a printer. Cura, PrusaSlicer and the
frontends also retain their recorded native-UI or physical acceptance gates.

## Appropriate external outreach

One narrowly scoped resource-list suggestion has been submitted to
`ad-si/awesome-3d-printing`. Its contribution rules invite useful individual
suggestions and require checking for duplicates. The public ledger records the
actual proposal URL and disposition once submitted. A fork or pending PR is not
acceptance by that list or by the ten printing projects.

OctoPrint core disallows AI-authored contributions, and its plugin directory
requires a competent, active human maintainer. Klipper's experimental work belongs
outside its core; DCO/CLA, contributor-vouch and physical Voron requirements are
not signed or bypassed by an assistant. The previous, unposted collaboration
plan is preserved in [UPSTREAM_COLLABORATION.md](UPSTREAM_COLLABORATION.md).

The public ChatGPT plugin still requires the owner's developer verification,
installation testing, submission and approval. No such process was completed in
this community-preview work. No paid advertisements, artificial stars, mass
messages, unrelated issue comments or unsolicited private emails are used.

## Feedback that would genuinely help

Report exact versions, minimal sanitized inputs, expected/observed behavior and
what was actually tested. Do not claim a native or physical result based on a
mock test. Keep the two workshop printers and their calibration methods separate.

## Preview validation

The current local suite passed 508 Python tests and 185 subtests, the existing
25 exporter tests, and 47 reference-core tests. Website tests check desktop and
mobile layouts, keyboard access, local images, ten source links and the working
synthetic reference demonstration. All browser requests are intercepted during
these tests; no printer or live LAN is contacted. The published commit's Actions
runs are authoritative for remote validation.

GitHub topics and project descriptions use the actual scope of the software.
Release files carry checksums and licenses. The publication ledger must distinguish
prepared artifacts, public downloads, sent suggestions and accepted listings.
Neither a release nor a resource-list entry proves physical safety, a speed gain,
a public ChatGPT listing, or inclusion in Klipper, Orca, Mainsail or Voron.

## Verified publication

The [project website](https://agnuxo1.github.io/KlipperLearn/) and synthetic demo
were opened successfully through public HTTPS in a real browser. All eight
[preview release downloads](https://github.com/Agnuxo1/KlipperLearn/releases/tag/community-preview-20260917)
were fetched without authentication and matched their expected sizes and SHA-256
digests. The new [community discussion](https://github.com/Agnuxo1/KlipperLearn/discussions/1)
is open for relevant feedback.

[Awesome 3D Printing PR #126](https://github.com/ad-si/awesome-3d-printing/pull/126)
contains one entry with AI assistance and project affiliation disclosed. It is
submitted, not an accepted listing unless the upstream merge status says so.
See [the publication record](publication-status.json) for verified outcomes and
remaining gates, and [the information kit](PRESS_KIT.md) for accurate descriptions.

The resource-list formatting check passed. Its global link checker reported HTTP
200 for KlipperLearn but failed on three unrelated existing URLs; no unrelated
entries were changed to make this proposal appear green. Maintainer acceptance
is still pending.
