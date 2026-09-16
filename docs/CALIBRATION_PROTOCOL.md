# Reproducible calibration protocol

## Define a comparable trial

Record printer identity, nozzle, material, source model and sliced-file hashes,
layer settings, effective temperatures, speed/acceleration, volumetric limits and
pressure/flow settings. Preserve the reference geometry and layer count when
making a speed comparison. A renamed file is not a new independent experiment.

Use the same camera mounting, lighting, framing and measurement procedure. Record
motion/orientation sampling quality, missing intervals and microphone permissions.
Aggregated audio describes a signal; it does not by itself identify a mechanical fault.

## Baseline and one-variable changes

Establish repeated baseline observations. The local proposal engine needs reviewed,
comparable values; a proposed local vertex is an experiment, not a global optimum.
Change one parameter at a time within an explicit maximum step and configured limits.
Keep failures and rejected proposals, and return to the verified baseline when
results deteriorate. Do not raise acceleration after a layer shift without checking
the mechanical cause and the actual machine configuration.

Six-zone charts are useful for screening. All zones share one physical session and
must not be counted as independent validation sessions. Clear the bed before a new
physical print; the application does not remove completed objects.

## End-of-trial evidence

Capture current camera views and supported paired phone photographs. Retain original
images for measurements; generative retouching is for presentation only. Associate
samples with the actual print interval and preserve raw reported job status. Record
human surface/geometry ratings separately from model estimates. Missing evidence
must remain missing rather than receiving an invented favourable score.

Verify heater targets, final position and restoration through the actual machine
state. A completed job or a successful HTTP response is insufficient. If an operation's
outcome is uncertain, inspect the state before retrying or starting another trial.

## Report a result

Publish the reproducible profile, immutable artifacts, actual timing convention,
quality criteria, repeated measurements and failures. Distinguish author-reported
workshop observations from independently reproduced measurements. Do not generalize
a result from one printer/material/mounting to all old printers or Android phones.
