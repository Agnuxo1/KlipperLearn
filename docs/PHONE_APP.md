# KlipperLearn Phone: tune a printer from one phone

**Preview. Tested with a simulated printer only; no physical printer, phone or USB
adapter has been validated yet.**

App: <https://agnuxo1.github.io/KlipperLearn/app/>

KlipperLearn Phone is a static web app. It runs in the phone's browser, talks to
the printer through the phone's USB port and stores everything on the phone. You
don't need a Raspberry Pi, a PC, an account or a server.

```
phone (Chrome) ── USB-OTG cable ── printer board (Marlin or compatible firmware)
   │  WebUSB drivers: CDC-ACM, CH340/CH341, CP210x, FTDI   (Web Serial on desktop)
   │  G-code host: line numbers, checksums, resends, temperatures, pause/cancel
   ├─ calibration G-code generators (no slicer needed)
   ├─ camera · microphone · accelerometer measurements
   ├─ trial history in IndexedDB (export/import JSON)
   └─ local advisor: one bounded change per trial; optional external advisor (JEV)
```

## Quick start (Android)

1. Open the app URL in **Chrome for Android**. Optionally use *Install app* or
   *Add to Home screen*; after that it also works offline.
2. Connect the phone to the printer's USB port with a **USB-OTG adapter or cable**.
   Keep the phone charged; many phones can't charge while they act as USB host.
3. Tap **Connect over USB**, choose the printer in Chrome's device list and allow
   access. Try 115200 baud first; many 8-bit Marlin boards use 250000.
4. Fill in the **printer profile**: bed size, nozzle, filament and temperature limits.
5. Open **Calibrate**, prepare a test and print it from **Print**. Keep the screen on
   and the tab open during the print.
6. In **Learn**, rate the result and mark any defects. The app recommends one change
   for the next trial. You can accept it, pick another candidate or keep the settings.

Desktop Chrome/Edge works too, using Web Serial. To try the app without a printer,
tap **Try the simulator**.

## What the phone does

| Function | How | Limits |
|---|---|---|
| Printer control | WebUSB or Web Serial and G-code over the firmware's serial protocol | Needs Marlin or compatible G-code firmware. A board running **Klipper firmware** needs a Klipper host; this app doesn't replace klippy. |
| Tuning without re-slicing | Streamed G-code is rewritten per trial: M220 speed, M221 flow, M204 acceleration, M205 junction deviation or jerk, M900 linear advance, M593 input shaping, temperature and fan offsets, retraction length | M900 and M593 only work if the firmware reports them in M503. Every trial ends by restoring the firmware values it read at connect. EEPROM is never written. |
| Calibration prints | Built-in generators: temperature tower, ringing (acceleration) tower, speed tower, retraction test, linear advance pattern, first-layer squares, standard trial part | Band values are written as `;KL_BAND` comments. A calibration never overrides the parameter it tests. |
| Camera | Photo every N layers plus a final photo; ringing wavelength from a user-drawn rectangle (f = v / λ) | Indicators for comparing trials taken under the same conditions, not metrology. |
| Manual ringing | Klipper's method: f = v · N / D | Uses your ruler count. |
| Microphone | Loudness, spectral centroid, click rate (possible skipped steps or extruder grinding) | Room noise affects it. Only features are kept, never audio. |
| Accelerometer | Records during a trial; an experimental resonance sweep drives one axis at known frequencies without heating or extruding | Phone sensors often sample at 60–200 Hz. The sweep compares energy per excitation frequency, so it's only a rough indicator. |
| Advisor | Score = 40 % measured + 60 % human rating. Fixes the worst defect first. Reverts a change that lowered the score. Explores faster settings when no major defect remains. | Compares only trials of the same printer and the same G-code. Never applies anything without your tap. |
| JEV (optional) | Set an advisor URL. The app POSTs the rated trial and the bounded candidates, and accepts only one of those candidates. | The public app holds no credentials. JEV runs behind your own local service. |

## Safety

- The top bar has a red **STOP** button (M112) whenever a printer is connected.
- Cancel turns heaters off, raises Z and disables the motors.
- A job only runs while the tab is open. The app requests a screen wake lock, but
  if Android suspends the tab, the printer stops receiving G-code. It stops moving,
  but the heaters keep the last target, so stay with the printer.
- Temperatures are clamped to the profile limits. Trial settings exist only in RAM
  and are restored at the end of each job.
- Supervise every print. This is experimental software without warranty.

## Advisor endpoint contract

Request (`POST`, JSON): `schema: "klipperlearn.advisor-request/v1"`, `goal`, `firmware`,
`weights`, `last` (the rated trial), `history` (up to 12 comparable trials) and
`candidates`. Each candidate has `{id, parameter, value, bounds, maximum_step, description}`,
and the list always includes `no_change`.

Response: `{candidate_id, confidence, provenance}`. The app rejects any id that
isn't among the candidates it sent. The app is served over HTTPS, so the endpoint
must be HTTPS or `http://localhost` / `http://127.0.0.1`.

## Validation status

- `tests/test_phone_app.cjs`: CH340 and FTDI baud encodings, the CH340 init sequence
  against a fake device, Marlin line protocol with injected checksum errors, cancel
  and shutdown, G-code trial transforms (absolute and relative E), calibration
  bounds, FFT, ringing analysis and advisor decisions.
- `tests/test_phone_app_browser.cjs`: real Chromium at phone and desktop widths,
  simulator connect, generated trial, rating and recommendation, with no external
  requests.
- **Not yet done:** printing on a real printer over Android USB. Record the phone
  model, Android and Chrome versions, the USB chipset, baud rate and results in a
  compatibility report before claiming support for a combination.
