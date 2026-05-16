# SPDX-FileCopyrightText: 2026 Heisenberg (acscpt)
# SPDX-License-Identifier: MIT

from __future__ import annotations

import struct
import zlib

import pytest

from beebjit_mcp.image import bgraToPng


_PNG_SIGNATURE: bytes = b"\x89PNG\r\n\x1a\n"


def _readChunks(png: bytes) -> list[tuple[bytes, bytes]]:
    """Parse PNG chunks. Validates the signature and per-chunk CRCs."""

    assert png.startswith(_PNG_SIGNATURE), "missing PNG signature"

    out: list[tuple[bytes, bytes]] = []
    pos = len(_PNG_SIGNATURE)
    while pos < len(png):
        length = struct.unpack(">I", png[pos : pos + 4])[0]
        typ = png[pos + 4 : pos + 8]
        data = png[pos + 8 : pos + 8 + length]
        crcExpected = struct.unpack(
            ">I", png[pos + 8 + length : pos + 12 + length]
        )[0]
        crcActual = zlib.crc32(typ + data) & 0xFFFFFFFF
        assert crcExpected == crcActual, (
            f"chunk {typ!r} CRC mismatch: {crcExpected:#x} vs {crcActual:#x}"
        )
        out.append((typ, data))
        pos += 12 + length

    return out


def testEmitsRequiredChunksInOrder() -> None:
    bgra = bytes([0x00, 0x00, 0x00, 0xFF] * 4)
    png = bgraToPng(bgra, 2, 2)
    chunks = _readChunks(png)
    assert [t for t, _ in chunks] == [b"IHDR", b"IDAT", b"IEND"]


def testIhdrEncodesGivenDimensionsAndRgba() -> None:
    bgra = bytes([0x00, 0x00, 0x00, 0xFF] * 6)
    png = bgraToPng(bgra, 3, 2)
    chunks = _readChunks(png)
    typ, data = chunks[0]
    assert typ == b"IHDR"
    width, height, depth, colorType, comp, filt, interlace = struct.unpack(
        ">IIBBBBB", data
    )
    assert (width, height) == (3, 2)
    assert depth == 8
    assert colorType == 6
    assert comp == 0
    assert filt == 0
    assert interlace == 0


def testBgraChannelSwapEmitsRgba() -> None:
    bgra = bytes([10, 20, 30, 40])
    png = bgraToPng(bgra, 1, 1)
    chunks = _readChunks(png)
    idat = next(d for t, d in chunks if t == b"IDAT")
    raw = zlib.decompress(idat)
    assert raw == bytes([0, 30, 20, 10, 40])


def testScanlinesPreserveRowOrder() -> None:
    blueBgra = bytes([0xFF, 0x00, 0x00, 0xFF]) * 2
    greenBgra = bytes([0x00, 0xFF, 0x00, 0xFF]) * 2
    redBgra = bytes([0x00, 0x00, 0xFF, 0xFF]) * 2
    bgra = blueBgra + greenBgra + redBgra
    png = bgraToPng(bgra, 2, 3)
    chunks = _readChunks(png)
    idat = next(d for t, d in chunks if t == b"IDAT")
    raw = zlib.decompress(idat)
    assert raw[0] == 0
    assert raw[1:9] == bytes([0, 0, 255, 255]) * 2
    assert raw[9] == 0
    assert raw[10:18] == bytes([0, 255, 0, 255]) * 2
    assert raw[18] == 0
    assert raw[19:27] == bytes([255, 0, 0, 255]) * 2


def testIendIsEmpty() -> None:
    bgra = bytes([0, 0, 0, 0xFF])
    png = bgraToPng(bgra, 1, 1)
    chunks = _readChunks(png)
    typ, data = chunks[-1]
    assert typ == b"IEND"
    assert data == b""


def testRejectsLengthMismatch() -> None:
    with pytest.raises(ValueError):
        bgraToPng(bytes(5), 1, 1)


def testRejectsNonPositiveDimensions() -> None:
    with pytest.raises(ValueError):
        bgraToPng(b"", 0, 1)
    with pytest.raises(ValueError):
        bgraToPng(b"", 1, 0)
    with pytest.raises(ValueError):
        bgraToPng(b"", -1, 1)


def testRoundTripsLargeBuffer() -> None:
    width, height = 64, 48
    bgra = bytes([(i * 7) & 0xFF for i in range(width * height * 4)])
    png = bgraToPng(bgra, width, height)
    chunks = _readChunks(png)
    idat = next(d for t, d in chunks if t == b"IDAT")
    raw = zlib.decompress(idat)
    stride = width * 4
    expectedSize = height * (1 + stride)
    assert len(raw) == expectedSize
    for y in range(height):
        rowStart = y * (1 + stride)
        assert raw[rowStart] == 0
        rgbaRow = raw[rowStart + 1 : rowStart + 1 + stride]
        bgraRow = bgra[y * stride : (y + 1) * stride]
        for x in range(width):
            b, g, r, a = bgraRow[x * 4 : x * 4 + 4]
            rr, gg, bb, aa = rgbaRow[x * 4 : x * 4 + 4]
            assert (rr, gg, bb, aa) == (r, g, b, a)
