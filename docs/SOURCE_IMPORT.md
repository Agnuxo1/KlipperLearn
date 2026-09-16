# Workstation source import and publication provenance

The 0.5.1 release imports the real workstation application identified as 0.5.0,
including the Python source, phone browser assets, test suites, example
configuration and original GPL notice. It is not a reconstruction from chat logs.

Work was performed in a separate release-review directory. Before editing, a
filtered source snapshot and SHA-256 inventory were created. The running
application, private configuration, credentials, evidence databases and original
Git history were not edited or uploaded. Source hashes are checked again before
publication to detect accidental changes to the original source selection.

## Included and reconciled

- Original application source and tests, with reviewed security, robustness,
  portability and English-language changes documented in the release review.
- Original GPL-3.0-or-later notice and GPL text.
- Example configuration with generic network addresses, not working credentials.
- Existing MIT reference reviewer and integration tools, retaining their license.
- Author-approved artwork and workshop photographs, with source metadata removed.
- English operational documentation consolidated from the application contracts.

## Not published

The working virtual environment, `.git`, `.cognition`, runtime `work` and `data`
directories, private certificates/keys, credential files, logs, model weights,
experiment databases, local deployment scripts and historical operational journals
remain private. The Spanish workstation planning/incident notes are retained in
the private snapshot; they are not presented as current public installation
instructions or newly verified measurements. Current public guides are in English.

No bulk upload of the original directory or inherited Git history was performed.
The original source license was preserved rather than silently replaced with the
MIT license used by the earlier reference-only publication.

## Review limitations

Secret scanning combines publication allowlists, exclusions, source inspection
and pattern checks. A clean scan is not a mathematical guarantee that every
possible credential format has been detected. Existing private credentials were
not deleted or rotated because the private installation still needs them. If a
credential is ever found in public history, revoke it and review that history;
adding an ignore rule alone is not remediation.
