# SPDX-FileCopyrightText: 2026 Heisenberg (acscpt)
# SPDX-License-Identifier: MIT

"""Stdlib-only BGRA-to-PNG encoder.

Implementation detail of the `screenshot` MCP tool. beebjit's
`savescreen` debugger command writes raw BGRA pixel data to disk;
this module turns those bytes into a PNG so MCP clients receive a
format every viewer understands.

Single public function `bgraToPng`. Internals are stdlib `zlib`
(deflate compression and CRC32) plus `struct` (big-endian chunk
headers). No third-party dependency.

Why a hand-rolled encoder rather than Pillow:

* Project keeps its dependency tree to MCP SDK plus transitive only;
  PNG output is small enough to own
* Future swap to Pillow stays a one-module change because callers
  only see `bgraToPng`

PNG wire format reference (PNG 1.2):

* Signature: `89 50 4E 47 0D 0A 1A 0A`
* Chunks: `length` (4B BE), `type` (4B), `data`, `crc32` (4B BE).
  CRC covers `type` and `data`, not `length`.
* IHDR (first chunk, 13 bytes): `width`, `height`, bit depth,
  colour type, compression method, filter method, interlace method.
* IDAT: zlib-compressed scanlines, each prefixed with a one-byte
  filter type (0 = None: pass raw bytes through).
* IEND: empty terminator.
"""

from __future__ import annotations

import struct
import zlib


# -----------------------------------------------------------------------
# PNG constants
# -----------------------------------------------------------------------

_PNG_SIGNATURE: bytes = b"\x89PNG\r\n\x1a\n"

_BIT_DEPTH_8: int = 8
_COLOR_TYPE_RGBA: int = 6
_COMPRESSION_DEFLATE: int = 0
_FILTER_ADAPTIVE: int = 0
_INTERLACE_NONE: int = 0
_FILTER_NONE: int = 0

_BYTES_PER_PIXEL: int = 4


# -----------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------

def bgraToPng(bgra: bytes, width: int, height: int) -> bytes:
    """Encode raw BGRA pixel data as a PNG. Returns the full PNG bytes.

    `bgra` is the framebuffer in B,G,R,A byte order (the layout
    beebjit's `savescreen` writes). `width` and `height` are in
    pixels. The returned bytes are a complete, self-contained PNG
    file ready to be written to disk or base64-encoded for transport.

    Raises `ValueError` if `len(bgra)` does not match
    `width * height * 4`, or if `width`/`height` are non-positive.
    """

    if width <= 0 or height <= 0:
        raise ValueError(
            f"width and height must be positive, got {width}x{height}"
        )

    expected = width * height * _BYTES_PER_PIXEL
    if len(bgra) != expected:
        raise ValueError(
            f"bgra length {len(bgra)} does not match "
            f"{width}x{height}*{_BYTES_PER_PIXEL} = {expected}"
        )

    rgba = _bgraToRgba(bgra)
    raw = _addFilterBytes(rgba, width, height)
    compressed = zlib.compress(raw)

    return (
        _PNG_SIGNATURE
        + _chunk(b"IHDR", _ihdrPayload(width, height))
        + _chunk(b"IDAT", compressed)
        + _chunk(b"IEND", b"")
    )


# -----------------------------------------------------------------------
# Internals
# -----------------------------------------------------------------------

def _bgraToRgba(bgra: bytes) -> bytes:
    """Swap B and R channels in every 4-byte pixel.

    The swap is not in-place: a snapshot of the blue channel is
    taken first because slice assignment on a bytearray would
    otherwise overwrite the source mid-update.
    """

    data = bytearray(bgra)
    blue = bytes(data[0::4])
    data[0::4] = data[2::4]
    data[2::4] = blue
    return bytes(data)


def _addFilterBytes(rgba: bytes, width: int, height: int) -> bytes:
    """Prepend a filter-type byte (0 = None) to each scanline.

    PNG requires every scanline in IDAT to carry an explicit filter
    type. None is the cheapest option: the decoder reads the row
    bytes as-is, no per-pixel reconstruction. Lossless and small
    enough after deflate that fancier filters are not worth the
    encoder complexity here.
    """

    stride = width * _BYTES_PER_PIXEL
    raw = bytearray()
    for y in range(height):
        raw.append(_FILTER_NONE)
        raw.extend(rgba[y * stride : (y + 1) * stride])
    return bytes(raw)


def _ihdrPayload(width: int, height: int) -> bytes:
    """Build the 13-byte IHDR data block."""

    return struct.pack(
        ">IIBBBBB",
        width,
        height,
        _BIT_DEPTH_8,
        _COLOR_TYPE_RGBA,
        _COMPRESSION_DEFLATE,
        _FILTER_ADAPTIVE,
        _INTERLACE_NONE,
    )


def _chunk(typ: bytes, data: bytes) -> bytes:
    """Wrap (type, data) into a length-prefixed PNG chunk with CRC."""

    crc = zlib.crc32(typ + data) & 0xFFFFFFFF
    return (
        struct.pack(">I", len(data))
        + typ
        + data
        + struct.pack(">I", crc)
    )
