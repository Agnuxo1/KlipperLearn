# Browser-store submission draft — Calibration Review 1.0.0

Name: **KlipperLearn Calibration Review**
Summary: Review local calibration trials, export advisor requests and validate
bounded proposals. No printer access, account or paid API.
Price: free. Support: https://github.com/Agnuxo1/KlipperLearn/issues
Privacy: https://agnuxo1.github.io/KlipperLearn/review/privacy.html

## Listing description

Compare repeated 3D-print calibration trials locally in your browser. Open a
session JSON, use the clearly marked synthetic example, run the deterministic
reviewer, save the audit, export a request for manual review by an assistant,
and validate a bounded one-variable proposal. Invalid input never replaces an
older session silently; it clears the old session and disables analysis actions.

All execution code is bundled. The extension cannot read websites or browsing
history, scan the LAN, access your camera, call an AI API, change settings in a
slicer, upload a job or control your printer. It requests no host permissions.
Only explicitly selected files are read; outputs download only after a click.
There is no tracking, account, subscription, payment or advertiser.

This is the original reference reviewer, not the full KlipperLearn phone/host
application or Python Quality/Standard/Speed profile generator. It does not score
photographs or certify that measured results are true. A proposal requires human
review and supervised physical testing. No performance gain is guaranteed.

## Reviewer procedure

1. Install the candidate temporarily using the official development workflow.
2. Click its toolbar icon: the bundled review page opens in a tab.
3. Load the synthetic example, then Analyze locally; inspect synthetic=true,
   executable=false and the human-approval flag in the decision.
4. Save the session and request JSON. Check that there is no network upload.
5. Load invalid JSON or duplicate keys; the previous session must be cleared and
   the analysis buttons disabled. Clear loaded session must remove page data.
6. No login, printer, dummy credentials or paid service is required.

Firefox manifest declares required data collection `none` and minimum version
140. Chromium has a separate service-worker manifest. No minification, remote
code, build-time downloads or obfuscated sources are included. Build with the
repository's `tools/build_distribution.py`, Python standard library only. Preserve
MIT notices for the standalone wrapper and original reference engine.

## Publication state

These are unsigned packages prepared for review, NOT an AMO, Edge or Chrome Web
Store listing. Mozilla signing, publisher-account access, native-browser acceptance
and store review remain distinct gates. Chrome's registration fee blocks any new
paid signup under the owner's zero-budget instruction. Edge enrollment has no
registration fee according to its official guide. Do not invent a listing ID or
claim Mozilla/Microsoft affiliation. Review any identity/trader disclosures with
the owner rather than guessing them.
