# SPDX-FileCopyrightText: 2026 Heisenberg (acscpt)
# SPDX-License-Identifier: MIT

"""Unit tests for `server.py` helpers that do not need a BBC session.

Everything here exercises pure logic (`_resolveKey`, `_discoverBinary`
error paths, etc.). The integration tests in `test_hello.py` and
`test_server_minimal.py` cover the wire-format round trips.
"""

from __future__ import annotations

import pytest

from beebjit_mcp.server import _resolveKey


def testResolveKeySymbolicName() -> None:
    assert _resolveKey("CAPS_LOCK") == 135
    assert _resolveKey("return") == 131


def testResolveKeySingleChar() -> None:
    assert _resolveKey("A") == ord("A")
    # Lower-case letter upcased so the matrix-position lookup is
    # stable regardless of CAPS LOCK state on the caller side.
    assert _resolveKey("a") == ord("A")
    # Non-alpha single chars go straight to ord(): digit 3 sits at
    # the BBC 3 key position, punctuation at its own code.
    assert _resolveKey("3") == ord("3")
    assert _resolveKey(";") == ord(";")


def testResolveKeyIntPassthrough() -> None:
    assert _resolveKey(65) == 65
    assert _resolveKey(255) == 255


def testResolveKeyRejectsUnknownName() -> None:
    with pytest.raises(ValueError):
        _resolveKey("NOSUCHKEY")


def testResolveKeyRejectsOutOfRangeInt() -> None:
    with pytest.raises(ValueError):
        _resolveKey(256)
