# KlipperLearn ecosystem integrations

This workstream builds useful external integrations and narrowly scoped upstream
contributions for ten relevant open-source projects. It is a practical selection,
not an objective ranking of the ten largest projects. A guide, local adapter,
fork, submitted PR and accepted upstream feature are different outcomes.

**Current authority:** [status.json](status.json), [work log](WORKLOG.md) and
[contribution rules](CONTRIBUTION_RULES.md). Check the repository ref and evidence
links before treating any item as published or accepted. All new materials are
in English and retain the project licenses and third-party attribution.

## Destinations and useful delivery forms

| Project | Intended integration | Initial evidence / next work |
| --- | --- | --- |
| Klipper | External, bounded calibration workflow over Moonraker | Preserve stock firmware; experimental work belongs outside upstream core. |
| Moonraker | Read-only history and camera-evidence adapter | Extend existing exporter without adding a heavy model dependency to Moonraker. |
| OrcaSlicer | Paired Quality / Standard / Speed presets and file identity | Existing 0.6.0 generation needs real slicer import verification. |
| Mainsail | Authenticated camera and external optimizer workflow | Do not bypass contributor-vouch requirements or alter control behavior. |
| Fluidd | Equivalent Moonraker camera/evidence workflow | Read development guidance, keep the integration external until a focused patch is justified. |
| OctoPrint | Separately maintained plugin or read-only export adapter | No AI-generated upstream PR, PR description or reviewer reply. |
| PrusaSlicer | Read-only post-processing sidecar | [Working helper setup](../prusaslicer/README.md) and appended-file contract tests. |
| Cura | Read-only PostProcessingPlugin evidence collector | [Working mocked-contract adapter](../cura/README.md); native Cura GUI/output acceptance remains pending. |
| KIAUH | Read-only prerequisites and coexistence checks | Do not reinstall Klipper or change services as an incidental integration step. |
| Voron | Printer-specific, reproducible test protocol | No VoronUsers mod submission without actual Voron compatibility and physical tests. |

## Scheduled overnight rounds

Eight bounded rounds are scheduled hourly from 01:00 to 08:00 on 17 September
2026, Europe/Madrid. They are separate scheduled executions, not a continuously
running unattended agent. Tool access and third-party service availability must
be rechecked on each run. Stop after the last round; do not create a recurring
promotion campaign or silently extend the work window.

Each round must read this state first, choose unfinished work, check the current
upstream rules, implement in an isolated branch, run applicable tests, publish
only reviewed public artifacts, and append a factual result. Resolve stale locks
using actual execution evidence rather than timestamps alone. Do not overwrite
concurrent changes or use force pushes. Preserve work when publishing is blocked.

Useful standalone integrations take priority over maintaining ten empty forks.
Create a fork only for a concrete change that benefits users and can be maintained.
No external contact has been made by the initial preparation round. At most one
relevant initial proposal per project; check duplicates and policy before contact.
A rejected or unwelcome contribution must not be re-posted in a different channel.

## Non-negotiable deployment boundaries

Do not modify the live printer services, firmware, motion, heaters or print queue.
Do not scan the home LAN, collect private histories, expose ports, open tunnels,
spend money, create accounts or handle identity documents. ChatGPT plugin identity
verification and directory submission are explicitly postponed by the owner.
The Flashforge Benchy series is operator-plus-ChatGPT evidence; the Anycubic 4Max
Pro charts/cubes are the separate KlipperLearn/phone/webcam installation. Keep
those cohorts distinct as documented in [provenance](../../docs/BENCHMARK_PROVENANCE.md).
