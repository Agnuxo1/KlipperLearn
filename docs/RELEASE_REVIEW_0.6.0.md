# Release review: Printer Optimizer 0.6.0

## What this release implements

A file-first, phone-optional workflow for producing Quality, Standard and Speed
slicer modes. The portable plugin contains a skill, a dependency-free Python
helper, a strict session contract, a synthetic example, and an original calibration
card STL. An existing assistant with file/code tools can run the helper without
installing a printer service. The optional MCP adapter exposes the same functions.

The authenticated local application also provides an optimizer page with printer
identity fields, a reviewer label, session review, proposal validation, preset
export and separately authorized LAN API discovery. The reviewer selector does
not call a model API or change the model used by a ChatGPT conversation.

## Selection and export

The selector compares complete, previously tested configurations. It requires an
unchanged, acceptable baseline and at least two independent complete, reviewed
trials per accepted configuration. Geometry, model identity, layer height and layer
count must match. Photos, review flags and historical identities remain supplied
evidence, not proof independently verified by software. No record is fabricated.

Quality ranks appearance/geometry scores; Speed minimizes print time above an
explicit quality floor; Standard uses a documented 65/35 quality/time policy.
This is a transparent selection policy, not a proof of global optimality.
Modes may legitimately select the same configuration. Unsafe, missing or
incomparable evidence results in an explanation rather than invented settings.

Native-format output currently targets OrcaSlicer: three process presets paired
with three filament presets, preserving inheritance and unrelated settings.
Generated files have not been imported into an actual Orca installation during
this review. Other slicers need a reviewed settings report or a future native
adapter; the release does not claim universal preset compatibility.

## Network and physical boundaries

Default MCP tools are read-only and cannot move, heat or start a printer. Optional
discovery is limited to a consented RFC1918 IPv4 subnet, at most /24, inside a
server-defined allowlist. Known Moonraker and OctoPrint GET endpoints are probed;
protected endpoints are not falsely identified as printer models. This is not a
Wi-Fi SSID scanner, USB driver or universal proprietary-printer connector.

Cloud ChatGPT cannot directly discover a private LAN through a file-only skill.
An already authorized local host or authenticated private MCP transport is needed
for that optional path. No public MCP endpoint, tunnel, paid model call or ChatGPT
account registration was provisioned. The portable package is not a public plugin
directory approval and is not claimed to be installed in the user's account.

The original STL is 40 x 30 x 12 mm with 7,756 triangles. Mesh tests establish a
closed, consistently oriented surface, not successful physical printing. The
operator slices it with their verified machine profile and approves the print.
No printer start/upload, firmware edit, live LAN scan or Linux service update was
performed in this release. The existing live 0.5.2 deployment is left unchanged.

## Supervised candidate files

A valid one-variable AI proposal returns two explicitly named UNVALIDATED TRIAL
Orca presets and its configuration identity. The operator reviews, imports and
reslices them before a new supervised trial. They are not silently adopted into
the accepted modes. Baseline values must also resolve numerically and remain
inside every declared machine/material limit.

## Validation completed locally

- 345 Python tests and 185 subtests passed, including an actual official MCP SDK
  stdio handshake, tool discovery, structured responses and profile generation.
- All 11 JavaScript test programs passed, including five real-browser suites with
  simulated services and hardware. The optimizer page was exercised without a
  printer connection, model API invocation or unsolicited LAN request.
- The existing exporter passed 25 tests; the separate reference core passed 47.
- Ruff E9/F and repository link/consistency checks passed.
- The packaged helper ran with Python isolated mode and standard-library imports,
  producing exactly six DEMO presets and an audit from its synthetic example.
- The canonical helper and the bundled helper are checked for byte equality.

Two existing third-party deprecation warnings remain. These are software tests,
not native-slicer import tests, certification of visual scoring or measured speed
gains on hardware. Check the published commit's GitHub Actions result separately
for remote CI. The package preserves GPL-3.0-or-later and the repository's existing
separately scoped MIT material. Private printer stores and credentials are excluded.
