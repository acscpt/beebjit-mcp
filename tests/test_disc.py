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


async def _loadDiscRoundTrip(
    params: StdioServerParameters, discPath: Path
) -> dict[str, object]:
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            create = await session.call_tool("create_machine", {})
            sessionId = json.loads(create.content[0].text)["session_id"]
            try:
                reply = await session.call_tool(
                    "load_disc",
                    {"session_id": sessionId, "disc": str(discPath)},
                )
                return json.loads(reply.content[0].text)
            finally:
                await session.call_tool(
                    "destroy_machine", {"session_id": sessionId}
                )


async def _loadDiscMissingFile(
    params: StdioServerParameters,
) -> object:
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            create = await session.call_tool("create_machine", {})
            sessionId = json.loads(create.content[0].text)["session_id"]
            try:
                return await session.call_tool(
                    "load_disc",
                    {
                        "session_id": sessionId,
                        "disc": "/no/such/path/missing.ssd",
                    },
                )
            finally:
                await session.call_tool(
                    "destroy_machine", {"session_id": sessionId}
                )


async def _bootDiscCyclesWrap(
    params: StdioServerParameters, discPath: Path
) -> tuple[int, int, dict[str, object]]:
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            create = await session.call_tool("create_machine", {})
            sessionId = json.loads(create.content[0].text)["session_id"]
            try:
                await session.call_tool(
                    "run_for_cycles",
                    {"session_id": sessionId, "cycles": 15_000_000},
                )
                regsBefore = await session.call_tool(
                    "read_registers", {"session_id": sessionId}
                )
                cyclesBefore = int(
                    json.loads(regsBefore.content[0].text)["cycles"]
                )

                reply = await session.call_tool(
                    "boot_disc",
                    {"session_id": sessionId, "disc": str(discPath)},
                )

                regsAfter = await session.call_tool(
                    "read_registers", {"session_id": sessionId}
                )
                cyclesAfter = int(
                    json.loads(regsAfter.content[0].text)["cycles"]
                )
                return (
                    cyclesBefore,
                    cyclesAfter,
                    json.loads(reply.content[0].text),
                )
            finally:
                await session.call_tool(
                    "destroy_machine", {"session_id": sessionId}
                )


async def _createMachineWithDisc(
    params: StdioServerParameters, discPath: Path
) -> str:
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            create = await session.call_tool(
                "create_machine",
                {"disc": str(discPath)},
            )
            sessionId = json.loads(create.content[0].text)["session_id"]
            try:
                screen = await session.call_tool(
                    "read_mode7_text", {"session_id": sessionId}
                )
                return json.loads(screen.content[0].text)["text"]
            finally:
                await session.call_tool(
                    "destroy_machine", {"session_id": sessionId}
                )


def testLoadDiscRoundTripViaMcp(
    beebjitBinary: Path, tmp_path: Path
) -> None:
    discPath = tmp_path / "blank.ssd"
    discPath.touch()
    payload = asyncio.run(
        _loadDiscRoundTrip(_buildParams(beebjitBinary), discPath)
    )
    assert payload == {
        "ok": True,
        "drive": 0,
        "disc": str(discPath),
        "writeable": False,
        "mutable": False,
    }


def testLoadDiscMissingFileErrors(beebjitBinary: Path) -> None:
    result = asyncio.run(_loadDiscMissingFile(_buildParams(beebjitBinary)))
    assert result.isError is True


def testBootDiscWrapsCycleCounterViaMcp(
    beebjitBinary: Path, tmp_path: Path
) -> None:
    # An empty SSD is enough to exercise the load + autoboot path:
    # the BBC's DFS will reject the missing catalogue, but the SHIFT+
    # BREAK reset itself wraps the cycle counter and reprints the
    # banner regardless of what !BOOT does (or fails to do).
    discPath = tmp_path / "blank.ssd"
    discPath.touch()
    cyclesBefore, cyclesAfter, reply = asyncio.run(
        _bootDiscCyclesWrap(_buildParams(beebjitBinary), discPath)
    )
    assert cyclesBefore > 15_000_000, cyclesBefore
    assert cyclesAfter < cyclesBefore, (cyclesBefore, cyclesAfter)
    assert reply["ok"] is True
    assert reply["drive"] == 0
    assert reply["disc"] == str(discPath)


def testCreateMachineWithDiscShowsBannerViaMcp(
    beebjitBinary: Path, tmp_path: Path
) -> None:
    # create_machine(disc=...) now does runtime mount + autoboot
    # rather than passing -0 -autoboot at argv time. The boot banner
    # should still be visible in MODE 7 once create_machine returns.
    discPath = tmp_path / "blank.ssd"
    discPath.touch()
    text = asyncio.run(
        _createMachineWithDisc(_buildParams(beebjitBinary), discPath)
    )
    assert "BBC Computer" in text, text
