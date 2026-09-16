# Architecture

## Product goal, not a claim of completed deployment

```text
Phone
  HTML/JavaScript interface and trial review
  Local advisor OR optional external multimodal advisor
                 | proposals only
  Evidence store + policy gate + bounded trial scheduler
                 | explicit approved actions
  Native/OS service: Klipper host + Moonraker + USB access
                 | USB
Printer MCU running compatible Klipper firmware
```

Mainsail remains a Moonraker client. OrcaSlicer remains a slicer; it can prepare
printer-specific artifacts on a separate computer. A complete phone-only product
must provide validated local chart generation or suitable pre-approved artifacts,
not quietly require a computer during every calibration cycle.

## Separate deployment from advisor choice

A companion phone connected to an existing Linux host is a useful test topology,
but it is not the primary phone-only goal. Local and external advisors must both
be usable with either deployment after each deployment is independently validated.

The historical prototype is to be imported under its existing module paths. The
new `reference/` reviewer is isolated deliberately: it has no device credentials,
transport, native bridge or command execution and cannot move a printer.

## Contracts

A session fixes printer, material, geometry, mount, slicer profile and dimensions.
Only the declared parameter varies in this reference comparator. All unrecorded
configuration changes invalidate the comparison. Values supplied by a caller are
not proof that the machine actually used them.

Evidence references are immutable IDs in the reference contract, not image bytes.
The full controller must resolve them to verified hashes and synchronized data,
retain original records, and keep image registration and camera geometry versioned.

Local and external advisors produce proposals. The current reference validates
shape, provenance references and declared bounds, and always returns
`executable: false`. A future control service must independently check live
printer state, capabilities, limits, freshness, authorization and an explicit
user decision. Never grant an external model shell or arbitrary G-code access.

## Failure independence

Firmware heater protection and host/MCU communication protections remain active.
A web page, remote model, subscription quota, UI heartbeat or cloud connection must
never be the sole safety mechanism. Heavy inference must not starve the host's
motion planning. An evidence logger should survive a UI disconnect, bounded by
storage and privacy policy; it must not infer that a lost UI means printing stopped.

See the official [Klipper architecture](https://www.klipper3d.org/Code_Overview.html)
and [Moonraker API](https://moonraker.readthedocs.io/en/latest/external_api/).
