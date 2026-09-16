import hashlib
import json
import zipfile

import pytest

from klipperlearn.experiment_store import ExperimentStore
from klipperlearn.evidence_backup import export_evidence


def test_backup_preserves_database_assets_and_hashes_not_server_secrets(tmp_path):
    root = tmp_path / "evidence"
    store = ExperimentStore(root)
    trial = store.create_trial(
        {
            "printer_id": "p",
            "session_id": "s",
            "model_sha256": "a" * 64,
            "material": "PLA",
            "nozzle_mm": 0.4,
        },
        {},
    )
    store.rate_trial(trial["id"], {"speed": 4, "surface": 3, "geometry": 4})
    assets = root / "assets"
    assets.mkdir(exist_ok=True)
    (assets / "events.jsonl").write_bytes(b'{"complete":true}\n{"incomplete":')
    (root / "token.txt").write_text("must-not-export")
    output = tmp_path / "backup.zip"
    result = export_evidence(root, output)
    assert result["files"] == 2
    with zipfile.ZipFile(output) as archive:
        assert "token.txt" not in archive.namelist()
        manifest = json.loads(archive.read("backup-manifest.json"))
        for entry in manifest["files"]:
            assert hashlib.sha256(archive.read(entry["path"])).hexdigest() == entry["sha256"]
        assert archive.read("assets/events.jsonl") == b'{"complete":true}\n'
    with pytest.raises(ValueError):
        export_evidence(root, output)
    with pytest.raises(ValueError):
        export_evidence(root, root / "nested.zip")
