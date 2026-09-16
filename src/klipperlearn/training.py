"""Optional local PyTorch training for multilabel FDM-defect assessment.

This module is intentionally imported only by the training command. The V88 does
not need PyTorch and should not be used for model training.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .dataset import load_training_rows
from .domain import DEFECT_KEYS


def _load_dependencies():
    try:
        import torch
        from PIL import Image
        from torch import nn
        from torch.utils.data import DataLoader, Dataset
        from torchvision import models, transforms
    except ImportError as exc:
        raise RuntimeError(
            "Training requires optional dependencies. Install with: pip install -e '.[training]'"
        ) from exc
    return torch, Image, nn, DataLoader, Dataset, models, transforms


def train_multilabel(
    manifest_path: str | Path,
    output_path: str | Path,
    epochs: int = 5,
    pretrained: bool = False,
) -> dict[str, Any]:
    """Train a compact multilabel CNN locally and save a transparent checkpoint.

    `pretrained=True` may download torchvision weights the first time. The caller
    explicitly opts into it; KlipperLearn never downloads models automatically.
    """
    if not pretrained:
        raise ValueError(
            "KlipperLearn requires transfer learning for this small local dataset. "
            "Pass --pretrained to consent to using or fetching the base weights."
        )
    torch, image_class, nn, data_loader_class, dataset_class, models, transforms = (
        _load_dependencies()
    )
    if epochs < 1:
        raise ValueError("epochs must be at least 1")
    rows = load_training_rows(manifest_path)
    training_rows = [row for row in rows if row["split"] == "train"]
    validation_rows = [row for row in rows if row["split"] == "validation"]
    transform = transforms.Compose(
        [
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
        ]
    )

    class PrintDataset(dataset_class):
        def __init__(self, selected_rows):
            self.rows = selected_rows

        def __len__(self):
            return len(self.rows)

        def __getitem__(self, index):
            row = self.rows[index]
            image = image_class.open(row["frame"]).convert("RGB")
            return (
                transform(image),
                torch.tensor(row["labels"], dtype=torch.float32),
                torch.tensor(row["label_mask"], dtype=torch.float32),
            )

    weights = models.MobileNet_V3_Small_Weights.DEFAULT if pretrained else None
    model = models.mobilenet_v3_small(weights=weights)
    model.classifier[3] = nn.Linear(model.classifier[3].in_features, len(DEFECT_KEYS))
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device)
    training_loader = data_loader_class(
        PrintDataset(training_rows), batch_size=min(16, len(training_rows)), shuffle=True
    )
    validation_loader = data_loader_class(
        PrintDataset(validation_rows), batch_size=min(16, len(validation_rows)), shuffle=False
    )
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
    loss_function = nn.BCEWithLogitsLoss(reduction="none")
    training_losses: list[float] = []
    validation_losses: list[float] = []
    for _ in range(epochs):
        model.train()
        epoch_loss = 0.0
        count = 0
        for inputs, labels, label_mask in training_loader:
            optimizer.zero_grad()
            output = model(inputs.to(device))
            mask = label_mask.to(device)
            raw_loss = loss_function(output, labels.to(device))
            loss = (raw_loss * mask).sum() / mask.sum().clamp_min(1.0)
            loss.backward()
            optimizer.step()
            epoch_loss += float(loss.item())
            count += 1
        training_losses.append(epoch_loss / max(1, count))

        model.eval()
        validation_loss = 0.0
        validation_count = 0
        with torch.no_grad():
            for inputs, labels, label_mask in validation_loader:
                output = model(inputs.to(device))
                mask = label_mask.to(device)
                raw_loss = loss_function(output, labels.to(device))
                loss = (raw_loss * mask).sum() / mask.sum().clamp_min(1.0)
                validation_loss += float(loss.item())
                validation_count += 1
        validation_losses.append(validation_loss / max(1, validation_count))

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    manifest_bytes = Path(manifest_path).read_bytes()
    torch.save(
        {
            "architecture": "torchvision.mobilenet_v3_small",
            "labels": list(DEFECT_KEYS),
            "epochs": epochs,
            "pretrained": pretrained,
            "training_rows": len(training_rows),
            "validation_rows": len(validation_rows),
            "training_sessions": len({row["session"] for row in training_rows}),
            "validation_sessions": len({row["session"] for row in validation_rows}),
            "training_losses": training_losses,
            "validation_losses": validation_losses,
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "state_dict": model.cpu().state_dict(),
        },
        destination,
    )
    return {
        "checkpoint": str(destination),
        "training_rows": len(training_rows),
        "validation_rows": len(validation_rows),
        "training_losses": training_losses,
        "validation_losses": validation_losses,
        "device": device,
    }
