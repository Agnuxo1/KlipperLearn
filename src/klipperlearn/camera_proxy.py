"""Render restrictive Mainsail/Fluidd camera configuration without deploying it.

Only exact read-only snapshot and MJPEG stream endpoints are exposed. The header
secret is stored separately, with exclusive creation and no credential output.
SPDX-License-Identifier: GPL-3.0-or-later
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys

from .ecosystem_evidence import EvidenceError, load_document, write_new

_PRIVATE = tuple(ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
_DNS = re.compile(
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+\Z", re.ASCII
)
_PATH = re.compile(r"/[A-Za-z0-9_./-]+\Z", re.ASCII)


def _path(value, name):
    if (
        not isinstance(value, str)
        or not _PATH.fullmatch(value)
        or any(part in {".", ".."} for part in value.split("/"))
        or "//" in value
        or len(value) > 512
        or value.endswith("/")
    ):
        raise EvidenceError(f"{name} must be an absolute, simple POSIX file path")
    if not PurePosixPath(value).is_absolute():
        raise EvidenceError("Absolute file path required")
    return value


def validate_spec(spec: dict) -> dict:
    """Reject configuration injection, public upstreams and overly broad grants."""
    required = {
        "backend_ip",
        "port",
        "allow_network",
        "tls_name",
        "ca_certificate",
        "viewer_header",
    }
    if not isinstance(spec, dict) or set(spec) != required:
        raise EvidenceError("The camera specification has missing or extra fields")
    try:
        address = ipaddress.IPv4Address(spec["backend_ip"])
        network = ipaddress.IPv4Network(spec["allow_network"], strict=True)
    except (ValueError, TypeError):
        raise EvidenceError("Use a literal IPv4 backend and an explicit IPv4 network") from None
    if not (
        any(address in net for net in _PRIVATE) or address == ipaddress.ip_address("127.0.0.1")
    ):
        raise EvidenceError("Backend must be private or the loopback address")
    private_net = any(network.subnet_of(net) for net in _PRIVATE)
    if network.prefixlen < 24 or not (private_net or str(network) == "127.0.0.1/32"):
        raise EvidenceError("Grant at most one /24 private LAN or loopback /32")
    if type(spec["port"]) is not int or not 1 <= spec["port"] <= 65535:
        raise EvidenceError("Port must be an integer from 1 to 65535")
    name = spec["tls_name"]
    if not isinstance(name, str) or len(name) > 253 or not _DNS.fullmatch(name):
        raise EvidenceError(
            "Use the literal DNS subject alternative name in the backend certificate"
        )
    try:
        ipaddress.ip_address(name)
    except ValueError:
        pass
    else:
        raise EvidenceError("Use a DNS certificate identity, not a numeric TLS name")
    ca = _path(spec["ca_certificate"], "ca_certificate")
    header = _path(spec["viewer_header"], "viewer_header")
    if ca == header:
        raise EvidenceError("Certificate and private header must be different files")
    return {**spec, "backend_ip": str(address), "allow_network": str(network)}


def render_proxy(spec: dict) -> str:
    """Return an nginx server-context include; no service/file is changed."""
    spec = validate_spec(spec)
    blocks = [
        "# Generated KlipperLearn camera include. Review before deployment.",
        "# Use inside a LAN-only HTTPS server. Never expose it publicly.",
    ]
    for endpoint in ("snapshot", "stream"):
        blocks.append(f"""location = /klipperlearn-camera/{endpoint} {{
    allow {spec["allow_network"]};
    deny all;
    limit_except GET {{ deny all; }}
    if ($args != "") {{ return 400; }}
    proxy_pass https://{spec["backend_ip"]}:{spec["port"]}/mobile/api/live/{endpoint};
    proxy_pass_request_headers off;
    proxy_pass_request_body off;
    proxy_set_header Host {spec["tls_name"]};
    proxy_set_header Connection "";
    proxy_set_header Content-Length "";
    include {spec["viewer_header"]};
    proxy_ssl_verify on;
    proxy_ssl_verify_depth 3;
    proxy_ssl_server_name on;
    proxy_ssl_name {spec["tls_name"]};
    proxy_ssl_trusted_certificate {spec["ca_certificate"]};
    proxy_ssl_protocols TLSv1.2 TLSv1.3;
    proxy_http_version 1.1;
    proxy_buffering off;
    proxy_cache off;
    proxy_no_cache 1;
    proxy_cache_bypass 1;
    proxy_next_upstream off;
    proxy_read_timeout 20s;
    proxy_intercept_errors on;
    error_page 301 302 303 307 308 =502 @klipperlearn_camera_redirect_rejected;
    proxy_hide_header Cache-Control;
    add_header Cache-Control "no-store" always;
    add_header X-Content-Type-Options "nosniff" always;
}}""")
    blocks += [
        "location ^~ /klipperlearn-camera/ { return 404; }",
        "location @klipperlearn_camera_redirect_rejected { return 502; }",
    ]
    return "\n\n".join(blocks) + "\n"


def webcam_settings(frontend: str) -> dict:
    """Return documented MJPEG URLs; registration still requires operator action."""
    if frontend not in ("mainsail", "fluidd"):
        raise EvidenceError("Select mainsail or fluidd")
    return {
        "frontend": frontend,
        "name": "KlipperLearn camera",
        "service": "mjpegstreamer",
        "stream_url": "/klipperlearn-camera/stream",
        "snapshot_url": "/klipperlearn-camera/snapshot",
        "target_fps": 1,
        "target_fps_idle": 1,
        "auto_register": False,
        "freshness_policy": "Backend rejects inactive or older-than-five-second snapshots",
        "camera_only": True,
        "printer_control_exposed": False,
    }


def private_viewer_header(token: str) -> bytes:
    """Derive the existing backend's view-only HMAC, not a control credential."""
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", token, re.ASCII):
        raise EvidenceError("A valid private backend token is required")
    viewer = hmac.new(token.encode("ascii"), b"camera-view-only-v1", hashlib.sha256).hexdigest()
    return f'proxy_set_header X-KlipperLearn-Viewer "{viewer}";\n'.encode("ascii")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    render = commands.add_parser("render")
    render.add_argument("--spec", type=Path, required=True)
    render.add_argument("--output", type=Path, required=True)
    settings = commands.add_parser("settings")
    settings.add_argument("--frontend", choices=("mainsail", "fluidd"), required=True)
    header = commands.add_parser("viewer-header")
    header.add_argument("--token-file", type=Path, required=True)
    header.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "settings":
            print(json.dumps(webcam_settings(args.frontend), indent=2))
            return 0
        if args.command == "render":
            encoded = render_proxy(load_document(args.spec)).encode("utf-8")
        else:
            # Private files remain local; no token is accepted in process arguments.
            import stat

            info = args.token_file.lstat()
            if (
                not stat.S_ISREG(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & 0x400
                or not 16 <= info.st_size <= 130
            ):
                raise EvidenceError("Token file must be a small regular file")
            with args.token_file.open("rb") as handle:
                opened = os.fstat(handle.fileno())
                if (info.st_dev, info.st_ino) != (opened.st_dev, opened.st_ino):
                    raise EvidenceError("Private token file changed before reading")
                raw = handle.read(131)
                after = os.fstat(handle.fileno())
            if (
                len(raw) > 130
                or info.st_size != after.st_size
                or info.st_mtime_ns != after.st_mtime_ns
            ):
                raise EvidenceError("Private token file changed during reading")
            encoded = private_viewer_header(raw.decode("ascii").strip())
        write_new(args.output, encoded)
        print("New configuration file created. No service was changed; keep the header private.")
        return 0
    except (OSError, ValueError, TypeError, UnicodeError):
        print(
            "Camera configuration rejected or output unavailable; no deployment performed.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
