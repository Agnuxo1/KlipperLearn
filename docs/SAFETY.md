# Safety case and control boundary

This publication is advisory-only. There is no hardware controller to enable.
The reference UI cannot print, home, heat, cool, pause, cancel, reset or flash a
printer. Its accepted proposal means only that the declared data passed software
checks. It does not establish that the physical setting is safe.

Future actuation must enforce an independently reviewed allowlist, live-state
checks, per-device/material limits, fresh evidence, exclusive job ownership,
explicit consent and auditable rollback. Never allow text from a model to become
G-code, a shell command, a configuration rewrite or a firmware change.

Firmware heater protection must remain enabled. Do not increase thermal-check
tolerances, motor current, acceleration ceilings, travel limits or temperature
limits to conceal a fault. Do not disable filament or endstop sensors to finish a
benchmark. Use proven shutdown/cancel paths and preserve cooling where required.

Keep motion-control work independent of the browser, heavy inference and external
services. Loss of quota or a chat session must not remove safety supervision.
A local watchdog may be part of the future design, but is not implemented here and
must not replace firmware safeguards or responsible physical supervision.

Record failures as failures. A phone camera or microphone may miss a defect, and
an accelerometer mounted on the frame cannot prove absolute nozzle position.
A no-error firmware log does not prove that no steps were lost.

Operator control remains essential for bed clearance, nozzle condition, battery
health, cabling and physical inspection. Reject unsafe or unsupported hardware
combinations rather than presenting them as universal compatibility.
