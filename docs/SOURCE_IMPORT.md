# Importing the historical workstation source

## Current boundary

The current publication does not contain the original `src/klipperlearn` workspace.
A conversation transcript is not source code, a Git snapshot or test evidence.
The export utility archive is the tool, not an export produced by running it.
Access to the actual files is required before the import can be declared complete.

## Preserve the working installation

Work on a separate staging copy, not the active printer installation. Inventory
the source, tests, configuration, assets and dependencies, and preserve an unchanged
private snapshot with file hashes. Do not run printer-control commands, change
credentials in the active installation or start an experiment as part of publishing.

The source-only offline exporter can prepare a private review package. Read its
manifest and inspect withheld files locally; the exporter intentionally does not
claim to include every file or to certify that a package is safe for publication.

## Review private material before creating public Git objects

Exclude private keys, certificates containing private keys, tokens, passwords,
Wi-Fi credentials, authentication cookies and session files. Inspect launchers,
configuration, notebooks, logs, generated HTML, screenshots and archived files,
not just the main source directory. Public certificate material must be distinguished
from private-key material and reviewed for necessity.

Remove personal account identifiers, workstation paths, device serial numbers,
private network details and unneeded image metadata from the publication copy.
Retain deliberately chosen public authorship and license attribution. Do not replace
safe software constants or test data solely because a pattern resembles a secret.

Keep private experiment databases, photographs, recordings and raw telemetry outside
the public repository unless a specific reviewed subset is approved for release.
Review privacy and provenance for every public media asset.

Replace embedded credentials with local configuration or environment-variable
loading, and provide non-secret examples with clear validation errors. Do not
silently disable authentication to make the public example run. Preserve the
working private configuration outside version control.

`.gitignore` prevents some accidental additions; it is not a content scanner and
it does not remove already tracked files. Inspect the staged diff, filenames,
file contents and any Git history intended for publication. Do not blindly push
an existing private history. If an actual credential is already public, removing
it from the latest file is not sufficient: address revocation or rotation through
the provider and review the exposed history without printing the secret in logs.

## Preserve licensing and implementation

Review the existing LICENSE, third-party notices, dependencies, model weights and
STL licenses before import. The MIT license for the new reference tools must not
overwrite the original project's requirements. Preserve attribution and retain
original history privately; publish historical commits only after reviewing them.

Import through a separate branch. Reconcile the original modules with the public
contracts rather than replacing them with transcript reconstructions. Document
API and data-schema differences, migration steps and all behavior-changing edits.
Translate user-facing text and documentation carefully; do not rename protocol
fields or identifiers in a way that breaks existing integrations.

## Validation and publication record

Reproduce the actual source tests without contacting hardware. Record exact commands,
environments, results, skipped tests and any limitations. Review configuration and
permission behavior after removing private defaults. Distinguish synthetic tests,
reported historical runs and newly verified hardware results.

Before merging, record the reviewed source snapshot, included/excluded categories,
license review, test results and remaining blockers. Reports must not contain secret
values. Verify the resulting remote commit, file tree and CI run after publication.

Close the import gate only when the source is accessible, the publication copy and
its history have been reviewed, provenance is recorded and tests have been reproduced.
Historical counts or screenshots of commands alone do not close that gate.
