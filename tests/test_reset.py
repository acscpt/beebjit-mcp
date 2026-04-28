# SPDX-FileCopyrightText: 2026 Heisenberg (acscpt)
# SPDX-License-Identifier: MIT

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


async def _resetRoundTrip(
    params: StdioServerParameters,
) -> tuple[int, int, dict[str, object]]:
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            create = await session.call_tool("create_machine", {})
            sessionId = json.loads(create.content[0].text)["session_id"]

            await session.call_tool(
                "run_for_cycles",
                {"session_id": sessionId, "cycles": 5_000_000},
            )
            await session.call_tool(
                "type_input",
                {"session_id": sessionId, "text": "LET A=42\n"},
            )
            await session.call_tool(
                "run_for_cycles",
                {"session_id": sessionId, "cycles": 2_000_000},
            )

            regsBefore = await session.call_tool(
                "read_registers", {"session_id": sessionId}
            )
            cyclesBefore = int(
                json.loads(regsBefore.content[0].text)["cycles"]
            )

            resetReply = await session.call_tool(
                "reset", {"session_id": sessionId}
            )

            regsAfter = await session.call_tool(
                "read_registers", {"session_id": sessionId}
            )
            cyclesAfter = int(
                json.loads(regsAfter.content[0].text)["cycles"]
            )

            await session.call_tool(
                "destroy_machine", {"session_id": sessionId}
            )
            return (
                cyclesBefore,
                cyclesAfter,
                json.loads(resetReply.content[0].text),
            )


async def _resetUnknownSession(
    params: StdioServerParameters,
) -> object:
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await session.call_tool(
                "reset",
                {"session_id": "00000000-0000-0000-0000-000000000000"},
            )


def testResetWrapsCycleCounterViaMcp(beebjitBinary: Path) -> None:
    cyclesBefore, cyclesAfter, reply = asyncio.run(
        _resetRoundTrip(_buildParams(beebjitBinary))
    )
    assert cyclesBefore > 5_000_000, cyclesBefore
    assert cyclesAfter < cyclesBefore, (cyclesBefore, cyclesAfter)
    assert reply == {"ok": True}, reply


def testResetUnknownSessionErrors(beebjitBinary: Path) -> None:
    result = asyncio.run(_resetUnknownSession(_buildParams(beebjitBinary)))
    assert result.isError is True
