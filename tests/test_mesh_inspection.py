import struct

import pytest

from klipperlearn.mesh_inspection import inspect_stl, six_zone_plan


def test_binary_bounds_and_unlicensed_provenance(tmp_path):
    path = tmp_path / "test.stl"
    path.write_bytes(
        b" " * 80 + struct.pack("<I12fH", 1, 0, 0, 1, 0, 0, 0, 30, 0, 0, 0, 30, 16.5, 0)
    )
    result = inspect_stl(path)
    assert result["size_assuming_mm"] == [30, 30, 16.5]
    assert result["triangles"] == 1
    assert not result["printability_validated"]


def test_six_cells_with_margins_not_an_execution_plan():
    result = six_zone_plan(270, 215)
    assert len(result["cells"]) == 6
    assert result["cells"][0]["size_mm"] == pytest.approx([76.6666667, 92.5])
    assert not result["execution_authorized"]
    for cell in result["cells"]:
        for axis, maximum in enumerate((270, 215)):
            assert cell["origin_mm"][axis] >= 10
            assert cell["origin_mm"][axis] + cell["size_mm"][axis] <= maximum - 10 + 1e-6
    with pytest.raises(ValueError):
        six_zone_plan(30, 30)
