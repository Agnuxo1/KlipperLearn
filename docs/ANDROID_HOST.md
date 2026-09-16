# Android phone as the Klipper host

**Design and validation requirements. No working Android host package is shipped.**

The target is a compatible old phone connected directly to the printer by USB,
without a Raspberry Pi. A browser interface can handle presentation and some
analysis, but it is not a Linux Klipper host or a general USB serial service.
Klipper's installation documentation assumes a Linux-based host. Android provides
USB-host APIs, subject to hardware capability and permissions.

## Required boundaries

- A validated host runtime on the phone must execute Klippy, its native helper and
  Moonraker, maintain the required IPC and reach the MCU through a proven USB path.
- An Android implementation needs explicit USB permission, tested serial/chipset
  behavior and a suitable long-lived native service or validated OS environment.
  A generic user-space Linux container is not proof of usable USB access.
- OTG/host mode and simultaneous charging depend on the phone and adapter. Test
  both; do not assume a passive splitter makes them reliable.
- Validate storage capacity, battery condition, charging temperature, CPU scheduling,
  memory pressure and screen/background transitions under realistic workloads.
- The MCU still requires compatible firmware and a printer-specific configuration.
  Do not flash firmware or change thermal protections as an installation shortcut.

Do not claim all Android phones work, all phones require root, or that root alone
solves the integration. Record the exact model, OS, runtime, USB bridge, serial
chipset, power arrangement and recovery behavior for every supported combination.
An old Android version may also have browser/security limitations.

## Sensor capability matrix

Probe each capability rather than promising every sensor on every phone. Camera
and microphone require consent and a secure browser context where applicable.
Motion/orientation API availability and sampling differ. Record actual sample
intervals, jitter, units, axes, gaps, saturation and mount placement.

GPS is not nozzle-position feedback and is disabled by design. Frame-mounted
acceleration is not a direct measurement of lost motor steps. Phone vibration
measurements are not automatically interchangeable with Klipper's supported
resonance-measurement hardware and procedures.

## Hardware acceptance

A phone-only run must remain functional with any development PC and external
Klipper host switched off. Test loss of Wi-Fi, external-advisor failure, USB
unplugging, permission revocation, screen lock, service restart, low storage and
power changes under controlled conditions. Record results; do not call any of
these combinations supported based on simulator tests.

Sources: [Klipper installation](https://www.klipper3d.org/Installation.html),
[Android USB host](https://developer.android.com/develop/connectivity/usb/host),
[media permissions](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia),
[motion events](https://developer.mozilla.org/en-US/docs/Web/API/DeviceMotionEvent),
[Klipper resonance measurements](https://www.klipper3d.org/Measuring_Resonances.html).
