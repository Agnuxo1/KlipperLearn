# Security policy

This research preview has no printer-control transport. Treat proposed settings,
imported evidence and external model output as untrusted data.

Do not expose Moonraker, SSH, ADB or a printer webcam directly to the public Internet.
Do not disable TLS verification or authorization to make an integration appear to work.
The exporter is a conservative filter, not a guarantee that arbitrary source files
contain no secrets. Review each private package before sharing or importing it.

For a suspected vulnerability, do not publish credentials, exploit details against
a real device or private print records. Use GitHub private vulnerability reporting
when available. Otherwise request a private reporting channel in a minimal issue
without technical exploit details. No response time or supported production branch
is promised for this experimental release.

See `docs/SAFETY.md` for the independent physical-safety boundary.
