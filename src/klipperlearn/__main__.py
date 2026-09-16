from __future__ import annotations

import argparse
import ipaddress
import json
from pathlib import Path
import secrets

from .atlas import build_atlas_plan
from .config import load_settings
from .dataset import audit_session, write_training_manifest
from .domain import DEFECT_KEYS, Finding
from .mobile import audit_mobile_export_file
from .observer import Observer
from .optimizer import propose_profiles
from .quality import missing_metrics, quality_score
from .storage import SessionStore, read_findings, session_summary


def _is_loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="KlipperLearn safe observation tools")
    subcommands = parser.add_subparsers(dest="command", required=True)
    backup = subcommands.add_parser(
        "export-evidence", help="Create a private portable SQLite, sensor and photo archive"
    )
    backup.add_argument("--root", default="data/experiments")
    backup.add_argument("--output", required=True)

    observe = subcommands.add_parser(
        "observe", help="Collect Moonraker telemetry and webcam frames"
    )
    observe.add_argument("--config", required=True)
    observe.add_argument("--duration", type=float, default=300)
    observe.add_argument("--session-root", default="data/sessions")

    atlas = subcommands.add_parser(
        "atlas", help="Create a Calibration Atlas plan without controlling a printer"
    )
    atlas.add_argument("--config", required=True)
    atlas.add_argument("--output", required=True)

    review = subcommands.add_parser(
        "review", help="Store transparent human quality labels for one session"
    )
    review.add_argument("--session", required=True)
    review.add_argument("--notes", default="")
    review.add_argument("--confidence", type=float, default=0.8)
    review.add_argument(
        "--complete",
        action="store_true",
        help="Explicitly record every omitted defect as reviewed and absent (severity 0)",
    )
    for metric in DEFECT_KEYS:
        review.add_argument(f"--{metric.replace('_', '-')}", type=float, default=None)

    report = subcommands.add_parser("report", help="Print an offline summary of one session")
    report.add_argument("--session", required=True)

    recommend = subcommands.add_parser(
        "recommend", help="Create offline profiles from reviewed evidence"
    )
    recommend.add_argument("--session", required=True)
    recommend.add_argument("--output", required=True)

    train_plan = subcommands.add_parser(
        "train-plan", help="Create a training manifest; does not download or train"
    )
    train_plan.add_argument("--session", action="append", required=True)
    train_plan.add_argument(
        "--validation-session",
        action="append",
        default=[],
        help="Independent reviewed session reserved for validation (repeatable)",
    )
    train_plan.add_argument("--output", required=True)

    dataset_audit = subcommands.add_parser(
        "dataset-audit", help="Verify frame hashes, labels, and provenance without changing data"
    )
    dataset_audit.add_argument("--session", action="append", required=True)

    mobile_audit = subcommands.add_parser(
        "mobile-audit", help="Validate a privacy-preserving phone sensor export without changing it"
    )
    mobile_audit.add_argument("--input", required=True)

    token_parser = subcommands.add_parser(
        "lan-token", help="Generate a high-entropy token for the local mobile receiver"
    )
    token_parser.add_argument(
        "--output", help="Create a new private token file without displaying its contents"
    )

    train = subcommands.add_parser(
        "train", help="Fine-tune the optional local CNN from an explicit manifest"
    )
    train.add_argument("--manifest", required=True)
    train.add_argument("--output", required=True)
    train.add_argument("--epochs", type=int, default=5)
    train.add_argument(
        "--pretrained",
        action="store_true",
        required=True,
        help="Required consent to use or fetch torchvision base weights for transfer learning",
    )

    serve = subcommands.add_parser("serve", help="Run the optional local evidence dashboard")
    serve.add_argument("--session-root", default="data/sessions")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--mobile-inbox", default="data/mobile-inbox")
    serve.add_argument(
        "--experiments-root",
        default="data/experiments",
        help="Private experiment storage directory",
    )
    serve.add_argument("--mobile-token", default=None)
    serve.add_argument(
        "--mobile-token-file", default=None, help="Read the local token from a private file"
    )
    serve.add_argument(
        "--local-connect-origin",
        default=None,
        help="Opt in to one-click access from this exact HTTPS origin",
    )
    serve.add_argument(
        "--local-connect-network",
        action="append",
        default=[],
        help="Explicit trusted LAN CIDR; repeatable",
    )
    serve.add_argument("--tls-certfile", default=None)
    serve.add_argument("--tls-keyfile", default=None)
    serve.add_argument(
        "--moonraker",
        default=None,
        help="Explicit Moonraker URL; enables the authenticated companion",
    )
    serve.add_argument(
        "--learning",
        action="store_true",
        help="Record print evidence and train the local multimodal estimator",
    )
    serve.add_argument(
        "--automatic-print",
        action="store_true",
        help="Enable bounded experiments for prints requested from KlipperLearn",
    )

    arguments = parser.parse_args(argv)
    if arguments.command == "export-evidence":
        from .evidence_backup import export_evidence

        print(json.dumps(export_evidence(arguments.root, arguments.output)))
    elif arguments.command == "observe":
        settings = load_settings(arguments.config)
        session = Observer(settings, Path(arguments.session_root)).run(arguments.duration)
        print(f"Observation session saved to {session}")
    elif arguments.command == "atlas":
        settings = load_settings(arguments.config)
        output = Path(arguments.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(build_atlas_plan(settings), indent=2), encoding="utf-8")
        print(f"Atlas plan saved to {output}")
    elif arguments.command == "review":
        session = Path(arguments.session)
        store = SessionStore(session / "telemetry.sqlite3")
        with store.open() as database:
            count = 0
            for metric in DEFECT_KEYS:
                value = getattr(arguments, metric)
                if value is not None or arguments.complete:
                    severity = 0.0 if value is None else value
                    store.finding(
                        database,
                        Finding(metric, severity, arguments.confidence, "human", arguments.notes),
                    )
                    count += 1
        print(f"Stored {count} human labels in {session}")
    elif arguments.command == "report":
        session = Path(arguments.session)
        findings = read_findings(session)
        human_findings = [item for item in findings if item.source == "human"]
        missing = missing_metrics(human_findings)
        payload = session_summary(session)
        payload["quality_score"] = (
            quality_score(human_findings) if human_findings and not missing else None
        )
        payload["finding_count"] = len(findings)
        payload["human_finding_count"] = len(human_findings)
        payload["review_complete"] = not missing
        payload["missing_metrics"] = missing
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    elif arguments.command == "recommend":
        findings = [item for item in read_findings(arguments.session) if item.source == "human"]
        if not findings:
            raise SystemExit(
                "No reviewed findings. Run 'review' first; recommendations must have evidence."
            )
        missing = missing_metrics(findings)
        if missing:
            raise SystemExit(
                "Recommendation requires a complete human review. Missing: " + ", ".join(missing)
            )
        output = Path(arguments.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(propose_profiles(findings), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"Offline recommendation saved to {output}; it has not been applied to the printer.")
    elif arguments.command == "train-plan":
        manifest = write_training_manifest(
            arguments.output, arguments.session, arguments.validation_session
        )
        eligible = sum(item["eligible_for_training"] for item in manifest["sessions"])
        print(
            f"Training manifest saved to {arguments.output}; {eligible}/{len(manifest['sessions'])} "
            "sessions are eligible and no training was run."
        )
    elif arguments.command == "dataset-audit":
        result = {
            "schema_version": 1,
            "mode": "read_only",
            "sessions": [audit_session(item) for item in arguments.session],
        }
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif arguments.command == "mobile-audit":
        print(json.dumps(audit_mobile_export_file(arguments.input), indent=2, ensure_ascii=False))
    elif arguments.command == "lan-token":
        token = secrets.token_urlsafe(32)
        if arguments.output:
            import os

            destination = Path(arguments.output).expanduser()
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                raise SystemExit(
                    "Token destination already exists; it was left unchanged."
                ) from None
            with os.fdopen(descriptor, "w", encoding="ascii") as handle:
                handle.write(token + "\n")
            print("A new token file was created; its contents are not displayed.")
        else:
            print(token)
    elif arguments.command == "train":
        from .training import train_multilabel

        result = train_multilabel(
            arguments.manifest, arguments.output, arguments.epochs, arguments.pretrained
        )
        print(json.dumps(result, indent=2))
    else:
        try:
            import uvicorn
        except ImportError as exc:
            raise SystemExit("Dashboard requires: pip install -e '.[dashboard]'") from exc
        from .webapp import create_app

        if (arguments.learning or arguments.automatic_print) and not arguments.moonraker:
            raise SystemExit(
                "Learning and automatic trials require an explicit --moonraker server."
            )
        if arguments.mobile_token_file:
            if arguments.mobile_token:
                raise SystemExit("Choose --mobile-token or --mobile-token-file, not both.")
            arguments.mobile_token = (
                Path(arguments.mobile_token_file).read_text(encoding="utf-8").strip()
            )
        if bool(arguments.local_connect_origin) != bool(arguments.local_connect_network):
            raise SystemExit(
                "One-click access requires both an exact origin and explicit trusted LAN networks."
            )
        if arguments.local_connect_origin:
            import ipaddress
            from urllib.parse import urlsplit

            origin = urlsplit(arguments.local_connect_origin)
            if (
                origin.scheme != "https"
                or origin.hostname != arguments.host
                or (origin.port or 443) != arguments.port
                or origin.username
                or origin.password
                or origin.path
                or origin.query
                or origin.fragment
                or not arguments.moonraker
            ):
                raise SystemExit(
                    "One-click origin must exactly match this HTTPS listener and requires Moonraker."
                )
            for value in arguments.local_connect_network:
                network = ipaddress.ip_network(value)
                if not network.is_private or network.is_loopback or network.prefixlen == 0:
                    raise SystemExit("One-click networks must be explicit private LAN ranges.")
        lan_host = not _is_loopback_host(arguments.host)
        if bool(arguments.tls_certfile) != bool(arguments.tls_keyfile):
            raise SystemExit("Use both --tls-certfile and --tls-keyfile, or neither.")
        if lan_host and not arguments.mobile_token:
            raise SystemExit(
                "A LAN listener requires --mobile-token. Create one with 'klipperlearn lan-token'."
            )
        if lan_host and not arguments.tls_certfile:
            raise SystemExit(
                "A LAN listener requires a trusted HTTPS certificate and key for phone sensors."
            )
        if arguments.host in {"0.0.0.0", "::"}:
            raise SystemExit(
                "Bind the LAN listener to its explicit private IP, not a wildcard address."
            )
        if arguments.mobile_token and len(arguments.mobile_token) < 16:
            raise SystemExit("--mobile-token must contain at least 16 characters.")
        if arguments.tls_certfile and not Path(arguments.tls_certfile).is_file():
            raise SystemExit("TLS certificate file was not found.")
        if arguments.tls_keyfile and not Path(arguments.tls_keyfile).is_file():
            raise SystemExit("TLS key file was not found.")
        app = create_app(arguments.session_root, arguments.mobile_inbox, arguments.mobile_token)
        if arguments.moonraker:
            from urllib.parse import urlsplit

            target = urlsplit(arguments.moonraker)
            if (
                target.scheme not in {"http", "https"}
                or not target.hostname
                or target.username
                or target.password
                or target.query
                or target.fragment
                or target.path not in {"", "/"}
            ):
                raise SystemExit(
                    "--moonraker requires an HTTP(S) server URL without credentials, path or query."
                )
            if not arguments.mobile_token:
                raise SystemExit("The companion requires --mobile-token.")
            from .companion import install_companion

            install_companion(
                app,
                arguments.mobile_token,
                arguments.moonraker.rstrip("/"),
                camera_cache_path=Path(arguments.session_root).parent / "camera-last.jpg",
                experiments_root=arguments.experiments_root,
                enable_learning=arguments.learning or arguments.automatic_print,
                enable_automatic_print=arguments.automatic_print,
                local_connect_origin=arguments.local_connect_origin,
                local_connect_networks=arguments.local_connect_network,
            )
        uvicorn.run(
            app,
            host=arguments.host,
            port=arguments.port,
            ssl_certfile=arguments.tls_certfile,
            ssl_keyfile=arguments.tls_keyfile,
            proxy_headers=False,
        )


if __name__ == "__main__":
    main()
