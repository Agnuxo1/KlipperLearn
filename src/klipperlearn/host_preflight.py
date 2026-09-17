"""Read-only KlipperLearn prerequisites for KIAUH-managed or standalone hosts.

Does not import third-party package code, query devices, start services, execute
commands, open sockets, install dependencies or reveal usernames/host paths.
SPDX-License-Identifier: GPL-3.0-or-later
"""

from __future__ import annotations

import argparse
from importlib import metadata
import json
import platform
from pathlib import Path
import re
import shutil
import ssl
import sys

from .ecosystem_evidence import EvidenceError, finite_number, load_document, write_new

MINIMUMS = {
    "fastapi": (0, 115),
    "uvicorn": (0, 30),
    "httpx": (0, 27),
    "Pillow": (10, 4),
    "numpy": (1, 26),
    "opencv-python": (4, 10),
}
_VERSION = re.compile(r"([0-9]+)\.([0-9]+)(?:\.([0-9]+))?(?:[+.-][A-Za-z0-9.-]+)?\Z", re.ASCII)


def collect_snapshot(storage: Path) -> dict:
    """Inspect the chosen interpreter and filesystem, not printer processes."""
    if storage.is_symlink() or not storage.is_dir():
        raise EvidenceError("Choose an existing real storage directory")
    versions = {}
    for package in MINIMUMS:
        try:
            versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            versions[package] = None
    return {
        "python": list(sys.version_info[:3]),
        "system": platform.system(),
        "machine": platform.machine(),
        "ssl_available": hasattr(ssl, "SSLContext"),
        "disk_free_mib": shutil.disk_usage(storage).free // (1024 * 1024),
        "packages": versions,
    }


def evaluate(snapshot: dict) -> dict:
    """Evaluate prerequisites without treating them as installation approval."""
    if not isinstance(snapshot, dict):
        raise EvidenceError("Preflight snapshot must be an object")
    version = snapshot.get("python")
    if (
        not isinstance(version, list)
        or len(version) != 3
        or any(type(v) is not int or v < 0 or v > 1000 for v in version)
    ):
        raise EvidenceError("Python version must contain three non-negative integers")
    free = finite_number(snapshot.get("disk_free_mib"))
    if free is None or type(snapshot.get("ssl_available")) is not bool:
        raise EvidenceError("Disk and SSL fields are required")
    packages = snapshot.get("packages")
    if not isinstance(packages, dict):
        raise EvidenceError("An explicit installed-package map is required")
    systems = {"Linux", "Windows", "Darwin"}
    system = snapshot.get("system")
    system = system if isinstance(system, str) and system in systems else "unknown"
    architectures = {"x86_64", "AMD64", "aarch64", "arm64", "armv7l", "i686"}
    machine = snapshot.get("machine")
    machine = machine if isinstance(machine, str) and machine in architectures else "unknown"
    blockers = []
    if version[0] != 3 or version[1] < 11:
        blockers.append("python_3_11_or_later_required")
    if not snapshot["ssl_available"]:
        blockers.append("ssl_unavailable")
    if free < 512:
        blockers.append("less_than_512_mib_free")
    package_checks = []
    for name, minimum in MINIMUMS.items():
        raw = packages.get(name)
        match = _VERSION.fullmatch(raw) if isinstance(raw, str) and len(raw) <= 80 else None
        installed = tuple(int(n or 0) for n in match.groups()) if match else None
        ok = installed is not None and installed[:2] >= minimum
        package_checks.append(
            {
                "package": name,
                "installed_version": raw if match else None,
                "minimum_version": ".".join(map(str, minimum)),
                "meets_minimum": ok,
            }
        )
    missing = [p["package"] for p in package_checks if not p["meets_minimum"]]
    return {
        "schema": "klipperlearn.host-preflight/v1",
        "python": version,
        "system": system,
        "machine": machine,
        "disk_free_mib": free,
        "packages": package_checks,
        "blockers": blockers,
        "optional_learning_dependencies_missing": missing,
        "status": "blocked"
        if blockers
        else "dependencies_needed"
        if missing
        else "prerequisites_present",
        "linux_host_reported": system == "Linux",
        "kiauh_installation_verified": False,
        "services_inspected": False,
        "certificates_validated": False,
        "port_availability_checked": False,
        "printer_connected": False,
        "installation_performed": False,
        "safe_to_deploy_certified": False,
        "note": "512 MiB is a preliminary disk threshold, not a performance or capacity guarantee.",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--snapshot", type=Path)
    group.add_argument("--storage", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = evaluate(
            load_document(args.snapshot) if args.snapshot else collect_snapshot(args.storage)
        )
        encoded = (json.dumps(result, indent=2, allow_nan=False) + "\n").encode()
        if args.output:
            write_new(args.output, encoded)
            print("Preflight report saved; no installation or service change performed.")
        else:
            print(encoded.decode(), end="")
        return 0 if result["status"] == "prerequisites_present" else 1
    except (OSError, ValueError, TypeError):
        print("Preflight input or output rejected; no system changes made.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
