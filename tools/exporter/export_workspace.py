#!/usr/bin/env python3
"""Collect an existing KlipperLearn workspace and read-only Moonraker history.

No dependency installation, printer commands, Git operations, uploads, camera
activation, secret-file reads, or source modifications are performed. The output
is a LOCAL REVIEW PACKAGE, not an automatically approved public repository.
Python 3.8 or newer; standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile

DEFAULT_ROOT = Path.cwd()
DEFAULT_URL = "http://127.0.0.1:7125"
SOURCE_DIRS = {"src", "tests", "docs", "config", ".github", "scripts", "tools", "reference", "integrations", "schemas"}
ROOT_FILES = {
    "readme.md", "license", "license.md", "license.txt", "copying",
    "third_party_notices.md", "contributing.md", "security.md", "agents.md",
    "code_of_conduct.md", "changelog.md", "citation.cff", "pyproject.toml", "setup.py",
    "setup.cfg", "requirements.txt", "requirements-dev.txt", "package.json",
    "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "uv.lock",
    ".gitignore", ".gitattributes", "pytest.ini", "tox.ini", "manifest.in",
    "makefile", "dockerfile", "compose.yaml", "docker-compose.yml",
}
TEXT_SUFFIXES = {
    ".py", ".js", ".cjs", ".mjs", ".ts", ".tsx", ".html", ".css",
    ".md", ".rst", ".txt", ".toml", ".json", ".yaml", ".yml", ".ini",
    ".cfg", ".conf", ".sh", ".ps1", ".bat", ".cmd", ".xml", ".svg",
    ".lock", ".in", ".csv", ".c", ".h", ".cpp", ".hpp", ".scad",
}
EXCLUDED_DIRS = {
    ".git", ".venv", "venv", "env", "node_modules", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".cognition", ".ssh",
    "lan-private", "private", "secrets", "credentials", "data", "work",
    "dist", "build", "backups", "logs", ".cache",
}
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
SAFE_JOB_FIELDS = (
    "job_id", "filename", "exists", "status", "start_time", "end_time",
    "print_duration", "total_duration", "filament_used",
)
PRIVATE_NETWORKS = tuple(ipaddress.ip_network(n) for n in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "::1/128",
))
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----"),
    re.compile(r"\b(?:sk-proj-|sk-)[A-Za-z0-9_-]{20,}"),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
    re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
    re.compile(r"(?i)(?:password|passwd|api[_-]?key|(?:access[_-]?)?token|secret|pin)"
               r"\s*[\"']?\s*[:=]\s*[\"'][^\"'\r\n]{4,}[\"']"),
    re.compile(r"(?i)(?:password|passwd|api[_-]?key|(?:access[_-]?)?token|secret|pin)"
               r"\s*[:=]\s*(?:[0-9]{4,}|[A-Za-z0-9_+/=-]{20,})\s*(?:$|#)", re.M),
    re.compile(r"(?i)https?://[^/\s:@]+:[^/\s@]+@"),
    re.compile(r"(?i)[?&#](?:token|key|password|secret|pair)=[A-Za-z0-9_+/=-]{8,}"),
)


def json_bytes(value: Any) -> bytes:
    """Encode a stable, readable JSON document without non-finite numbers."""
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def is_link(path: Path) -> bool:
    """Reject symlinks and Windows reparse points, including directory junctions."""
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def secret_filename(path: Path) -> bool:
    """Exclude common credential file names before opening their contents."""
    name = path.name.lower()
    if name == ".env" or name.startswith(".env."):
        return True
    if path.suffix.lower() in {".pem", ".key", ".p12", ".pfx", ".crt", ".cer", ".keystore"}:
        return True
    return bool(re.search(r"(^|[-_.])(token|password|secret|credentials|id_rsa|id_ed25519)([-_.]|$)", name))


def collect_sources(root: Path) -> Tuple[List[Tuple[str, bytes]], Dict[str, Any]]:
    """Read selected text source files; report every excluded or withheld file.

    Detection is deliberately conservative and may withhold harmless tests.
    Human review remains mandatory; arbitrary secrets cannot be detected with
    certainty. Original files are never rewritten or deleted.
    """
    result: List[Tuple[str, bytes]] = []
    report: Dict[str, Any] = {"root_found": root.is_dir(), "included": [], "omitted": [],
                              "requires_human_review": True, "bytes_included": 0}
    if not root.is_dir():
        report["error"] = "Workspace directory not found; history can still be exported."
        return result, report
    if is_link(root):
        report["error"] = "Workspace root is a link or reparse point; source collection stopped."
        return result, report

    def omit(name: str, reason: str) -> None:
        report["omitted"].append({"path": name, "reason": reason})

    def visit_error(error: OSError) -> None:
        # Do not copy arbitrary error strings or absolute user paths into reports.
        report.setdefault("traversal_errors", []).append(type(error).__name__)

    for folder, dirs, files in os.walk(root, topdown=True, followlinks=False, onerror=visit_error):
        here = Path(folder)
        retained = []
        for name in sorted(dirs):
            path = here / name
            relative = path.relative_to(root).as_posix() + "/"
            try:
                if is_link(path):
                    omit(relative, "link_or_reparse_point")
                elif name.lower() in EXCLUDED_DIRS:
                    omit(relative, "private_data_environment_or_generated_directory")
                elif here == root and name not in SOURCE_DIRS:
                    omit(relative, "outside_source_directory_allowlist")
                else:
                    retained.append(name)
            except OSError:
                omit(relative, "directory_unreadable")
        dirs[:] = retained
        for name in sorted(files):
            path = here / name
            relative = path.relative_to(root).as_posix()
            try:
                if is_link(path):
                    omit(relative, "link_or_reparse_point")
                    continue
                if here == root and name.lower() not in ROOT_FILES:
                    omit(relative, "outside_root_file_allowlist")
                    continue
                if secret_filename(path):
                    omit(relative, "credential_filename")
                    continue
                if path.suffix.lower() not in TEXT_SUFFIXES and name.lower() not in ROOT_FILES:
                    omit(relative, "binary_or_unrecognized_type_requires_manual_review")
                    continue
                size = path.stat().st_size
                if size > MAX_FILE_BYTES or report["bytes_included"] + size > MAX_TOTAL_BYTES:
                    omit(relative, "size_limit")
                    continue
                with path.open("rb") as source:
                    payload = source.read(MAX_FILE_BYTES + 1)
                if len(payload) > MAX_FILE_BYTES or report["bytes_included"] + len(payload) > MAX_TOTAL_BYTES:
                    omit(relative, "size_limit")
                    continue
                text = payload.decode("utf-8-sig")
                if "\x00" in text:
                    omit(relative, "binary_content")
                    continue
                if any(pattern.search(text) for pattern in SECRET_PATTERNS):
                    omit(relative, "possible_embedded_credential_review_original_locally")
                    continue
                result.append(("source/" + relative, payload))
                report["included"].append({"path": relative, "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest()})
                report["bytes_included"] += len(payload)
            except (OSError, UnicodeError) as error:
                omit(relative, "unreadable_or_non_utf8_" + type(error).__name__)
    return result, report


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Do not follow redirects from the specified local printer host."""
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str,
                         headers: Any, newurl: str) -> None:
        return None


class HistoryReader:
    """A small GET-only client restricted to the documented history endpoint."""
    def __init__(self, base_url: str, timeout: float = 8.0) -> None:
        parsed = urllib.parse.urlsplit(base_url)
        try:
            address = ipaddress.ip_address(parsed.hostname or "")
            valid_host = any(address in network for network in PRIVATE_NETWORKS)
            port = parsed.port
        except ValueError as error:
            raise ValueError("Use a literal private or loopback IP address with a valid port.") from error
        if (not valid_host or parsed.scheme not in {"http", "https"}
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in {"", "/"} or port == 0):
            raise ValueError("Only a local HTTP(S) origin without credentials or a path is accepted.")
        self.base_url = base_url.rstrip("/")
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Timeout must be positive and finite.")
        self.timeout = timeout
        # Bypass environment proxies so local printer data is not sent to a proxy.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def page(self, start: int, limit: int, before: float) -> Dict[str, Any]:
        """Return one history page without changing any printer or server state."""
        query = urllib.parse.urlencode({"start": start, "limit": limit,
                                       "order": "asc", "before": before})
        request = urllib.request.Request(self.base_url + "/server/history/list?" + query,
            headers={"Accept": "application/json", "Cache-Control": "no-cache"}, method="GET")
        with self.opener.open(request, timeout=self.timeout) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError("History response exceeded the size limit.")
        def reject_constant(value: str) -> None:
            raise ValueError("Non-finite JSON number rejected.")
        envelope = json.loads(body.decode("utf-8"), parse_constant=reject_constant)
        if not isinstance(envelope, dict) or not isinstance(envelope.get("result"), dict):
            raise ValueError("The server did not return a Moonraker result object.")
        return envelope["result"]


def export_history(fetch_page: Callable[[int, int, float], Dict[str, Any]],
                   page_size: int = 100, max_seconds: float = 60.0) -> Dict[str, Any]:
    """Page until an empty response, preserving partial results on any failure.

    Never assume that `count` is the total or that a short page is the last one.
    Detect duplicate IDs and report an unstable listing rather than silently
    claiming a complete export. This is not a transactional database snapshot.
    """
    if type(page_size) is not int or not 1 <= page_size <= 1000:
        raise ValueError("page_size must be an integer between 1 and 1000.")
    if type(max_seconds) not in (int, float) or not math.isfinite(max_seconds) or max_seconds <= 0:
        raise ValueError("max_seconds must be positive and finite.")
    cutoff = time.time()
    deadline = time.monotonic() + max_seconds
    record: Dict[str, Any] = {
        "schema": "klipperlearn-history-export-v1", "captured_before_unix": cutoff,
        "pagination_finished": False, "transactional_snapshot": False,
        "jobs": [], "warnings": [], "pages_read": 0,
        "quality_assessed": False,
        "note": "A completed print job is not a verified quality result. No photos or sensor waveforms are included.",
        "privacy": "User names, arbitrary metadata and thumbnail paths are intentionally omitted.",
    }
    seen = set()
    start = 0
    try:
        for _ in range(1000):
            if time.monotonic() > deadline:
                raise TimeoutError("Export time budget reached.")
            page = fetch_page(start, page_size, cutoff)
            if not isinstance(page, dict):
                raise ValueError("History page must be an object.")
            jobs = page.get("jobs")
            if not isinstance(jobs, list):
                raise ValueError("History jobs is not a list.")
            record["pages_read"] += 1
            if not jobs:
                record["pagination_finished"] = True
                break
            for job in jobs:
                if not isinstance(job, dict) or not isinstance(job.get("job_id"), str):
                    raise ValueError("A job entry has no valid job_id.")
                key = job["job_id"]
                if not key or len(key) > 128:
                    raise ValueError("Invalid job identifier length.")
                if key in seen:
                    raise ValueError("Duplicate job ID: listing changed or pagination is unsupported.")
                clean = {}
                for name in SAFE_JOB_FIELDS:
                    if name not in job:
                        continue
                    value = job[name]
                    if name in {"job_id", "filename", "status"}:
                        if not isinstance(value, str) or len(value) > 1024:
                            raise ValueError("Invalid history text field.")
                    elif name == "exists":
                        if not isinstance(value, bool):
                            raise ValueError("Invalid history boolean field.")
                    elif value is not None:
                        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                            raise ValueError("Invalid history numeric field.")
                    clean[name] = value
                seen.add(key)
                record["jobs"].append(clean)
            start += len(jobs)
        else:
            raise ValueError("Maximum history page count reached.")
    except urllib.error.HTTPError as error:
        code = error.code
        explanation = ("Authorization is required. No authentication bypass was attempted."
                       if code in {401, 403} else "The local history endpoint returned an HTTP error.")
        record["warnings"].append("HTTP %s. %s" % (code, explanation))
    except (OSError, ValueError, OverflowError, RecursionError, urllib.error.URLError) as error:
        # Keep remote bodies and arbitrary exception strings out of the export.
        record["warnings"].append("History retrieval stopped: " + type(error).__name__ +
                                  ". Check local connectivity and the history component.")
    record["exported_job_count"] = len(record["jobs"])
    return record


def create_package(root: Path, output_dir: Path, base_url: str, offline: bool = False) -> Path:
    """Write a new review ZIP; do not modify the workspace or publish anything."""
    output_dir.mkdir(parents=True, exist_ok=True)
    # The default destination is outside the source workspace.
    entries, source_report = collect_sources(root)
    if offline:
        history = {"pagination_finished": False, "jobs": [], "exported_job_count": 0,
                   "warnings": ["Offline mode selected; no network requests were made."]}
    else:
        reader = HistoryReader(base_url)
        history = export_history(reader.page)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    path = output_dir / ("KlipperLearn-handoff-" + stamp + "-" + uuid.uuid4().hex[:6] + ".zip")
    manifest = {
        "schema": "klipperlearn-workspace-export-v1", "created_utc": stamp,
        "source_report": source_report,
        "history_report": {key: value for key, value in history.items() if key != "jobs"},
        "public_release_ready": False,
        "publication_warning": "Review locally before sharing. Do not publish this entire archive to GitHub.",
        "not_collected": ["private keys", "token files", "environment files", "git history",
            "work directory", "data directory", "photos", "audio", "sensor waveforms", "binary assets"],
    }
    temporary = path.with_suffix(".partial")
    try:
        with zipfile.ZipFile(temporary, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, payload in entries:
                archive.writestr(name, payload)
            archive.writestr("EXPORT_MANIFEST.json", json_bytes(manifest))
            archive.writestr("evidence-private/moonraker-history.json", json_bytes(history))
            archive.writestr("READ_BEFORE_SHARING.txt", (
                "LOCAL REVIEW PACKAGE - NOT A PUBLIC RELEASE\n\n"
                "source/ contains selected source files in their original byte form.\n"
                "EXPORT_MANIFEST.json records exclusions and possible credentials.\n"
                "evidence-private/ contains printing history, including model file names.\n"
                "Inspect all included content before sharing. Pattern screening is not a guarantee.\n"
                "Do not publish personal evidence or third-party assets without reviewing permissions.\n"
                "A completed job is NOT proof of dimensional or visual quality.\n"
                "This archive does not contain all workspace files; omissions are intentional.\n"
                "No source files, printer settings or original experiment records were changed.\n"
            ))
        temporary.replace(path)
    except Exception:
        # Clean up only this run's incomplete output, never the source files.
        temporary.unlink(missing_ok=True)
        raise
    print("Source files included:", len(entries))
    print("Source entries omitted:", len(source_report["omitted"]))
    print("History jobs exported:", history["exported_job_count"])
    print("History pagination finished:", history["pagination_finished"])
    if source_report.get("error"):
        print("SOURCE WARNING:", source_report["error"])
    for warning in history.get("warnings", []):
        print("HISTORY WARNING:", warning)
    print("\nReview this ZIP locally before uploading it to the conversation:\n", path)
    return path


def main(argv: Optional[List[str]] = None) -> int:
    """Run a bounded, local-only export using an explicitly selected workspace."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--moonraker-url", default=DEFAULT_URL)
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--offline", action="store_true", help="Copy selected source files without reading history.")
    args = parser.parse_args(argv)
    try:
        create_package(args.root, args.output_dir, args.moonraker_url, args.offline)
        return 0
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        print("Export failed:", type(error).__name__, "- check paths, permissions and disk space.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
