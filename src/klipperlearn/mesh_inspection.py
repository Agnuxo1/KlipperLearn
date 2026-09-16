"""Inspect user-supplied STL geometry without executing or distributing it."""

import hashlib
from pathlib import Path
import re
import struct


def inspect_stl(path):
    import numpy as np

    path = Path(path)
    if path.stat().st_size > 256 * 1024 * 1024:
        raise ValueError("STL exceeds 256 MB inspection limit")
    raw = path.read_bytes()
    triangles = struct.unpack_from("<I", raw, 80)[0] if len(raw) >= 84 else 0
    binary = triangles > 0 and 84 + 50 * triangles == len(raw)
    if binary:
        dtype = np.dtype(
            [("normal", "<f4", (3,)), ("vertices", "<f4", (3, 3)), ("attribute", "<u2")]
        )
        vertices = np.frombuffer(raw, dtype=dtype, count=triangles, offset=84)["vertices"].reshape(
            -1, 3
        )
    else:
        text = raw.decode("ascii")
        points = re.findall(r"\bvertex\s+(\S+)\s+(\S+)\s+(\S+)", text, re.I)
        if not points or len(points) % 3:
            raise ValueError("Invalid STL triangle structure")
        vertices = np.array(points, dtype=float)
        triangles = len(points) // 3
    if not np.isfinite(vertices).all():
        raise ValueError("STL contains non-finite coordinates")
    low, high = vertices.min(axis=0), vertices.max(axis=0)
    return {
        "filename": path.name,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "triangles": triangles,
        "format": "binary" if binary else "ascii",
        "bounds": [low.tolist(), high.tolist()],
        "size_assuming_mm": (high - low).tolist(),
        "units": "STL has no unit declaration; millimetres assumed",
        "license": "not supplied; do not redistribute",
        "printability_validated": False,
    }


def six_zone_plan(width, depth, margin=10.0, corridor=10.0):
    import math

    if not all(
        isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v > 0
        for v in (width, depth, margin, corridor)
    ):
        raise ValueError("Finite positive bed dimensions and clearances required")
    cell_w, cell_d = (width - 2 * margin - 2 * corridor) / 3, (depth - 2 * margin - corridor) / 2
    if min(cell_w, cell_d) < 20:
        raise ValueError("Insufficient space for six calibration zones")
    return {
        "schema": "klipperlearn-six-zones-v1",
        "bed_mm": [width, depth],
        "margin_mm": margin,
        "corridor_mm": corridor,
        "execution_authorized": False,
        "clearance_verified": False,
        "strategy": "one homing before batch; parameter changes between coupons only",
        "cells": [
            {
                "id": f"R{row + 1}C{col + 1}",
                "origin_mm": [
                    margin + col * (cell_w + corridor),
                    margin + row * (cell_d + corridor),
                ],
                "size_mm": [cell_w, cell_d],
            }
            for row in range(2)
            for col in range(3)
        ],
        "requirements": [
            "verify actual toolhead clearance and maximum coupon height",
            "do not treat six cells as six independent sessions",
            "do not rescale calibration features or import unlicensed models into public repository",
        ],
    }
