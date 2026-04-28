# SPDX-FileCopyrightText: 2026 Heisenberg (acscpt)
# SPDX-License-Identifier: MIT

from __future__ import annotations

import pytest

from beebjit_mcp.screen import (
    MODE7_BASE_ADDR,
    MODE7_BYTES,
    MODE7_COLS,
    MODE7_PAGE_BYTES,
    MODE7_ROWS,
    Mode7Controls,
    decodeMode7,
    mode7TextContains,
    rotateMode7Page,
)


def testDecodesBlankFrameToAllSpaces() -> None:
    fb = bytes([0x20] * MODE7_BYTES)
    rows = decodeMode7(fb)
    assert len(rows) == MODE7_ROWS
    assert all(len(r) == MODE7_COLS for r in rows)
    assert all(r == " " * MODE7_COLS for r in rows)


def testDecodesNonPrintableAsSpaces() -> None:
    fb = bytes([0x00] * MODE7_BYTES)
    rows = decodeMode7(fb)
    assert all(r == " " * MODE7_COLS for r in rows)


def testPlacesTextOnExactRow() -> None:
    fb = bytearray(0x20 for _ in range(MODE7_BYTES))
    message = b"HELLO"
    rowIdx = 7
    fb[rowIdx * MODE7_COLS : rowIdx * MODE7_COLS + len(message)] = message
    rows = decodeMode7(bytes(fb))
    assert rows[rowIdx].startswith("HELLO")
    assert rows[rowIdx] == "HELLO" + " " * (MODE7_COLS - len(message))
    # Other rows untouched.
    for otherIdx in range(MODE7_ROWS):
        if otherIdx == rowIdx:
            continue
        assert rows[otherIdx] == " " * MODE7_COLS


def testDecodeRejectsWrongLengthFramebuffer() -> None:
    with pytest.raises(ValueError):
        decodeMode7(bytes(MODE7_BYTES - 1))
    with pytest.raises(ValueError):
        decodeMode7(bytes(MODE7_BYTES + 1))


def testRotateMode7PageNoScroll() -> None:
    # Offset zero: first 1000 bytes of the 1024-byte page are the
    # displayed bytes, in order.
    page = bytes(i & 0xFF for i in range(MODE7_PAGE_BYTES))
    out = rotateMode7Page(page, MODE7_BASE_ADDR)
    assert out == page[:MODE7_BYTES]


def testRotateMode7PageOneRowScrolled() -> None:
    # Scrolled 1 row = 40 bytes. First 40 bytes of `out` should be
    # the bytes that sat at offsets 40..79 of the physical page.
    page = bytes(i & 0xFF for i in range(MODE7_PAGE_BYTES))
    out = rotateMode7Page(page, MODE7_BASE_ADDR + MODE7_COLS)
    assert out[:MODE7_COLS] == page[MODE7_COLS : MODE7_COLS * 2]
    assert len(out) == MODE7_BYTES


def testRotateMode7PageWrapsAtPageEnd() -> None:
    # Start near the end of the 1024-byte page: display order must
    # wrap from the end of the page back to offset 0.
    page = bytes(i & 0xFF for i in range(MODE7_PAGE_BYTES))
    startOffset = MODE7_PAGE_BYTES - 10
    out = rotateMode7Page(page, MODE7_BASE_ADDR + startOffset)
    assert out[:10] == page[startOffset:]
    assert out[10:20] == page[:10]


def testRotateMode7PageRejectsBadInputs() -> None:
    with pytest.raises(ValueError):
        rotateMode7Page(bytes(MODE7_PAGE_BYTES - 1), MODE7_BASE_ADDR)
    with pytest.raises(ValueError):
        rotateMode7Page(bytes(MODE7_PAGE_BYTES), MODE7_BASE_ADDR - 1)
    with pytest.raises(ValueError):
        rotateMode7Page(
            bytes(MODE7_PAGE_BYTES),
            MODE7_BASE_ADDR + MODE7_PAGE_BYTES,
        )


def testContainsMatchesAcrossRowsJoin() -> None:
    fb = bytearray(0x20 for _ in range(MODE7_BYTES))
    fb[MODE7_COLS * 5 : MODE7_COLS * 5 + 5] = b"HELLO"
    assert mode7TextContains(bytes(fb), "HELLO")
    assert not mode7TextContains(bytes(fb), "GOODBYE")


# -----------------------------------------------------------------------
# controls parameter
# -----------------------------------------------------------------------

def testControlsSpaceMatchesDefault() -> None:
    fb = bytearray(0x00 for _ in range(MODE7_BYTES))
    fb[0:5] = b"HELLO"
    rows = decodeMode7(bytes(fb), controls=Mode7Controls.SPACE)
    assert rows == decodeMode7(bytes(fb))
    assert rows[0] == "HELLO" + " " * (MODE7_COLS - 5)
    assert all(len(r) == MODE7_COLS for r in rows)


def testControlsQuestionRendersControlBytesAsQuestionMarks() -> None:
    fb = bytearray(0x00 for _ in range(MODE7_BYTES))
    fb[0:5] = b"HELLO"
    rows = decodeMode7(bytes(fb), controls=Mode7Controls.QUESTION)
    assert rows[0] == "HELLO" + "?" * (MODE7_COLS - 5)
    # Width invariant holds for QUESTION mode just like SPACE.
    assert all(len(r) == MODE7_COLS for r in rows)


def testControlsEscapeRendersControlBytesAsHexEscape() -> None:
    fb = bytearray(0x00 for _ in range(MODE7_BYTES))
    fb[0:5] = b"HELLO"
    fb[5] = 0x80
    fb[6] = 0x1F
    rows = decodeMode7(bytes(fb), controls=Mode7Controls.ESCAPE)
    # First six visible bytes round-trip into HELLO + escapes for
    # 0x80 and 0x1F. Every remaining 0x00 expands to "\\x00".
    expected = "HELLO" + "\\x80" + "\\x1F" + "\\x00" * (MODE7_COLS - 7)
    assert rows[0] == expected
    # Width is intentionally variable in ESCAPE mode: a row of all
    # control bytes expands to 4 chars per cell.
    assert len(rows[1]) == MODE7_COLS * 4


def testControlsEscapeLeavesPrintableBytesUntouched() -> None:
    # Pure-printable row stays the same width and content as
    # SPACE/QUESTION output, since no substitution fires.
    fb = bytearray(0x20 for _ in range(MODE7_BYTES))
    fb[0:5] = b"HELLO"
    rows = decodeMode7(bytes(fb), controls=Mode7Controls.ESCAPE)
    assert rows[0] == "HELLO" + " " * (MODE7_COLS - 5)
    assert all(len(r) == MODE7_COLS for r in rows)


def testControlsEscapeUsesUppercaseHex() -> None:
    fb = bytearray(0x20 for _ in range(MODE7_BYTES))
    fb[0] = 0xAB
    rows = decodeMode7(bytes(fb), controls=Mode7Controls.ESCAPE)
    # Lowercase variant would be `\\xab`; uppercase keeps escapes
    # visually distinct from the printable-ASCII glyphs around them.
    assert rows[0].startswith("\\xAB")


def testMode7ControlsValuesAreWireFormatStrings() -> None:
    # Members IS their string value because of the (str, Enum) base.
    # MCP wire format depends on this round-trip working both ways.
    assert Mode7Controls.SPACE == "space"
    assert Mode7Controls.QUESTION == "question"
    assert Mode7Controls.ESCAPE == "escape"
    assert Mode7Controls("space") is Mode7Controls.SPACE
