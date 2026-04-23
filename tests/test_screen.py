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
