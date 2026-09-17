# KlipperLearn standalone ecosystem toolkit

Free, GPL-3.0-or-later. Requires Python 3.11+. No pip packages, printer service,
phone, API key or network access are required for these offline commands.
Unzip into a new directory and open a terminal in that directory. Nothing is
installed automatically and existing outputs are never overwritten.

```sh
python -m klipperlearn.ecosystem_evidence history --input examples/ecosystem-history.json --printer-id demo --workflow manual --output history.json
python -m klipperlearn.ecosystem_evidence status --input examples/ecosystem-status.json --output status.json
python -m klipperlearn.host_preflight --snapshot examples/host-preflight.json --output host.json
python -m klipperlearn.camera_proxy settings --frontend mainsail
python -m klipperlearn.camera_proxy settings --frontend fluidd
python -m klipperlearn.slicer_optimizer profiles --session examples/synthetic-slicer-session.json --output DEMO-profiles.zip
python -m klipperlearn.orca_bundle_audit --session examples/synthetic-slicer-session.json --bundle DEMO-profiles.zip --output DEMO-audit.json
```

The examples are synthetic and do not authorize a real print. The output file
names above must be new. The Voron template is intentionally incomplete and
requires actual independently reviewed physical evidence; it is not a passing
demonstration of compatibility. Camera configuration generation is not deployment.

The separate Cura archive installs as a post-processing script, the separate
OctoPrint archive packages an independent event plugin, and the slicer-sidecar
archive serves OrcaSlicer/PrusaSlicer without changing G-code. These deliverables
are not installed or officially included in ten upstream repositories. Native
application acceptance and maintained upstream submissions are separate steps.

Detailed current guides, source and limitations:
https://github.com/Agnuxo1/KlipperLearn/tree/main/integrations
