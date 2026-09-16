import pytest
import itertools

from klipperlearn.adaptive_policy import compile_variant, next_experiment, source_profile

BASE = {"flow_multiplier": 1.0, "pressure_advance": 0.02, "accel_mm_s2": 1500.0}
RESTORE = {"extrusion_factor": 1.0, "pressure_advance": 0.02, "accel_mm_s2": 1500.0}
SOURCE = "; sample\nM221 S100\nSET_PRESSURE_ADVANCE ADVANCE=0.02\nM204 S1500\nG28\nG1 X12 Y34 Z0.2 E1 F1200\nM104 S0\nM221 S100\n"


identities = itertools.count()


def observed(profile=None, score=None, quality=4):
    return {
        "trial_id": f"test-{next(identities)}",
        "completed": True,
        "human_score": 80,
        "human_quality": quality,
        "usable_images": True,
        "combined_score": score,
        "profile": profile or BASE,
        "model_validated": score is not None,
        "prediction_error": 2,
    }


def test_bounded_bracket_controls_and_missing_evidence():
    assert next_experiment(BASE, [], 3000)["kind"] == "baseline"
    plus = next_experiment(BASE, [observed()], 3000)
    assert plus["profile"]["flow_multiplier"] == 1.005
    minus = next_experiment(BASE, [observed(), observed()], 3000)
    assert minus["profile"]["flow_multiplier"] == 0.995
    assert next_experiment(BASE, [observed() for _ in range(3)], 3000)["kind"] == "baseline"
    assert not plus["adopted"]
    assert next_experiment(BASE, [{**observed(), "human_score": None}], 3000)["kind"] == "baseline"
    assert (
        next_experiment(BASE, [{**observed(), "usable_images": False}], 3000)["kind"] == "baseline"
    )


def test_adoption_requires_repetitions_score_margin_and_no_surface_regression():
    better = {**BASE, "flow_multiplier": 1.005}
    observations = [observed(score=70) for _ in range(2)] + [observed(better, score=80)]
    assert not next_experiment(BASE, observations, 3000)["adopted"]
    observations.append(observed(better, score=80))
    assert next_experiment(BASE, observations, 3000)["adopted"]
    for item in observations[2:]:
        item["human_quality"] = 3
    assert not next_experiment(BASE, observations, 3000)["adopted"]


def test_duplicate_records_do_not_count_as_independent_trials():
    control = observed(score=70)
    candidate = observed({**BASE, "flow_multiplier": 1.005}, score=80)
    assert not next_experiment(BASE, [control, control, candidate, candidate], 3000)["adopted"]


@pytest.mark.parametrize(
    "parameter,value",
    [("flow_multiplier", 1.005), ("pressure_advance", 0.021), ("accel_mm_s2", 1530.0)],
)
def test_compiler_preserves_all_paths_homing_and_temperatures_and_restores(parameter, value):
    decision = {"profile": {**BASE, parameter: value}}
    variant, audit = compile_variant(SOURCE, BASE, decision, RESTORE, 3000)
    assert audit["changed"]
    for line in SOURCE.splitlines():
        if line.startswith(("G", "M104")):
            assert line in variant.splitlines()
    assert "KlipperLearn original settings restored" in variant
    assert audit["restore_commands"][0] in variant.splitlines()[-3:]
    assert source_profile(SOURCE, RESTORE) == BASE


def test_no_accumulated_changes_no_temperature_change_no_tuning_towers():
    with pytest.raises(ValueError):
        compile_variant(SOURCE, BASE, {"profile": {**BASE, "flow_multiplier": 1.1}}, RESTORE, 3000)
    with pytest.raises(ValueError):
        compile_variant(
            SOURCE,
            BASE,
            {"profile": {**BASE, "flow_multiplier": 1.005, "pressure_advance": 0.021}},
            RESTORE,
            3000,
        )
    with pytest.raises(ValueError):
        compile_variant(
            "TUNING_TOWER COMMAND=M221\n" + SOURCE,
            BASE,
            {"profile": {**BASE, "flow_multiplier": 1.005}},
            RESTORE,
            3000,
        )
