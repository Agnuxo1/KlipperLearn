#!/usr/bin/env python3
"""Build the original calibration coupon distribution; never contact hardware.

SPDX-License-Identifier: GPL-3.0-or-later
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path
import struct
import zipfile

ROOT = Path(__file__).resolve().parents[1]
COUPON = "src/klipperlearn/mobile_app/adjustment-card.stl"
SOURCE = "src/klipperlearn/slicer_benchmark.py"
STL_NAME = "KlipperLearn-Calibration-Card.stl"


def audit_stl(data: bytes) -> dict:
    """Check binary structure and closed, consistently oriented edge topology.

    These are geometric checks, not self-intersection or physical print tests.
    """
    if len(data) < 84:
        raise ValueError("Truncated binary STL")
    count = struct.unpack_from("<I", data, 80)[0]
    if not count or len(data) != 84 + 50 * count:
        raise ValueError("Invalid binary STL triangle count")
    directed = Counter()
    adjacency = defaultdict(set)
    unique_faces = set()
    volume = 0.0
    for record in struct.iter_unpack("<12fH", data[84:]):
        if not all(math.isfinite(v) for v in record[:12]):
            raise ValueError("Non-finite STL coordinate or normal")
        n = record[:3]
        a, b, c = record[3:6], record[6:9], record[9:12]
        u = tuple(b[i] - a[i] for i in range(3))
        v = tuple(c[i] - a[i] for i in range(3))
        cross = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
        if not any(cross) or sum(n[i] * cross[i] for i in range(3)) <= 0:
            raise ValueError("Degenerate triangle or inconsistent stored normal")
        face = tuple(sorted((a, b, c)))
        if face in unique_faces:
            raise ValueError("Duplicate triangle")
        unique_faces.add(face)
        for first, second in ((a, b), (b, c), (c, a)):
            directed[(first, second)] += 1
            adjacency[first].add(second)
            adjacency[second].add(first)
        volume += (
            a[0] * (b[1] * c[2] - b[2] * c[1])
            + a[1] * (b[2] * c[0] - b[0] * c[2])
            + a[2] * (b[0] * c[1] - b[1] * c[0])
        ) / 6
    if any(n != 1 or directed[(b, a)] != 1 for (a, b), n in directed.items()):
        raise ValueError("Open, non-manifold or inconsistently oriented edge")
    remaining = set(adjacency)
    components = 0
    while remaining:
        components += 1
        pending = [remaining.pop()]
        while pending:
            for neighbor in adjacency[pending.pop()]:
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    pending.append(neighbor)
    if components != 1 or volume <= 0:
        raise ValueError("Expected one connected positive-volume component")
    bounds = [
        [min(p[i] for p in adjacency) for i in range(3)],
        [max(p[i] for p in adjacency) for i in range(3)],
    ]
    return {
        "schema": "klipperlearn.coupon-geometry/v1",
        "file": STL_NAME,
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "triangles": count,
        "vertices": len(adjacency),
        "bounds_mm": bounds,
        "dimensions_mm": [bounds[1][i] - bounds[0][i] for i in range(3)],
        "geometric_volume_mm3": round(volume, 6),
        "connected_components": components,
        "closed_oriented_edges": True,
        "finite_nondegenerate_triangles": True,
        "self_intersections_tested": False,
        "physically_tested": False,
        "native_slicer_acceptance_tested": False,
    }


def source_exporter(root: Path) -> bytes:
    """Keep the exact original generator and add a safe standalone CLI."""
    source = (root / SOURCE).read_text(encoding="utf-8")
    return (
        source + '\n\nif __name__ == "__main__":\n'
        "    import argparse\n    from pathlib import Path\n"
        '    parser = argparse.ArgumentParser(description="Export the original coupon; never print it.")\n'
        '    parser.add_argument("--output", type=Path, default=Path("KlipperLearn-Calibration-Card.stl"))\n'
        "    args = parser.parse_args()\n"
        '    with args.output.open("xb") as stream:\n        stream.write(calibration_card_stl())\n'
    ).encode("utf-8")


def package_files(root: Path) -> dict[str, bytes]:
    """Select public files explicitly; never package local state or credentials."""
    data = (root / COUPON).read_bytes()
    report = audit_stl(data)
    spec = importlib.util.spec_from_file_location("publication_coupon", root / SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if module.calibration_card_stl() != data:
        raise ValueError("Published STL no longer matches its original source")
    files = {
        STL_NAME: data,
        "README.txt": (root / "publication/listing.en.txt").read_bytes(),
        "LICENSE.txt": (root / "LICENSE").read_bytes(),
        "COPYING.txt": (root / "COPYING").read_bytes(),
        "export_calibration_card.py": source_exporter(root),
        "geometry-report.txt": (json.dumps(report, indent=2) + "\n").encode(),
    }
    image = root / "publication/calibration-card-render.png"
    if image.is_file():
        files[image.name] = image.read_bytes()
    sums = "".join(
        f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in sorted(files.items())
    )
    files["SHA256SUMS.txt"] = sums.encode()
    return files


def archive_bytes(files: dict[str, bytes]) -> bytes:
    """Create a deterministic archive with portable names and fixed timestamps."""
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            if Path(name).name != name or name in {".", ".."} or "\\" in name:
                raise ValueError("Only safe, flat public filenames are accepted")
            info = zipfile.ZipInfo(name, date_time=(2026, 9, 17, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    return stream.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    files = package_files(ROOT)
    for name, data in files.items():
        (args.output / name).write_bytes(data)
    archive = args.output / "KlipperLearn-0.6.0-Model-Platform-Kit.zip"
    archive.write_bytes(archive_bytes(files))
    print(
        json.dumps(
            {
                "archive": archive.name,
                "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                "bytes": archive.stat().st_size,
                "files": len(files),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
