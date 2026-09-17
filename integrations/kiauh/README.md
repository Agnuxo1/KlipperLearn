# KIAUH coexistence: read-only preflight

KIAUH installs and updates the printer stack. This helper does neither: it checks
the selected Python environment and storage location before an operator considers
a separate KlipperLearn service. It is not an entry added to KIAUH's menu.

```sh
python -m klipperlearn.host_preflight --storage /path/to/existing/storage --output preflight.json
```

A command that can be exercised entirely offline with a synthetic input:

```sh
python -m klipperlearn.host_preflight --snapshot examples/host-preflight.json --output preflight.json
```

The core and standalone ecosystem toolkit have no third-party runtime dependency
for this command. The report checks Python 3.11+, SSL availability, a preliminary
512 MiB free-space threshold and version metadata for optional learning packages.
It does not import those packages, execute system commands, enumerate serial
hardware, read credentials, test network ports, contact a printer, start services,
install Python or run KIAUH. The chosen path, hostname and user are not printed.

Exit 0 means these preliminary prerequisites are present; exit 1 means blockers
or dependencies remain; exit 2 means invalid input/output. None of these results
certifies that TLS, permissions, power/USB stability, performance or memory are
adequate. Do not modify a working Klipper environment to satisfy this report.
Use an isolated environment and the existing Linux deployment guide.

Official KIAUH project: https://github.com/dw-0/kiauh

## Scope and contribution status

This is an independently maintained KlipperLearn integration. It is not an
upstream merge, official listing, endorsement, or physical-printer validation.
All new commands below run locally on supplied files and do not start a print.
No firmware, operating-system service or existing preset is modified.
