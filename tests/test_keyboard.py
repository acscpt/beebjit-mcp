# SPDX-FileCopyrightText: 2026 Heisenberg (acscpt)
# SPDX-License-Identifier: MIT

from __future__ import annotations

import pytest

from beebjit_mcp.keyboard import (
    BBC_KEY_CAPS_LOCK,
    BBC_KEY_ESCAPE,
    BBC_KEY_F1,
    BBC_KEY_RELEASE_ALL,
    BBC_KEY_RETURN,
    BBC_KEY_SHIFT_LEFT,
    BBC_KEY_UP_ARROW,
    SPECIAL_KEYS,
    UnsupportedCharError,
    asciiToKeys,
    asciiToKeysRaw,
    resolveKeyName,
)


def testUppercaseLettersAreUnshifted() -> None:
    assert asciiToKeys("HELLO") == [
        (ord("H"), False),
        (ord("E"), False),
        (ord("L"), False),
        (ord("L"), False),
        (ord("O"), False),
    ]


def testLowercaseUpcasedSilently() -> None:
    # CAPS LOCK is on by default, so lowercase input still yields the
    # unshifted uppercase matrix key.
    assert asciiToKeys("hello") == asciiToKeys("HELLO")


def testDigitsUnshifted() -> None:
    assert asciiToKeys("1234567890") == [
        (ord(c), False) for c in "1234567890"
    ]


def testSpaceAndReturn() -> None:
    assert asciiToKeys(" ") == [(ord(" "), False)]
    assert asciiToKeys("\n") == [(BBC_KEY_RETURN, False)]


def testDoubleQuoteIsShiftedTwo() -> None:
    keys = asciiToKeys('"')
    assert keys == [(ord("2"), True)]


def testPrintHelloLine() -> None:
    keys = asciiToKeys('PRINT "HELLO"\n')
    expected = [
        (ord("P"), False),
        (ord("R"), False),
        (ord("I"), False),
        (ord("N"), False),
        (ord("T"), False),
        (ord(" "), False),
        (ord("2"), True),
        (ord("H"), False),
        (ord("E"), False),
        (ord("L"), False),
        (ord("L"), False),
        (ord("O"), False),
        (ord("2"), True),
        (BBC_KEY_RETURN, False),
    ]
    assert keys == expected


def testColonAndSemicolonUnshifted() -> None:
    # beebjit's matrix is PC-positional: BBC `:` lives on PC `'`,
    # BBC `;` lives on PC `;` directly.
    assert asciiToKeys(":;") == [
        (ord("'"), False),
        (ord(";"), False),
    ]


def testAtSignOnBackquoteCarrier() -> None:
    assert asciiToKeys("@") == [(ord("`"), False)]


def testStarUsesApostropheCarrierShifted() -> None:
    assert asciiToKeys("*") == [(ord("'"), True)]


def testUnsupportedCharRaises() -> None:
    with pytest.raises(UnsupportedCharError):
        asciiToKeys("é")


def testShiftKeyCodeIsCorrect() -> None:
    # Sanity check that the constant matches beebjit's published key code.
    assert BBC_KEY_SHIFT_LEFT == 133


def testSpecialKeyConstantsAreCorrect() -> None:
    # Sanity-check against beebjit's published key codes.
    assert BBC_KEY_ESCAPE == 128
    assert BBC_KEY_CAPS_LOCK == 135
    assert BBC_KEY_F1 == 137
    assert BBC_KEY_UP_ARROW == 146
    assert BBC_KEY_RELEASE_ALL == 255


def testResolveKeyNameAcceptsSymbolicNames() -> None:
    assert resolveKeyName("CAPS_LOCK") == 135
    assert resolveKeyName("RETURN") == 131
    assert resolveKeyName("ENTER") == 131


def testResolveKeyNameIsCaseInsensitive() -> None:
    assert resolveKeyName("caps_lock") == 135
    assert resolveKeyName("Escape") == 128


def testResolveKeyNamePassesThroughInt() -> None:
    assert resolveKeyName(65) == 65
    assert resolveKeyName(0) == 0
    assert resolveKeyName(255) == 255


def testResolveKeyNameRejectsOutOfRangeInt() -> None:
    with pytest.raises(ValueError):
        resolveKeyName(-1)
    with pytest.raises(ValueError):
        resolveKeyName(256)


def testResolveKeyNameRejectsUnknownName() -> None:
    with pytest.raises(ValueError):
        resolveKeyName("NOPE")


def testRawPreservesLowercase() -> None:
    # CAPS LOCK OFF: unshifted letter key produces lowercase, so
    # lower-case input lands as unshifted matrix key.
    assert asciiToKeysRaw("hello") == [
        (ord("H"), False),
        (ord("E"), False),
        (ord("L"), False),
        (ord("L"), False),
        (ord("O"), False),
    ]


def testRawShiftsUppercase() -> None:
    # CAPS LOCK OFF: uppercase input requires SHIFT to produce the
    # uppercase letter, inverse of the default `asciiToKeys`.
    assert asciiToKeysRaw("HELLO") == [
        (ord("H"), True),
        (ord("E"), True),
        (ord("L"), True),
        (ord("L"), True),
        (ord("O"), True),
    ]


def testRawMixedCaseAndDigits() -> None:
    assert asciiToKeysRaw("Hi 3") == [
        (ord("H"), True),
        (ord("I"), False),
        (ord(" "), False),
        (ord("3"), False),
    ]


def testRawPreservesReturnAndShiftedPunct() -> None:
    # Non-letter mappings match `asciiToKeys` exactly; only letter
    # case handling differs between the two.
    assert asciiToKeysRaw('"') == [(ord("2"), True)]
    assert asciiToKeysRaw("\n") == [(BBC_KEY_RETURN, False)]


def testSpecialKeysCoverageIsComplete() -> None:
    # Cheap guard against accidental removal of names used by the
    # MCP surface; the public list must at minimum include the keys
    # that `docs/debugger-protocol.md` enumerates.
    required = {
        "ESCAPE",
        "BACKSPACE",
        "TAB",
        "RETURN",
        "CTRL",
        "SHIFT_LEFT",
        "SHIFT_RIGHT",
        "CAPS_LOCK",
        "UP_ARROW",
        "DOWN_ARROW",
        "LEFT_ARROW",
        "RIGHT_ARROW",
        "DELETE",
        "HOME",
    }
    assert required.issubset(SPECIAL_KEYS.keys())
