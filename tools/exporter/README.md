# Workspace and history review exporter

Python 3.8+, standard library only. Select an existing workspace with `--root`.
Default workspace is the current directory; default Moonraker origin is loopback.
Use `--offline` for source-only export.

The tool reads selected text source and GET-only history, and produces a private
review ZIP. It never prints, heats, homes, cancels, changes settings, installs
packages or uploads files. Known private directories and credential files are
excluded. Suspicious content is withheld without changing the original file.
Review the manifest and all included bytes locally: screening is not a guarantee.

History pagination is not a transactional snapshot. Failures preserve partial
results and warnings. Authorization is not bypassed; authenticated servers need
another approved export route. TLS verification is never disabled.

Run tests from the repository root:

```sh
python -m unittest discover -s tools/exporter/tests -v
```
