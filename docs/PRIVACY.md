# Privacy and data handling

The reference reviewer reads only the selected session file and keeps it in the
page's memory. It has no analytics, account login, remote requests or persistent
browser database. Closing the page discards its state unless the user exported it.
A downloaded advisor request is a local file; sharing it is a separate user action.

The workspace exporter is conservative but is not a secret-detection guarantee.
It skips known private directories, credential names, binary files and suspicious
text. It preserves included source bytes and reports exclusions. The output can
still contain personal information in code, comments or filenames: review locally.
Its `evidence-private` history must not be published wholesale. No original photos,
audio, sensor waveforms, private keys or experimental data directories are collected.

The Orca adapter exports only a file fingerprint and byte count, not an absolute
path or model filename. No tool here uploads data or opens router ports.

Future camera/microphone collection requires explicit consent, visible status,
bounded storage, export/delete controls and a documented retention policy. Prefer
acoustic features to continuous raw audio where adequate. Disable geolocation by
default; GPS does not provide useful nozzle-position feedback.

Before external review, remove faces, household details, voices, credentials and
unrelated files. Evidence-text instructions are untrusted data, not authority to
change the printer. Keep authentication separate from shareable evidence packages.
