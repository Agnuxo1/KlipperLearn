# Installation and first connection

## Host requirements

Use Python 3.11+ and an existing, independently configured Klipper/Moonraker host.
The phone runs a compatible browser. Camera and sensor access normally require a
trusted HTTPS origin or a loopback development origin. Native Android hosting and
USB integration require a separate supported OS/runtime and are not installed here.

Create a virtual environment and install `.[learning]` as shown in the README.
The optional `.[training]` extra installs PyTorch/torchvision; do not install it
merely to view the console. No model weights are downloaded by inference.

## Start without printer access

```sh
python -m klipperlearn serve --host 127.0.0.1 --port 8765
```

This serves the application locally without a printer-control adapter. A phone
cannot access another machine's loopback address. Network access is an additional,
explicit deployment step, not a reason to bind an unauthenticated server publicly.

## Create local credentials

```sh
python -m klipperlearn lan-token --output .private/mobile-token.txt
```

Keep this file private. It must not be committed, pasted into issues, or embedded
in a public URL. Tokens should be generated rather than reused from examples.
The listener rejects invalid tokens and unauthenticated private evidence requests.

For a LAN deployment, provide a trusted certificate and key for the actual host,
then start the server using the supported options:

```text
python -m klipperlearn serve --host <actual-LAN-address> --port 8765
  --mobile-token-file .private/mobile-token.txt
  --tls-certfile .private/server-cert.pem --tls-keyfile .private/server-key.pem
  --moonraker http://127.0.0.1:7125
  --experiments-root data/experiments --learning
```

The line breaks above document arguments; enter the command as a single line.
Replace only the host/certificate locations required by your installation. This
is intentionally not a universal printer profile. Do not disable browser TLS
warnings, firmware thermal checks, or router/firewall protections to make it work.

`--learning` enables evidence processing. `--automatic-print` is a separate opt-in
for bounded experimental trial preparation, not a promise of unattended operation.
Read `python -m klipperlearn serve --help` and the safety guide before enabling it.
The application does not trust forwarded proxy headers by default.

## Pair the phone

Use a private pairing link with the token in its URL fragment, not a query string:
`https://<actual-LAN-address>:8765/mobile/console.html#pair=<private-token>`.
The browser removes the fragment after processing and sends authentication in a
header. Pairing is retained in that browser's local storage; use a dedicated trusted
browser profile and clear site storage when retiring or sharing the phone.

Local one-touch pairing is an optional trusted-network deployment feature, not
Internet authentication. Explicitly configure its allowed origins/networks and
retain host/origin checks. Do not publish a pairing link in the README or a screenshot.

Allow only the requested camera/microphone/motion permissions you intend to use.
A pending microphone permission must not prevent camera-only collection. Keep the
page visible; Android power management may suspend background browser work.
Check that the camera produces fresh frames and that the installation handles
screen lock, network loss and recovery before relying on it during a print.

## Updates and rollback

Install updates in a separate environment, keep private configuration and evidence
outside the source tree, and back up databases using the export command. Review
changes and test with the printer idle before switching services. This publication
does not restart or replace a running local installation.
