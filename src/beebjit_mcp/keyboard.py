# SPDX-FileCopyrightText: 2026 Heisenberg (acscpt)
# SPDX-License-Identifier: MIT

"""ASCII to BBC key sequence mapping.

Pure translation layer between host-side ASCII text and the key codes
accepted by beebjit's debugger `keydown`/`keyup` commands. No IO, no
emulator dependency; the driver composes this module's output with
`tapKey` / `keyDown` / `keyUp`.

BBC keyboard model, relevant to translation:

* beebjit's `keydown` and `keyup` debugger commands accept
  uppercase ASCII (A-Z, 0-9) and a subset of punctuation as
  *direct* key codes
* Special keys (RETURN, SHIFT, ...) use beebjit codes 128-157
* CAPS LOCK is on by default on a cold BBC boot, so uppercase
  letters type as uppercase with no shift needed
* Characters produced by SHIFT + another key on a BBC UK layout
  (e.g. `"` = SHIFT + 2) are mapped to the underlying unshifted
  key; the driver holds SHIFT around the tap

v0.1 scope: uppercase letters, digits, space, newline (-> RETURN),
and enough shifted punctuation for typical BASIC immediate-mode
input. Lowercase ASCII is uppercased transparently so demo callers
do not have to track CAPS LOCK state.

Functions:
    asciiToKeys -- translate a string to (bbcKey, shifted) tuples

Exceptions:
    UnsupportedCharError -- no BBC matrix mapping for a given char
"""

from __future__ import annotations


# -----------------------------------------------------------------------
# beebjit special-key codes (128-157, plus 255 release-all)
# -----------------------------------------------------------------------

# Named codes below cover the 128-157 range and the special 255
# release-all code. Callers that want a specific physical key press
# without going through the ASCII layer use `SPECIAL_KEYS` or
# `resolveKeyName`.

BBC_KEY_ESCAPE: int = 128
BBC_KEY_BACKSPACE: int = 129
BBC_KEY_TAB: int = 130
BBC_KEY_RETURN: int = 131
BBC_KEY_CTRL: int = 132
BBC_KEY_SHIFT_LEFT: int = 133
BBC_KEY_SHIFT_RIGHT: int = 134
BBC_KEY_CAPS_LOCK: int = 135
BBC_KEY_F0: int = 136
BBC_KEY_F1: int = 137
BBC_KEY_F2: int = 138
BBC_KEY_F3: int = 139
BBC_KEY_F4: int = 140
BBC_KEY_F5: int = 141
BBC_KEY_F6: int = 142
BBC_KEY_F7: int = 143
BBC_KEY_F8: int = 144
BBC_KEY_F9: int = 145
BBC_KEY_UP_ARROW: int = 146
BBC_KEY_DOWN_ARROW: int = 147
BBC_KEY_LEFT_ARROW: int = 148
BBC_KEY_RIGHT_ARROW: int = 149
BBC_KEY_F11: int = 151
BBC_KEY_F12: int = 152
BBC_KEY_DELETE: int = 156
BBC_KEY_HOME: int = 157
BBC_KEY_RELEASE_ALL: int = 255

# F12 is what beebjit accepts for the BBC BREAK key (per beebjit's
# EXAMPLES file). Aliased so callers building a "reset" path do not
# need to know the F-key encoding.
BBC_KEY_BREAK: int = BBC_KEY_F12


# Public name -> code map. Names are the form callers pass to
# `key_down` / `key_up` MCP tools. Case-insensitive at the public
# API layer via `resolveKeyName`.
SPECIAL_KEYS: dict[str, int] = {
    "ESCAPE": BBC_KEY_ESCAPE,
    "BACKSPACE": BBC_KEY_BACKSPACE,
    "TAB": BBC_KEY_TAB,
    "RETURN": BBC_KEY_RETURN,
    "ENTER": BBC_KEY_RETURN,
    "CTRL": BBC_KEY_CTRL,
    "SHIFT_LEFT": BBC_KEY_SHIFT_LEFT,
    "SHIFT_RIGHT": BBC_KEY_SHIFT_RIGHT,
    "CAPS_LOCK": BBC_KEY_CAPS_LOCK,
    "F0": BBC_KEY_F0,
    "F1": BBC_KEY_F1,
    "F2": BBC_KEY_F2,
    "F3": BBC_KEY_F3,
    "F4": BBC_KEY_F4,
    "F5": BBC_KEY_F5,
    "F6": BBC_KEY_F6,
    "F7": BBC_KEY_F7,
    "F8": BBC_KEY_F8,
    "F9": BBC_KEY_F9,
    "UP_ARROW": BBC_KEY_UP_ARROW,
    "DOWN_ARROW": BBC_KEY_DOWN_ARROW,
    "LEFT_ARROW": BBC_KEY_LEFT_ARROW,
    "RIGHT_ARROW": BBC_KEY_RIGHT_ARROW,
    "F11": BBC_KEY_F11,
    "F12": BBC_KEY_F12,
    "DELETE": BBC_KEY_DELETE,
    "HOME": BBC_KEY_HOME,
    "RELEASE_ALL": BBC_KEY_RELEASE_ALL,
    "BREAK": BBC_KEY_BREAK,
}


# -----------------------------------------------------------------------
# Direct-map character sets
# -----------------------------------------------------------------------

# Punctuation that beebjit's keydown command accepts as a plain
# ASCII code without any shift. These are the characters we
# actually need for BASIC immediate-mode input; the table can grow as
# new use cases appear.
_DIRECT_PUNCT: tuple[str, ...] = (" ", ",", ".", "/", "-", ";")


# PC-to-BBC key translations. beebjit's matrix is addressed by PC
# keyboard scancodes, so BBC keys whose physical position does not
# match a PC key need an explicit carrier. Left side is the user
# character; right side is the PC ASCII code that lands on the BBC
# key's matrix position. These carriers were established by probing
# the debugger's keydown response.
_PC_CARRIER: dict[str, int] = {
    ":": ord("'"),
    "@": ord("`"),
}


# BBC UK layout shifted characters: the user-visible char on the
# left, the underlying unshifted BBC key code on the right. At tap
# time the driver holds SHIFT, and the BBC matrix produces the
# shifted character on its own.
_SHIFTED: dict[str, int] = {
    '"': ord("2"),
    "!": ord("1"),
    "#": ord("3"),
    "$": ord("4"),
    "%": ord("5"),
    "&": ord("6"),
    "'": ord("7"),
    "(": ord("8"),
    ")": ord("9"),
    "*": ord("'"),
    "+": ord(";"),
    "=": ord("-"),
    "?": ord("/"),
    "<": ord(","),
    ">": ord("."),
}


# -----------------------------------------------------------------------
# Exceptions
# -----------------------------------------------------------------------

class UnsupportedCharError(ValueError):
    """Raised when the input string contains a character we cannot type.

    Treated as a hard error rather than silently dropped so callers
    see exactly which character broke their sequence.
    """


# -----------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------

def asciiToKeys(text: str) -> list[tuple[int, bool]]:
    """Translate an ASCII string to a list of (bbcKey, shifted) tuples.

    Each tuple is one key-tap: the caller issues a SHIFT-held tap
    when `shifted` is true, a plain tap otherwise. Mixed sequences
    (some shifted, some not) are supported by composing taps; the
    caller is not expected to batch SHIFT events.

    Raises UnsupportedCharError for characters with no BBC keyboard
    matrix mapping.
    """

    out: list[tuple[int, bool]] = []

    for ch in text:

        # Newline is the explicit RETURN signal. Handled first so a
        # stray newline does not go through case-folding and hit the
        # A-Z branch.
        if ch == "\n":
            out.append((BBC_KEY_RETURN, False))
            continue

        # CAPS LOCK is on by default on a cold BBC boot, so uppercase
        # and lowercase both produce uppercase output without shift.
        # Upcasing here keeps callers free of CAPS-LOCK awareness.
        upper = ch.upper()

        if "A" <= upper <= "Z":
            out.append((ord(upper), False))
            continue

        if "0" <= ch <= "9":
            out.append((ord(ch), False))
            continue

        if ch in _DIRECT_PUNCT:
            out.append((ord(ch), False))
            continue

        # PC-carrier keys: the BBC key exists but sits at a PC
        # position whose ASCII does not match the BBC character.
        carrier = _PC_CARRIER.get(ch)

        if carrier is not None:
            out.append((carrier, False))
            continue

        # Shifted punctuation: the matrix key is the unshifted char's
        # code; the driver wraps the tap with SHIFT hold/release.
        shiftedKey = _SHIFTED.get(ch)

        if shiftedKey is not None:
            out.append((shiftedKey, True))
            continue

        raise UnsupportedCharError(
            f"no BBC key mapping for character {ch!r} (ord {ord(ch)})"
        )

    return out


def asciiToKeysRaw(text: str) -> list[tuple[int, bool]]:
    """Case-preserving variant of `asciiToKeys`.

    Assumes CAPS LOCK is OFF on the BBC (use `set_caps_lock(False)`
    to guarantee this state). Under that assumption an unshifted
    letter key produces lowercase, shifted produces uppercase -- the
    inverse of the CAPS-LOCK-ON default.

    Non-letter characters map the same way `asciiToKeys` does.
    """

    out: list[tuple[int, bool]] = []

    for ch in text:

        if ch == "\n":
            out.append((BBC_KEY_RETURN, False))
            continue

        # Letters preserve case by deciding SHIFT from the original
        # character rather than collapsing to uppercase up front. The
        # matrix key itself is always the uppercase ASCII code.
        if "a" <= ch <= "z":
            out.append((ord(ch.upper()), False))
            continue

        if "A" <= ch <= "Z":
            out.append((ord(ch), True))
            continue

        if "0" <= ch <= "9":
            out.append((ord(ch), False))
            continue

        if ch in _DIRECT_PUNCT:
            out.append((ord(ch), False))
            continue

        carrier = _PC_CARRIER.get(ch)
        if carrier is not None:
            out.append((carrier, False))
            continue

        shiftedKey = _SHIFTED.get(ch)
        if shiftedKey is not None:
            out.append((shiftedKey, True))
            continue

        raise UnsupportedCharError(
            f"no BBC key mapping for character {ch!r} (ord {ord(ch)})"
        )

    return out


def resolveKeyName(name: str | int) -> int:
    """Return the BBC key code for a symbolic name or pass through an int.

    Symbolic names are matched case-insensitively against
    `SPECIAL_KEYS` (so `"caps_lock"`, `"CAPS_LOCK"`, and `"Caps_Lock"`
    all resolve to 135). A plain integer is accepted as a raw key
    code and returned unchanged after a 0-255 range check, which lets
    callers mix named special keys with ASCII codes (`ord("A")`) in
    the same tool call.
    """

    if isinstance(name, int):
        if not 0 <= name <= 255:
            raise ValueError(f"raw key code out of range: {name}")
        return name

    upper = name.upper()
    code = SPECIAL_KEYS.get(upper)
    if code is None:
        supported = ", ".join(sorted(SPECIAL_KEYS))
        raise ValueError(
            f"unknown key name {name!r}; supported: {supported}"
        )
    return code
