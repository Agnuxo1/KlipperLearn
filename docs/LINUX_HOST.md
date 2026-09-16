# Run KlipperLearn without a desktop PC

The browser interface, Python backend and private evidence store are separate
components. Installing Klipper/Moonraker on Linux does not automatically move a
KlipperLearn server that was started on a Windows workstation.

## Required deployment

Phone browser -> HTTPS KlipperLearn on Linux -> Moonraker -> Klipper -> printer MCU.
The desktop PC is used for development only. This deployment does not claim that
Klipper itself is running natively on Android.

Use Python 3.11 or later, an isolated virtual environment and a trusted HTTPS
certificate matching the address opened on the phone. An older host with an
unsupported Python version requires a separate migration plan; do not upgrade or
reflash a working printer host as an incidental installation step.

The sample service is in `integrations/linux/klipperlearn.service.example`.
Its address is an example, not a universal configuration. Configure the listener,
Moonraker URL, exact HTTPS origin and trusted LAN subnet for the actual host.
Use `--instance-name` to identify the printer visibly and in authenticated status.

Install the application with its `learning` extra in the service environment.
Create a fresh token locally using `klipperlearn lan-token --output` and protect
the containing directory. A service should read a token file; never embed an
actual token in a public unit file, command pasted into an issue, or a repository.
TLS private keys remain on the server. Trust a verified public CA certificate on
the phone rather than disabling certificate checks or bypassing browser warnings.

## Preserve the existing evidence

Stop only the old KlipperLearn backend, after checking that no print or unresolved
control operation is in progress. Do not stop Klipper or Moonraker. Make SQLite
online backups and transfer the associated immutable assets over an authenticated
encrypted connection. Do not copy live WAL files as a database backup, follow
symlinks, publish private evidence, or merge unrelated printer stores blindly.

Use explicit paths for `--session-root`, `--mobile-inbox` and
`--experiments-root`; a changed working directory must not silently create an
empty history. Keep the printer's existing identity stable when migrating data.
Use a dedicated service account, private file permissions, bounded CPU threads,
restart-on-failure and startup ordering after network availability.

Observation-only `--learning` must not replay a persisted restoration operation.
Version 0.5.2 requires explicit `--automatic-print` server enablement before that
controller is called. Enabling a server flag is not approval to start a print.

## Remove hidden desktop dependencies

Replace old phone bookmarks and installed-web-app URLs with the Linux address.
Grant camera, motion and microphone permissions for the new HTTPS origin.
Inspect webcam proxies too: a Linux `/samsung/` route may still forward images to
a workstation. Update that upstream and its view-only credential locally.
Re-test HTTPS, authentication, camera freshness and UI error messages.

A `200` HTML response from `/health` is not evidence of a KlipperLearn backend:
Mainsail's single-page application may return its own index for unknown routes.
Check JSON content, the `version`, and the configured instance name.

## Verification without moving the printer

With the old desktop backend stopped, verify JSON health and authenticated GET
status from the Linux service. Check that it is enabled at boot, its state files
are local and Klipper/Moonraker process identities have not changed. A physical
PC power-off and phone-permission check remains a separate operator acceptance test.

A reachable server is not the same as a ready printer. The console now exposes
an MCU connection failure separately and allows access to the dashboard while
keeping motion, heating and printing controls disabled until Klipper is ready.

For real benchmark reviews keep job identifiers, exact layer settings and both
`print_duration` and `total_duration`. Exclude cancelled and partial trials from
full-model speed comparisons. A completed job does not establish print quality.
