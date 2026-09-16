"""Local first-layer geometry chart analysis.

The chart is a measurement aid, not a printer controller.  A homography maps
four ordered image fiducials to known millimetre coordinates, the image is
rectified to the chart plane, and an explicit light/dark Otsu segmentation is
compared with the paths declared by the manifest.  The result remains
geometrical evidence for human review; it does not infer pressure advance,
input-shaper values, or any other printer parameter.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import hashlib
import json
import math
from numbers import Real
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
CHART_KIND = "first_layer_geometry"
ANALYSIS_KIND = "first_layer_geometry"
MAX_RECTIFIED_SIZE = 1024
MAX_INPUT_PIXELS = 20_000_000
MIN_PROJECTED_PIXELS_PER_LINE = 2.0
MIN_CONTRAST_SCORE = 0.05
MIN_FOCUS_SCORE = 12.0
_GEOMETRY_EPSILON = 1e-9


class ChartGeometryError(ValueError):
    """Raised internally when a chart cannot produce a reliable map."""


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ChartGeometryError(f"{field} must be a finite number")
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ChartGeometryError(f"{field} must be a finite number") from exc
    if not math.isfinite(number):
        raise ChartGeometryError(f"{field} must be a finite number")
    return number


def _point_list(value: Any, field: str, *, exact_length: int | None = None) -> list[list[float]]:
    if not isinstance(value, (list, tuple)):
        raise ChartGeometryError(f"{field} must be a list of points")
    if exact_length is not None and len(value) != exact_length:
        raise ChartGeometryError(f"{field} must contain exactly {exact_length} points")
    result: list[list[float]] = []
    for index, raw_point in enumerate(value):
        if not isinstance(raw_point, (list, tuple)) or len(raw_point) != 2:
            raise ChartGeometryError(f"{field}[{index}] must be [x, y]")
        result.append(
            [
                _finite_number(raw_point[0], f"{field}[{index}][0]"),
                _finite_number(raw_point[1], f"{field}[{index}][1]"),
            ]
        )
    return result


def _polygon_area(points: Sequence[Sequence[float]]) -> float:
    return abs(
        sum(
            points[index][0] * points[(index + 1) % len(points)][1]
            - points[(index + 1) % len(points)][0] * points[index][1]
            for index in range(len(points))
        )
        / 2.0
    )


def _validate_convex_quadrilateral(points: Any, field: str) -> list[list[float]]:
    normalized = _point_list(points, field, exact_length=4)
    scale = max(
        1.0,
        max(abs(point[coordinate]) for point in normalized for coordinate in (0, 1)),
    )
    cross_products: list[float] = []
    for index in range(4):
        previous = normalized[index - 1]
        current = normalized[index]
        following = normalized[(index + 1) % 4]
        edge_a = (current[0] - previous[0], current[1] - previous[1])
        edge_b = (following[0] - current[0], following[1] - current[1])
        cross_products.append(edge_a[0] * edge_b[1] - edge_a[1] * edge_b[0])

    tolerance = _GEOMETRY_EPSILON * scale * scale
    if any(abs(cross) <= tolerance for cross in cross_products):
        raise ChartGeometryError(f"{field} is degenerate")
    signs = {cross > 0.0 for cross in cross_products}
    if len(signs) != 1:
        raise ChartGeometryError(f"{field} must be ordered as a convex quadrilateral")
    area = _polygon_area(normalized)
    if area <= tolerance:
        raise ChartGeometryError(f"{field} has zero area")
    return normalized


def validate_corners(corners_px: Any) -> list[list[float]]:
    """Validate four ordered, finite, convex image corners."""
    return _validate_convex_quadrilateral(corners_px, "corners_px")


def validate_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize the schema-v1 first-layer geometry manifest."""
    if not isinstance(manifest, Mapping):
        raise ChartGeometryError("manifest must be an object")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ChartGeometryError("manifest schema_version must be 1")
    if manifest.get("kind") != CHART_KIND:
        raise ChartGeometryError("manifest kind must be 'first_layer_geometry'")

    bounds_raw = manifest.get("bounds_mm")
    if not isinstance(bounds_raw, (list, tuple)) or len(bounds_raw) != 4:
        raise ChartGeometryError("bounds_mm must be [x, y, width, height]")
    bounds = [
        _finite_number(value, f"bounds_mm[{index}]") for index, value in enumerate(bounds_raw)
    ]
    x0, y0, width_mm, height_mm = bounds
    if width_mm <= 0.0 or height_mm <= 0.0:
        raise ChartGeometryError("bounds_mm width and height must be positive")

    line_width_mm = _finite_number(manifest.get("line_width_mm"), "line_width_mm")
    layer_height_mm = _finite_number(manifest.get("layer_height_mm"), "layer_height_mm")
    if line_width_mm <= 0.0:
        raise ChartGeometryError("line_width_mm must be positive")
    if layer_height_mm <= 0.0:
        raise ChartGeometryError("layer_height_mm must be positive")

    paths_raw = manifest.get("paths")
    if not isinstance(paths_raw, list) or not paths_raw:
        raise ChartGeometryError("paths must be a non-empty list")
    paths: list[dict[str, Any]] = []
    path_ids: set[str] = set()
    boundary_tolerance = max(width_mm, height_mm, 1.0) * 1e-7
    for index, raw_path in enumerate(paths_raw):
        if not isinstance(raw_path, Mapping):
            raise ChartGeometryError(f"paths[{index}] must be an object")
        path_id = raw_path.get("id")
        role = raw_path.get("role")
        if not isinstance(path_id, str) or not path_id.strip():
            raise ChartGeometryError(f"paths[{index}].id must be non-empty text")
        if path_id in path_ids:
            raise ChartGeometryError(f"duplicate path id: {path_id}")
        path_ids.add(path_id)
        if not isinstance(role, str) or not role.strip():
            raise ChartGeometryError(f"paths[{index}].role must be non-empty text")
        points = _point_list(raw_path.get("points_mm"), f"paths[{index}].points_mm")
        if len(points) < 2:
            raise ChartGeometryError(f"paths[{index}].points_mm needs at least two points")
        if not any(
            math.hypot(
                points[point_index + 1][0] - points[point_index][0],
                points[point_index + 1][1] - points[point_index][1],
            )
            > boundary_tolerance
            for point_index in range(len(points) - 1)
        ):
            raise ChartGeometryError(f"paths[{index}].points_mm is degenerate")
        for point_index, point in enumerate(points):
            if not (
                x0 - boundary_tolerance <= point[0] <= x0 + width_mm + boundary_tolerance
                and y0 - boundary_tolerance <= point[1] <= y0 + height_mm + boundary_tolerance
            ):
                raise ChartGeometryError(
                    f"paths[{index}].points_mm[{point_index}] lies outside bounds_mm"
                )
        paths.append({"id": path_id, "role": role, "points_mm": points})

    fiducials = _validate_convex_quadrilateral(manifest.get("fiducials_mm"), "fiducials_mm")
    for index, point in enumerate(fiducials):
        if not (
            x0 - boundary_tolerance <= point[0] <= x0 + width_mm + boundary_tolerance
            and y0 - boundary_tolerance <= point[1] <= y0 + height_mm + boundary_tolerance
        ):
            raise ChartGeometryError(f"fiducials_mm[{index}] lies outside bounds_mm")

    synthetic = manifest.get("synthetic", False)
    if type(synthetic) is not bool:
        raise ChartGeometryError("manifest synthetic must be boolean when present")

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": CHART_KIND,
        "bounds_mm": bounds,
        "line_width_mm": line_width_mm,
        "layer_height_mm": layer_height_mm,
        "paths": paths,
        "fiducials_mm": fiducials,
        "synthetic": synthetic,
    }


def sha256_file(path: str | Path) -> str:
    """Return a local image/file SHA-256 digest."""
    source = Path(path)
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_vision_dependencies():
    try:
        import cv2
        import numpy as np
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(
            "Chart analysis requires optional OpenCV, NumPy, and Pillow dependencies. "
            "Install them with: pip install -e '.[vision]'"
        ) from exc
    return cv2, np, Image


def _empty_metrics() -> dict[str, Any]:
    return {
        "coverage": None,
        "precision": None,
        "iou": None,
        "missing_fraction": None,
        "excess_fraction": None,
        "loss": 1.0,
        "contrast_score": None,
        "contrast": None,
        "focus_score": None,
        "focus": None,
        "laplacian_variance": None,
        "projected_px_per_line": None,
        "source_px_per_line": None,
        "raster_px_per_line": None,
        "source_px_per_mm_lower_bound": None,
        "otsu_threshold": None,
        "expected_pixels": None,
        "observed_pixels": None,
        "evaluated_pixels": None,
    }


def _invalid_result(
    image_hash: str | None,
    reasons: Sequence[str],
    *,
    synthetic: bool = False,
    metrics: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    merged_metrics = _empty_metrics()
    if metrics:
        merged_metrics.update(metrics)
    result = {
        "schema_version": SCHEMA_VERSION,
        "kind": ANALYSIS_KIND,
        "analysis": "chart_vision",
        "synthetic": synthetic,
        "metrics": merged_metrics,
        "usable_for_review": False,
        "reasons": list(reasons),
        "image_sha256": image_hash,
        "requires_human_review": True,
        "adjustment_allowed": False,
        "validated_on_printer": False,
        "automatic_control": False,
        "evidence_scope": "first_layer_geometry_only",
        "limitations": [
            "Geometrical IoU is not proof of pressure advance or input-shaper performance."
        ],
    }
    for metric_name in (
        "coverage",
        "precision",
        "iou",
        "missing_fraction",
        "excess_fraction",
        "loss",
        "focus_score",
        "contrast_score",
        "projected_px_per_line",
        "source_px_per_line",
        "raster_px_per_line",
        "source_px_per_mm_lower_bound",
    ):
        result[metric_name] = merged_metrics[metric_name]
    return result


def _world_to_rectified(
    point: Sequence[float], bounds: Sequence[float], scale_x: float, scale_y: float
) -> tuple[float, float]:
    return ((point[0] - bounds[0]) * scale_x, (point[1] - bounds[1]) * scale_y)


def _point_inside_convex_polygon(
    point: Sequence[float], polygon: Sequence[Sequence[float]]
) -> bool:
    crosses = []
    for index in range(len(polygon)):
        current = polygon[index]
        following = polygon[(index + 1) % len(polygon)]
        crosses.append(
            (following[0] - current[0]) * (point[1] - current[1])
            - (following[1] - current[1]) * (point[0] - current[0])
        )
    tolerance = 1e-6 * max(1.0, max(abs(value) for vertex in polygon for value in vertex))
    return all(cross >= -tolerance for cross in crosses) or all(
        cross <= tolerance for cross in crosses
    )


def _inverse_homography_jacobian(np, inverse_homography, point):
    u, v = float(point[0]), float(point[1])
    a, b, c = inverse_homography[0]
    d, e, f = inverse_homography[1]
    g, h, i = inverse_homography[2]
    denominator = g * u + h * v + i
    if not math.isfinite(float(denominator)) or abs(float(denominator)) <= 1e-12:
        return None
    x_numerator = a * u + b * v + c
    y_numerator = d * u + e * v + f
    denominator_squared = denominator * denominator
    jacobian = np.asarray(
        [
            [
                (a * denominator - x_numerator * g) / denominator_squared,
                (b * denominator - x_numerator * h) / denominator_squared,
            ],
            [
                (d * denominator - y_numerator * g) / denominator_squared,
                (e * denominator - y_numerator * h) / denominator_squared,
            ],
        ],
        dtype=np.float64,
    )
    if not np.isfinite(jacobian).all():
        return None
    return jacobian


def _source_resolution_lower_bound(np, homography, destination):
    """Sample the inverse map and return source px per rectified output px."""
    try:
        inverse_homography = np.linalg.inv(homography)
    except np.linalg.LinAlgError:
        return None
    samples: list[tuple[float, float]] = [tuple(map(float, point)) for point in destination]
    for index in range(4):
        current = destination[index]
        following = destination[(index + 1) % 4]
        samples.append(
            (
                (current[0] + following[0]) / 2.0,
                (current[1] + following[1]) / 2.0,
            )
        )
    samples.append(
        (
            sum(point[0] for point in destination) / 4.0,
            sum(point[1] for point in destination) / 4.0,
        )
    )
    min_x = min(point[0] for point in destination)
    max_x = max(point[0] for point in destination)
    min_y = min(point[1] for point in destination)
    max_y = max(point[1] for point in destination)
    for y_value in np.linspace(min_y, max_y, num=7):
        for x_value in np.linspace(min_x, max_x, num=7):
            candidate = (float(x_value), float(y_value))
            if _point_inside_convex_polygon(candidate, destination):
                samples.append(candidate)

    singular_values: list[float] = []
    for point in samples:
        jacobian = _inverse_homography_jacobian(np, inverse_homography, point)
        if jacobian is None:
            return None
        try:
            values = np.linalg.svd(jacobian, compute_uv=False)
        except np.linalg.LinAlgError:
            return None
        if not np.isfinite(values).all() or values.size != 2:
            return None
        smallest = float(values[-1])
        if not math.isfinite(smallest) or smallest <= 0.0:
            return None
        singular_values.append(smallest)
    if not singular_values:
        return None
    return min(singular_values)


def _rectify_image(cv2, np, image, corners_px, manifest):
    height, width = image.shape[:2]
    source_area = _polygon_area(corners_px)
    image_area = float(max(1, width * height))
    if source_area < 16.0 or source_area / image_area < 1e-5:
        raise ChartGeometryError("unreliable_homography: image quadrilateral is too small")
    for index, point in enumerate(corners_px):
        if not (-0.5 <= point[0] <= width - 0.5 and -0.5 <= point[1] <= height - 0.5):
            raise ChartGeometryError(f"invalid_geometry: corners_px[{index}] lies outside image")

    bounds = manifest["bounds_mm"]
    chart_width_mm = bounds[2]
    chart_height_mm = bounds[3]
    scale = min(MAX_RECTIFIED_SIZE / chart_width_mm, MAX_RECTIFIED_SIZE / chart_height_mm)
    rectified_width = max(2, min(MAX_RECTIFIED_SIZE, int(round(chart_width_mm * scale))))
    rectified_height = max(2, min(MAX_RECTIFIED_SIZE, int(round(chart_height_mm * scale))))
    scale_x = rectified_width / chart_width_mm
    scale_y = rectified_height / chart_height_mm
    raster_px_per_line = manifest["line_width_mm"] * min(scale_x, scale_y)

    destination = [
        _world_to_rectified(point, bounds, scale_x, scale_y) for point in manifest["fiducials_mm"]
    ]
    source_array = np.asarray(corners_px, dtype=np.float32)
    destination_array = np.asarray(destination, dtype=np.float32)
    homography = cv2.getPerspectiveTransform(source_array, destination_array)
    if not np.isfinite(homography).all() or abs(float(np.linalg.det(homography))) <= 1e-12:
        raise ChartGeometryError("unreliable_homography: non-finite or singular map")
    try:
        condition = float(np.linalg.cond(homography))
    except (TypeError, ValueError, np.linalg.LinAlgError):
        condition = math.inf
    if not math.isfinite(condition) or condition > 1e12:
        raise ChartGeometryError("unreliable_homography: ill-conditioned map")

    mapped = cv2.perspectiveTransform(source_array.reshape(1, 4, 2), homography).reshape(4, 2)
    if not np.isfinite(mapped).all() or float(np.max(np.abs(mapped - destination_array))) > 1.0:
        raise ChartGeometryError("unreliable_homography: fiducials do not map reliably")
    destination_area = _polygon_area(destination)
    if destination_area < 16.0:
        raise ChartGeometryError("unreliable_homography: projected fiducials are too small")
    source_px_per_output_px = _source_resolution_lower_bound(np, homography, destination)
    if source_px_per_output_px is None:
        raise ChartGeometryError("unreliable_homography: inverse map resolution is not finite")
    source_px_per_mm_lower_bound = source_px_per_output_px * min(scale_x, scale_y)
    source_px_per_line = manifest["line_width_mm"] * source_px_per_mm_lower_bound

    rectified = cv2.warpPerspective(
        image,
        homography,
        (rectified_width, rectified_height),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0),
    )
    valid_region = np.zeros((rectified_height, rectified_width), dtype=np.uint8)
    destination_polygon = np.rint(destination).astype(np.int32)
    cv2.fillConvexPoly(valid_region, destination_polygon, 255)
    if int(np.count_nonzero(valid_region)) < 16:
        raise ChartGeometryError("unreliable_homography: valid chart region is too small")
    return (
        rectified,
        valid_region,
        scale_x,
        scale_y,
        source_px_per_line,
        raster_px_per_line,
        source_px_per_mm_lower_bound,
        (rectified_width, rectified_height),
    )


def _expected_masks(cv2, np, manifest, scale_x, scale_y, size, thickness):
    rectified_width, rectified_height = size
    expected = np.zeros((rectified_height, rectified_width), dtype=np.uint8)
    role_masks: dict[str, Any] = {}
    bounds = manifest["bounds_mm"]
    for path in manifest["paths"]:
        coordinates = [
            _world_to_rectified(point, bounds, scale_x, scale_y) for point in path["points_mm"]
        ]
        points = np.rint(np.asarray(coordinates, dtype=np.float32)).astype(np.int32)
        role = path["role"]
        role_mask = role_masks.setdefault(
            role, np.zeros((rectified_height, rectified_width), dtype=np.uint8)
        )
        role_name = role.casefold()
        is_perimeter = role_name in {"perimeter", "border", "outline"}
        cv2.polylines(
            expected,
            [points],
            isClosed=is_perimeter,
            color=255,
            thickness=thickness,
            lineType=cv2.LINE_8,
        )
        cv2.polylines(
            role_mask,
            [points],
            isClosed=is_perimeter,
            color=255,
            thickness=thickness,
            lineType=cv2.LINE_8,
        )
    if int(np.count_nonzero(expected)) == 0:
        raise ChartGeometryError("invalid_geometry: expected path mask is empty")
    return expected, role_masks


def _compute_metrics(cv2, np, rectified, valid_region, expected, polarity):
    gray = cv2.cvtColor(rectified, cv2.COLOR_BGR2GRAY)
    valid = valid_region > 0
    samples = gray[valid]
    if samples.size < 16:
        raise ChartGeometryError("unreliable_homography: too few chart pixels")

    contrast_score = float(np.std(samples) / 255.0)
    laplacian = cv2.Laplacian(gray, cv2.CV_64F)
    laplacian_variance = float(np.var(laplacian[valid]))
    threshold_input = samples.reshape(-1, 1)
    otsu_threshold, _ = cv2.threshold(threshold_input, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if polarity == "light":
        observed = gray > otsu_threshold
    else:
        observed = gray <= otsu_threshold
    observed &= valid

    expected_bool = (expected > 0) & valid
    expected_count = int(np.count_nonzero(expected_bool))
    observed_count = int(np.count_nonzero(observed))
    intersection_count = int(np.count_nonzero(expected_bool & observed))
    union_count = int(np.count_nonzero(expected_bool | observed))
    evaluated_count = int(np.count_nonzero(valid))
    if expected_count == 0:
        raise ChartGeometryError("invalid_geometry: expected path mask is empty")

    coverage = intersection_count / expected_count
    precision = intersection_count / observed_count if observed_count else 0.0
    iou = intersection_count / union_count if union_count else 0.0
    missing_fraction = 1.0 - coverage
    excess_fraction = (
        (observed_count - intersection_count) / observed_count if observed_count else 0.0
    )
    loss = min(1.0, max(0.0, 1.0 - iou))
    return {
        "coverage": float(min(1.0, max(0.0, coverage))),
        "precision": float(min(1.0, max(0.0, precision))),
        "iou": float(min(1.0, max(0.0, iou))),
        "missing_fraction": float(min(1.0, max(0.0, missing_fraction))),
        "excess_fraction": float(min(1.0, max(0.0, excess_fraction))),
        "loss": float(loss),
        "contrast_score": contrast_score,
        "contrast": contrast_score,
        "focus_score": laplacian_variance,
        "focus": laplacian_variance,
        "laplacian_variance": laplacian_variance,
        "otsu_threshold": float(otsu_threshold),
        "expected_pixels": expected_count,
        "observed_pixels": observed_count,
        "evaluated_pixels": evaluated_count,
    }


def _role_metrics(np, observed, valid_region, role_masks):
    result: dict[str, dict[str, float]] = {}
    for role, role_mask in role_masks.items():
        expected = (role_mask > 0) & (valid_region > 0)
        expected_count = int(np.count_nonzero(expected))
        intersection = int(np.count_nonzero(expected & observed))
        result[role] = {
            "coverage": float(intersection / expected_count) if expected_count else 0.0,
            "expected_pixels": expected_count,
        }
    return result


def analyze_chart(
    image_path: str | Path,
    manifest: Mapping[str, Any],
    corners_px: Sequence[Sequence[float]],
    polarity: str,
) -> dict[str, Any]:
    """Analyze one locally stored chart image against a schema-v1 manifest."""
    if not isinstance(polarity, str) or polarity not in {"light", "dark"}:
        raise ValueError("polarity must be 'light' or 'dark'")
    image_hash = sha256_file(image_path)
    synthetic = bool(manifest.get("synthetic", False)) if isinstance(manifest, Mapping) else False
    try:
        normalized_manifest = validate_manifest(manifest)
    except ChartGeometryError as exc:
        return _invalid_result(image_hash, [f"invalid_geometry: {exc}"], synthetic=synthetic)

    try:
        normalized_corners = validate_corners(corners_px)
    except ChartGeometryError as exc:
        return _invalid_result(
            image_hash,
            [f"invalid_geometry: {exc}"],
            synthetic=normalized_manifest["synthetic"],
        )

    cv2, np, image_class = _load_vision_dependencies()
    try:
        with image_class.open(image_path) as image_header:
            header_width, header_height = image_header.size
    except Exception as exc:
        raise ValueError(f"Could not read chart image header: {exc}") from exc
    if header_width <= 0 or header_height <= 0:
        return _invalid_result(
            image_hash,
            ["invalid_image_dimensions"],
            synthetic=normalized_manifest["synthetic"],
        )
    if header_width * header_height > MAX_INPUT_PIXELS:
        return _invalid_result(
            image_hash,
            ["image_too_large"],
            synthetic=normalized_manifest["synthetic"],
        )
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Could not read chart image: {image_path}")

    try:
        (
            rectified,
            valid_region,
            scale_x,
            scale_y,
            source_px_per_line,
            raster_px_per_line,
            source_px_per_mm_lower_bound,
            rectified_size,
        ) = _rectify_image(cv2, np, image, normalized_corners, normalized_manifest)
        thickness = max(1, int(round(raster_px_per_line)))
        expected, role_masks = _expected_masks(
            cv2,
            np,
            normalized_manifest,
            scale_x,
            scale_y,
            rectified_size,
            thickness,
        )
        metrics = _compute_metrics(cv2, np, rectified, valid_region, expected, polarity)
        metrics["projected_px_per_line"] = float(source_px_per_line)
        metrics["source_px_per_line"] = float(source_px_per_line)
        metrics["raster_px_per_line"] = float(raster_px_per_line)
        metrics["source_px_per_mm_lower_bound"] = float(source_px_per_mm_lower_bound)
        gray = cv2.cvtColor(rectified, cv2.COLOR_BGR2GRAY)
        valid = valid_region > 0
        threshold = metrics["otsu_threshold"]
        observed = (gray > threshold) if polarity == "light" else (gray <= threshold)
        observed &= valid
        metrics["roles"] = _role_metrics(np, observed, valid_region, role_masks)
    except ChartGeometryError as exc:
        return _invalid_result(
            image_hash,
            [str(exc)],
            synthetic=normalized_manifest["synthetic"],
            metrics={
                "projected_px_per_line": None,
                "source_px_per_line": None,
                "raster_px_per_line": None,
                "source_px_per_mm_lower_bound": None,
            },
        )

    reasons: list[str] = []
    if metrics["projected_px_per_line"] < MIN_PROJECTED_PIXELS_PER_LINE:
        reasons.append("low_projected_px_per_line")
    if metrics["contrast_score"] < MIN_CONTRAST_SCORE:
        reasons.append("low_contrast")
    if metrics["focus_score"] < MIN_FOCUS_SCORE:
        reasons.append("blurry")
    if not all(
        isinstance(metrics[key], (int, float)) and math.isfinite(float(metrics[key]))
        for key in (
            "coverage",
            "precision",
            "iou",
            "missing_fraction",
            "excess_fraction",
            "loss",
            "contrast_score",
            "focus_score",
            "projected_px_per_line",
            "source_px_per_line",
            "raster_px_per_line",
            "source_px_per_mm_lower_bound",
        )
    ):
        reasons.append("unreliable_metrics")

    result = {
        "schema_version": SCHEMA_VERSION,
        "kind": ANALYSIS_KIND,
        "analysis": "chart_vision",
        "synthetic": normalized_manifest["synthetic"],
        "metrics": metrics,
        "usable_for_review": not reasons,
        "reasons": reasons,
        "image_sha256": image_hash,
        "rectified_size_px": [rectified_size[0], rectified_size[1]],
        "polarity": polarity,
        "requires_human_review": True,
        "adjustment_allowed": False,
        "validated_on_printer": False,
        "automatic_control": False,
        "evidence_scope": "first_layer_geometry_only",
        "limitations": [
            "Geometrical IoU is not proof of pressure advance or input-shaper performance."
        ],
    }
    for metric_name in (
        "coverage",
        "precision",
        "iou",
        "missing_fraction",
        "excess_fraction",
        "loss",
        "focus_score",
        "contrast_score",
        "projected_px_per_line",
        "source_px_per_line",
        "raster_px_per_line",
        "source_px_per_mm_lower_bound",
    ):
        result[metric_name] = metrics[metric_name]
    return result


def _load_json_argument(value: str) -> Any:
    candidate = Path(value)
    if candidate.is_file():
        return json.loads(candidate.read_text(encoding="utf-8"))
    return json.loads(value)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze a local first-layer geometry chart")
    parser.add_argument("--image", required=True)
    parser.add_argument("--manifest", required=True, help="Path to the manifest JSON")
    parser.add_argument(
        "--corners",
        required=True,
        help="Four ordered image corners as JSON, or a path to JSON containing them",
    )
    parser.add_argument("--polarity", choices=("light", "dark"), required=True)
    arguments = parser.parse_args(argv)
    try:
        manifest = json.loads(Path(arguments.manifest).read_text(encoding="utf-8"))
        corners = _load_json_argument(arguments.corners)
        result = analyze_chart(arguments.image, manifest, corners, arguments.polarity)
    except (OSError, json.JSONDecodeError, TypeError, ValueError, RuntimeError) as exc:
        print(
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "kind": ANALYSIS_KIND,
                    "usable_for_review": False,
                    "reasons": [str(exc)],
                    "requires_human_review": True,
                    "adjustment_allowed": False,
                },
                ensure_ascii=False,
            )
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
