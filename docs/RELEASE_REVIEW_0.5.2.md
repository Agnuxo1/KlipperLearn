# 0.5.2: Linux-host independence

## Reported defect and observed cause

The phone console depended on a Python backend running on the development PC.
A webcam proxy on the Linux printer host also forwarded requests to that PC.
Changing a Moonraker address alone could not remove either dependency.

A separate inspected printer host was reachable through Moonraker but reported
an MCU connection failure. This was not a browser-permission failure. No printer
firmware, motion settings or physical connection was changed to mask that state.

## Corrective work

- Document Linux system-service deployment with persistent private storage.
- Add a visible, configurable backend instance name and versioned JSON health.
- Separate server/Moonraker availability from Klipper readiness in the console.
- Permit dashboard access during an MCU error while keeping machine controls disabled.
- Prevent an observation-only learner from replaying persisted restoration commands.
- Update the browser cache and add regression coverage for these distinctions.

## Deployment checks

The reviewed application was installed in an isolated Python environment on a
Debian 13 / aarch64 host. The previous desktop backend was stopped while the
printer was idle and its prior experiment was already restored. The Linux backend
then served authenticated status successfully, with unauthenticated access denied.
Its service is enabled at boot. The original Klipper and Moonraker process IDs
remained unchanged. This check did not physically power off the desktop computer.

The private migration preserved 33 trials and transferred 5,497 selected state
files using SQLite online snapshots and an archive hash checked after encrypted
transfer. Runtime data, credentials and host-specific deployment scripts were not
added to Git. The old workstation copy was retained.

The new Linux host generates and retains its own private TLS keys and token.
Its public CA certificate requires operator trust on the phone, and the phone
must open the new origin and grant permissions there. Certificate checks were
not disabled. The camera proxy uses a verified DNS certificate identity in
addition to the leaf's IP subject alternative name. An absent phone stream
returns unavailable rather than a stale frame or a broken TLS gateway.

Phone camera/microphone operation on the new origin, physical PC power-off,
and a new physical print remain operator acceptance checks, not completed tests.
The historical dataset may take time to analyse on the lower-powered host.
Automatic experiments remain disabled in the migrated service.

## Software validation

The local Python suite passed 283 tests and 185 subtests. The extended browser
connection suite passed with all network and hardware interactions simulated.
Ruff E9/F and repository consistency checks passed. A 0.5.2 wheel built and
installed on Linux. Existing third-party test deprecation warnings remain.
Check the commit's GitHub Actions result separately for remote CI validation.

## Benchmark wording

The available history supports 22 min 17 s print duration / 25 min 35 s total for
the fastest identifiable completed, non-partial Benchy entry, at 0.4 mm / 121
layers. Different trials have different layer counts. The earlier artwork's
approximate 20-minute claim is not an exact timing measurement; neither unchanged
layers across all trials nor acceptable quality follows from a completed job.
