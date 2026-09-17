# KlipperLearn sliced-file evidence

Standalone **MIT-licensed**, dependency-free Python helper for OrcaSlicer and
PrusaSlicer post-processing. It fingerprints the exact regular input file without
changing, uploading, interpreting or printing its G-code. SHA-256 proves byte
identity, not equivalent geometry, safe settings, print success or quality.

Requires Python 3.8 or later. Use the slicer's post-processing command field with
an explicit interpreter, this script, and a private output directory. The slicer
appends its temporary filename. Do not append a guessed final filename yourself.
Example syntax on Linux (use actual local paths, quoted when they contain spaces):

```sh
/usr/bin/python3 "/opt/klipperlearn-tools/klipperlearn_manifest.py" --output-dir "/home/operator/KlipperLearn/slice-manifests"
```

For a manual standalone check, append the file explicitly:

```sh
python klipperlearn_manifest.py --output-dir ./manifests ./supervised-test.gcode
```

The file is streamed with a 512 MiB maximum and checked for changes during reading.
Manifests contain the hash and size, not G-code, private filenames or source paths.
Existing conflicting outputs are never overwritten. A sidecar may refer to a
slicer-generated temporary copy, not a later modified or uploaded file. Verify
identity at the actual downstream stage separately.

Contract tests include spaces, Unicode, links, failure cases and original-byte
preservation. **Native-slicer GUI acceptance has not been performed.** This is
not an official vendor plugin, built-in feature or accepted upstream change.
Project support and canonical source: https://github.com/Agnuxo1/KlipperLearn
