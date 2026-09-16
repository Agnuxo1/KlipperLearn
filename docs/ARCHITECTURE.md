# Architecture

## Runtime boundaries

The phone browser supplies the touch UI, camera, motion/orientation readings,
aggregated acoustic features, and a persistent upload outbox. It connects over
trusted HTTPS to the Python companion. The companion communicates with Moonraker;
Klipper's host and MCU remain responsible for motion scheduling and firmware
protections. The phone is not automatically a Klipper host merely because its
browser can control the console.

## Source map

| Area | Main modules |
| --- | --- |
| Application and authenticated API | `webapp.py`, `companion.py`, `request_safety.py`, `__main__.py` |
| Read-only observations | `observer.py`, `moonraker.py`, `http_readonly.py`, `storage.py` |
| Durable trials and reviewed evidence | `experiment_store.py`, `experiment_api.py`, `trial_telemetry.py`, `photo_pair.py` |
| Geometry and camera evidence | `calibration_chart.py`, `chart_vision.py`, `registered_vision.py`, `printer_cameras.py` |
| Bounded adjustment proposals | `calibration_loop.py`, `calibration_control.py`, `experiment_learning.py`, `adaptive_policy.py` |
| Optional controlled trial workflow | `automatic_print.py`, `learning_service.py`, `six_zone_service.py`, `six_zone_batch.py` |
| Local model experiments | `multimodal_learning.py`, `dataset.py`, `training.py`, `inference.py` |
| Slicer and archive interoperability | `orca_export.py`, `gcode.py`, `evidence_backup.py`, `integrations/` |
| Browser implementation | `src/klipperlearn/mobile_app/` |
| Separate advisory-only reviewer | `reference/` |

## Data and control

Status queries are not print commands. Explicit authenticated actions are checked
against printer state and configured limits. Proposals are previewed before use;
physical application and restoration need confirmation or a previously enabled,
bounded trial workflow. An uncertain operation is not retried blindly. Independent
firmware protections must remain active even when the browser disconnects.

Evidence routes enforce bounded inputs and reject malformed/ambiguous JSON.
Private API responses are non-cacheable. Camera snapshots expire after five
seconds, and a stopped/cached camera cannot impersonate a current observation.
No raw audio or private runtime evidence is shipped in the source repository.

## Packaging

The Python host and phone assets form the GPL-3.0-or-later application. The earlier
MIT offline reviewer is a separately scoped tool. Optional vision/training
libraries are installed only through their package extras. No native Android
USB bridge, universal printer profile or trained checkpoint is silently bundled.
See [Android requirements](ANDROID_HOST.md), [installation](INSTALLATION.md),
[local learning](LOCAL_LEARNING.md), and [status](STATUS.md).
