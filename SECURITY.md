# Security

Do not put credentials, private network configuration, printer logs, personal
photographs or model checkpoints into public issues. Report suspected vulnerabilities
privately using the repository's private security-reporting facility when available.
Otherwise ask the maintainer for a private channel without publishing exploit details.

This project is experimental. Keep it on a trusted local network behind trusted
HTTPS and explicit authentication. Do not expose Moonraker or local one-touch pairing
to the public Internet. Leave Klipper's independent thermal and motion protections on.

The reviewed source rejects ambiguous authentication headers, non-finite/duplicate
JSON fields, oversized bodies and stale live frames. These controls do not constitute
a complete security certification. Only load trusted optional model files using a
patched PyTorch runtime; version 0.5.1 blocks known-vulnerable checkpoint loaders below
2.10.0. See `docs/RELEASE_REVIEW_0.5.1.md` for the review scope and limitations.
