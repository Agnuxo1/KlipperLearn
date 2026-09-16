# Release status and capability matrix

Release: **0.5.1 reviewed source**, September 2026. This imports the workstation
application previously identified as 0.5.0 and preserves the earlier MIT reference
reviewer. Software verification is separate from hardware and statistical validation.

| Capability | Implementation | Validation boundary |
| --- | --- | --- |
| Python package and CLI | Included | Unit tests and package smoke tests; not a native Android installer. |
| HTML/JavaScript touch console | Included, English UI | Browser tests use simulated device permissions and APIs. |
| Motion, orientation and aggregated audio | Collectors and persistent upload queues included | Sensor availability, sample quality and mounting are device-dependent. |
| Camera and paired photographs | Included | A stale snapshot fails closed; physical torch support is not universal. |
| Authenticated printer controls | Included, explicitly enabled | Mocked transport tests; no printer actuation in this review. |
| Charts and bounded proposals | Included | Geometry and numeric tests do not prove a physical result. |
| Local ridge model | Included | Session-split experimental quality estimation, not a general defect detector. |
| Optional MobileNet training/inference | Included | Requires trusted labelled data and patched optional dependencies; no trained weights bundled. |
| External advisor | Manual request export and response validation | No automatic cloud API integration or direct model-to-G-code execution. |
| Phone-only Klipper host over USB | Design target | Not shipped or newly hardware-validated. |
| Unattended recursive optimization | Not claimed | No automatic bed clearing or independent visual safety certification. |
| Upstream acceptance | Not claimed | Interoperability tools live in this repository. |

Historical workshop observations must be labelled as historical and author-reported.
An AI-retouched photograph cannot be used as a quantitative quality measurement.
A completed job, successful upload or passing unit test is not proof of a good print.
