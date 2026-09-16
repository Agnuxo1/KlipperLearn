"""Official SDK stdio round trip; no network or printer connection."""

import asyncio
import os
import sys

import pytest

pytest.importorskip("mcp")
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from test_slicer_optimizer import session_fixture


def test_official_mcp_handshake_tools_and_profile_response():
    async def exercise():
        env = dict(os.environ)
        env.pop("KLIPPERLEARN_DISCOVERY_NETWORKS", None)
        parameters = StdioServerParameters(
            command=sys.executable, args=["-m", "klipperlearn.optimizer_mcp"], env=env
        )
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                tools = (await client.list_tools()).tools
                assert len(tools) == 5
                assert all(t.annotations.readOnlyHint for t in tools)
                assert all(not t.annotations.destructiveHint for t in tools)
                assert all(not t.annotations.openWorldHint for t in tools)
                contract = await client.call_tool("optimizer_contract", {})
                assert not contract.isError and not contract.structuredContent["printer_commands"]
                result = await client.call_tool(
                    "build_slicer_profiles", {"session": session_fixture()}
                )
                assert not result.isError
                assert len(result.structuredContent["files"]) == 6
                invalid = await client.call_tool("review_printer_trials", {"session": {}})
                assert invalid.isError

    asyncio.run(exercise())
