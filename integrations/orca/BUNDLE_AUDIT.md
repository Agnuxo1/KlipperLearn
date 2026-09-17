# Verify the three-mode preset bundle before importing it

The existing generator emits three process/filament pairs plus `review.json`.
The new audit reconstructs the expected output from the exact reviewed session
and checks the supplied ZIP without extracting or importing any file:

```sh
python -m klipperlearn.orca_bundle_audit --session session.json --bundle profiles.zip --output bundle-audit.json
```

It rejects missing/duplicate/extra paths, linked or encrypted entries, oversized
members, a different session, changed temperatures/G-code, geometry alterations
and mismatched preset pairs. It fingerprints the exact audited archive bytes.
The command needs only the dependency-free core or standalone ecosystem toolkit.

This is stronger than checking that six JSON files exist, but it remains a
reproducibility/consistency check. It does not invoke Orca's native importer,
resolve all inherited printer settings, certify hardware compatibility or print
a model. After review, import the presets through Orca's normal configuration
import, inspect the effective settings and G-code preview, then supervise the
first physical trial. Keep synthetic DEMO outputs separate from real presets.

Orca's public import/export workflow:
https://www.orcaslicer.com/wiki/general_settings/import_export
