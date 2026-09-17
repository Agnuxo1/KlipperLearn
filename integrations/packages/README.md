# Downloadable integration packages

These standalone source distributions are built from the reviewed files in this
repository. They are **not** official upstream releases or registrations.

| Package | Purpose | Acceptance scope |
| --- | --- | --- |
| [Cura evidence](KlipperLearn-Cura-Evidence.zip) | Post-processing without G-code changes | Contract tests; native GUI not verified. |
| [OctoPrint Evidence 0.1.1](OctoPrint-KlipperLearnEvidence-0.1.1.zip) | Independent local event plugin | Package build and simulated plugin API; native instance not exercised. |
| [Orca/PrusaSlicer sidecar](KlipperLearn-Slicer-Evidence.zip) | Exact sliced-file fingerprint | File/CLI tests; native UI not verified. |
| [Offline ecosystem toolkit](KlipperLearn-Ecosystem-Toolkit.zip) | History, status, camera configuration, host preflight, Orca bundle and Voron evidence checks | Standalone commands verified without site-packages; no device control. |

Check [SHA256SUMS](SHA256SUMS) and [manifest.json](manifest.json). The manifest
lists every source and destination file with its SHA-256. ZIP members use fixed
timestamps and stored text with LF line endings for cross-platform reproducibility.
No Git history, runtime database, private credentials, model weights or pip packages
are included. Relative event file names can identify private projects and must
be reviewed before sharing generated evidence.

Run `python tools/build_ecosystem_packages.py --check` in the repository to verify
all artifacts. To build fresh outputs, pass `--output-dir` with a new path.
The builder refuses to overwrite an existing directory. Installation and physical
trials require operator review; this command performs neither.

Project-specific instructions: [ecosystem guide](../ecosystem/README.md).
