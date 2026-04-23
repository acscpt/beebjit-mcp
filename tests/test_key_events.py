# SPDX-FileCopyrightText: 2026 Heisenberg (acscpt)
# SPDX-License-Identifier: MIT

"""End-to-end tests for `key_down`, `key_up`, and `write_memory`.

Exercises the low-level composable tools: manual key press/release
with explicit cycle advance in between, plus a memory round trip
through the MCP layer rather than the driver directly.
"""

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


async def _runKeyEventsRoundTrip(
    params: StdioServerParameters,
) -> dict[str, object]:
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            create = await session.call_tool("create_machine", {})
            sessionId = json.loads(create.content[0].text)["session_id"]

            try:
                # Memory round trip over MCP: pick an unused area of
                # low memory. `&7100` sits in screen-adjacent RAM but
                # outside any mode's active framebuffer at boot.
                await session.call_tool(
                    "write_memory",
                    {
                        "session_id": sessionId,
                        "addr": 0x7100,
                        "data": "DE AD BE EF",
                    },
                )
                readBack = await session.call_tool(
                    "read_memory",
                    {
                        "session_id": sessionId,
                        "addr": 0x7100,
                        "length": 4,
                    },
                )
                readPayload = json.loads(readBack.content[0].text)

                # Let the emulator boot so we have a BASIC prompt.
                await session.call_tool(
                    "run_for_cycles",
                    {"session_id": sessionId, "cycles": BOOT_CYCLES},
                )

                # Manual tap of 'A' via key_down / run_for_cycles /
                # key_up, with the symbolic form for key_down and the
                # single-char form for key_up. This exercises both
                # input shapes accepted by the resolver.
                await session.call_tool(
                    "key_down",
                    {"session_id": sessionId, "key": "A"},
                )
                await session.call_tool(
                    "run_for_cycles",
                    {"session_id": sessionId, "cycles": 5_000_000},
                )
                await session.call_tool(
                    "key_up",
                    {"session_id": sessionId, "key": ord("A")},
                )
                await session.call_tool(
                    "run_for_cycles",
                    {"session_id": sessionId, "cycles": 5_000_000},
                )

                screen = await session.call_tool(
                    "read_mode7_text",
                    {"session_id": sessionId},
                )
                screenText = json.loads(screen.content[0].text)["text"]

                return {
                    "read_payload": readPayload,
                    "screen": screenText,
                }

            finally:
                await session.call_tool(
                    "destroy_machine", {"session_id": sessionId}
                )


def testWriteMemoryAndKeyEventsViaMcp(beebjitBinary: Path) -> None:
    params = _buildParams(beebjitBinary)
    result = asyncio.run(_runKeyEventsRoundTrip(params))

    # write_memory accepts space-separated hex and the bytes round
    # trip through read_memory unchanged.
    readPayload = result["read_payload"]
    assert readPayload["hex"].lower() == "deadbeef"

    # Manual key_down/key_up produced 'A' on the prompt row. CAPS
    # LOCK is on by default so uppercase lands even without SHIFT.
    screen: str = result["screen"]
    assert ">A" in screen, f"'>A' missing from screen:\n{screen}"
