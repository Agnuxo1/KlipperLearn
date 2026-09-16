"""Safe, local inference for the optional defect classifier.

Only load checkpoints obtained from trusted sources. Patched runtime and bounded
file checks reduce risk but do not make arbitrary model files trustworthy. This
module never downloads weights, enables unsafe fallback loading or sends printer
commands. Metadata validation does not establish model accuracy.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from .domain import DEFECT_KEYS


ARCHITECTURE = "torchvision.mobilenet_v3_small"
IMAGE_SIZE = (224, 224)
NORMALIZE_MEAN = (0.485, 0.456, 0.406)
NORMALIZE_STD = (0.229, 0.224, 0.225)
MAX_INPUT_PIXELS = 20_000_000
MAX_CHECKPOINT_BYTES = 128 * 1024 * 1024
MINIMUM_TORCH_VERSION = (2, 10, 0)
_SHA256_PATTERN = re.compile(r"\A[0-9a-fA-F]{64}\Z")
_REQUIRED_METADATA = (
    "architecture",
    "labels",
    "state_dict",
    "epochs",
    "training_rows",
    "validation_rows",
    "validation_sessions",
    "manifest_sha256",
)


class CheckpointValidationError(ValueError):
    """Raised when a checkpoint cannot be trusted for this model contract."""


class _OversizedImageError(ValueError):
    """Internal marker used to keep the image-size rejection message safe."""


def _positive_integer(value: Any, field: str, *, allow_zero: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CheckpointValidationError(f"Checkpoint field '{field}' must be an integer.")
    minimum = 0 if allow_zero else 1
    if value < minimum:
        comparator = "non-negative" if allow_zero else "positive"
        raise CheckpointValidationError(
            f"Checkpoint field '{field}' must be {comparator}; got {value}."
        )
    return value


def validate_checkpoint_metadata(checkpoint: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and return the trusted metadata subset without importing torch.

    The validation split is dataset validation evidence only.  It is intentionally
    not interpreted as validation on a printer.
    """
    if not isinstance(checkpoint, Mapping):
        raise CheckpointValidationError("Checkpoint must be a mapping.")

    missing = [field for field in _REQUIRED_METADATA if field not in checkpoint]
    if missing:
        raise CheckpointValidationError(
            "Checkpoint is missing required metadata: " + ", ".join(missing)
        )

    if checkpoint["architecture"] != ARCHITECTURE:
        raise CheckpointValidationError(
            f"Unsupported checkpoint architecture: {checkpoint['architecture']!r}."
        )

    labels = checkpoint["labels"]
    if isinstance(labels, (str, bytes)) or not isinstance(labels, Sequence):
        raise CheckpointValidationError("Checkpoint labels must be an ordered sequence.")
    if list(labels) != list(DEFECT_KEYS):
        raise CheckpointValidationError(
            "Checkpoint label order does not match klipperlearn.domain.DEFECT_KEYS."
        )

    state_dict = checkpoint["state_dict"]
    if not isinstance(state_dict, Mapping) or not state_dict:
        raise CheckpointValidationError("Checkpoint state_dict must be a non-empty mapping.")

    epochs = _positive_integer(checkpoint["epochs"], "epochs")
    training_rows = _positive_integer(checkpoint["training_rows"], "training_rows")
    validation_rows = _positive_integer(checkpoint["validation_rows"], "validation_rows")
    validation_sessions = _positive_integer(
        checkpoint["validation_sessions"], "validation_sessions"
    )

    manifest_sha256 = checkpoint["manifest_sha256"]
    if not isinstance(manifest_sha256, str) or not _SHA256_PATTERN.fullmatch(manifest_sha256):
        raise CheckpointValidationError(
            "Checkpoint manifest_sha256 must be a 64-character hexadecimal SHA-256 digest."
        )
    synthetic = checkpoint.get("synthetic", False)
    if type(synthetic) is not bool:
        raise CheckpointValidationError("Checkpoint synthetic must be boolean when present.")

    return {
        "architecture": ARCHITECTURE,
        "labels": list(DEFECT_KEYS),
        "state_dict": state_dict,
        "epochs": epochs,
        "training_rows": training_rows,
        "validation_rows": validation_rows,
        "validation_sessions": validation_sessions,
        "manifest_sha256": manifest_sha256,
        "synthetic": synthetic,
    }


def sha256_file(path: str | Path) -> str:
    """Return the SHA-256 digest of one local file."""
    source = Path(path)
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_supported_torch_version(version: str) -> None:
    """Block known-vulnerable or unidentifiable checkpoint-loading runtimes."""
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:\+[A-Za-z0-9._-]+)?", str(version))
    if match is None or tuple(int(part) for part in match.groups()) < MINIMUM_TORCH_VERSION:
        raise CheckpointValidationError(
            "Checkpoint loading requires a stable PyTorch version >= 2.10.0. "
            "Only load checkpoints from trusted sources."
        )


def _load_torch():
    try:
        import torch
    except ImportError as exc:
        raise RuntimeError(
            "Inference requires optional PyTorch dependencies. "
            "Install them with: pip install -e '.[training]'"
        ) from exc
    require_supported_torch_version(torch.__version__)
    return torch


def _load_model_dependencies():
    torch = _load_torch()
    try:
        from torch import nn
        from torchvision import models, transforms
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(
            "Inference requires optional PyTorch, torchvision, and Pillow dependencies. "
            "Install them with: pip install -e '.[training]'"
        ) from exc
    except Exception as exc:
        # A mismatched torch/torchvision installation commonly raises RuntimeError
        # while importing an operator.  Keep the failure actionable and local.
        raise RuntimeError(
            "Inference could not import the optional PyTorch/torchvision stack. "
            "Install compatible versions with: pip install -e '.[training]'"
        ) from exc
    return torch, nn, models, transforms, Image


def load_checkpoint(checkpoint_path: str | Path) -> tuple[dict[str, Any], str]:
    """Load one local checkpoint with the safe torch deserialisation mode only."""
    path = Path(checkpoint_path)
    if not path.is_file():
        raise FileNotFoundError("Checkpoint file was not found.")
    if path.is_symlink() or path.stat().st_size > MAX_CHECKPOINT_BYTES:
        raise CheckpointValidationError("Checkpoint must be a regular file no larger than 128 MiB.")
    torch = _load_torch()
    try:
        checkpoint = torch.load(path, weights_only=True, map_location="cpu")
    except Exception as exc:
        raise CheckpointValidationError(
            "Could not safely load the local checkpoint with weights_only=True."
        ) from exc
    metadata = validate_checkpoint_metadata(checkpoint)
    return metadata, sha256_file(path)


def build_model(checkpoint: Mapping[str, Any]):
    """Construct the exact architecture with random torchvision weights disabled."""
    metadata = validate_checkpoint_metadata(checkpoint)
    torch, nn, models, _transforms, _image_class = _load_model_dependencies()

    # `weights=None` is intentional: inference never downloads a base model.
    model = models.mobilenet_v3_small(weights=None)
    model.classifier[3] = nn.Linear(model.classifier[3].in_features, len(DEFECT_KEYS))
    try:
        model.load_state_dict(metadata["state_dict"], strict=True)
    except Exception as exc:
        raise CheckpointValidationError(
            "Checkpoint state_dict does not match torchvision.mobilenet_v3_small."
        ) from exc
    model.to("cpu")
    model.eval()
    # Keep torch reachable for callers that use this helper in a controlled test,
    # while the public inference function still owns the no_grad context.
    _ = torch
    return model


def _preprocess_image(image_path: str | Path, transforms, image_class, torch):
    transform = transforms.Compose(
        [
            transforms.Resize(IMAGE_SIZE),
            transforms.ToTensor(),
            transforms.Normalize(NORMALIZE_MEAN, NORMALIZE_STD),
        ]
    )
    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError("Image file was not found.")
    try:
        with image_class.open(path) as image:
            width, height = image.size
            if width <= 0 or height <= 0:
                raise ValueError("Inference image dimensions are invalid.")
            if width * height > MAX_INPUT_PIXELS:
                raise _OversizedImageError("Inference image exceeds the 20 MP safety limit.")
            tensor = transform(image.convert("RGB"))
    except _OversizedImageError as exc:
        raise ValueError(str(exc)) from exc
    except Exception as exc:
        raise ValueError("Could not read the local inference image.") from exc
    return tensor.unsqueeze(0).to("cpu", dtype=torch.float32)


def infer_image(image_path: str | Path, checkpoint_path: str | Path) -> dict[str, Any]:
    """Predict independent defect probabilities for one local image.

    The return value is evidence for review.  It is never a printer-control
    instruction, and `validated_on_printer` is always false.
    """
    metadata, model_sha256 = load_checkpoint(checkpoint_path)
    torch, _nn, _models, transforms, image_class = _load_model_dependencies()
    model = build_model(metadata)
    batch = _preprocess_image(image_path, transforms, image_class, torch)
    with torch.no_grad():
        output = model(batch)
        if not torch.is_tensor(output):
            raise CheckpointValidationError("Model output is not a tensor.")
        if output.ndim != 2 or output.shape[0] != 1 or output.shape[1] != len(DEFECT_KEYS):
            raise CheckpointValidationError(
                "Model output shape does not match the checkpoint label order."
            )
        if not bool(torch.isfinite(output).all().item()):
            raise CheckpointValidationError("Model output contains non-finite values.")
        probabilities_tensor = torch.sigmoid(output)[0].detach().cpu()
    if not bool(torch.isfinite(probabilities_tensor).all().item()):
        raise CheckpointValidationError("Model probabilities contain non-finite values.")
    if not bool(((probabilities_tensor >= 0.0) & (probabilities_tensor <= 1.0)).all().item()):
        raise CheckpointValidationError("Model probabilities are outside the [0, 1] range.")
    try:
        probabilities = probabilities_tensor.tolist()
    except Exception as exc:
        raise RuntimeError("Model output could not be converted to probabilities.") from exc
    if len(probabilities) != len(DEFECT_KEYS):
        raise CheckpointValidationError(
            "Model output size does not match the checkpoint label order."
        )

    per_label = {label: float(probabilities[index]) for index, label in enumerate(DEFECT_KEYS)}
    return {
        "architecture": ARCHITECTURE,
        "probabilities": per_label,
        "model_sha256": model_sha256,
        "validated_on_printer": False,
        "automatic_control": False,
        "requires_human_review": True,
        "synthetic": metadata["synthetic"],
        "validation_sessions": metadata["validation_sessions"],
        "manifest_sha256": metadata["manifest_sha256"],
    }


def predict_image(checkpoint_path: str | Path, image_path: str | Path) -> dict[str, Any]:
    """Compatibility-oriented name with checkpoint-first argument order."""
    return infer_image(image_path=image_path, checkpoint_path=checkpoint_path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run local KlipperLearn image inference")
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--image", required=True)
    arguments = parser.parse_args(argv)
    try:
        result = infer_image(arguments.image, arguments.checkpoint)
    except (OSError, RuntimeError, ValueError) as exc:
        print(json.dumps({"error": str(exc), "automatic_control": False}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
