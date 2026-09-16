"""Refresh the portable helper/coupon copies without altering printer data."""

from pathlib import Path
import shutil


def build(root: Path) -> None:
    """Copy only the published helper, coupon and license into the skills package."""
    plugin = root / "plugins/printer-optimizer"
    skill = plugin / "skills/printer-optimizer"
    for source, target in (
        (root / "src/klipperlearn/slicer_optimizer.py", skill / "scripts/optimizer.py"),
        (
            root / "src/klipperlearn/mobile_app/adjustment-card.stl",
            skill / "assets/adjustment-card.stl",
        ),
        (root / "COPYING", plugin / "COPYING"),
        (root / "docs/BENCHMARK_PROVENANCE.md", skill / "references/benchmark-provenance.md"),
        (root / "docs/PLUGIN_PRIVACY.md", plugin / "PRIVACY.md"),
        (root / "docs/PLUGIN_TERMS.md", plugin / "TERMS.md"),
        (root / "docs/SLICER_OPTIMIZER.md", skill / "references/workflow.md"),
        (
            root / "examples/synthetic-slicer-session.json",
            skill / "references/synthetic-session.json",
        ),
    ):
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


if __name__ == "__main__":
    build(Path(__file__).resolve().parents[1])
