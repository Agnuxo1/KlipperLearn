# Android phone as the Klipper host

**Design and validation requirements. No working Android *Klipper* host package is shipped.**

For printers that run Marlin or compatible G-code firmware, the phone can already act
as the host through the browser: see [KlipperLearn Phone](PHONE_APP.md), which uses
WebUSB drivers (CDC-ACM, CH340/CH341, CP210x and FTDI) and the firmware's serial
G-code protocol. The requirements below still apply to running Klipper itself on a phone.

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

## Candidate route under test: Termux without root (2026-09-27)

[klipper_termux](https://github.com/thingsapart/klipper_termux) runs mainline Klipper,
Moonraker and Mainsail in Termux on Android 7+ without root. A companion APK owns the
USB device through Android's USB host API (usb-serial-for-android: CDC-ACM, CH340,
CP210x, FTDI, PL2303) and forwards the bytes to a pseudo-terminal that Klippy opens as
its serial port. Klipper needs one small patch for old Android clocks. The project is
young, so the requirements above still apply and nothing here is marked supported.

KlipperLearn fits on top of it without keys: serve `docs/app/` from the same local web
server as Mainsail (for example `http://localhost:8080/klipperlearn/`). The page is then
a secure context (camera, microphone and accelerometer work), its Moonraker mode uses
the page origin, and every trial is recorded as a `klipperlearn-dataset/v1` folder.

Order of work, one step at a time, keeping the existing Linux host as the fallback:

1. Run `tools/android/phone_host_check.sh` in Termux (read-only) and keep its output.
2. Install Termux (F-Droid or GitHub build) and the klipper_termux APK; grant USB access.
3. Reuse the working `printer.cfg`, including the safety limits (acceleration cap,
   velocity cap, square corner velocity); do not change thermal protections.
4. Connect only the printer by OTG, check `FIRMWARE_RESTART` and temperatures, then a
   motion test without heat before any print.
5. Record the model, Android version, OTG/charging arrangement and recovery behaviour.

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
