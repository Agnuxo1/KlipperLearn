import unittest

from klipperlearn.atlas import build_atlas_plan
from klipperlearn.config import Settings


class AtlasPlanTests(unittest.TestCase):
    def test_cells_stay_inside_the_usable_bed(self):
        settings = Settings("http://example", None, "observe", 5, False, 220, 140, 12, 45, 45)
        plan = build_atlas_plan(settings)
        self.assertEqual(len(plan["cells"]), 8)
        for cell in plan["cells"]:
            self.assertGreaterEqual(cell["x_mm"], 12)
            self.assertGreaterEqual(cell["y_mm"], 12)
            self.assertLessEqual(cell["x_mm"] + cell["width_mm"], 208)
            self.assertLessEqual(cell["y_mm"] + cell["depth_mm"], 128)


if __name__ == "__main__":
    unittest.main()
