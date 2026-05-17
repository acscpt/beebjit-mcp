# SPDX-FileCopyrightText: 2026 Heisenberg (acscpt)
# SPDX-License-Identifier: MIT

from __future__ import annotations

import asyncio
import base64
import json
import os
import struct
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


_PNG_SIGNATURE: bytes = b"\x89PNG\r\n\x1a\n"


def _buildParams(beebjitBinary: Path) -> StdioServerParameters:
    env = dict(os.environ)
    env["BEEBJIT"] = str(beebjitBinary)
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "beebjit_mcp.server"],
        env=env,
    )


def _readIhdrDims(png: bytes) -> tuple[int, int]:
    """Decode the IHDR width/height from a PNG bytes object."""

    assert png.startswith(_PNG_SIGNATURE), "missing PNG signature"
    # Length(4) + "IHDR"(4) sit immediately after the 8-byte sig;
    # IHDR data begins at offset 16 and starts with width, height
    # as two big-endian 32-bit ints.
    width, height = struct.unpack(">II", png[16:24])
    return width, height


def _parseScreenshot(result: object) -> bytes:
    """Decode the PNG bytes from a `screenshot` MCP response.

    The tool returns a single `image` content block carrying
    base64 PNG bytes.
    """
    return base64.b64decode(result.content[0].data)


async def _captureBootScreen(
    params: StdioServerParameters, settleCycles: int
) -> bytes:
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            create = await session.call_tool("create_machine", {})
            sessionId = json.loads(create.content[0].text)["session_id"]
            await session.call_tool(
                "run_for_cycles",
                {"session_id": sessionId, "cycles": settleCycles},
            )
            shot = await session.call_tool(
                "screenshot", {"session_id": sessionId}
            )
            await session.call_tool(
                "destroy_machine", {"session_id": sessionId}
            )
            return _parseScreenshot(shot)


async def _captureBeforeAndAfterTyping(
    params: StdioServerParameters, settleCycles: int
) -> tuple[bytes, bytes]:
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            create = await session.call_tool("create_machine", {})
            sessionId = json.loads(create.content[0].text)["session_id"]
            await session.call_tool(
                "run_for_cycles",
                {"session_id": sessionId, "cycles": settleCycles},
            )
            before = await session.call_tool(
                "screenshot", {"session_id": sessionId}
            )
            # One keypress is enough to mutate the visible screen
            # (the prompt line gets a new character). Anything that
            # changes pixels proves the renderer is responsive
            # between captures.
            await session.call_tool(
                "type_input", {"session_id": sessionId, "text": "P"}
            )
            after = await session.call_tool(
                "screenshot", {"session_id": sessionId}
            )
            await session.call_tool(
                "destroy_machine", {"session_id": sessionId}
            )
            return _parseScreenshot(before), _parseScreenshot(after)


async def _captureUnknownSession(
    params: StdioServerParameters,
) -> object:
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await session.call_tool(
                "screenshot",
                {"session_id": "00000000-0000-0000-0000-000000000000"},
            )


def testScreenshotBootScreenIsValidPng(beebjitBinary: Path) -> None:
    png = asyncio.run(
        _captureBootScreen(_buildParams(beebjitBinary), 5_000_000)
    )
    assert png.startswith(_PNG_SIGNATURE)
    width, height = _readIhdrDims(png)
    assert (width, height) == (768, 640)


def testScreenshotChangesAfterKeyPress(beebjitBinary: Path) -> None:
    before, after = asyncio.run(
        _captureBeforeAndAfterTyping(_buildParams(beebjitBinary), 5_000_000)
    )
    assert before != after, (
        "screenshot bytes did not change after a key press; "
        "renderer may be stale or savescreen returning a cached buffer"
    )
    # Dimensions stay the same; only the rendered content shifts.
    assert _readIhdrDims(before) == _readIhdrDims(after) == (768, 640)


def testScreenshotUnknownSessionErrors(beebjitBinary: Path) -> None:
    result = asyncio.run(_captureUnknownSession(_buildParams(beebjitBinary)))
    # FastMCP surfaces tool-side exceptions via the `isError` flag
    # plus a text payload; we only need to know the error happened.
    assert result.isError is True
