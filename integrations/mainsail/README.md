# Mainsail: restricted camera interoperability

Keep Mainsail and its normal printer controls. KlipperLearn can supply its existing
snapshot/MJPEG camera feed, while the optimizer remains a separate page.
The backend, phone permissions and trusted HTTPS must already be configured.

The renderer creates an **uninstalled nginx server-context snippet** from a
strict specification. A complete synthetic specification is provided as
`examples/camera-proxy-spec.json`; replace its example addresses/certificate paths
with the operator's actual deployment values before use.

```sh
python -m klipperlearn.camera_proxy render --spec camera-proxy-spec.json --output camera.conf
python -m klipperlearn.camera_proxy settings --frontend mainsail
python -m klipperlearn.camera_proxy viewer-header --token-file backend-token.txt --output viewer-header.conf
```

The last file contains a derived view-only secret. Protect it and its directory;
never commit it or paste it in an issue. It is distinct from the control token.
The proxy configuration refers to that file instead of embedding the token.
The configured `tls_name` must match a **DNS SAN** on the backend certificate;
the backend address can be an IP SAN too. Do not disable certificate validation.

After an operator reviews the snippet, tests nginx configuration and chooses an
appropriate maintenance time to install it, configure a camera in Mainsail:

| Setting | Value |
| --- | --- |
| Name | KlipperLearn camera |
| Service | MJPEG / `mjpegstreamer` |
| Snapshot | `/klipperlearn-camera/snapshot` |
| Stream | `/klipperlearn-camera/stream` |
| Target FPS | 1 |

The proxy only exposes these two exact routes. It denies write requests, unknown
subpaths and query-string credentials, does not forward browser credentials,
verifies upstream TLS, refuses redirects and disables caching. Access is limited
to one explicit private subnet of at most /24. The surrounding server must remain
LAN-only and HTTPS-protected. This is not a remote-access or authentication product.

The backend's existing freshness check returns unavailable without an active
recent phone frame. That is expected until a phone reconnects. A proxy cannot
create a live camera or judge a printed part. Run the separate optimizer directly
at its configured HTTPS origin; do not add a broad proxy to its control API.

A real nginx/TLS validation script is `tools/check_camera_proxy_native.py`; it
starts disposable loopback-only services in an isolated runner, not your printer.
Native Mainsail GUI acceptance remains a separate operator test.

Official sources:
- https://moonraker.readthedocs.io/en/latest/configuration/#webcam
- https://github.com/mainsail-crew/mainsail
- https://nginx.org/en/docs/http/ngx_http_proxy_module.html

## Scope and contribution status

This is an independently maintained KlipperLearn integration. It is not an
upstream merge, official listing, endorsement, or physical-printer validation.
All new commands below run locally on supplied files and do not start a print.
No firmware, operating-system service or existing preset is modified.
