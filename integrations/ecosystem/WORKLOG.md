# Ecosystem work log

## Initial preparation — 17 September 2026

- Confirmed public base commit 6bbc120 and used a separate source checkout.
- Confirmed canonical names, default branches and license metadata for ten targets.
- Read seven available project contribution files; reviewed the official VoronUsers
  submission rules separately. Root/.github/docs discovery is not exhaustive.
- Recorded OctoPrint AI restrictions, Mainsail contributor-vouch requirements,
  real DCO sign-offs, Klipper experimental exclusion and Voron physical testing.
- Created the ten-target ledger with distinct delivery/submission/acceptance states.
- Added a PrusaSlicer setup using the existing canonical fingerprint helper and
  five passing temporary-file contract tests; no helper duplication or G-code edits.
- Scheduled eight bounded rounds, 01:00–08:00 Europe/Madrid on 17 September.
- No upstream issue, PR, fork or promotional message was created in this round.
- No LAN scan, printer action, service update, payment or identity action occurred.

This preparation does not claim installed-PrusaSlicer acceptance, ten completed
integrations or upstream adoption. Subsequent rounds append exact artifacts, tests,
commit refs, submission URLs and blockers here. Preserve this log; do not replace
past test outcomes with a later aggregate that obscures what actually ran.

### Initial validation

The complete local suite passed 350 tests plus 185 subtests, including the five
new PrusaSlicer contract cases. Ruff E9/F and repository consistency passed.
Two pre-existing third-party deprecation warnings remain. The public-file scan
found no configured private host addresses, workstation paths or matched secret
formats in this change; this is a scoped scan, not a security certification.
