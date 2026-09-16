"""Create explicit candidate OrcaSlicer profile artifacts.

The builder is pure: it copies caller-owned profile dictionaries, changes only
the requested setting and profile identity, and never talks to OrcaSlicer or a
printer.  The command-line entry point only reads the two input JSON files and
writes candidates to a new, explicitly empty output directory.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import re
import unicodedata
from collections.abc import Sequence
from pathlib import Path
from typing import Any


PARAMETER_BOUNDS = {
    "pressure_advance": (0.0, 0.2),
    "extrusion_factor": (0.8, 1.2),
    "accel_mm_s2": (100.0, 10_000.0),
}

_KNOWN_ACCELERATION_KEYS = frozenset(
    {
        "default_acceleration",
        "initial_layer_acceleration",
        "outer_wall_acceleration",
        "inner_wall_acceleration",
        "travel_acceleration",
        "top_surface_acceleration",
        "sparse_infill_acceleration",
        "internal_solid_infill_acceleration",
        "bridge_acceleration",
        "initial_layer_travel_acceleration",
    }
)
_FLOW_WARNING = "Manually reset M221 to 100 before using this profile to avoid double scaling; this exporter never executes that command."
_ACCELERATION_WARNING = "Only acceleration overrides present in this JSON were limited; unresolved inherited settings may remain higher. Review and slice the profile before using it."


class OrcaExportError(ValueError):
    """The requested candidate cannot be produced under the safety checks."""


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise OrcaExportError(f"{field} must be a finite number")
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise OrcaExportError(f"{field} must be a finite number") from exc
    if not math.isfinite(number):
        raise OrcaExportError(f"{field} must be a finite number")
    return number


def _label(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OrcaExportError(f"{field} must be non-empty text")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise OrcaExportError(f"{field} contiene caracteres de control")
    return value


def _assert_json_safe(value: Any, field: str = "profile") -> None:
    if value is None or isinstance(value, (bool, str)):
        return
    if isinstance(value, (int, float)):
        _finite_number(value, field)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _assert_json_safe(item, f"{field}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise OrcaExportError(f"{field} contains a non-string key")
            _assert_json_safe(item, f"{field}.{key}")
        return
    raise OrcaExportError(f"{field} contiene un valor no JSON")


def _require_profile_dict(profile: Any, kind: str, printer_name: str) -> dict[str, Any]:
    if not isinstance(profile, dict):
        raise OrcaExportError(f"The profile {kind} must be a JSON object")
    _assert_json_safe(profile, kind)

    for key in ("inherits", "name", "version"):
        _label(profile.get(key), f"{kind}.{key}")

    compatible = profile.get("compatible_printers")
    if (
        not isinstance(compatible, list)
        or not compatible
        or any(not isinstance(item, str) or not item for item in compatible)
    ):
        raise OrcaExportError(f"{kind}.compatible_printers must be an explicit list of names")
    if printer_name not in compatible:
        raise OrcaExportError(
            f"{kind}.compatible_printers no demuestra compatibilidad con printer_name"
        )
    return copy.deepcopy(profile)


def _validate_metadata(
    filament: dict[str, Any],
    process: dict[str, Any],
    profile_name: str,
) -> None:
    filament_ids = filament.get("filament_settings_id")
    if (
        not isinstance(filament_ids, list)
        or not filament_ids
        or any(not isinstance(item, str) or not item for item in filament_ids)
    ):
        raise OrcaExportError("filament_settings_id must be a non-empty list of strings")
    print_id = process.get("print_settings_id")
    if not isinstance(print_id, str) or not print_id:
        raise OrcaExportError("print_settings_id must be non-empty text")

        # The inherited base is deliberately preserved.  Never substitute a
        # caller-controlled name into inherits, because that could redirect Orca's
        # profile chain to an unrelated or newly-created profile.
    _label(filament["inherits"], "filament.inherits")
    _label(process["inherits"], "process.inherits")
    _label(profile_name, "profile_name")

    collisions = {
        filament["name"],
        process["name"],
        filament["inherits"],
        process["inherits"],
        *filament_ids,
        print_id,
    }
    for profile in (filament, process):
        setting_id = profile.get("setting_id")
        if isinstance(setting_id, str) and setting_id:
            collisions.add(setting_id)
        elif isinstance(setting_id, list):
            collisions.update(item for item in setting_id if isinstance(item, str))
    if profile_name in collisions:
        raise OrcaExportError(
            "profile_name must differ from the base profile names, identifiers and inherits values"
        )


def _number_text(value: float) -> str:
    return format(value, ".12g")


def _validate_parameter(parameter: Any, value: Any) -> tuple[str, float]:
    if not isinstance(parameter, str) or parameter not in PARAMETER_BOUNDS:
        raise OrcaExportError("Unsupported Orca parameter")
    number = _finite_number(value, "value")
    lo, hi = PARAMETER_BOUNDS[parameter]
    if not lo <= number <= hi:
        raise OrcaExportError(f"value is outside the limits for {parameter}")
    return parameter, number


def _process_acceleration_number(raw: Any, field: str) -> float:
    if isinstance(raw, bool):
        raise OrcaExportError(f"{field} is not a numeric acceleration")
    if isinstance(raw, str):
        if not raw.strip():
            raise OrcaExportError(f"{field} is not a numeric acceleration")
        try:
            value = float(raw)
        except ValueError as exc:
            raise OrcaExportError(f"{field} is not a numeric acceleration") from exc
        if not math.isfinite(value):
            raise OrcaExportError(f"{field} is not a numeric acceleration")
        return value
    return _finite_number(raw, field)


def _is_acceleration_key(key: Any) -> bool:
    return isinstance(key, str) and (
        key in _KNOWN_ACCELERATION_KEYS or key.endswith("_acceleration")
    )


def _cap_acceleration_overrides(process: dict[str, Any], value: float) -> None:
    for key in list(process):
        if not _is_acceleration_key(key):
            continue
        if key == "default_acceleration":
            continue
        current = _process_acceleration_number(process[key], f"process.{key}")
        if current < 0.0:
            raise OrcaExportError(f"process.{key} must not be negative")
        if current == 0.0:
            # Zero has Orca's documented inherited meaning.  Keep its exact
            # string so inheritance remains visible in the exported profile.
            if not isinstance(process[key], str):
                process[key] = "0"
            continue
        process[key] = _number_text(min(current, value))

    process["default_acceleration"] = _number_text(value)


def _safe_slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^A-Za-z0-9]+", "-", ascii_value).strip("-").lower()
    return slug or "orca-profile"


def build_orca_overrides(
    base_filament: dict,
    base_process: dict,
    parameter,
    value,
    profile_name,
    printer_name,
    base_flow_ratio=None,
) -> dict[str, Any]:
    """Return explicit Orca profile copies for one requested parameter.

    No value is inferred from a missing printer compatibility list or an
    inherited profile.  The caller must provide the resolved base flow ratio
    before requesting an extrusion-factor artifact.
    """
    printer_name = _label(printer_name, "printer_name")
    profile_name = _label(profile_name, "profile_name")
    parameter, number = _validate_parameter(parameter, value)

    filament = _require_profile_dict(base_filament, "filament", printer_name)
    process = _require_profile_dict(base_process, "process", printer_name)
    _validate_metadata(filament, process, profile_name)

    # User profiles get a new identity, but keep both the base inheritance and
    # every unrelated setting from the supplied dictionaries.
    filament["from"] = "User"
    filament["name"] = profile_name
    filament["filament_settings_id"] = [profile_name]
    process["from"] = "User"
    process["name"] = profile_name
    process["print_settings_id"] = profile_name

    warnings: list[str] = []
    if parameter == "pressure_advance":
        filament["enable_pressure_advance"] = ["1"]
        filament["pressure_advance"] = [_number_text(number)]
    elif parameter == "extrusion_factor":
        flow_ratio = _finite_number(base_flow_ratio, "base_flow_ratio")
        if not 0.5 <= flow_ratio <= 1.5:
            raise OrcaExportError("base_flow_ratio must be between 0.5 and 1.5")
        filament["filament_flow_ratio"] = [_number_text(flow_ratio * number)]
        warnings.append(_FLOW_WARNING)
    else:
        _cap_acceleration_overrides(process, number)
        warnings.append(_ACCELERATION_WARNING)

    return {
        "filament": filament,
        "process": process,
        "warnings": warnings,
        "automatic_install": False,
        "validated_on_printer": False,
    }


def _read_json_object(path: str | Path, field: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OrcaExportError(f"Could not read {field}") from exc
    if not isinstance(value, dict):
        raise OrcaExportError(f"{field} must contain a JSON object")
    return value


def _prepare_empty_output(path: Path) -> None:
    if path.exists():
        if not path.is_dir():
            raise OrcaExportError("output must be a new or empty directory")
        try:
            next(path.iterdir())
        except StopIteration:
            return
        except OSError as exc:
            raise OrcaExportError("The output could not be inspected") from exc
        raise OrcaExportError("output must be a new or empty directory")
    try:
        path.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        raise OrcaExportError("The output could not be created") from exc


def _write_json(path: Path, value: dict[str, Any]) -> None:
    try:
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    except (OSError, TypeError, ValueError) as exc:
        raise OrcaExportError("An Orca artifact could not be written") from exc


def _write_artifacts(
    result: dict[str, Any],
    output: str | Path,
    profile_name: str,
    parameter: str,
    value: float,
    printer_name: str,
) -> dict[str, str]:
    output_path = Path(output)
    _prepare_empty_output(output_path)
    slug = _safe_slug(profile_name)
    filament_name = f"{slug}_filament.json"
    process_name = f"{slug}_process.json"
    report_name = "report.json"
    _write_json(output_path / filament_name, result["filament"])
    _write_json(output_path / process_name, result["process"])
    _write_json(
        output_path / report_name,
        {
            "kind": "orca_profile_override_candidates",
            "profile_name": profile_name,
            "printer_name": printer_name,
            "parameter": parameter,
            "value": value,
            "warnings": result["warnings"],
            "automatic_install": False,
            "validated_on_printer": False,
            "filament_file": filament_name,
            "process_file": process_name,
        },
    )
    return {
        "filament": filament_name,
        "process": process_name,
        "report": report_name,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """CLI for explicit local candidate export; it never installs a profile."""
    parser = argparse.ArgumentParser(description="Export candidate OrcaSlicer overrides")
    parser.add_argument("--filament", required=True, help="JSON de filamento base")
    parser.add_argument("--process", required=True, help="JSON de proceso base")
    parser.add_argument("--parameter", required=True)
    parser.add_argument("--value", required=True, type=float)
    parser.add_argument("--name", required=True, dest="profile_name")
    parser.add_argument("--printer", required=True, dest="printer_name")
    parser.add_argument("--base-flow-ratio", type=float, default=None)
    parser.add_argument("--output", required=True, help="New or empty directory")
    arguments = parser.parse_args(argv)

    try:
        result = build_orca_overrides(
            _read_json_object(arguments.filament, "filament"),
            _read_json_object(arguments.process, "process"),
            arguments.parameter,
            arguments.value,
            arguments.profile_name,
            arguments.printer_name,
            arguments.base_flow_ratio,
        )
        files = _write_artifacts(
            result,
            arguments.output,
            arguments.profile_name,
            arguments.parameter,
            arguments.value,
            arguments.printer_name,
        )
    except OrcaExportError as exc:
        print(json.dumps({"status": "invalid", "error": str(exc)}, ensure_ascii=False))
        return 2

    print(json.dumps({"status": "ok", "files": files}, ensure_ascii=False))
    return 0


__all__ = ["OrcaExportError", "build_orca_overrides", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
