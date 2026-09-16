"""Bounded one-variable experiments and self-contained G-code variants.

Variants never change temperature, homing, paths, Z hopping or filament geometry.
The source remains untouched. An experimental candidate is not an adopted gain.
"""

from __future__ import annotations

import math
import re
import statistics

PARAMETERS = ("flow_multiplier", "pressure_advance", "accel_mm_s2")
NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)"


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except (ValueError, OverflowError):
        return False


def source_profile(gcode, live):
    pa = []
    accelerations = []
    for line in gcode.splitlines():
        command = line.split(";", 1)[0].strip().upper()
        if command.startswith("SET_PRESSURE_ADVANCE "):
            match = re.search(r"\bADVANCE=(" + NUMBER + r")\b", command)
            if match:
                pa.append(float(match[1]))
        if command.startswith("SET_VELOCITY_LIMIT "):
            match = re.search(r"\bACCEL=(" + NUMBER + r")\b", command)
            if match:
                accelerations.append(float(match[1]))
        if command.startswith("M204 "):
            accelerations.extend(
                float(value) for value in re.findall(r"\b[SPT](" + NUMBER + r")\b", command)
            )
    return {
        "flow_multiplier": 1.0,
        "pressure_advance": pa[0]
        if len(set(pa)) == 1
        else (None if pa else live["pressure_advance"]),
        "accel_mm_s2": max(accelerations) if accelerations else live["accel_mm_s2"],
    }


def bounds_and_step(parameter, baseline, machine_max_accel):
    if parameter == "flow_multiplier":
        return (0.95, 1.05, 0.005)
    if parameter == "pressure_advance":
        return (max(0, baseline - 0.01), min(0.2, baseline + 0.01), 0.001)
    if parameter == "accel_mm_s2":
        return (
            max(100, baseline * 0.85),
            min(machine_max_accel, baseline * 1.15),
            min(50, baseline * 0.02),
        )
    raise ValueError("Unsupported automatic parameter")


def next_experiment(baseline, observations, machine_max_accel, enabled=True):
    """Explore a small bracket, with repeated controls; adopt only replicated gains.

    Observations are completed independent jobs of the exact source G-code,
    material and nozzle. A missing rating or measurement is not a zero score.
    """
    base = dict(baseline)
    result = {
        "profile": base,
        "parameter": None,
        "kind": "baseline",
        "adopted": False,
        "reason": "Initial baseline: file parameters are unchanged.",
    }
    if not enabled:
        return {**result, "reason": "Learning without physical adjustments."}
        # A retry/import of a record is not another independent physical test.
    unique = {}
    for row in observations:
        identity = row.get("session_id") or row.get("trial_id")
        if identity and row.get("completed") is True:
            unique[identity] = row
    completed = list(unique.values())
    if not completed:
        return result
    last = completed[-1]
    if last.get("human_score") is None:
        return {**result, "reason": "The last print has not been rated; the baseline is preserved."}
    if not last.get("usable_images"):
        return {
            **result,
            "reason": "No usable result photographs are available; the baseline is preserved.",
        }

        # Candidate adoption needs repetitions, a measured combined score and no
        # quality regression in the human surface/geometry assessments.
    groups = {}
    for row in completed:
        profile = row.get("profile")
        if not isinstance(profile, dict) or not number(row.get("combined_score")):
            continue
        if not row.get("model_validated") or not row.get("usable_images"):
            continue
        groups.setdefault(tuple(profile.get(key) for key in PARAMETERS), []).append(row)
    control_key = tuple(base.get(key) for key in PARAMETERS)
    control = groups.get(control_key, [])
    if len(control) >= 2:
        control_score = statistics.mean(row["combined_score"] for row in control)
        for key, group in groups.items():
            if key == control_key or len(group) < 2:
                continue
            candidate = dict(zip(PARAMETERS, key))
            changed = [
                parameter
                for parameter in PARAMETERS
                if candidate.get(parameter) != base.get(parameter)
            ]
            if len(changed) != 1:
                continue
            parameter = changed[0]
            if not number(candidate[parameter]) or not number(base[parameter]):
                continue
            low, high, step = bounds_and_step(parameter, base[parameter], machine_max_accel)
            if (
                not low <= candidate[parameter] <= high
                or abs(candidate[parameter] - base[parameter]) > step + 1e-8
            ):
                continue
            error = max(float(row.get("prediction_error", 100)) for row in group + control)
            margin = max(2.0, error / math.sqrt(min(len(group), len(control))))
            score = statistics.mean(row["combined_score"] for row in group)
            quality = lambda rows: statistics.mean(row.get("human_quality", 0) for row in rows)
            if score > control_score + margin and quality(group) >= quality(control):
                return {
                    "profile": candidate,
                    "parameter": parameter,
                    "kind": "replicated_candidate",
                    "adopted": True,
                    "reason": "Repeated improvement over the baseline using 40% evidence and 60% human ratings.",
                    "source_trial_ids": [row["trial_id"] for row in group + control],
                }
                # Four-print blocks: control / +small step / -small step / repeated control.
                # Then move to the next eligible variable, never accumulate unproven changes.
    index = len(completed) % 12
    parameter = PARAMETERS[index // 4]
    position = index % 4
    if position in (0, 3):
        return {
            **result,
            "reason": "Repeated control to distinguish a repeatable result from random variation.",
        }
    if not number(base.get(parameter)):
        return {
            **result,
            "reason": "This parameter cannot be isolated in the file; the baseline is preserved.",
        }
    low, high, step = bounds_and_step(parameter, base[parameter], machine_max_accel)
    if not low <= base[parameter] <= high or step <= 0:
        return {
            **result,
            "reason": "No verified adjustment margin remains within the machine limits.",
        }
    value = min(high, max(low, base[parameter] + (step if position == 1 else -step)))
    if math.isclose(value, base[parameter], abs_tol=1e-10):
        return result
    candidate = {**base, parameter: value}
    return {
        "profile": candidate,
        "parameter": parameter,
        "kind": "bounded_exploration",
        "adopted": False,
        "reason": "One-variable trial with a small step; not yet established as an improvement.",
    }


def compile_variant(source, baseline, decision, restore, machine_max_accel):
    """Change numeric settings only. Preserve every movement and thermal command."""
    profile = decision["profile"]
    changed = [key for key in PARAMETERS if profile.get(key) != baseline.get(key)]
    if len(changed) > 1:
        raise ValueError("Only one variable may change")
    if not changed:
        return source, {"changed": False, "motion_unchanged": True}
    parameter = changed[0]
    current, target = baseline[parameter], profile[parameter]
    if not number(current) or not number(target):
        raise ValueError("Invalid candidate")
    low, high, step = bounds_and_step(parameter, current, machine_max_accel)
    if not low <= target <= high or abs(target - current) > step + 1e-8:
        raise ValueError("Candidate exceeds its bounds or step")
    if any(
        line.split(";", 1)[0]
        .strip()
        .upper()
        .startswith(("TUNING_TOWER", "SAVE_CONFIG", "SET_GCODE_VARIABLE"))
        for line in source.splitlines()
    ):
        raise ValueError("Do not stack automatic tuning on another tuning workflow")
    fmt = lambda value: format(value, ".8g")
    prefix, suffix, output, replacements = [], [], [], 0
    if parameter == "flow_multiplier":
        if not 0.8 <= restore["extrusion_factor"] <= 1.2:
            raise ValueError("Unverified original flow")
        prefix = ["M221 S" + fmt(target * 100)]
        suffix = ["M221 S" + fmt(restore["extrusion_factor"] * 100)]
    elif parameter == "pressure_advance":
        if not 0 <= restore["pressure_advance"] <= 0.2:
            raise ValueError("Unverified original PA")
        prefix = ["SET_PRESSURE_ADVANCE ADVANCE=" + fmt(target)]
        suffix = ["SET_PRESSURE_ADVANCE ADVANCE=" + fmt(restore["pressure_advance"])]
    else:
        if current <= 0 or not 100 <= restore["accel_mm_s2"] <= machine_max_accel:
            raise ValueError("Unverified original acceleration")
        prefix = ["SET_VELOCITY_LIMIT ACCEL=" + fmt(target)]
        suffix = ["SET_VELOCITY_LIMIT ACCEL=" + fmt(restore["accel_mm_s2"])]
    for line in source.splitlines():
        code, separator, comment = line.partition(";")
        upper = code.strip().upper()
        if parameter == "flow_multiplier" and re.match(r"^M221\b", upper):

            def flow(match):
                original = float(match[1])
                value = original * target
                if not 80 <= value <= 120:
                    raise ValueError("Source flow exceeds the automatic envelope")
                return "S" + fmt(value)

            code, count = re.subn(r"\bS(" + NUMBER + r")\b", flow, code, flags=re.I)
            if count != 1:
                raise ValueError("Unsupported flow command")
            replacements += count
        elif parameter == "pressure_advance" and upper.startswith("SET_PRESSURE_ADVANCE "):
            if "EXTRUDER=" in upper:
                raise ValueError("Multi-extruder PA needs a dedicated calibration")
            code, count = re.subn(
                r"\bADVANCE=" + NUMBER + r"\b", "ADVANCE=" + fmt(target), code, flags=re.I
            )
            if count != 1:
                raise ValueError("Unsupported PA command")
            replacements += count
        elif parameter == "accel_mm_s2":

            def acceleration(match):
                value = float(match[2]) * target / current
                if not 0 < value <= machine_max_accel:
                    raise ValueError("Acceleration exceeds machine limit")
                return match[1] + fmt(value)

            if upper.startswith("SET_VELOCITY_LIMIT "):
                code, count = re.subn(
                    r"\b(ACCEL=)(" + NUMBER + r")\b", acceleration, code, flags=re.I
                )
                replacements += count
            elif re.match(r"^M204\b", upper):
                code, count = re.subn(
                    r"\b([SPT])(" + NUMBER + r")\b", acceleration, code, flags=re.I
                )
                if not count:
                    raise ValueError("Unsupported acceleration command")
                replacements += count
        output.append(code + (separator + comment if separator else ""))
    variant = "\n".join(
        [
            "; KlipperLearn bounded experiment",
            *prefix,
            *output,
            "M400",
            *suffix,
            "; KlipperLearn original settings restored",
            "",
        ]
    )
    return variant, {
        "changed": True,
        "parameter": parameter,
        "value": target,
        "replacements": replacements,
        "motion_unchanged": True,
        "restore_commands": suffix,
    }
