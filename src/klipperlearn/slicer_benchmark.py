"""Original 40 x 30 x 12 mm calibration coupon; never slices or prints it.

SPDX-License-Identifier: GPL-3.0-or-later
The connected voxel boundary provides steps, narrow walls, gaps and a bridge.
It is an original screening coupon, not 3DBenchy or an official benchmark.
"""

import struct


def calibration_card_stl() -> bytes:
    """Return a watertight binary STL in millimetres, preserving all exposed faces."""
    boxes = (
        (0, 40, 0, 30, 0, 1),
        (2, 12, 2, 12, 1, 5),
        (4, 10, 4, 10, 5, 9),
        (16, 20, 2, 8, 1, 11),
        (30, 34, 2, 8, 1, 11),
        (16, 34, 2, 8, 11, 12),
        (2, 38, 26, 27, 1, 6),
        (2, 3, 17, 23, 1, 4),
        (5, 7, 17, 23, 1, 4),
        (10, 13, 17, 23, 1, 4),
    )
    voxels = {
        (x, y, z)
        for x0, x1, y0, y1, z0, z1 in boxes
        for x in range(x0, x1)
        for y in range(y0, y1)
        for z in range(z0, z1)
    }
    faces = (
        ((-1, 0, 0), ((0, 0, 0), (0, 0, 1), (0, 1, 1), (0, 1, 0))),
        ((1, 0, 0), ((1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1))),
        ((0, -1, 0), ((0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1))),
        ((0, 1, 0), ((0, 1, 0), (0, 1, 1), (1, 1, 1), (1, 1, 0))),
        ((0, 0, -1), ((0, 0, 0), (0, 1, 0), (1, 1, 0), (1, 0, 0))),
        ((0, 0, 1), ((0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1))),
    )
    triangles = []
    for x, y, z in sorted(voxels):
        for normal, corners in faces:
            if (x + normal[0], y + normal[1], z + normal[2]) in voxels:
                continue
            points = [(x + dx, y + dy, z + dz) for dx, dy, dz in corners]
            for a, b, c in ((0, 1, 2), (0, 2, 3)):
                triangles.append(
                    struct.pack("<12fH", *normal, *points[a], *points[b], *points[c], 0)
                )
    return (
        b"KlipperLearn original screening coupon; millimetres; not 3DBenchy".ljust(80, b" ")
        + struct.pack("<I", len(triangles))
        + b"".join(triangles)
    )
