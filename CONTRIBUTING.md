# Contributing

Keep changes focused, in English, and accompanied by reproducible tests. The core
application is GPL-3.0-or-later; retain existing attribution and any separately scoped
MIT notices. Never include private runtime data, credentials, unlicensed models or
unverified performance claims in a pull request.

Use Python 3.11+, install `.[learning,dev]`, run `npm ci`, and install the Playwright
browser required by the tests. Run the commands in the README. Browser printer APIs
are simulated and Python source tests block outbound sockets. Do not use a running
printer as a unit-test fixture.

For control changes, document state checks, explicit intent, bounds, ambiguous-result
handling and restoration. For models, separate sessions and report data provenance,
uncertainty and failure cases. A passing synthetic test does not validate hardware.

Before proposing an upstream change, follow that project's contribution guidance,
search for duplicate issues, and provide a specific interoperability improvement.
Do not send promotional issues or repeated requests for attention. This repository
is independent of Klipper, Moonraker, Mainsail, OrcaSlicer and Voron.
