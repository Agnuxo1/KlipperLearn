# Release status and capability matrix

Release: **0.6.0 file-first Printer Optimizer**, September 2026. This imports the workstation
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

## Additive 0.6.0 capabilities

| Capability | Implementation | Boundary |
| --- | --- | --- |
| Portable ChatGPT skill package | Manifest, skill, helper, original STL and examples | Package only; public registration and installation are separate. |
| Optional MCP tools | Five default read-only tools; opt-in discovery tool | Local SDK round-trip tests; no account tunnel or public endpoint provisioned. |
| Three slicer modes | Six native-format Orca JSON artifacts from accepted whole configurations | Import/reslicing and physical validation must be performed on the actual setup. |
| LAN identification | Moonraker/OctoPrint GET-only probes, consent and explicit subnet allowlist | No live scan in development; no claim of universal vendor connectivity. |
| Original calibration card | Included STL and deterministic source generator | Mesh validated; no physical print performed for this release. |
| Local optimizer page | Brand/model context, session review, proposal validation and export | Requires the configured KlipperLearn backend; it is not an offline LAN scanner. |

The file-first skill does not require a phone or Klipper. The host assistant must
provide file/code tools for verified artifact generation. Other slicers receive
a reviewed settings report until a native-format adapter is implemented.
