"""Locate printed zone markers in either camera; abstain on missing geometry."""

from pathlib import Path
import hashlib

from .chart_vision import analyze_chart


def refine_fiducials(gray, zone, homography, polarity):
    """Use the four isolated printed crosses, not chart lines, for registration.

    A small distant marker alone amplifies subpixel error over the whole coupon.
    Require four unambiguous local crosses; otherwise abstain from scoring.
    """
    import cv2
    import numpy as np

    x, y, w, h = zone["bounds_mm"]
    scale = 8.0
    world_to_crop = np.float64([[scale, 0, -x * scale], [0, scale, -y * scale], [0, 0, 1]])
    image_to_crop = world_to_crop @ np.linalg.inv(homography)
    crop = cv2.warpPerspective(gray, image_to_crop, (round(w * scale), round(h * scale)))
    if polarity == "dark":
        crop = 255 - crop
    found = []
    for px, py in zone["fiducials_mm"]:
        cx, cy = (px - x) * scale, (py - y) * scale
        radius = round(3 * scale)
        left, top = round(cx) - radius, round(cy) - radius
        patch = crop[top : round(cy) + radius + 1, left : round(cx) + radius + 1]
        if (
            patch.shape != (2 * radius + 1, 2 * radius + 1)
            or float(patch.max()) - float(patch.min()) < 24
        ):
            return None
        _, binary = cv2.threshold(patch, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        count, _, stats, centers = cv2.connectedComponentsWithStats(binary)
        candidates = []
        for index in range(1, count):
            bx, by, bw, bh, area = stats[index]
            center = centers[index]
            if (
                1.6 * scale <= bw <= 3.3 * scale
                and 1.6 * scale <= bh <= 3.3 * scale
                and 0.1 <= area / (bw * bh) <= 0.65
                and np.linalg.norm(center - [radius, radius]) <= 1.5 * scale
            ):
                candidates.append([left + center[0], top + center[1]])
        if len(candidates) != 1:
            return None
        found.append(candidates[0])
    return cv2.perspectiveTransform(np.float32([found]), np.linalg.inv(image_to_crop))[0].tolist()


def registered_crop(path, zone, corners_px):
    import cv2
    import numpy as np

    image = cv2.imdecode(np.frombuffer(Path(path).read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR)
    x, y, w, h = zone["bounds_mm"]
    size = 384
    destination = np.float32(
        [[(px - x) / w * size, (y + h - py) / h * size] for px, py in zone["fiducials_mm"]]
    )
    transform = cv2.getPerspectiveTransform(np.float32(corners_px), destination)
    cropped = cv2.warpPerspective(image, transform, (size, size))
    ok, encoded = cv2.imencode(".jpg", cropped, [cv2.IMWRITE_JPEG_QUALITY, 95])
    if not ok:
        raise ValueError("Could not encode registered evidence")
    return bytes(encoded)


def analyze_registered_photo(path, manifest):
    import cv2
    import numpy as np

    raw = Path(path).read_bytes()
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError("Photo exceeds limit")
    image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None or image.shape[0] * image.shape[1] > 20_000_000:
        raise ValueError("Invalid photo dimensions")
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    parameters = cv2.aruco.DetectorParameters()
    parameters.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    parameters.cornerRefinementWinSize = 3
    detector = cv2.aruco.ArucoDetector(dictionary, parameters)
    detections = {}
    for frame, polarity in ((gray, "light"), (255 - gray, "dark")):
        corners, ids, _ = detector.detectMarkers(frame)
        if ids is None:
            continue
        for identifier, quad in zip(ids.flatten(), corners):
            detections.setdefault(int(identifier), []).append((quad.reshape(4, 2), polarity))
    results = []
    for zone in manifest["zones"]:
        matches = detections.get(zone["marker_id"], [])
        result = {
            "zone_id": zone["id"],
            "marker_id": zone["marker_id"],
            "usable": False,
            "reason": "marker_missing_or_ambiguous",
            "image_sha256": hashlib.sha256(raw).hexdigest(),
        }
        if len(matches) == 1:
            quad, polarity = matches[0]
            if min(np.linalg.norm(quad[i] - quad[(i + 1) % 4]) for i in range(4)) < 18:
                result["reason"] = "marker_too_small"
            else:
                homography = cv2.getPerspectiveTransform(
                    np.float32(zone["marker_corners_mm"]), np.float32(quad)
                )
                points = refine_fiducials(gray, zone, homography, polarity)
                if points is None:
                    result["reason"] = "fiducials_missing_or_ambiguous"
                    results.append(result)
                    continue
                geometry = {
                    key: zone[key]
                    for key in (
                        "bounds_mm",
                        "paths",
                        "fiducials_mm",
                        "line_width_mm",
                        "layer_height_mm",
                    )
                }
                geometry.update(schema_version=1, kind="first_layer_geometry")
                analysis = analyze_chart(path, geometry, points, polarity)
                result.update(
                    usable=analysis["usable_for_review"],
                    reason="measured"
                    if analysis["usable_for_review"]
                    else "insufficient_image_quality",
                    corners_px=points,
                    polarity=polarity,
                    analysis=analysis,
                    scope="projected_line_geometry; not height, support strength or input shaping",
                )
        results.append(result)
    return {"schema": "klipperlearn-registered-vision-v1", "zones": results}
