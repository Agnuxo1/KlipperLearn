# Model and estimator card

## What ships

The application includes a local engineered-feature ridge estimator and optional
MobileNetV3-small training/inference code. It includes **no pretrained defect
checkpoint** and no representative, publicly redistributable labelled dataset.
The separate reference reviewer uses deterministic comparison rules, not a CNN.

## Intended use

Support reviewed, comparable calibration trials and identify candidates for further
measurement. Features describe images and available sensor signals; human scores
are labels, not instrumented dimensional measurements. A successful model fit or
held-out-session gate is not certification for a new printer, material or mounting.

## Validation and abstention

`multimodal_learning.py` separates sessions during evaluation, requires sufficient
evidence, and abstains on out-of-distribution or malformed inputs. Prediction also
checks model version, feature order, array shapes, finite values, positive scales
and model digest. A digest identifies integrity, not authorship or accuracy.

The MobileNet loader requires a stable PyTorch version >= 2.10.0, bounded local
checkpoint size, `weights_only=True`, expected metadata and state-dictionary shape.
It never falls back to unrestricted loading and never downloads weights during
inference. **Only use checkpoints from trusted sources.** Version and metadata
checks do not make malicious files safe. See the upstream advisory:
https://github.com/pytorch/pytorch/security/advisories/GHSA-63cw-57p8-fm3p

Inference reports `validated_on_printer: false` and `automatic_control: false`.
Synthetic checkpoint tests verify software paths only. Probabilities must be finite
and within [0, 1]; invalid outputs fail rather than producing a quality score.

## Unestablished claims

No universal defect accuracy, measured lost-step detector, exact position recovery,
phone-browser CNN performance, unattended safety guarantee or global printer optimum
is established by this release. Evaluate held-out printers, materials and sessions,
report false positives/negatives, and keep human intervention available.
