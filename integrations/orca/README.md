# OrcaSlicer slice manifest adapter

Run `klipperlearn_manifest.py` as a standalone CLI or the last post-processing
script. It writes an exact SHA-256 and byte-count manifest to a persistent directory
without changing the input file. It never contacts a printer.

See `../../docs/INTEGRATIONS.md`. The output is an artifact identity, not a quality
score, a geometry-equivalence proof or confirmation that those bytes were printed.
The adapter is not a native plugin and has not been tested inside Orca's desktop UI.
