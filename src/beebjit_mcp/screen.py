# SPDX-FileCopyrightText: 2026 Heisenberg (acscpt)
# SPDX-License-Identifier: MIT

"""MODE 7 (teletext) screen decode.

Pure function layer that converts raw framebuffer bytes into a list
of human-readable text rows. No IO, no emulator dependency; the
driver reads the 1000-byte block at `&7C00` from the BBC, and the
server calls `decodeMode7(bytes)` to render it.

Teletext encoding notes, relevant to what we choose to decode:

* MODE 7 is a 40 x 25 grid of teletext character codes
* Bytes 0x20-0x7E are printable ASCII with a few BBC-specific
  substitutions (e.g. `\\`, `_`) that are close enough to their
  ASCII glyphs for text assertions
* Bytes 0x00-0x1F and 0x80-0x9F are teletext control codes: colour
  set, flash, double-height, graphics-mode toggle. In MODE 7 these
  occupy screen cells (they are *not* interleaved out-of-band)
* A control code leaves its cell visually blank, so rendering them
  as space preserves column alignment, which is what human readers
  and text assertions both want

v0.1 scope: printable ASCII passes through, anything else becomes
space. Richer decoding (colour, graphics glyphs) is not needed for
text-based assertions and is deferred.

Functions:
    decodeMode7        -- framebuffer -> 25 rows of 40-char strings
    mode7TextContains  -- convenience wrapper for substring matching
"""

from __future__ import annotations


# -----------------------------------------------------------------------
# MODE 7 geometry and memory-map constants
# -----------------------------------------------------------------------

MODE7_ROWS: int = 25
MODE7_COLS: int = 40
MODE7_BYTES: int = MODE7_ROWS * MODE7_COLS
MODE7_BASE_ADDR: int = 0x7C00

# MODE 7's physical memory page is 1024 bytes at `&7C00-&7FFF`.
# The CRTC masks its address counter with `0x3FF`, so hardware
# scroll wraps at `&8000` back to `&7C00`. Only the first 1000 bytes
# after the CRTC start are actually displayed; the remaining 24 are
# "off-screen" padding within the 1K page.
MODE7_PAGE_BYTES: int = 1024
MODE7_PAGE_MASK: int = MODE7_PAGE_BYTES - 1


# -----------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------

def decodeMode7(framebuffer: bytes) -> list[str]:
    """Decode a 1000-byte MODE 7 framebuffer into 25 rows of 40 chars.

    Non-printable bytes render as a single space so column alignment
    is preserved. Rows are not right-stripped; every returned string
    is exactly `MODE7_COLS` characters, which keeps caller-side
    column-indexing straightforward.

    Raises `ValueError` if the framebuffer is not exactly
    `MODE7_BYTES` long.
    """

    # Length check up front: callers typically pass the result of a
    # fixed-size `readMemory` call, so a mismatch here almost always
    # means the driver read the wrong region or was short-circuited
    # by an emulator exit. Better to fail loud than return truncated
    # rows and hide the underlying bug.
    if len(framebuffer) != MODE7_BYTES:
        raise ValueError(
            f"MODE 7 framebuffer must be {MODE7_BYTES} bytes, "
            f"got {len(framebuffer)}"
        )

    rows: list[str] = []

    # Row-by-row slicing keeps the decode cache-friendly and makes
    # the output directly indexable by BBC row number.
    for r in range(MODE7_ROWS):
        rowBytes = framebuffer[r * MODE7_COLS : (r + 1) * MODE7_COLS]

        # Printable ASCII passes through; everything else (teletext
        # control codes, uninitialised memory, mode switches) becomes
        # a space so screen columns remain aligned for humans.
        rowText = "".join(
            chr(b) if 0x20 <= b <= 0x7E else " " for b in rowBytes
        )

        rows.append(rowText)

    return rows


def rotateMode7Page(page: bytes, startAddr: int) -> bytes:
    """Rotate a 1024-byte MODE 7 page into display order.

    BBC MODE 7 uses hardware scrolling: the CRTC R12:R13 register
    points at the first displayed byte within the 1024-byte page at
    `&7C00`. As the screen scrolls, that pointer advances and the
    display wraps at the end of the page. The BBC MOS keeps a
    CPU-space copy of this pointer at `&0350/&0351` (little-endian).

    Given the full 1024-byte page and the MOS pointer, this function
    returns the 1000 bytes the CRTC is currently painting, in the
    order they appear on screen from top-left to bottom-right.

    `startAddr` must lie in `&7C00-&7FFF`; anything outside that
    range raises `ValueError`. The low 10 bits of the offset are
    used as the rotation amount, mirroring the CRTC mask.
    """

    if len(page) != MODE7_PAGE_BYTES:
        raise ValueError(
            f"MODE 7 page must be {MODE7_PAGE_BYTES} bytes, "
            f"got {len(page)}"
        )

    if not (MODE7_BASE_ADDR <= startAddr < MODE7_BASE_ADDR + MODE7_PAGE_BYTES):
        raise ValueError(
            f"startAddr {startAddr:#x} outside MODE 7 page "
            f"{MODE7_BASE_ADDR:#x}-{MODE7_BASE_ADDR + MODE7_PAGE_BYTES - 1:#x}"
        )

    offset = (startAddr - MODE7_BASE_ADDR) & MODE7_PAGE_MASK

    # Single rotation, then slice the first 1000 bytes. The remaining
    # 24 bytes in the page are never displayed in a given frame.
    rotated = page[offset:] + page[:offset]
    return rotated[:MODE7_BYTES]


def mode7TextContains(framebuffer: bytes, needle: str) -> bool:
    """True if `needle` appears anywhere in the decoded screen.

    Joins rows with `\\n` so a search string does not accidentally
    span a row boundary (e.g. `END` at the end of row 0 followed by
    a space at the start of row 1 will not match `END `).
    """

    joined = "\n".join(decodeMode7(framebuffer))

    return needle in joined
