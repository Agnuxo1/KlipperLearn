"""Optional read-only MCP server for the same file-first optimizer functions.

The SDK is an optional dependency. No API key, model inference or printer-control
connection is created here. HTTP binds only to loopback; use an authenticated
private transport such as Secure MCP Tunnel, never expose this listener publicly.
"""

from __future__ import annotations

import argparse
import os
from typing import Any

from .printer_discovery import discover_printers
from .slicer_optimizer import (
    PARAMETERS,
    advisor_request,
    build_profiles,
    review_session,
    validate_proposal,
)


def create_server(allowed_networks=()):
    """Build the official SDK server; no files, sockets or printer calls at creation."""
    try:
        from mcp.server.fastmcp import FastMCP
        from mcp.types import ToolAnnotations
    except ImportError as exc:
        raise RuntimeError(
            "Install the optional mcp extra, or use the dependency-free skills/file workflow."
        ) from exc

    server = FastMCP(
        "KlipperLearn Printer Optimizer",
        host="127.0.0.1",
        port=8791,
        stateless_http=True,
        json_response=True,
        instructions="Use original supplied profiles and reviewed, comparable trials. Photograph hashes are not photographs. Never invent evidence. These tools only return data and profile artifacts; they cannot control a printer.",
    )
    local = ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
    )

    @server.tool(annotations=local, structured_output=True)
    def optimizer_contract() -> dict[str, Any]:
        """Read supported settings and workflow before preparing printer optimization inputs."""
        return {
            "session_schema": "klipperlearn.slicer-session/v1",
            "modes": ["Quality", "Standard", "Speed"],
            "parameters": {
                k: {"absolute_min": v[0], "absolute_max": v[1], "unit": v[2]}
                for k, v in PARAMETERS.items()
            },
            "limits_note": "These are software rejection ceilings, not recommended or manufacturer-approved settings. Supply lower machine/material-specific bounds.",
            "requires": [
                "original exported Orca process and filament presets",
                "explicit printer identity and nozzle/material",
                "unchanged baseline",
                "same model hash, layers and other geometry settings",
                "at least two independent complete reviewed prints per accepted configuration",
            ],
            "image_review": "The selected ChatGPT model reviews original images supplied in the conversation. No image is fetched or sent by these tools.",
            "printer_commands": False,
            "universal_native_slicer_support": False,
        }

    @server.tool(annotations=local, structured_output=True)
    def review_printer_trials(session: dict) -> dict[str, Any]:
        """Review supplied trial records and select evidence-supported modes; never invent absent data."""
        return review_session(session)

    @server.tool(annotations=local, structured_output=True)
    def prepare_ai_review(session: dict) -> dict[str, Any]:
        """Return an allowlisted numerical review request without original private scripts."""
        return advisor_request(session)

    @server.tool(annotations=local, structured_output=True)
    def check_ai_proposal(session: dict, proposal: dict) -> dict[str, Any]:
        """Validate one bounded model suggestion against the exact session; it remains unprinted."""
        return validate_proposal(session, proposal)

    @server.tool(annotations=local, structured_output=True)
    def build_slicer_profiles(session: dict) -> dict[str, Any]:
        """Return six Orca JSON preset artifacts for three modes. Does not install profiles or change files."""
        return build_profiles(session)

    if allowed_networks:

        @server.tool(
            annotations=ToolAnnotations(
                readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True
            )
        )
        async def discover_network_printers(cidr: str, confirmed: bool) -> dict[str, Any]:
            """Probe approved LAN API endpoints only after explicit user consent. Never scan Wi-Fi credentials or print."""
            return await discover_printers(cidr, tuple(allowed_networks), confirmed)

    return server


def main() -> None:
    """Default to local stdio; HTTP is loopback-only and has no public auth bypass."""
    parser = argparse.ArgumentParser(
        description="Run the optional KlipperLearn optimizer MCP server"
    )
    parser.add_argument("--transport", choices=("stdio", "streamable-http"), default="stdio")
    args = parser.parse_args()
    networks = tuple(
        v.strip()
        for v in os.environ.get("KLIPPERLEARN_DISCOVERY_NETWORKS", "").split(",")
        if v.strip()
    )
    create_server(networks).run(transport=args.transport)


if __name__ == "__main__":
    main()
