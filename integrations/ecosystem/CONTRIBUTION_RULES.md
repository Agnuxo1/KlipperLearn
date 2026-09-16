# Contribution gates for the overnight workstream

Policy snapshot: 17 September 2026. The exact source URLs and content hashes of
retrieved contribution files are in [status.json](status.json). This review does
not establish that all applicable policies were found; recheck root instructions,
AI policies, templates, licenses and plugin-directory rules before external writes.

## Hard gates already identified

**Klipper:** the main repository excludes experimental work. Experiments stay in
our repository; Discourse is its suggested route for technical feedback. Core PRs
require broad readiness, regression tests and a real contributor DCO sign-off.
Source: https://www.klipper3d.org/CONTRIBUTING.html

**Moonraker:** contributions need significant benefit, documented testing, careful
async behavior and suitable dependencies for low-powered hosts. A real sign-off is
required. Keep model inference outside Moonraker; do not certify the owner's DCO
agreement or personal review on their behalf.
Source: https://github.com/Arksine/moonraker/blob/master/docs/contributing.md

**Mainsail:** target develop; duplicate checks, conventional commits and DCO apply.
Its vouch system rejects PRs by unvouched contributors. Do not submit a knowingly
unqualified PR, solicit endorsements in bulk or bypass the trust gate using bots.
A focused feature proposal is different from an advertisement or support question.
Source: https://github.com/mainsail-crew/mainsail/blob/develop/CONTRIBUTING.md

**Fluidd:** work from develop, use conventional commit subjects within its length
limit, valid sign-off, lint/type/tests and its documented development environment.
Its existence of AI-assistant instructions is not blanket approval of every AI PR.
Source: https://github.com/fluidd-core/fluidd/blob/develop/CONTRIBUTING.md

**OctoPrint:** no fully or predominantly AI-generated core PRs, including generated
code later edited by a human. AI-generated documentation, PR descriptions and
responses to human reviewers are also disallowed. This autonomous workstream must
not send such material to OctoPrint. A separately maintained external plugin is
possible; its directory admission has separate rules and is not implied here.
Source: https://github.com/OctoPrint/OctoPrint/blob/dev/CONTRIBUTING.md

**PrusaSlicer:** issues are for reproducible bugs; general suggestions belong in
Discussions. Keep source patches local, tested and narrowly scoped. The existing
post-processing interface can support our external helper without a core patch.
Source: https://github.com/prusa3d/PrusaSlicer/blob/master/.github/CONTRIBUTING.md

**Cura:** choose the correct component and provide a concrete benefit and test
results. A third-party extension is not a Marketplace listing or an upstream
feature. Native GUI acceptance is distinct from mocked Script API tests.
Source: https://github.com/Ultimaker/Cura/blob/main/CONTRIBUTING.md

**VoronUsers:** mods must target a Voron printer and be tested, with the required
source/CAD formats and documentation. We have no verified Voron hardware test.
Do not submit our generic calibration STL as a tested Voron mod.
Source: https://github.com/VoronDesign/VoronUsers/wiki/Mod-Submission-Rules

**OrcaSlicer and KIAUH:** no standalone CONTRIBUTING file was found in the inspected
root/.github/docs directories. This is not permission or a complete policy audit.
Inspect their current README, templates, discussions and applicable project rules
before preparing an upstream submission. No automatic contact is authorized by
this checklist alone.

Keep licenses intact, reveal AI assistance when relevant, avoid unsupported
performance claims, and never sign legal/personal attestations that were not made.
