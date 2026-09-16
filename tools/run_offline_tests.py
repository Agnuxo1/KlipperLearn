#!/usr/bin/env python3
"""Run source tests with outbound sockets blocked, not against printer hardware."""

from __future__ import annotations

import os
from pathlib import Path
import socket
import sys
import threading


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    sys.path.insert(0, str(root / "src"))
    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    sys.dont_write_bytecode = True
    internal = threading.local()
    connect = socket.socket.connect
    connect_ex = socket.socket.connect_ex
    socketpair = socket.socketpair
    create_connection = socket.create_connection

    def internal_socketpair(*args, **kwargs):
        internal.active = True
        try:
            return socketpair(*args, **kwargs)
        finally:
            internal.active = False

    def guarded_connect(sock, address):
        # Windows implements the asyncio wakeup socket pair via loopback TCP.
        if getattr(internal, "active", False) and address[0] in ("127.0.0.1", "::1"):
            return connect(sock, address)
        raise RuntimeError("Outbound sockets are blocked in offline validation")

    def deny_connection(*args, **kwargs):
        raise RuntimeError("Outbound sockets are blocked in offline validation")

    socket.socketpair = internal_socketpair
    socket.socket.connect = guarded_connect
    socket.socket.connect_ex = deny_connection
    socket.create_connection = deny_connection
    try:
        import pytest

        return int(pytest.main(["tests", "-q", "--tb=short", *sys.argv[1:]]))
    finally:
        socket.socketpair = socketpair
        socket.socket.connect = connect
        socket.socket.connect_ex = connect_ex
        socket.create_connection = create_connection


if __name__ == "__main__":
    raise SystemExit(main())
