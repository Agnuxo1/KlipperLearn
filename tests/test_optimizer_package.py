"""Package integrity and original benchmark geometry checks."""

from collections import Counter
from pathlib import Path
import json
import struct

from klipperlearn.slicer_benchmark import calibration_card_stl

ROOT = Path(__file__).resolve().parents[1]


def test_coupon_is_watertight_positive_volume_and_exact_size():
    raw = calibration_card_stl()
    count = struct.unpack_from("<I", raw, 80)[0]
    assert len(raw) == 84 + 50 * count
    edges, vertices = Counter(), set()
    volume = 0
    for i in range(count):
        data = struct.unpack_from("<12fH", raw, 84 + 50 * i)
        normal, a, b, c = data[:3], data[3:6], data[6:9], data[9:12]
        vertices.update((a, b, c))
        ab, ac = [b[j] - a[j] for j in range(3)], [c[j] - a[j] for j in range(3)]
        cross = (
            ab[1] * ac[2] - ab[2] * ac[1],
            ab[2] * ac[0] - ab[0] * ac[2],
            ab[0] * ac[1] - ab[1] * ac[0],
        )
        assert sum(normal[j] * cross[j] for j in range(3)) > 0
        volume += sum(a[j] * cross[j] for j in range(3)) / 6
        for left, right in ((a, b), (b, c), (c, a)):
            edges[tuple(sorted((left, right)))] += 1
    assert set(edges.values()) == {2} and volume > 0
    assert [max(v[j] for v in vertices) - min(v[j] for v in vertices) for j in range(3)] == [
        40,
        30,
        12,
    ]


def test_plugin_copies_match_canonical_source_and_coupon():
    skill = ROOT / "plugins/printer-optimizer/skills/printer-optimizer"
    assert (skill / "scripts/optimizer.py").read_bytes() == (
        ROOT / "src/klipperlearn/slicer_optimizer.py"
    ).read_bytes()
    assert (skill / "assets/adjustment-card.stl").read_bytes() == calibration_card_stl()
    assert (
        ROOT / "src/klipperlearn/mobile_app/adjustment-card.stl"
    ).read_bytes() == calibration_card_stl()


def test_plugin_manifest_and_marketplace_have_no_invented_connection():
    plugin = ROOT / "plugins/printer-optimizer"
    manifest = json.loads((plugin / "plugin.json").read_text())
    assert manifest["name"] == "klipperlearn-printer-optimizer"
    assert manifest["$schema"].startswith("https://agent-plugins.org/")
    assert "apps" not in manifest["extensions"]["com.openai"]
    assert not (plugin / "mcp.json").exists()
    marketplace = json.loads((ROOT / ".agents/plugins/marketplace.json").read_text())
    source = marketplace["plugins"][0]["source"]["path"]
    assert (ROOT / source / "plugin.json").is_file()
