# SPDX-FileCopyrightText: 2026 Heisenberg (acscpt)
# SPDX-License-Identifier: MIT

"""End-to-end test for the `run_basic` MCP tool."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


BOOT_CYCLES: int = 5_000_000


def _buildParams(beebjitBinary: Path) -> StdioServerParameters:
    env = dict(os.environ)
    env["BEEBJIT"] = str(beebjitBinary)
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "beebjit_mcp.server"],
        env=env,
    )


async def _runBasicProgram(params: StdioServerParameters) -> dict[str, object]:
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            create = await session.call_tool("create_machine", {})
            sessionId = json.loads(create.content[0].text)["session_id"]
            try:
                await session.call_tool(
                    "run_for_cycles",
                    {"session_id": sessionId, "cycles": BOOT_CYCLES},
                )
                result = await session.call_tool(
                    "run_basic",
                    {
                        "session_id": sessionId,
                        "program": '10 PRINT "HELLO"\n',
                    },
                )
                return json.loads(result.content[0].text)
            finally:
                await session.call_tool(
                    "destroy_machine", {"session_id": sessionId}
                )


def testRunBasicOneLineProgram(beebjitBinary: Path) -> None:
    params = _buildParams(beebjitBinary)
    result = asyncio.run(_runBasicProgram(params))

    text: str = result["text"]
    assert "HELLO" in text, f"HELLO missing from screen:\n{text}"
    assert "PRINT" in text, f"PRINT line missing from screen:\n{text}"
