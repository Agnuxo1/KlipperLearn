# Safety boundaries

This software is experimental printer software, not a certified safety system.
A 3D printer contains hot surfaces and moving components. Software review does not
establish the condition of a particular machine or justify unattended operation.

## Preserve independent protection

Do not disable thermal runaway checks, alter stepper current or raise firmware
limits merely to improve a benchmark. Configured limits are upper constraints,
not evidence that a worn machine, hotend, belt or filament can safely reach them.
Do not use a phone's frame-mounted accelerometer as an exact carriage encoder.

## Control requires explicit intent

The default server does not install printer control. The companion, learning and
bounded automatic trial preparation are explicit options. Manual proposals require
preview and separate confirmation. Uncertain starts/restorations are not blindly
retried. Check the actual machine and its current state before any physical action.

A new print requires a clear bed and explicit operator intent. No robotic bed
clearing, independently validated vision watchdog or unattended recursive tuner is
provided. Phone sleep, Wi-Fi loss, cloud limits or a model failure must not become
the printer's primary protection mechanism.

## Evidence quality

A completed job does not establish a good part. Stale frames return unavailable,
not a misleading current image. Missing sensors, insufficient image resolution,
non-finite numbers and unvalidated models must remain explicit. Synthetic tests
and AI-retouched illustrations are not measured hardware evidence.

## Deployment and update discipline

Keep Moonraker and the companion off the public Internet, use trusted HTTPS and
private credentials, and leave the original working installation intact while
validating a new source release. Install it only after idle-state and recovery
checks on the actual setup. No movement, heating, printing, firmware update or
service restart was performed as part of this source-publication review.
