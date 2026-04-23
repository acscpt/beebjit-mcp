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


async def _runCreateDestroy(params: StdioServerParameters) -> dict[str, object]:
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            toolNames = {t.name for t in tools.tools}
            createResult = await session.call_tool("create_machine", {})
            createPayload = json.loads(createResult.content[0].text)
            sessionId = createPayload["session_id"]
            destroyResult = await session.call_tool(
                "destroy_machine", {"session_id": sessionId}
            )
            destroyPayload = json.loads(destroyResult.content[0].text)
            return {
                "tool_names": toolNames,
                "session_id": sessionId,
                "destroy_ok": destroyPayload["ok"],
            }


def testServerCreateDestroyRoundTrip(beebjitBinary: Path) -> None:
    params = _buildParams(beebjitBinary)
    result = asyncio.run(_runCreateDestroy(params))
    assert "create_machine" in result["tool_names"]
    assert "destroy_machine" in result["tool_names"]
    assert isinstance(result["session_id"], str) and len(result["session_id"]) > 0
    assert result["destroy_ok"] is True
