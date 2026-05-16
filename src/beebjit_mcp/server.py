# SPDX-FileCopyrightText: 2026 Heisenberg (acscpt)
# SPDX-License-Identifier: MIT

"""MCP server exposing the beebjit driver as JSON-RPC tools.

Thin wiring layer: every tool translates a JSON-RPC call to a
`BeebjitDriver` method and serialises the result. Anything more
substantive (protocol parsing, keyboard layout, screen decode)
lives in its own module.

Session model:

* `create_machine` spawns a `BeebjitDriver` and returns a UUID
* the UUID is the session handle for every subsequent tool
* `destroy_machine` tears the driver down and drops the entry
* sessions are kept in an in-process dict; this process owns one
  set of sessions for its lifetime

Binary discovery order:

1. `$BEEBJIT` env var (absolute path to an executable file)
2. `beebjit` on `$PATH` (via `shutil.which`)
3. hard error with a clear message pointing at install docs

No auto-download, no bundling: the user installs beebjit themselves
(licence-motivated -- see docs/architecture.md).
"""

from __future__ import annotations

import base64
import importlib
import os
import shutil
import sys
import uuid
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from beebjit_mcp.image import bgraToPng
from beebjit_mcp.driver import BeebjitDriver
from beebjit_mcp.keyboard import BBC_KEY_CAPS_LOCK, resolveKeyName
from beebjit_mcp.screen import Mode7Controls, decodeMode7


# -----------------------------------------------------------------------
# MCP app and session registry
# -----------------------------------------------------------------------

# FastMCP handles the JSON-RPC / stdio framing; we only register tools
# and let it run its own event loop in `main()`.
mcp: FastMCP = FastMCP("beebjit-mcp")


# One dict per process. MCP stdio is a single client per server, so
# there is no authentication concern; concurrent sessions exist only
# to support clients that want multiple BBCs in parallel.
_sessions: dict[str, BeebjitDriver] = {}


# -----------------------------------------------------------------------
# Internal helpers
# -----------------------------------------------------------------------

def _discoverBinary() -> Path:
    """Locate the beebjit binary by env var or `$PATH`.

    Raises `FileNotFoundError` with a clear message if nothing is
    found; the error message is what the user sees on a fresh
    install and needs to point at the install docs.
    """

    # Env var takes priority: lets a user force a specific build
    # (e.g. the fork on `test-integration`) without polluting PATH.
    env = os.environ.get("BEEBJIT")

    if env:
        path = Path(env)

        # Exist-and-executable check here so a stale env var gives
        # a useful message rather than deferring to the subprocess.
        if path.is_file() and os.access(path, os.X_OK):
            return path

        raise FileNotFoundError(
            f"$BEEBJIT points at {env!r} which is not an executable file"
        )

    # Fall back to $PATH. `shutil.which` handles the platform-specific
    # extension lookup (Windows `.exe`) should we ever support it.
    which = shutil.which("beebjit")
    if which is not None:
        return Path(which)

    raise FileNotFoundError(
        "beebjit binary not found. Set $BEEBJIT or put beebjit on $PATH."
    )


def _getDriver(sessionId: str) -> BeebjitDriver:
    """Look up a driver by session id. Raises KeyError if unknown.

    Kept separate from the tools so every tool has a one-liner
    "resolve or fail" at the top, and so future authorisation
    logic has a single hook point.
    """

    drv = _sessions.get(sessionId)

    if drv is None:
        raise KeyError(f"no such session: {sessionId}")

    return drv


def _resolveKey(key: str | int) -> int:
    """Translate a `key_down`/`key_up` argument into a raw BBC key code.

    Three input shapes, in order of specificity:

    1. Integer -> passthrough (0-255 range-checked).
    2. Single-character string -> matrix position for that char. The
       BBC keys letters are ASCII-upper, so a lowercase letter is
       upper-cased first; other single characters go through `ord`.
       For PC-carrier cases (`:` via `'`, `@` via `` ` ``) the
       caller should use `type_input` instead.
    3. Multi-character string -> `SPECIAL_KEYS` lookup
       (case-insensitive) via `resolveKeyName`.
    """

    if isinstance(key, int):
        return resolveKeyName(key)

    if len(key) == 1:
        ch = key.upper() if key.isalpha() else key
        return resolveKeyName(ord(ch))

    return resolveKeyName(key)


# -----------------------------------------------------------------------
# Lifecycle tools
# -----------------------------------------------------------------------

@mcp.tool()
def create_machine(model: str = "b", disc: str | None = None) -> dict[str, str]:
    """Boot a BBC Micro session. Returns a `session_id` for subsequent tools.

    `model` selects the BBC variant. Accepted values are `b` (BBC B,
    default), `master` (Master 128 with MOS 3.20), `mos35` (Master 128
    with MOS 3.50), and `compact` (Master Compact). `disc` is an
    optional path to a disc image, mounted into drive 0 at runtime and
    SHIFT+BREAK autobooted. The disc is mounted read-only; for
    writeable or host-mutating mounts call `load_disc` directly.

    Disc-image format follows from the model: BBC B and the two Master
    128 variants read DFS images (`.ssd` and `.dsd`); Master Compact
    reads ADFS images (`.adl` and `.adf`). The fork's `loaddisc`
    accepts all four extensions; the BBC's filing system on the other
    side reads what it understands.
    """

    # Resolve the binary first so the user sees a useful error at
    # session start, not later when a tool fails mid-run.
    binary = _discoverBinary()

    # Validate the disc path Python-side before spawning, so a typo
    # fails fast with a clean error rather than after subprocess setup.
    discPath: Path | None = None
    if disc:
        discPath = Path(disc)
        if not discPath.is_file():
            raise FileNotFoundError(f"disc image not found: {disc}")

    # Spawn and wait for the first debugger prompt. Blocks until
    # beebjit is ready (or raises on failure to start).
    driver = BeebjitDriver(binary, model=model)
    driver.start()

    # Cold-boot autoboot: SHIFT held from cycle 0 and disc mounted
    # before MOS init runs. Equivalent to a user holding SHIFT before
    # powering on with a disc inserted, and the only path that fires
    # autoboot uniformly across BBC B, Master 128 / MOS 3.20, Master
    # 128 / MOS 3.50, and Master Compact. A mid-session SHIFT+BREAK
    # via `reset(autoboot=True)` works on three of those models but
    # silently misses on MOS 3.50.
    if discPath is not None:
        driver.coldBootWithAutoboot(0, discPath)

    # UUID4 session id: opaque to callers, collision-free for all
    # realistic session counts.
    sessionId = str(uuid.uuid4())
    _sessions[sessionId] = driver

    return {"session_id": sessionId}


@mcp.tool()
def load_disc(
    session_id: str,
    disc: str,
    drive: int = 0,
    writeable: bool = False,
    mutable: bool = False,
) -> dict[str, object]:
    """Mount a disc image into the named drive at runtime.

    Drives are 0 or 1 (the BBC has two physical drives in its
    matrix; beebjit exposes both). `writeable` cuts the write-protect
    notch so the BBC can write to the in-memory image; `mutable`
    flushes those writes back to the host file. `mutable` requires
    `writeable`. Both default false: the disc is read-only and the
    host file is never modified.

    The mount does not trigger a reset or autoboot: the BBC keeps
    its current state and the new disc is available for the next OS
    read. Use `boot_disc` for the mount + SHIFT+BREAK autoboot
    one-shot, or compose `load_disc` with `reset(autoboot=True)`.
    """

    drv = _getDriver(session_id)

    # Python-side existence check so the caller sees a clean
    # FileNotFoundError before the debugger gets the command. The
    # fork would also catch this (`loaddisc: failed`) but its message
    # is generic; ours points at the missing path.
    discPath = Path(disc)
    if not discPath.is_file():
        raise FileNotFoundError(f"disc image not found: {disc}")

    drv.loadDisc(drive, discPath, writeable=writeable, mutable=mutable)

    return {
        "ok": True,
        "drive": drive,
        "disc": str(discPath),
        "writeable": writeable,
        "mutable": mutable,
    }


@mcp.tool()
def boot_disc(
    session_id: str,
    disc: str,
    drive: int = 0,
    writeable: bool = False,
    mutable: bool = False,
) -> dict[str, object]:
    """Mount a disc and SHIFT+BREAK autoboot it in one call.

    Equivalent to `load_disc` followed by `reset(autoboot=True)`,
    bundled so the common "load and run" workflow is a single tool
    call. Same parameters as `load_disc`. The gesture matches a real
    user holding SHIFT and pressing BREAK on a running BBC after
    inserting a disc; the running BBC's state is otherwise preserved
    through the soft reset.

    Blocks until the boot banner reappears in MODE 7 screen RAM, so
    the call returns with the disc's `!BOOT` already running (or
    already finished).
    """

    drv = _getDriver(session_id)

    discPath = Path(disc)
    if not discPath.is_file():
        raise FileNotFoundError(f"disc image not found: {disc}")

    drv.loadDisc(drive, discPath, writeable=writeable, mutable=mutable)
    drv.reset(autoboot=True)

    return {
        "ok": True,
        "drive": drive,
        "disc": str(discPath),
        "writeable": writeable,
        "mutable": mutable,
    }


@mcp.tool()
def destroy_machine(session_id: str) -> dict[str, bool]:
    """Tear down a session and release its beebjit subprocess.

    Returns `{"ok": False}` if the session id is not recognised;
    this is not an error because double-destroy on client error
    is common and should not crash the server.
    """

    # Pop before close so a subsequent call cannot pick up a
    # half-torn-down driver.
    driver = _sessions.pop(session_id, None)

    if driver is None:
        return {"ok": False}

    driver.close()
    return {"ok": True}


@mcp.tool()
def reset(
    session_id: str,
    autoboot: bool = False,
) -> dict[str, bool]:
    """Hard-reset the BBC without destroying the session.

    Equivalent to a user pressing BREAK on the real keyboard.
    With `autoboot=True`, holds SHIFT across the BREAK so an
    inserted disc's `!BOOT` runs after reset (the BBC equivalent
    of SHIFT+BREAK).
    """

    drv = _getDriver(session_id)
    drv.reset(autoboot=autoboot)
    return {"ok": True}


# -----------------------------------------------------------------------
# Execution tools
# -----------------------------------------------------------------------

@mcp.tool()
def run_for_cycles(session_id: str, cycles: int) -> dict[str, object]:
    """Advance the emulator by `cycles` BBC cycles.

    Returns the number of cycles just consumed plus the total
    cycle count so the client can track session progress without
    a separate `read_registers` round trip.
    """

    drv = _getDriver(session_id)
    drv.runCycles(cycles)

    # Cycles-total from a fresh register read, not a local counter:
    # beebjit may over-shoot `breakat` by a handful of cycles, and
    # the live value is the canonical one.
    regs = drv.readRegisters()
    return {"ok": True, "cycles_ran": cycles, "cycles_total": regs["cycles"]}


@mcp.tool()
def run_until_prompt(
    session_id: str,
    prompt: str = ">",
    max_cycles: int = 20_000_000,
    chunk_cycles: int = 500_000,
) -> dict[str, object]:
    """Run in chunks until `prompt` appears at the start of a MODE 7 row.

    Convenience wrapper for the common "wait for BASIC to return
    to the `>` prompt" pattern. Differs from `run_until_text` by
    anchoring the match to the beginning of a row: a bare `>`
    mid-line (e.g. inside the typed command itself) does not
    count. Defaults to `">"` which is the standard BBC BASIC
    prompt.
    """

    drv = _getDriver(session_id)
    totalRun = 0

    while totalRun < max_cycles:

        drv.runCycles(chunk_cycles)
        totalRun += chunk_cycles

        fb = drv.captureMode7Bytes()
        rows = decodeMode7(fb)

        # Row-anchored match. Right-strip to ignore trailing spaces
        # and catch `">"` on a line that has the prompt but nothing
        # typed after it yet.
        if any(row.lstrip().startswith(prompt) for row in rows):
            return {
                "ok": True,
                "found": True,
                "cycles_ran": totalRun,
                "prompt": prompt,
            }

    return {
        "ok": False,
        "found": False,
        "cycles_ran": totalRun,
        "prompt": prompt,
    }


@mcp.tool()
def run_until_text(
    session_id: str,
    needle: str,
    max_cycles: int = 20_000_000,
    chunk_cycles: int = 500_000,
) -> dict[str, object]:
    """Run in chunks until `needle` appears in the MODE 7 screen.

    Returns early as soon as the text is found. Returns with
    `found=False` if `max_cycles` elapsed without a match. The
    chunk size trades responsiveness (shorter = checks more
    often) against overhead (shorter = more memory reads).
    """

    drv = _getDriver(session_id)
    totalRun = 0

    # Chunk loop: run a fixed slice, check the framebuffer, repeat.
    # We check AFTER running at least one chunk so an uninitialised
    # screen full of random bytes does not accidentally match on
    # the very first call.
    while totalRun < max_cycles:

        drv.runCycles(chunk_cycles)
        totalRun += chunk_cycles

        # Read the framebuffer in display order each iteration.
        # `captureMode7Bytes` handles hardware-scroll rotation, so
        # the decoded rows match what a human sees on the screen
        # even after many PRINT statements have scrolled content.
        fb = drv.captureMode7Bytes()
        joined = "\n".join(decodeMode7(fb))

        if needle in joined:
            return {"ok": True, "found": True, "cycles_ran": totalRun}

    # Timed out without a match. `ok=False` plus `found=False` lets
    # the client choose between "retry with larger budget" and
    # "report the failure".
    return {"ok": False, "found": False, "cycles_ran": totalRun}


# -----------------------------------------------------------------------
# Input tool
# -----------------------------------------------------------------------

@mcp.tool()
def type_input(session_id: str, text: str) -> dict[str, object]:
    """Type an ASCII string into the BBC keyboard.

    Uses the default keypress timings (HOLD=5M, GAP=5M BBC
    cycles). Use `\\n` to submit a line. Raises via the underlying
    `UnsupportedCharError` if the string contains a character with
    no BBC matrix mapping.
    """

    drv = _getDriver(session_id)
    drv.typeText(text)

    # `chars` is the ASCII char count, not the key-event count, so
    # the client has a stable number regardless of shifted vs
    # unshifted composition inside the driver.
    return {"ok": True, "chars": len(text)}


@mcp.tool()
def run_basic(
    session_id: str,
    program: str,
    boot_cycles: int = 5_000_000,
    settle_cycles: int = 20_000_000,
) -> dict[str, object]:
    """Type a BBC BASIC program, RUN it, and return the final screen.

    Convenience wrapper around `type_input` + cycle runs. `program`
    is the full BASIC source; each line must carry its own line
    number (this tool does not auto-number). A leading `NEW` is
    issued first so the program runs in a clean workspace.

    `boot_cycles` gives BASIC time to reach the prompt after NEW;
    `settle_cycles` is the max BBC cycle budget for the program's
    own execution after RUN.

    Returns the MODE 7 screen as `rows` (list of 25 lines) and
    `text` (newline-joined) so callers can assert on either shape.
    """

    drv = _getDriver(session_id)

    # Clear any previous program so RUN does not see stale lines.
    # The trailing `\n` triggers RETURN inside `typeText`.
    drv.typeText("NEW\n")
    drv.runCycles(boot_cycles)

    # Type the program verbatim. A trailing newline on the last
    # line is normalised so RUN has a clean prompt to return to.
    if not program.endswith("\n"):
        program = program + "\n"
    drv.typeText(program)

    # RUN it and wait the settle budget. We do not poll for a
    # prompt here: some programs loop forever or print without
    # returning to `>`, and the caller may want to read the screen
    # mid-program. `run_until_prompt` is the right tool for
    # prompt-terminated programs.
    drv.typeText("RUN\n")
    drv.runCycles(settle_cycles)

    fb = drv.captureMode7Bytes()
    rows = decodeMode7(fb)
    return {"ok": True, "rows": rows, "text": "\n".join(rows)}


@mcp.tool()
def type_input_raw(session_id: str, text: str) -> dict[str, object]:
    """Type an ASCII string, preserving case.

    Requires CAPS LOCK to be OFF. Call `set_caps_lock(session_id,
    False)` first if the session is at its cold-boot default of
    CAPS LOCK ON. Case mismatches produce the wrong letter; no
    silent fallback.
    """

    drv = _getDriver(session_id)
    drv.typeTextRaw(text)
    return {"ok": True, "chars": len(text)}


@mcp.tool()
def key_down(session_id: str, key: str | int) -> dict[str, object]:
    """Inject a raw BBC keydown event into the matrix.

    `key` is either a symbolic name (`"A"`, `"CAPS_LOCK"`,
    `"LEFT_ARROW"`, ...) or an integer key code. Single-character
    ASCII strings (`"A"`) are accepted and treated as the
    corresponding matrix position; everything longer goes through
    `SPECIAL_KEYS`. The press stays held until a matching
    `key_up`; callers that want a tap should use `type_input`
    instead, which handles the HOLD/GAP timing.
    """

    drv = _getDriver(session_id)
    code = _resolveKey(key)
    drv.keyDown(code)
    return {"ok": True, "key": code}


@mcp.tool()
def press_caps_lock(session_id: str) -> dict[str, object]:
    """Tap CAPS LOCK once to toggle the current state.

    A pure toggle: the tool does not know or care about the
    pre-tap state. Use `set_caps_lock(on)` if you need a
    deterministic final state; that tool reads the MOS caps-lock
    flag and presses only if needed.
    """

    drv = _getDriver(session_id)
    drv.tapKey(BBC_KEY_CAPS_LOCK)
    return {"ok": True, "key": BBC_KEY_CAPS_LOCK}


# MOS CAPS LOCK state lives at `&025A` bit 4. Clear (0) means ON;
# set (1) means OFF. See `project_caps_lock_byte.md` for the probe
# that identified this.
_CAPS_LOCK_BYTE: int = 0x025A
_CAPS_LOCK_BIT: int = 0x10


def _readCapsLockState(drv: BeebjitDriver) -> bool:
    """Return True if CAPS LOCK is currently ON."""
    return (drv.readMemory(_CAPS_LOCK_BYTE, 1)[0] & _CAPS_LOCK_BIT) == 0


@mcp.tool()
def set_caps_lock(session_id: str, on: bool) -> dict[str, object]:
    """Set CAPS LOCK to a specific state, tapping only if needed.

    Reads `&025A` to learn the current MOS CAPS LOCK state, taps
    key 135 once iff the current state differs from `on`. Returns
    the resulting state and whether a tap was issued, so callers
    can assert the final state without a follow-up `read_memory`.
    """

    drv = _getDriver(session_id)
    before = _readCapsLockState(drv)

    # Early-out so a caller can spam `set_caps_lock(True)` without
    # flipping state on every call; keeps the tool idempotent.
    if before == on:
        return {"ok": True, "tapped": False, "caps_lock_on": before}

    drv.tapKey(BBC_KEY_CAPS_LOCK)

    # Confirm via a second read rather than trusting the tap: if the
    # MOS was somehow in a state where our 5M-cycle hold was not seen
    # the caller needs to know, not silently get the wrong state.
    after = _readCapsLockState(drv)
    return {"ok": after == on, "tapped": True, "caps_lock_on": after}


@mcp.tool()
def key_up(session_id: str, key: str | int) -> dict[str, object]:
    """Inject a raw BBC keyup event into the matrix.

    Inverse of `key_down`. Accepts the same `key` formats.
    Sending `"RELEASE_ALL"` (code 255) clears every held key
    in one call.
    """

    drv = _getDriver(session_id)
    code = _resolveKey(key)
    drv.keyUp(code)
    return {"ok": True, "key": code}


# -----------------------------------------------------------------------
# Read-only inspection tools
# -----------------------------------------------------------------------

@mcp.tool()
def write_memory(session_id: str, addr: int, data: str) -> dict[str, object]:
    """Poke bytes into memory starting at `addr`.

    `data` is a hex string. Optional whitespace between bytes is
    tolerated, so `"4269AB"` and `"42 69 AB"` both write the same
    three bytes. Symmetric to `read_memory`, whose `hex` field can
    be round-tripped back in here.
    """

    drv = _getDriver(session_id)

    # Strip whitespace so the caller can paste a space-delimited
    # dump straight from `read_memory`'s output without re-formatting.
    cleaned = "".join(data.split())

    try:
        payload = bytes.fromhex(cleaned)
    except ValueError as exc:
        raise ValueError(f"invalid hex string: {exc}") from exc

    drv.writeMemory(addr, payload)
    return {"ok": True, "addr": addr, "length": len(payload)}


@mcp.tool()
def read_memory(session_id: str, addr: int, length: int) -> dict[str, str]:
    """Peek `length` bytes starting at `addr`. Returns hex and ASCII views.

    Dot-substitution in the ASCII view (non-printable -> `.`) is
    the convention a human already expects from `hexdump` and
    similar tools.
    """

    drv = _getDriver(session_id)
    data = drv.readMemory(addr, length)

    # Two parallel views: hex for machines, dotted ASCII for humans.
    # Assemble together so the two always correspond to the same
    # bytes (no risk of a re-read between them).
    asciiView = "".join(chr(b) if 0x20 <= b <= 0x7E else "." for b in data)
    return {"hex": data.hex(), "ascii": asciiView}


@mcp.tool()
def disassemble(
    session_id: str, addr: int, count: int = 20
) -> dict[str, object]:
    """Disassemble `count` 6502 instructions starting at `addr`.

    Returns a list of `{addr, info, text}` dicts. `info` is
    beebjit's per-line tag (`"ITRP"`, `"JIT"`, sometimes empty);
    `text` is the mnemonic and operands. `count` is capped at 20
    (beebjit's native batch size); for a longer disassembly loop
    by advancing to the address past the last instruction.
    """

    drv = _getDriver(session_id)
    items = drv.disassemble(addr, count)
    return {"ok": True, "instructions": items}


@mcp.tool()
def read_registers(session_id: str) -> dict[str, object]:
    """Return 6502 register state: A, X, Y, S, F (flag string), PC, cycles."""

    drv = _getDriver(session_id)

    # `dict(...)` copies the driver's dict so a future driver-side
    # mutation cannot leak through a cached reference.
    return dict(drv.readRegisters())


@mcp.tool()
def read_mode7_text(
    session_id: str, controls: Mode7Controls = Mode7Controls.SPACE
) -> dict[str, object]:
    """Capture the MODE 7 screen as 25 rows of teletext text.

    `controls` selects how non-printable bytes render:

    - "space" (default): single space, every row stays exactly 40
      characters wide. Best for substring assertions and any caller
      that indexes into rows by column.
    - "question": single `?`, every row stays exactly 40 characters
      wide. Useful when callers want non-printable cells visually
      distinct without decoding the byte value.
    - "escape": four-character `\\xNN` escape per non-printable
      byte. Row widths become variable; use when callers need the
      original byte value preserved in the decoded string.

    JSON callers send these as the literal strings; Pydantic
    coerces them to `Mode7Controls` members before this function
    runs, and rejects unknown values at the wire boundary.

    Returns both the raw row list and a `\\n`-joined single string
    so callers can use whichever view they prefer.
    """

    drv = _getDriver(session_id)

    # One read, one decode. Keeping both views (rows + joined) is
    # cheap and saves callers a common composition step.
    fb = drv.captureMode7Bytes()
    rows = decodeMode7(fb, controls=controls)
    return {"rows": rows, "text": "\n".join(rows)}


@mcp.tool()
def screenshot(session_id: str) -> dict[str, object]:
    """Capture the current rendered BBC screen as a PNG.

    Returns base64-encoded PNG bytes plus the rendered width and
    height in pixels. Works in any BBC display mode: beebjit does
    the rendering, this tool just packages the result. Requires a
    fork binary that supports `-headless-render` and the
    `savescreen` debugger command; older binaries surface a
    structured error pointing at the install docs.
    """

    drv = _getDriver(session_id)

    # captureScreen returns BGRA + dimensions parsed from beebjit's
    # own savescreen line, so MCP-side never has to guess at the
    # render geometry.
    bgra, width, height = drv.captureScreen()

    png = bgraToPng(bgra, width, height)

    return {
        "format": "png",
        "bytes": base64.b64encode(png).decode("ascii"),
        "width": width,
        "height": height,
    }


# -----------------------------------------------------------------------
# Development aids
# -----------------------------------------------------------------------

# Which names each pure module exports into which dependents. Used by
# `reload_module` to re-bind after `importlib.reload` replaces the
# function/constant objects in the source module -- the old references
# in `driver.py` and `server.py` would otherwise stay frozen on the
# pre-reload values.
_RELOAD_REBIND: dict[str, list[tuple[str, tuple[str, ...]]]] = {
    "keyboard": [
        (
            "beebjit_mcp.driver",
            ("BBC_KEY_SHIFT_LEFT", "asciiToKeys", "asciiToKeysRaw"),
        ),
        (
            "beebjit_mcp.server",
            ("BBC_KEY_CAPS_LOCK", "resolveKeyName"),
        ),
    ],
    "screen": [
        (
            "beebjit_mcp.driver",
            (
                "MODE7_BASE_ADDR",
                "MODE7_BYTES",
                "MODE7_PAGE_BYTES",
                "rotateMode7Page",
            ),
        ),
        ("beebjit_mcp.server", ("decodeMode7",)),
    ],
}


@mcp.tool()
def reload_module(module_name: str) -> dict[str, object]:
    """Reload a pure beebjit_mcp module without restarting the server.

    Intended for in-session development: edit `keyboard.py` or
    `screen.py`, call this tool, and the next tool call picks up
    the change. Only the pure (IO-free) modules are supported;
    reloading `driver` or `server` would invalidate live session
    objects and is rejected.
    """

    if module_name not in _RELOAD_REBIND:
        supported = ", ".join(sorted(_RELOAD_REBIND))
        raise ValueError(
            f"reload of {module_name!r} not supported; "
            f"supported modules: {supported}"
        )

    fqName = f"beebjit_mcp.{module_name}"
    target = sys.modules[fqName]
    importlib.reload(target)

    # After reload, rebind the names the dependents imported with
    # `from X import Y`. Without this step, `driver.asciiToKeys`
    # would still point at the pre-reload function object.
    reboundIn: list[str] = []
    for depFq, names in _RELOAD_REBIND[module_name]:
        dep = sys.modules[depFq]
        for name in names:
            setattr(dep, name, getattr(target, name))
        reboundIn.append(depFq)

    return {
        "ok": True,
        "reloaded": fqName,
        "rebound_in": reboundIn,
    }


# -----------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------

def main() -> None:
    """Run the server over stdio. Blocks until the client disconnects."""

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
