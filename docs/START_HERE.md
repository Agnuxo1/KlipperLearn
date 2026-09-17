# Start here: choose a small, reversible setup

KlipperLearn is free, open-source experimental software. This guide separates
what to download from what still requires native-application or physical testing.
Do not replace a working printer installation just to try an evidence tool.

## I want Quality, Standard and Speed presets

Download the Printer Optimizer package from the
[community preview](https://github.com/Agnuxo1/KlipperLearn/releases/tag/community-preview-20260917).
It contains a portable skill, a standard-library Python helper and an original
calibration STL. It is not already published in the ChatGPT plugin directory.
An assistant must already support file reading and code execution to use the helper.

Provide sanitized copies of your existing Orca process and filament presets,
printer/nozzle/material identity and comparable, reviewed test records. Keep your
original files. The helper requires an accepted unchanged baseline and independent
repetitions; it will not invent measurements or an optimization when data are absent.

For a demonstration only, extract the package and run in that directory:

```sh
python -I skills/printer-optimizer/scripts/optimizer.py profiles --session skills/printer-optimizer/references/synthetic-session.json --output DEMO-only-profiles.zip
```

The result contains six **DEMO** JSON presets plus an audit. Do not import synthetic
examples as production profiles. Real output also needs native-slicer inspection,
reslicing and supervised validation. See [the full workflow](SLICER_OPTIMIZER.md).

## I use Cura or PrusaSlicer and only want evidence

Use [Cura's independent script](../integrations/cura/README.md) or the
[PrusaSlicer post-processing helper](../integrations/prusaslicer/README.md).
These record hashes without changing the source G-code. Cura's script hashes
its in-memory UTF-8 stream; it cannot certify bytes written later by Cura.
These are not Cura-native or PrusaSlicer-native three-mode preset exporters.

## I use OctoPrint

The [independent evidence plugin](../integrations/octoprint/README.md) records
selected local file and print events. Install its specific standalone archive,
not the entire KlipperLearn repository as an OctoPrint plugin. It does not send
printer commands, upload evidence, or modify system services. Start with a
disposable test instance and keep your existing OctoPrint backup.

Official Plugin Repository registration is a separate review and maintenance
commitment. A downloadable archive does not mean the plugin is officially listed.

## I already use Klipper with Mainsail or Fluidd

Start with the standalone [ecosystem toolkit](../integrations/ecosystem/TOOLKIT.md)
for local-file diagnostics and history review. A toolkit check does not change
your machine, scan your LAN or make a printer ready.

The [host installation](INSTALLATION.md) is a separate optional path for the
phone console, webcam and sensors. Run it on a supported Linux printer host to
avoid a hidden desktop-PC dependency; see [Linux-host setup](LINUX_HOST.md).
HTTPS trust, device permissions and explicitly configured private storage matter.
Do not disable TLS verification, expose Moonraker publicly or share private tokens.

## What should I verify before accepting a mode?

Use the same physical printer, material, nozzle, model, layer height and layer
count. A completed job is not proof of good quality. Review original photographs,
record failures and distinguish print time from total job time. Keep separate
printers and calibration methods in separate evidence cohorts.

Compare effective slicer settings, not just the preset name. Preserve thermal
protection and machine limits. A proposed single-variable trial is labelled
UNVALIDATED TRIAL until it has repeatable reviewed evidence. It must not be
silently treated as the accepted Quality, Standard or Speed profile.

## Help improve compatibility

Use the repository's [compatibility report](https://github.com/Agnuxo1/KlipperLearn/issues/new?template=compatibility.yml)
with exact software versions, a minimal non-sensitive reproduction, observed
results and the tests you actually performed. A static-format check, an actual
application import and a physical print are different evidence levels.

The [integration ledger](../integrations/ecosystem/status.json) records remaining
gates. No approval from the ten upstream projects or OpenAI is implied.
