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
  as a single character (space or `?`) preserves the 40-column
  alignment human readers and text assertions both want; rendering
  them as a `\\xNN` escape preserves the byte value at the cost of
  variable cell width

Functions:
    decodeMode7        -- framebuffer -> 25 rows; control-byte
                          rendering selected by `controls`
    mode7TextContains  -- convenience wrapper for substring matching
"""

from __future__ import annotations

from enum import Enum


# -----------------------------------------------------------------------
# Public enum
# -----------------------------------------------------------------------

class Mode7Controls(str, Enum):
    """Selector for how `decodeMode7` renders non-printable bytes.

    Values are the wire-format strings used by the MCP tool and any
    JSON consumer; Pydantic accepts those strings and coerces them
    to enum members before our code sees them. Direct Python callers
    use the members directly so typos are caught at parse time
    rather than as a runtime ValueError.

    The `(str, Enum)` base means each member also IS its string
    value: `Mode7Controls.SPACE == "space"` is True, and JSON
    serialisation, logging, and dict round-trips return the string
    form without needing `.value` extraction. Internal dispatch
    relies on this equality, so a stray raw string from a loose
    integration still routes correctly while a typo'd string
    fails to match any branch.
    """

    # Single space per non-printable byte. Rows stay 40 chars wide.
    # Best for substring assertions and column-indexing callers.
    SPACE = "space"

    # Single `?` per non-printable byte. Rows stay 40 chars wide.
    # Best when callers want non-printable cells visually distinct
    # without decoding the byte value.
    QUESTION = "question"

    # Four-character `\\xNN` escape per non-printable byte. Row
    # widths become variable. Best when callers need the original
    # byte value preserved in the decoded string.
    ESCAPE = "escape"


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

def decodeMode7(
    framebuffer: bytes, controls: Mode7Controls = Mode7Controls.SPACE
) -> list[str]:
    """Decode a 1000-byte MODE 7 framebuffer into 25 rows.

    Non-printable bytes render per `controls` (see the
    `Mode7Controls` enum for the available members and their
    semantics). Rows are not right-stripped, so column-indexing
    into the SPACE or QUESTION outputs stays straightforward; the
    ESCAPE variant produces variable-width rows.

    Raises `ValueError` if the framebuffer is not exactly
    `MODE7_BYTES` long. Invalid `controls` values are impossible
    by construction: the type system rejects non-members at the
    call site, and Pydantic rejects unknown wire-format strings
    before they reach this function.
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
        rows.append(_renderMode7Row(rowBytes, controls))

    return rows


def _renderMode7Row(rowBytes: bytes, controls: Mode7Controls) -> str:
    """Render one MODE 7 row of bytes per the controls policy.

    Equality (`==`) rather than identity so the dispatch survives an
    `importlib.reload` of this module: a stale function holding an
    old `Mode7Controls.SPACE` default keeps working against the new
    class because str-Enum members compare by string value. Typos
    still cannot dispatch because `"spcae" == Mode7Controls.SPACE`
    is False.

    The final NotImplementedError is unreachable as long as every
    `Mode7Controls` member has its own branch; an unhandled member
    surfaces loudly at the first call rather than as a silent
    fallback.
    """

    if controls == Mode7Controls.SPACE:
        return "".join(
            chr(b) if 0x20 <= b <= 0x7E else " " for b in rowBytes
        )
    if controls == Mode7Controls.QUESTION:
        return "".join(
            chr(b) if 0x20 <= b <= 0x7E else "?" for b in rowBytes
        )
    if controls == Mode7Controls.ESCAPE:
        return "".join(
            chr(b) if 0x20 <= b <= 0x7E else f"\\x{b:02X}" for b in rowBytes
        )
    raise NotImplementedError(
        f"no renderer for Mode7Controls member {controls!r}"
    )


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
