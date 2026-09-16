import unittest

from klipperlearn.training import train_multilabel


class TrainingTests(unittest.TestCase):
    def test_random_initialization_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            train_multilabel("missing.json", "unused.pt", pretrained=False)


if __name__ == "__main__":
    unittest.main()
