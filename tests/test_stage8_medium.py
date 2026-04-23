# SPDX-FileCopyrightText: 2026 Heisenberg (acscpt)
# SPDX-License-Identifier: MIT

"""End-to-end tests for Stage 8 medium tools.

Covers `disassemble`, `run_until_prompt`, and `run_basic` through
the MCP stack. Each test runs one full round trip against a real
beebjit session so there is no mock-reality drift.
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


async def _runDisassemble(params: StdioServerParameters) -> dict[str, object]:
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
                    "disassemble",
                    {
                        "session_id": sessionId,
                        "addr": 0xE000,
                        "count": 3,
                    },
                )
                return json.loads(result.content[0].text)
            finally:
                await session.call_tool(
                    "destroy_machine", {"session_id": sessionId}
                )


def testDisassembleMosEntryViaMcp(beebjitBinary: Path) -> None:
    params = _buildParams(beebjitBinary)
    result = asyncio.run(_runDisassemble(params))

    instructions = result["instructions"]
    assert len(instructions) == 3
    assert instructions[0]["addr"] == 0xE000
    assert "JSR" in instructions[0]["text"]


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
                        "program": '10 PRINT "STAGE8"\n',
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
    # PRINT output must land on screen. `STAGE8` is a deliberate
    # choice to avoid collision with any boot banner text.
    assert "STAGE8" in text, f"STAGE8 missing from screen:\n{text}"
    # And the typed PRINT line itself should be visible so we catch
    # silent-typing regressions.
    assert "PRINT" in text, f"PRINT line missing from screen:\n{text}"
