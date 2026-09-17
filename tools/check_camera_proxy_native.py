#!/usr/bin/env python3
"""Run an opt-in real nginx/TLS contract check on disposable loopback services.

Requires nginx and openssl on PATH. Never reads production nginx configuration,
changes a service or contacts a printer/LAN host. Not part of outbound-blocked
application tests; invoke this file explicitly in an isolated validation runner.
"""

from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from klipperlearn.camera_proxy import private_viewer_header, render_proxy


def run_checks() -> dict:
    nginx, openssl = shutil.which("nginx"), shutil.which("openssl")
    if not nginx or not openssl:
        raise RuntimeError("Native checks require nginx and openssl")
    calls, mode = [], {"status": 200}

    class Camera(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append({"path": self.path, "headers": dict(self.headers)})
            self.send_response(mode["status"])
            if mode["status"] == 307:
                self.send_header("Location", "https://do-not-contact.invalid/")
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Cache-Control", "max-age=3600")
            self.end_headers()
            self.wfile.write(b"\xff\xd8TEST\xff\xd9" if mode["status"] == 200 else b"Unavailable")

        def log_message(self, *_args):
            return

    results = []
    with tempfile.TemporaryDirectory(prefix="klipperlearn-nginx-") as directory:
        tmp = Path(directory)
        key, cert = tmp / "key.pem", tmp / "cert.pem"
        subprocess.run(
            [
                openssl,
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "1",
                "-keyout",
                str(key),
                "-out",
                str(cert),
                "-subj",
                "/CN=klipperlearn.internal",
                "-addext",
                "subjectAltName=DNS:klipperlearn.internal",
            ],
            check=True,
            capture_output=True,
            timeout=20,
        )
        header = tmp / "viewer.conf"
        control = "isolated-test-control-token-not-real"
        header.write_bytes(private_viewer_header(control))
        camera = ThreadingHTTPServer(("127.0.0.1", 0), Camera)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        camera.socket = context.wrap_socket(camera.socket, server_side=True)
        worker = threading.Thread(target=camera.serve_forever, daemon=True)
        worker.start()
        with socket.socket() as available:
            available.bind(("127.0.0.1", 0))
            proxy_port = available.getsockname()[1]
        spec = {
            "backend_ip": "127.0.0.1",
            "port": camera.server_port,
            "allow_network": "127.0.0.1/32",
            "tls_name": "klipperlearn.internal",
            "ca_certificate": str(cert),
            "viewer_header": str(header),
        }

        def request(path, method="GET", headers=None):
            opener = build_opener(ProxyHandler({}))
            req = Request(
                f"http://127.0.0.1:{proxy_port}" + path, method=method, headers=headers or {}
            )
            try:
                with opener.open(req, timeout=3) as response:
                    return response.status, dict(response.headers), response.read()
            except HTTPError as error:
                return error.code, dict(error.headers), error.read()

        @contextmanager
        def proxy(settings):
            config = (
                f"pid {tmp}/nginx.pid;\nerror_log {tmp}/error.log;\nevents {{}}\nhttp {{\n"
                f"access_log off; server {{ listen 127.0.0.1:{proxy_port};\n"
                'location = /probe { return 200 "ok"; }\n' + render_proxy(settings) + "\n}\n}\n"
            )
            conf = tmp / "nginx.conf"
            conf.write_text(config)
            subprocess.run(
                [nginx, "-t", "-p", str(tmp) + "/", "-c", str(conf)],
                check=True,
                capture_output=True,
                timeout=10,
            )
            process = subprocess.Popen(
                [
                    nginx,
                    "-p",
                    str(tmp) + "/",
                    "-c",
                    str(conf),
                    "-g",
                    "daemon off; master_process off;",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                for attempt in range(40):
                    try:
                        if request("/probe")[0] == 200:
                            break
                    except OSError:
                        pass
                    time.sleep(0.05)
                else:
                    raise RuntimeError("Isolated nginx did not become ready")
                yield
            finally:
                process.terminate()
                process.wait(timeout=5)

        try:
            with proxy(spec):
                status, headers, content = request(
                    "/klipperlearn-camera/snapshot",
                    headers={
                        "Authorization": "do-not-forward",
                        "Cookie": "private-cookie",
                        "X-KlipperLearn-Token": control,
                        "X-KlipperLearn-Viewer": "spoofed",
                    },
                )
                assert status == 200 and content.startswith(b"\xff\xd8")
                seen = {k.lower(): v for k, v in calls[-1]["headers"].items()}
                assert (
                    "authorization" not in seen
                    and "cookie" not in seen
                    and "x-klipperlearn-token" not in seen
                )
                assert seen["x-klipperlearn-viewer"] not in (control, "spoofed")
                assert headers["Cache-Control"] == "no-store"
                results.append("verified_TLS_and_private_header_isolation")
                assert request("/klipperlearn-camera/stream")[0] == 200
                results.append("exact_stream_mapping")
                count = len(calls)
                assert request("/klipperlearn-camera/snapshot", method="POST")[0] == 403
                assert request("/klipperlearn-camera/frame")[0] == 404
                assert request("/klipperlearn-camera/snapshot?token=ignored")[0] == 400
                assert len(calls) == count
                results.append("writes_unknown_paths_and_query_credentials_blocked")
                mode["status"] = 503
                assert request("/klipperlearn-camera/snapshot")[0] == 503
                results.append("unavailable_camera_not_replaced_with_cached_frame")
                mode["status"] = 307
                assert request("/klipperlearn-camera/snapshot")[0] == 502
                results.append("redirects_rejected")
                mode["status"] = 200
            with proxy({**spec, "tls_name": "wrong-identity.internal"}):
                assert request("/klipperlearn-camera/snapshot")[0] == 502
                results.append("wrong_certificate_identity_rejected")
            with proxy({**spec, "allow_network": "192.168.50.0/24"}):
                count = len(calls)
                assert request("/klipperlearn-camera/snapshot")[0] == 403 and len(calls) == count
                results.append("network_allowlist_enforced")
        finally:
            camera.shutdown()
            camera.server_close()
            worker.join(timeout=3)
    return {
        "native_nginx": True,
        "passed_checks": results,
        "production_config_read": False,
        "printer_or_LAN_contact": False,
        "temporary_services_stopped": True,
    }


if __name__ == "__main__":
    print(json.dumps(run_checks(), indent=2))
