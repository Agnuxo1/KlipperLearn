import hashlib
from pathlib import Path
import tempfile
import unittest


def _vision_available() -> bool:
    try:
        import cv2  # noqa: F401
        import numpy  # noqa: F401
    except Exception:
        return False
    return True


@unittest.skipUnless(_vision_available(), "optional OpenCV/NumPy stack is not installed")
class ChartVisionSyntheticTests(unittest.TestCase):
    @staticmethod
    def _manifest() -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": "first_layer_geometry",
            "bounds_mm": [0.0, 0.0, 20.0, 20.0],
            "line_width_mm": 0.4,
            "layer_height_mm": 0.2,
            "paths": [
                {
                    "id": "perimeter",
                    "role": "perimeter",
                    "points_mm": [[1.0, 1.0], [19.0, 1.0], [19.0, 19.0], [1.0, 19.0]],
                },
                {
                    "id": "crossbar",
                    "role": "interior",
                    "points_mm": [[2.0, 10.0], [18.0, 10.0]],
                },
                {
                    "id": "crossbar-2",
                    "role": "interior",
                    "points_mm": [[2.0, 14.0], [18.0, 14.0]],
                },
            ],
            "fiducials_mm": [[0.0, 0.0], [20.0, 0.0], [20.0, 20.0], [0.0, 20.0]],
            "synthetic": True,
        }

    @staticmethod
    def _draw_image(
        path: Path,
        manifest: dict[str, object],
        *,
        missing: bool = False,
        excess: bool = False,
        lowcontrast: bool = False,
    ) -> None:
        import cv2
        import numpy as np

        image = np.full((300, 300, 3), 255 if not lowcontrast else 128, dtype=np.uint8)
        left, top, right, bottom = 20.0, 20.0, 280.0, 280.0
        line_width = int(round(float(manifest["line_width_mm"]) * (right - left) / 20.0))

        def pixel(point: list[float]) -> list[int]:
            return [
                int(round(left + point[0] / 20.0 * (right - left))),
                int(round(top + point[1] / 20.0 * (bottom - top))),
            ]

        color = (0, 0, 0) if not lowcontrast else (124, 124, 124)
        for index, raw_path in enumerate(manifest["paths"]):
            if missing and index == 1:
                continue
            points = np.asarray([pixel(point) for point in raw_path["points_mm"]], dtype=np.int32)
            cv2.polylines(
                image,
                [points],
                isClosed=raw_path["role"] == "perimeter",
                color=color,
                thickness=line_width,
                lineType=cv2.LINE_8,
            )
        if excess:
            cv2.line(
                image, (45, 245), (255, 55), color=color, thickness=line_width, lineType=cv2.LINE_8
            )
        cv2.imwrite(str(path), image)

    @staticmethod
    def _draw_low_resolution_image(path: Path, manifest: dict[str, object]) -> None:
        import cv2
        import numpy as np

        image = np.full((64, 64, 3), 255, dtype=np.uint8)
        line_width = max(1, int(round(float(manifest["line_width_mm"]) * 63.0 / 20.0)))

        def pixel(point: list[float]) -> list[int]:
            return [int(round(point[0] / 20.0 * 63.0)), int(round(point[1] / 20.0 * 63.0))]

        for raw_path in manifest["paths"]:
            points = np.asarray([pixel(point) for point in raw_path["points_mm"]], dtype=np.int32)
            cv2.polylines(
                image,
                [points],
                isClosed=raw_path["role"] == "perimeter",
                color=(0, 0, 0),
                thickness=line_width,
                lineType=cv2.LINE_8,
            )
        cv2.imwrite(str(path), image)

    def _analyze(self, image_path: Path, *, corners=None) -> dict[str, object]:
        from klipperlearn.chart_vision import analyze_chart

        return analyze_chart(
            image_path,
            self._manifest(),
            corners or [[20.0, 20.0], [280.0, 20.0], [280.0, 280.0], [20.0, 280.0]],
            "dark",
        )

    def test_good_missing_and_excess_charts_are_deterministic_synthetic_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            good_path = root / "good.png"
            missing_path = root / "missing.png"
            excess_path = root / "excess.png"
            self._draw_image(good_path, self._manifest())
            self._draw_image(missing_path, self._manifest(), missing=True)
            self._draw_image(excess_path, self._manifest(), excess=True)

            good = self._analyze(good_path)
            good_repeat = self._analyze(good_path)
            missing = self._analyze(missing_path)
            excess = self._analyze(excess_path)

        self.assertTrue(good["synthetic"])
        self.assertTrue(good["usable_for_review"])
        self.assertEqual(good["metrics"], good_repeat["metrics"])
        self.assertGreater(good["metrics"]["iou"], 0.75)
        self.assertLess(missing["metrics"]["coverage"], good["metrics"]["coverage"])
        self.assertGreater(missing["metrics"]["missing_fraction"], 0.0)
        self.assertGreater(excess["metrics"]["excess_fraction"], good["metrics"]["excess_fraction"])
        for result in (good, missing, excess):
            self.assertGreaterEqual(result["metrics"]["loss"], 0.0)
            self.assertLessEqual(result["metrics"]["loss"], 1.0)
            self.assertTrue(result["requires_human_review"])
            self.assertFalse(result["adjustment_allowed"])
            self.assertIn("IoU", result["limitations"][0])

    def test_low_contrast_is_rejected_but_still_reported_as_synthetic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lowcontrast.png"
            self._draw_image(path, self._manifest(), lowcontrast=True)
            result = self._analyze(path)

        self.assertTrue(result["synthetic"])
        self.assertFalse(result["usable_for_review"])
        self.assertIn("low_contrast", result["reasons"])
        self.assertGreaterEqual(result["metrics"]["loss"], 0.0)
        self.assertLessEqual(result["metrics"]["loss"], 1.0)

    def test_low_resolution_chart_uses_original_pixels_for_line_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "low-resolution.png"
            manifest = self._manifest()
            self._draw_low_resolution_image(path, manifest)
            result = self._analyze(
                path,
                corners=[[0.0, 0.0], [63.0, 0.0], [63.0, 63.0], [0.0, 63.0]],
            )

        self.assertFalse(result["usable_for_review"])
        self.assertIn("low_projected_px_per_line", result["reasons"])
        self.assertGreater(result["metrics"]["raster_px_per_line"], 2.0)
        self.assertLess(result["metrics"]["source_px_per_line"], 2.0)

    def test_overflow_and_non_string_polarity_are_rejected_without_decode(self) -> None:
        from klipperlearn.chart_vision import ChartGeometryError, analyze_chart, validate_manifest

        manifest = self._manifest()
        manifest["bounds_mm"] = [10**10000, 0.0, 20.0, 20.0]
        with self.assertRaises(ChartGeometryError):
            validate_manifest(manifest)
        with self.assertRaises(ValueError):
            analyze_chart("does-not-exist.png", self._manifest(), [], [])

    def test_bad_corners_are_rejected_without_a_geometry_claim(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad-corners.png"
            self._draw_image(path, self._manifest())
            expected_image_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
            result = self._analyze(
                path,
                corners=[[20.0, 20.0], [280.0, 20.0], [280.0, 280.0], [280.0, 280.0]],
            )

        self.assertFalse(result["usable_for_review"])
        self.assertTrue(any("invalid_geometry" in reason for reason in result["reasons"]))
        self.assertEqual(result["image_sha256"], expected_image_sha256)
        self.assertTrue(result["requires_human_review"])
        self.assertNotIn("pressure_advance", result)
        self.assertNotIn("shaper_freq_x", result)


if __name__ == "__main__":
    unittest.main()
