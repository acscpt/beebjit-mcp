# SPDX-FileCopyrightText: 2026 Heisenberg (acscpt)
# SPDX-License-Identifier: MIT

"""End-to-end test for the `run_until_prompt` MCP tool."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _buildParams(beebjitBinary: Path) -> StdioServerParameters:
    env = dict(os.environ)
    env["BEEBJIT"] = str(beebjitBinary)
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "beebjit_mcp.server"],
        env=env,
    )


async def _runUntilPrompt(params: StdioServerParameters) -> dict[str, object]:
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            create = await session.call_tool("create_machine", {})
            sessionId = json.loads(create.content[0].text)["session_id"]
            try:
                result = await session.call_tool(
                    "run_until_prompt",
                    {
                        "session_id": sessionId,
                        "max_cycles": 20_000_000,
                    },
                )
                return json.loads(result.content[0].text)
            finally:
                await session.call_tool(
                    "destroy_machine", {"session_id": sessionId}
                )


def testRunUntilPromptHitsBasicPrompt(beebjitBinary: Path) -> None:
    params = _buildParams(beebjitBinary)
    result = asyncio.run(_runUntilPrompt(params))

    # A cold-boot run must reach the BASIC `>` prompt well under
    # the 20M cycle budget.
    assert result["found"] is True
    assert result["prompt"] == ">"
    assert result["cycles_ran"] > 0
