import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from klipperlearn.domain import DEFECT_KEYS
from klipperlearn.inference import (
    ARCHITECTURE,
    CheckpointValidationError,
    MAX_INPUT_PIXELS,
    _preprocess_image,
    infer_image,
    sha256_file,
    validate_checkpoint_metadata,
)


def checkpoint_metadata(**overrides):
    metadata = {
        "architecture": ARCHITECTURE,
        "labels": list(DEFECT_KEYS),
        "state_dict": {"synthetic": object()},
        "epochs": 2,
        "training_rows": 3,
        "validation_rows": 2,
        "validation_sessions": 1,
        "manifest_sha256": "a" * 64,
    }
    metadata.update(overrides)
    return metadata


class InferenceMetadataTests(unittest.TestCase):
    def test_valid_metadata_preserves_exact_domain_label_order(self) -> None:
        trusted = validate_checkpoint_metadata(checkpoint_metadata())

        self.assertEqual(trusted["architecture"], ARCHITECTURE)
        self.assertEqual(trusted["labels"], list(DEFECT_KEYS))
        self.assertEqual(trusted["validation_sessions"], 1)
        self.assertFalse(trusted["synthetic"])

    def test_metadata_rejects_wrong_architecture_labels_and_no_validation_session(self) -> None:
        for overrides in (
            {"architecture": "torchvision.mobilenet_v3_large"},
            {"labels": list(reversed(DEFECT_KEYS))},
            {"validation_sessions": 0},
            {"manifest_sha256": "not-a-sha256"},
        ):
            with self.subTest(overrides=overrides):
                with self.assertRaises(CheckpointValidationError):
                    validate_checkpoint_metadata(checkpoint_metadata(**overrides))

    def test_sha256_helper_is_local_and_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint.pt"
            path.write_bytes(b"synthetic checkpoint bytes")

            expected = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(sha256_file(path), expected)
            self.assertEqual(sha256_file(path), sha256_file(path))


def _real_torch_stack_available() -> bool:
    try:
        import torch  # noqa: F401
        from PIL import Image  # noqa: F401
        from torchvision import models  # noqa: F401
    except Exception:
        return False
    return True


@unittest.skipUnless(
    _real_torch_stack_available(),
    "optional torch/torchvision/Pillow stack is not installed",
)
class RealInferenceSmokeTests(unittest.TestCase):
    def test_weights_none_checkpoint_loads_and_returns_probabilities(self) -> None:
        import torch
        from PIL import Image
        from torchvision import models

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = models.mobilenet_v3_small(weights=None)
            model.classifier[3] = torch.nn.Linear(model.classifier[3].in_features, len(DEFECT_KEYS))
            checkpoint_path = root / "synthetic.pt"
            torch.save(
                checkpoint_metadata(state_dict=model.state_dict(), synthetic=True),
                checkpoint_path,
            )
            expected_model_sha256 = hashlib.sha256(checkpoint_path.read_bytes()).hexdigest()
            image_path = root / "image.png"
            Image.new("RGB", (48, 32), (128, 128, 128)).save(image_path)

            result = infer_image(image_path, checkpoint_path)

        self.assertEqual(list(result["probabilities"]), list(DEFECT_KEYS))
        self.assertEqual(len(result["probabilities"]), len(DEFECT_KEYS))
        self.assertTrue(all(0.0 <= value <= 1.0 for value in result["probabilities"].values()))
        self.assertEqual(result["model_sha256"], expected_model_sha256)
        self.assertFalse(result["validated_on_printer"])
        self.assertFalse(result["automatic_control"])
        self.assertTrue(result["requires_human_review"])
        self.assertTrue(result["synthetic"])

    def test_nonfinite_model_output_is_rejected_before_probabilities(self) -> None:
        import torch
        from PIL import Image

        class NonFiniteModel:
            def __call__(self, _batch):
                return torch.full((1, len(DEFECT_KEYS)), float("nan"))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkpoint_path = root / "synthetic-nan-output.pt"
            torch.save(
                checkpoint_metadata(state_dict={"synthetic": torch.tensor(0.0)}, synthetic=True),
                checkpoint_path,
            )
            image_path = root / "image.png"
            Image.new("RGB", (24, 24), (128, 128, 128)).save(image_path)

            with patch("klipperlearn.inference.build_model", return_value=NonFiniteModel()):
                with self.assertRaisesRegex(CheckpointValidationError, "non-finite"):
                    infer_image(image_path, checkpoint_path)

    def test_oversized_image_is_rejected_before_convert_without_large_allocation(self) -> None:
        import torch
        from torchvision import transforms

        class HeaderOnlyImage:
            size = (MAX_INPUT_PIXELS + 1, 1)
            convert_called = False

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def convert(self, _mode):
                type(self).convert_called = True
                raise AssertionError("convert must not run for an oversized image")

        class HeaderOnlyImageClass:
            header = HeaderOnlyImage()

            @classmethod
            def open(cls, _path):
                cls.header.convert_called = False
                return cls.header

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "oversized-header-only.img"
            path.write_bytes(b"synthetic header; no large raster allocated")
            with self.assertRaisesRegex(ValueError, "20 MP"):
                _preprocess_image(path, transforms, HeaderOnlyImageClass, torch)

        self.assertFalse(HeaderOnlyImageClass.header.convert_called)


if __name__ == "__main__":
    unittest.main()
