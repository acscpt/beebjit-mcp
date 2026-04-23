# SPDX-FileCopyrightText: 2026 Heisenberg (acscpt)
# SPDX-License-Identifier: MIT

"""End-to-end CAPS LOCK and case-preserving input tests.

Exercises the `set_caps_lock` / `type_input_raw` pair against a real
beebjit session: cold-boot default is CAPS LOCK ON, flipping it off
makes lowercase input actually land as lowercase on the MODE 7
screen.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


BOOT_CYCLES: int = 10_000_000


def _buildParams(beebjitBinary: Path) -> StdioServerParameters:
    env = dict(os.environ)
    env["BEEBJIT"] = str(beebjitBinary)
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "beebjit_mcp.server"],
        env=env,
    )


async def _runCapsLockRoundTrip(
    params: StdioServerParameters,
) -> dict[str, object]:
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

                # Cold-boot state: CAPS LOCK is ON, so `set_caps_lock(True)`
                # should be a no-op (no tap issued).
                idempotent = await session.call_tool(
                    "set_caps_lock",
                    {"session_id": sessionId, "on": True},
                )
                idempotentPayload = json.loads(idempotent.content[0].text)

                # Turn CAPS LOCK off. Tool should tap once and report
                # the new state.
                flipOff = await session.call_tool(
                    "set_caps_lock",
                    {"session_id": sessionId, "on": False},
                )
                flipOffPayload = json.loads(flipOff.content[0].text)

                # Case-preserving input now lands lowercase on screen.
                await session.call_tool(
                    "type_input_raw",
                    {
                        "session_id": sessionId,
                        "text": 'PRINT "hi"\n',
                    },
                )

                # Run until the output appears.
                await session.call_tool(
                    "run_until_text",
                    {
                        "session_id": sessionId,
                        "needle": "hi",
                        "max_cycles": 20_000_000,
                    },
                )

                screen = await session.call_tool(
                    "read_mode7_text",
                    {"session_id": sessionId},
                )
                screenText = json.loads(screen.content[0].text)["text"]

                # Flip caps lock back on via press_caps_lock (the
                # toggle tool) and verify it matches via a follow-up
                # set_caps_lock(True) that should be a no-op.
                await session.call_tool(
                    "press_caps_lock", {"session_id": sessionId}
                )
                await session.call_tool(
                    "run_for_cycles",
                    {"session_id": sessionId, "cycles": 2_000_000},
                )
                followup = await session.call_tool(
                    "set_caps_lock",
                    {"session_id": sessionId, "on": True},
                )
                followupPayload = json.loads(followup.content[0].text)

                return {
                    "idempotent": idempotentPayload,
                    "flip_off": flipOffPayload,
                    "screen": screenText,
                    "followup": followupPayload,
                }

            finally:
                await session.call_tool(
                    "destroy_machine", {"session_id": sessionId}
                )


def testCapsLockAndRawTypingRoundTrip(beebjitBinary: Path) -> None:
    params = _buildParams(beebjitBinary)
    result = asyncio.run(_runCapsLockRoundTrip(params))

    # Cold-boot default is CAPS LOCK ON; set_caps_lock(True) must
    # report no tap was issued.
    idempotent = result["idempotent"]
    assert idempotent["tapped"] is False
    assert idempotent["caps_lock_on"] is True

    # Flipping off issues a tap and reports the new state.
    flipOff = result["flip_off"]
    assert flipOff["tapped"] is True
    assert flipOff["caps_lock_on"] is False

    # Lowercase "hi" lands on screen in the PRINT output; uppercase
    # "HI" would indicate CAPS LOCK was not actually off.
    screen: str = result["screen"]
    assert "hi" in screen, f"lowercase output missing from screen:\n{screen}"
    # Case-preserving typing means PRINT uppercase made it through
    # too (matrix requires SHIFT for uppercase letters with CAPS
    # LOCK OFF).
    assert "PRINT" in screen, f"uppercase PRINT missing from screen:\n{screen}"

    # After press_caps_lock re-enables CAPS LOCK, set_caps_lock(True)
    # should again be idempotent (no tap).
    followup = result["followup"]
    assert followup["tapped"] is False
    assert followup["caps_lock_on"] is True
