# Upstream collaboration without spam

Status: integration tools and this contribution plan are published here. No
upstream acceptance, partnership or completed merge is claimed.

## Klipper

The [contribution guidelines](https://www.klipper3d.org/CONTRIBUTING.html) direct
experimental work to independent repositories and discussion to Klipper Discourse.
Do not open a pull request that simply advertises this project or adds an unvalidated
controller. Do not ping maintainers individually. A future upstream fix must solve
a reproducible Klipper problem, include tests and follow the required commit and
sign-off rules. The author must personally approve any DCO certification.

A narrowly scoped discussion draft is included below. It has not been posted.
It asks about a technical boundary instead of requesting promotional links.

## Moonraker and Mainsail

Prefer existing public APIs. Reproduce any integration bug locally before filing
it upstream. If a change is needed, submit the smallest documented patch rather
than a new general AI framework. Respect [Moonraker's contribution requirements](https://moonraker.readthedocs.io/en/latest/contributing/)
and [Mainsail's contribution guide](https://github.com/mainsail-crew/mainsail/blob/develop/CONTRIBUTING.md).

## OrcaSlicer

Start with the post-processing adapter in this repository. A future native plugin
must use the API of a tested Orca version; do not confuse a CLI with a registered
plugin. Submit a documentation addition only after an actual installation test
and only when the project's contribution guidance considers it appropriate.

## Voron

Seek volunteers for named machine configurations after reproducible installation,
thermal safety and artifact provenance are established. Do not request endorsement
or add a generic link to unrelated repositories.

## Single discussion draft

Title: Phone-assisted calibration evidence: host and measurement boundaries

We are developing KlipperLearn as an independent, experimental phone-first project.
The long-term goal is an older phone hosting compatible Klipper hardware over USB,
with either local analysis or an optional external advisor. The current public
release contains an advisory-only reviewer, read-only Moonraker history export and
a slice-fingerprint adapter; it does not ship a validated Android host or learned
printer controller.

We are keeping experimentation out of Klipper's core and leaving firmware thermal
protections unchanged. The proposed evidence record separates completed jobs from
reviewed quality, fixes geometry and mounting context, and preserves failed trials.
Before proposing any upstream change, we would value technical feedback on two
boundaries: timestamp/correlation requirements for phone-mounted sensors, and the
validation evidence expected of an alternative phone-host runtime. A frame sensor
is not being treated as absolute nozzle-position feedback.

Implementation and reproducible synthetic tests: https://github.com/Agnuxo1/KlipperLearn

No action should post this draft automatically. Check for an existing discussion,
update its evidence status and use one relevant channel only.
