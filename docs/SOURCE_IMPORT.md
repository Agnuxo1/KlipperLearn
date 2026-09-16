# Importing the historical workstation source

The current publication does not contain the original `src/klipperlearn` workspace.
A conversation transcript is not source code, a Git snapshot or test evidence.
The export utility archive is the tool, not an export produced by running it.

Run the exporter against the actual workspace, inspect its manifest and withheld
files locally, and preserve the original snapshot unchanged. Source-only offline
export is supported. Do not send private keys, tokens, personal evidence or the
entire raw work directory to a public repository.

Review the existing LICENSE, third-party notices, dependencies, model weights and
STL licenses before import. The MIT license for newly written reference tools must
not overwrite the original project's license requirements. Import in a separate
branch, retaining attribution and commit history where available.

Reproduce the actual tests on that snapshot. Compare original modules with the
contracts in this publication; do not replace them with transcript reconstructions.
Document changed APIs, incompatible data schemas and migration steps. Existing
private experiment databases need explicit review and consent before publication.

Close the import gate only when the source is accessible, secret review is complete,
its provenance is recorded and tests have been reproduced. Historical reported
counts or screenshots of terminal commands alone do not close that gate.
