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


_INJECTED_ROW: bytes = b"A\x00B\x80C\x1F" + b" " * 34
_INJECT_ADDR: int = 0x7C00


async def _readScreenAllControlsModes(
    params: StdioServerParameters, settleCycles: int
) -> dict[str, dict[str, object]]:
    """Inject a known mixed-bytes row, capture under each controls mode.

    Cold-boot BBC BASIC fills the screen with pure-ASCII text, so
    differentiating SPACE/QUESTION/ESCAPE off the natural screen
    is impossible. We poke a known mix of printable and control
    bytes at the start of the MODE 7 page first, then read it back
    three ways. The screen-start pointer at `&0350/&0351` still
    points at `&7C00` at this stage of boot (no scroll yet), so the
    injected bytes land on row 0 of the decoded output.
    """

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            create = await session.call_tool("create_machine", {})
            sessionId = json.loads(create.content[0].text)["session_id"]
            await session.call_tool(
                "run_for_cycles",
                {"session_id": sessionId, "cycles": settleCycles},
            )

            await session.call_tool(
                "write_memory",
                {
                    "session_id": sessionId,
                    "addr": _INJECT_ADDR,
                    "data": _INJECTED_ROW.hex(),
                },
            )

            results: dict[str, dict[str, object]] = {}
            for mode in ("space", "question", "escape"):
                resp = await session.call_tool(
                    "read_mode7_text",
                    {"session_id": sessionId, "controls": mode},
                )
                results[mode] = json.loads(resp.content[0].text)

            await session.call_tool(
                "destroy_machine", {"session_id": sessionId}
            )
            return results


async def _readScreenInvalidControls(
    params: StdioServerParameters, settleCycles: int
) -> object:
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            create = await session.call_tool("create_machine", {})
            sessionId = json.loads(create.content[0].text)["session_id"]
            await session.call_tool(
                "run_for_cycles",
                {"session_id": sessionId, "cycles": settleCycles},
            )
            result = await session.call_tool(
                "read_mode7_text",
                {"session_id": sessionId, "controls": "bogus"},
            )
            await session.call_tool(
                "destroy_machine", {"session_id": sessionId}
            )
            return result


def testReadMode7TextControlsModesProduceExpectedShapes(
    beebjitBinary: Path,
) -> None:
    payloads = asyncio.run(
        _readScreenAllControlsModes(_buildParams(beebjitBinary), 5_000_000)
    )

    spaceRows = payloads["space"]["rows"]
    questionRows = payloads["question"]["rows"]
    escapeRows = payloads["escape"]["rows"]

    assert len(spaceRows) == 25
    assert len(questionRows) == 25
    assert len(escapeRows) == 25

    # Width invariant: SPACE and QUESTION stay 40-wide on every row,
    # ESCAPE row 0 grows because the injected control bytes expand.
    assert all(len(r) == 40 for r in spaceRows)
    assert all(len(r) == 40 for r in questionRows)

    # Injected row was b"A\x00B\x80C\x1F" + 34 spaces. Each control
    # byte takes the substitute character per mode.
    assert spaceRows[0] == "A B C " + " " * 34
    assert questionRows[0] == "A?B?C?" + " " * 34
    assert escapeRows[0] == "A\\x00B\\x80C\\x1F" + " " * 34

    # ESCAPE row 0 is wider than 40 because three control bytes
    # expanded to four chars each (gain of 9 chars).
    assert len(escapeRows[0]) == 40 + 9


def testReadMode7TextRejectsUnknownControlsValue(beebjitBinary: Path) -> None:
    result = asyncio.run(
        _readScreenInvalidControls(_buildParams(beebjitBinary), 5_000_000)
    )
    # Pydantic validates the Literal at the MCP layer before our
    # code runs, so "bogus" surfaces as a tool-call error.
    assert result.isError is True
