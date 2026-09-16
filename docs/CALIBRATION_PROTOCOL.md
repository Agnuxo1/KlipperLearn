# 3D calibration chart protocol

The "3D calibration chart" is the project's repeatable physical test artifact,
not necessarily a 3DBenchy model. The repository does not redistribute third-party
STL files or provide universal, ready-to-print G-code.

## Controlled comparison

Record the exact model license and geometry hash, nozzle, layer height, line width,
material/batch, moisture treatment, plate, room conditions, slicer/version/profile,
firmware/configuration and phone/camera mount. Record both requested and observed
settings. Fix everything except the selected variable. A changed model, infill or
extrusion geometry must start a different comparison, not count as a speed win.

The new slice-manifest tool fingerprints exact bytes. It does not prove that two
different G-code files have equivalent geometry, extrusion or machine effects.
The existing prototype's geometry-preservation checks must be recovered and tested.

Collect a repeated baseline. Define a quality floor and a bounded search interval
from hardware/material limits and measured stability, not an LLM's confidence.
Use repeat trials, a stopping budget and an unchanged reference. Where conditions
drift, interleave reference runs. Two repeats are only a minimum software gate,
not evidence of statistical significance or generalization.

## Evidence and scoring

Capture synchronized telemetry during each zone/trial and registered photographs
afterwards. Record resolution, lighting, camera pose, blur and occlusion. Flash and
non-flash views should remain separate. Reject stale images or insufficient detail.
Missing data remain missing, never synthetic measurements silently used as real ones.

Quality needs observable dimensions: dimensional error, visible layer shift,
ringing, stringing, bridging and extrusion consistency, each with a declared rubric.
Time, material use and failures are separate outcomes. A finished job can have
poor quality. A safety failure remains valuable negative evidence, but must not
be relabeled as a successful quality sample.

## Bounded loop

1. Verify a clear build area, approved limits and sufficient supplies.
2. Execute only a separately authorized, validated trial.
3. Capture evidence, review quality and record failures without erasing history.
4. Compare repeated observations and propose at most one bounded adjustment.
5. Require the execution gate and operator decision before the next physical trial.
6. Stop on faults, missing evidence, exhausted budget or the approved boundary.

Success means a measured trade-off improvement within tested conditions, not an
assurance that a global maximum has been found. Avoid automatic retries after
layer shifts, collisions, detachments or thermal faults.

A completed object does not leave the build plate automatically. Sequential trials
need confirmed removal or a validated non-overlapping batch plan, toolhead clearance
and remaining-space checks. No unattended bed-clearing capability is claimed.
