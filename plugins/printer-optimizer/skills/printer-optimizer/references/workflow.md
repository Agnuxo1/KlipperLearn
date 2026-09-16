# Printer Optimizer: file first, phone optional

## The product goal

Use ChatGPT or another selected multimodal assistant to review calibration prints
and propose bounded improvements. Preserve the user's printer firmware and slicer
where possible. The practical output is a **Quality / Standard / Speed** set of
presets, not a continuously connected AI telling the printer how to move.

A legacy printer can participate through its normal SD/USB print workflow and
original photographs. A webcam is convenient for repeatable capture; it must
actually be connected to a host or have a supported network interface. A webcam
alone does not add networking or control capabilities to an old printer.

## Two ways to use it

**File workflow:** use the bundled ChatGPT/Codex skill with your existing assistant.
Give it the actual slicer presets, print logs and original result photographs.
The bundled Python helper uses the standard library only. There is no mandatory
new service, phone, AI API key or printer firmware installation. The assistant
needs a file/code execution capability; without it, use the same reviewed settings
report and import the profiles manually. No plugin can grant itself account access.

**Connected workflow:** the existing KlipperLearn host serves an authenticated
optimizer page at `/mobile/optimizer.html`. An optional MCP server exposes the
same pure operations to an assistant. No optimizer endpoint sends G-code, starts a
print, installs a profile or edits the user's existing presets. Local scanning
is opt-in and uses the already configured trusted LAN networks.

## The user journey

1. Confirm brand, exact model, modifications, firmware, nozzle, filament, slicer
   version and the exact printer preset. A brand label is not a compatibility test.
2. Export the current process and filament presets. Preserve them unchanged.
   Resolve inherited numeric values and exact compatible printer names explicitly.
3. Slice the same full benchmark using those presets. The included original
   40 x 30 x 12 mm coupon has steps, walls, gaps and a bridge; it is not 3DBenchy.
   Original 3DBenchy may instead be obtained from its publisher; it is not bundled.
4. Record each full print's identity, exact configuration hash, model hash, layer
   height/count, printing time, total time, original photograph hashes and reviewed
   surface/geometry scores. Reuse of a physical session/photo does not count as a
   repeat. Hashes identify supplied bytes; they do not authenticate a historical run.
5. Ask the selected AI to inspect the actual images. The request helper exports
   numerical summaries and hashes, **not photographs**. Attach the originals
   separately and do not represent a hash as a visual analysis.
6. Validate the returned one-variable proposal. It must cite usable trial records,
   match the entire session hash, and remain inside operator-confirmed bounds and
   maximum step. Perform a supervised trial through the existing slicer. Approval
   of a JSON proposal is not permission for unattended physical printing.
7. After at least two independent complete reviewed repetitions of each accepted
   configuration and a usable baseline, generate the three modes. Import the
   corresponding **process + filament pair** and reslice each new model.

## Selection, not invented presets

Quality maximizes the mean of each print's weaker surface/geometry score, with
printing time as a tiebreaker. Standard uses a disclosed 65% quality / 35% relative
printing-time utility. Speed minimizes median printing time while **every**
accepted repeat meets the configured quality floor. Timing variability can block
a configuration. Failed trials require investigation rather than being hidden.

These weights are a design choice, not a universal physical law. Selection is
from whole tested configurations. The code does not combine the fastest speed,
best flow and best acceleration from unrelated trials into an untested hybrid.
Two or three modes may legitimately have identical settings. Missing evidence
produces `more_evidence_required`, not arbitrary speed percentages.

The calibration comparison locks the benchmark, layer height/count and base
presets. The exporter does not change infill, supports, temperature, toolpaths or
custom G-code. This deliberately prevents a thick-layer speed trial from being
presented as an equal-resolution improvement. For a different resolution, material,
nozzle or structural objective, begin a separate comparison.

## Slicer support

**OrcaSlicer:** implemented JSON process/filament copies preserve inheritance and
unrelated fields, generate fresh identities, and explicitly bind printer
compatibility. Software tests validate the transformation. Import and re-slicing
must still be checked in the user's installed Orca version; no native Orca plugin
or accepted upstream integration is claimed.

**Cura, PrusaSlicer, FlashPrint and other slicers:** the skill can prepare an
English setting-by-setting report from the user's real exported settings. Do not
rename Orca JSON as a native profile for another slicer. Native adapters for those
formats are not shipped in this revision.

See Orca's export/import workflow:
https://www.orcaslicer.com/wiki/general_settings/import_export

## Model choice

ChatGPT uses the model the user selected in ChatGPT. An app cannot silently
switch that account's model or turn a chat subscription into a third-party API
credential. The web page's reviewer/model menu labels an exported review request;
it does not call an external model. Other assistants can consume the same files
or use MCP. There are no bundled weights or automatic paid inference calls.

## Network discovery

The bridge probes only known Moonraker and OctoPrint read-only HTTP endpoints on
a user-approved RFC1918 IPv4 subnet of /24 or smaller. Concurrency, response bytes
and elapsed time are bounded. The server must independently allow that subnet.
No Wi-Fi password, SSID scanning, host reconfiguration, redirects, arbitrary ports
or printing commands are involved. A protected server is not falsely identified
as a printer. Brand/model are operator-confirmed, and timeouts report partial scans.

Printers connected by Wi-Fi or Ethernet can be discovered from the same reachable
IP network. A cloud chat or ordinary unprivileged HTML page cannot scan a private
home network without a local connection. The file workflow does not need scanning.

## Limits and acceptance

No user-supplied data become independent certification. The protocol cannot prove
that entered scores, identities or hashes describe an actual physical run.
Photograph review does not by itself measure internal strength or dimensional
accuracy without scale, viewpoints and suitable tests. Firmware thermal protection
and motion limits remain active. A profile does not supersede a machine limit.

The source is a working file/MCP integration package, not an already approved
public ChatGPT plugin or a completed universal printer-control product. Nothing in
this revision auto-clears a bed, prints unattended, validates phone-native hosting,
or claims an optimum for every future geometry.

## Propose, test, then adopt

A validated AI proposal returns a process/filament pair explicitly named
UNVALIDATED TRIAL. It represents one bounded change around the chosen anchor,
not an accepted mode. The UI offers the two JSON files and a candidate audit.
Import and inspect them locally only after reviewing the suggestion; slice the
unchanged calibration card, supervise the print, and record new original evidence.
The final three modes are generated separately from acceptable repeated trials.
