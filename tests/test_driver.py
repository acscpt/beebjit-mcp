# SPDX-FileCopyrightText: 2026 Heisenberg (acscpt)
# SPDX-License-Identifier: MIT

from __future__ import annotations

from pathlib import Path

from beebjit_mcp.driver import BeebjitDriver


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
