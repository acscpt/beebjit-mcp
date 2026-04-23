# SPDX-FileCopyrightText: 2026 Heisenberg (acscpt)
# SPDX-License-Identifier: MIT

"""End-to-end HELLO demo tests.

The Stage 4 acceptance gate. Two tests:

* `testDriverHelloRoundTrip` exercises the driver directly. Fast
  iteration when debugging the typing path.
* `testServerHelloRoundTripViaMcp` exercises the full MCP stack:
  stdio transport, JSON-RPC handshake, tool calls. This is the
  HELLO demo the grand plan calls for.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from beebjit_mcp.driver import BeebjitDriver
from beebjit_mcp.screen import MODE7_COLS, decodeMode7


# -----------------------------------------------------------------------
# Constants shared across both test variants
# -----------------------------------------------------------------------

# Cycles to run after power-on to reach a stable BASIC `>` prompt.
# 5M is empirically comfortable (see driver tests); gives ~0.5s of
# real time at `-fast`.
BOOT_CYCLES: int = 5_000_000


# Cycles to run after pressing RETURN for BASIC to tokenise, execute,
# and print the output. Far more than needed for a one-liner, but
# small compared to overall test time and leaves headroom for slower
# host runners.
SETTLE_CYCLES: int = 10_000_000


# The demo line. Trailing `\n` triggers RETURN inside `typeText`.
HELLO_LINE: str = 'PRINT "HELLO"\n'


# -----------------------------------------------------------------------
# Driver-level test
# -----------------------------------------------------------------------

def testDriverHelloRoundTrip(beebjitBinary: Path) -> None:
    """Drive the emulator directly to confirm HELLO echoes to the screen."""

    with BeebjitDriver(beebjitBinary) as drv:

        # Boot to the BASIC prompt. The fixture guarantees beebjit
        # exists; the driver raises BeebjitError if the subprocess
        # fails to reach the first prompt.
        drv.runCycles(BOOT_CYCLES)

        # Sanity check: prompt really did appear. Protects the rest
        # of the test from a silent boot failure (e.g. missing ROM).
        fb = drv.captureMode7Bytes()
        promptRow = decodeMode7(fb)[7]
        assert promptRow.startswith(">"), (
            f"no BASIC prompt after boot: {promptRow!r}"
        )

        # Type the program. Each character takes HOLD+GAP = 8M BBC
        # cycles; 14 chars = ~112M cycles, a few hundred ms at
        # `-fast`. The driver handles SHIFT for the `"` characters
        # via `tapShiftedKey` under the hood.
        drv.typeText(HELLO_LINE)

        # Let BASIC tokenise and run. HELLO should appear on the
        # line after the typed command.
        drv.runCycles(SETTLE_CYCLES)

        # Assert HELLO turns up somewhere in the MODE 7 framebuffer.
        # We do not fix the row: BASIC's line scrolling and prompt
        # placement are stable within a run but not worth pinning.
        fb = drv.captureMode7Bytes()
        rows = decodeMode7(fb)
        joined = "\n".join(rows)
        assert "HELLO" in joined, (
            "HELLO not found in screen after running PRINT \"HELLO\". "
            f"Screen dump:\n{joined}"
        )

        # Also assert the typed line is visible: catches the failure
        # mode where the program runs but none of our keypresses
        # registered (would have produced a blank line plus a stray
        # BASIC error).
        assert any('PRINT' in r for r in rows), (
            "typed PRINT command did not appear on screen"
        )


# -----------------------------------------------------------------------
# MCP-level end-to-end test
# -----------------------------------------------------------------------

def _buildServerParams(beebjitBinary: Path) -> StdioServerParameters:
    """Build the MCP stdio parameters for spawning the server subprocess.

    Propagates `$BEEBJIT` explicitly so the server-side binary
    discovery picks up the same binary as the test fixture, even
    under environments that scrub PATH.
    """

    env = dict(os.environ)
    env["BEEBJIT"] = str(beebjitBinary)

    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "beebjit_mcp.server"],
        env=env,
    )


async def _runHelloOverMcp(params: StdioServerParameters) -> dict[str, object]:
    """Drive the HELLO demo through the MCP client. Returns a result summary.

    Keeps all the async plumbing in one place so the pytest entry
    point stays sync-friendly via `asyncio.run`.
    """

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:

            # MCP handshake. Required before any tool call.
            await session.initialize()

            # Start a BBC session and extract the handle.
            createResult = await session.call_tool("create_machine", {})
            createPayload = json.loads(createResult.content[0].text)
            sessionId: str = createPayload["session_id"]

            # Boot to the BASIC prompt.
            await session.call_tool(
                "run_for_cycles",
                {"session_id": sessionId, "cycles": BOOT_CYCLES},
            )

            # Type the demo line. The server uses the driver's
            # default HOLD/GAP timings, which are known reliable.
            await session.call_tool(
                "type_input",
                {"session_id": sessionId, "text": HELLO_LINE},
            )

            # Wait for HELLO to show on the screen. Using
            # run_until_text rather than a fixed run_for_cycles
            # keeps the test tolerant of slightly different
            # settlement times across hosts.
            untilResult = await session.call_tool(
                "run_until_text",
                {
                    "session_id": sessionId,
                    "needle": "HELLO",
                    "max_cycles": SETTLE_CYCLES * 2,
                },
            )
            untilPayload = json.loads(untilResult.content[0].text)

            # Capture the final screen for assertion.
            screenResult = await session.call_tool(
                "read_mode7_text",
                {"session_id": sessionId},
            )
            screenPayload = json.loads(screenResult.content[0].text)

            # Clean up the server-side session so we do not leak a
            # beebjit process when the server outlives this test.
            destroyResult = await session.call_tool(
                "destroy_machine",
                {"session_id": sessionId},
            )
            destroyPayload = json.loads(destroyResult.content[0].text)

            return {
                "until": untilPayload,
                "screen_text": screenPayload["text"],
                "screen_rows": screenPayload["rows"],
                "destroy_ok": destroyPayload["ok"],
            }


def testServerHelloRoundTripViaMcp(beebjitBinary: Path) -> None:
    """Full MCP round trip: create, boot, type, wait for HELLO, destroy."""

    # Build params once; the server subprocess is spawned inside
    # `_runHelloOverMcp` via the MCP client library.
    params = _buildServerParams(beebjitBinary)

    # asyncio.run drives the client coroutine; pytest stays sync.
    result = asyncio.run(_runHelloOverMcp(params))

    # HELLO really did appear on screen, not just "did not time out".
    assert "HELLO" in result["screen_text"], (
        "HELLO missing from server-side screen capture. Dump:\n"
        f"{result['screen_text']}"
    )

    # And the server reported a clean find through run_until_text.
    assert result["until"]["found"] is True, result["until"]

    # Screen has the expected MODE 7 geometry. Guards against a
    # decoder regression sneaking past behind the HELLO substring
    # match.
    rows = result["screen_rows"]
    assert len(rows) == 25
    assert all(len(r) == MODE7_COLS for r in rows)

    # Session teardown succeeded. If this fails, a stray beebjit
    # process is probably still running on the test host.
    assert result["destroy_ok"] is True
