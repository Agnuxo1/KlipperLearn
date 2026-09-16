from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import product
from .config import Settings


@dataclass(frozen=True)
class AtlasCell:
    id: str
    row: int
    column: int
    x_mm: float
    y_mm: float
    width_mm: float
    depth_mm: float
    status: str = "free"


def build_atlas_plan(settings: Settings) -> dict:
    usable_width = settings.bed_width_mm - 2 * settings.margin_mm
    usable_depth = settings.bed_depth_mm - 2 * settings.margin_mm
    columns = int(usable_width // settings.cell_width_mm)
    rows = int(usable_depth // settings.cell_depth_mm)
    cells = []
    for row, column in product(range(rows), range(columns)):
        cells.append(
            AtlasCell(
                id=f"R{row + 1}C{column + 1}",
                row=row + 1,
                column=column + 1,
                x_mm=settings.margin_mm + column * settings.cell_width_mm,
                y_mm=settings.margin_mm + row * settings.cell_depth_mm,
                width_mm=settings.cell_width_mm,
                depth_mm=settings.cell_depth_mm,
            )
        )
    return {
        "schema_version": 1,
        "purpose": "Planning only. No G-code is generated or executed.",
        "bed": {
            "width_mm": settings.bed_width_mm,
            "depth_mm": settings.bed_depth_mm,
            "margin_mm": settings.margin_mm,
        },
        "cells": [asdict(cell) for cell in cells],
        "recommended_order": [cell.id for cell in cells],
        "safety": {
            "mode": "observe",
            "parameter_changes_only_between_cells": True,
            "occupied_cells_must_not_be_crossed_at_print_height": True,
        },
    }
