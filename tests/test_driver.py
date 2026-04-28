# SPDX-FileCopyrightText: 2026 Heisenberg (acscpt)
# SPDX-License-Identifier: MIT

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from beebjit_mcp.driver import BeebjitDriver, BeebjitError


def testDriverSpawnAndQuit(beebjitBinary: Path) -> None:
    with BeebjitDriver(beebjitBinary) as drv:
        regs = drv.readRegisters()
        assert isinstance(regs["A"], int) and 0 <= regs["A"] <= 0xFF
        assert isinstance(regs["PC"], int) and 0 <= regs["PC"] <= 0xFFFF
        assert isinstance(regs["cycles"], int)


def testDriverMemoryRoundTrip(beebjitBinary: Path) -> None:
    with BeebjitDriver(beebjitBinary) as drv:
        payload = bytes([0x42, 0x69, 0xAB, 0xCD])
        drv.writeMemory(0x7100, payload)
        readBack = drv.readMemory(0x7100, len(payload))
        assert readBack == payload


def testDriverCaptureMode7Text(beebjitBinary: Path) -> None:
    with BeebjitDriver(beebjitBinary) as drv:
        drv.runCycles(5_000_000)
        screenRow0 = drv.readMemory(0x7C00, 40)
        printable = sum(1 for b in screenRow0 if 0x20 <= b <= 0x7E)
        assert printable > 0, f"row 0 all non-printable: {screenRow0.hex()}"


def testDriverDisassembleReturnsInstructionBatch(beebjitBinary: Path) -> None:
    # `&E000` is the start of the MOS ROM on a booted Model B. The
    # first instruction is always `JSR $E004` (the `OSFIND` entry
    # point); even if beebjit's opcode formatting shifts, the 4-hex
    # address and the JSR mnemonic are stable anchors.
    with BeebjitDriver(beebjitBinary) as drv:
        drv.runCycles(5_000_000)
        items = drv.disassemble(0xE000, count=5)
        assert len(items) == 5
        assert items[0]["addr"] == 0xE000
        assert "JSR" in items[0]["text"]
        # Each subsequent address is strictly greater (instructions
        # don't shrink or overlap).
        for earlier, later in zip(items, items[1:]):
            assert int(later["addr"]) > int(earlier["addr"])


def testDriverTapKeyTypesTwoChars(beebjitBinary: Path) -> None:
    with BeebjitDriver(beebjitBinary) as drv:
        drv.runCycles(5_000_000)
        bbcPromptRow = drv.readMemory(0x7C00 + 7 * 40, 40)
        assert bbcPromptRow.startswith(b">"), bbcPromptRow.hex()
        drv.tapKey(ord("P"))
        drv.tapKey(ord("R"))
        row7 = drv.readMemory(0x7C00 + 7 * 40, 40)
        text = row7.rstrip(b" ").decode("ascii", errors="replace")
        assert text.startswith(">PR"), f"expected >PR..., got {text!r}"


def testDriverCaptureScreenReturnsBgraBuffer(beebjitBinary: Path) -> None:
    with BeebjitDriver(beebjitBinary) as drv:
        drv.runCycles(5_000_000)
        bgra, width, height = drv.captureScreen()
        assert (width, height) == (768, 640)
        assert len(bgra) == 768 * 640 * 4
        # Border around the BBC display area is opaque black, so the
        # very first pixel reads as B=0,G=0,R=0,A=0xFF in BGRA byte
        # order. A regression that broke the byte order would change
        # the alpha or zero out the alpha channel.
        assert bgra[:4] == bytes([0x00, 0x00, 0x00, 0xFF])


def testDriverCaptureScreenRaisesOnNoRenderBuffer(tmp_path: Path) -> None:
    # No real beebjit needed: stub sendCommand to simulate the line
    # the binary emits when started without -headless-render.
    drv = BeebjitDriver(Path("/nonexistent/beebjit"))
    drv._tempDir = tmp_path
    with patch.object(
        drv,
        "sendCommand",
        return_value=[
            "no render buffer; start with -headless-render or -frame-cycles"
        ],
    ):
        with pytest.raises(BeebjitError, match="no render buffer"):
            drv.captureScreen()


def testDriverCaptureScreenRaisesIfNotStarted(tmp_path: Path) -> None:
    drv = BeebjitDriver(Path("/nonexistent/beebjit"))
    with pytest.raises(BeebjitError, match="not started"):
        drv.captureScreen()
