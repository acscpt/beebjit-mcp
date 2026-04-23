# SPDX-FileCopyrightText: 2026 Heisenberg (acscpt)
# SPDX-License-Identifier: MIT

"""Subprocess driver for beebjit's debugger.

Spawns a beebjit process in debug mode, exchanges commands over its
stdin/stdout pipes, and parses the human-readable debugger output
into structured Python values. Everything above this module
(`server.py`, higher-level helpers) stays free of subprocess and
pipe-handling details.

Protocol model:

* beebjit prints `(6502db) ` (no trailing newline) and flushes
  whenever it is ready for a command. That prompt is the framing
  signal: a command is complete when the next prompt arrives.
* Each command is followed by zero or more output lines, then a
  single prompt. Some commands produce two prompts back-to-back
  (see `debugger-protocol-notes.md` for the per-command quirks).
* Diagnostic logging from beebjit goes to *stderr* thanks to the
  `-log-stderr` fork patch, keeping stdout clean for parsing.

Threading model:

* One background thread drains stdout into `self._buf`, notifying
  a Condition variable on each chunk.
* A second thread drains stderr into a bounded ring (`_stderrBuf`)
  for diagnostic surfacing on failure.
* The main thread is the only sender; `sendCommand` writes, then
  waits on the Condition until `self._buf` ends with `_PROMPT`.
* Single-sender by construction: callers must not share a driver
  instance across threads without their own serialisation.

Cycle model:

* `runCycles(n)` uses `breakat <target>; c` to advance exactly
  `n` BBC cycles. Anchored to the current `cycles` register so
  repeated calls remain accurate without drift.
* Keypress timings are in BBC cycles; see
  `untracked/keypress-debug.md` for why the HOLD/GAP defaults
  are 5M / 5M cycles.
"""

from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from pathlib import Path
from types import TracebackType

from beebjit_mcp.keyboard import BBC_KEY_SHIFT_LEFT, asciiToKeys, asciiToKeysRaw
from beebjit_mcp.screen import (
    MODE7_BASE_ADDR,
    MODE7_BYTES,
    MODE7_PAGE_BYTES,
    rotateMode7Page,
)


# -----------------------------------------------------------------------
# Protocol framing constants
# -----------------------------------------------------------------------

# The debugger prompt. Nine bytes, no trailing newline, flushed by
# beebjit after every command. The driver uses the literal bytes
# (not a regex) as the completion marker for each command.
_PROMPT: bytes = b"(6502db) "


# `r` (registers) output line:
#   6502 [A=00 X=00 Y=00 S=FF F=nvdizc PC=E577 cycles=5000020]
_REG_RE: re.Pattern[bytes] = re.compile(
    rb"6502 \[A=([0-9A-F]{2}) X=([0-9A-F]{2}) Y=([0-9A-F]{2}) S=([0-9A-F]{2}) "
    rb"F=(.{8}) PC=([0-9A-F]{4}) cycles=(\d+)\]"
)


# `m <addr>` (memory dump) output line:
#   7C00: 20 20 20 20 ...  (16 hex bytes per row, four rows per cmd)
_MEM_LINE_RE: re.Pattern[bytes] = re.compile(
    rb"^([0-9A-F]{4}):((?:\s+[0-9A-F]{2}){16})\s"
)


# Hex-byte tokeniser used to split the 16 bytes out of the matched
# memory-line payload.
_HEX_BYTE_RE: re.Pattern[bytes] = re.compile(rb"[0-9A-F]{2}")


# `d <addr>` (disassemble) output line:
#   [ITRP] E000: JSR $E004
# Address-info tag can be empty brackets on some lines, hence the
# `[^\]]*` non-greedy match on any non-bracket chars.
_DISASS_LINE_RE: re.Pattern[bytes] = re.compile(
    rb"^\[([^\]]*)\] ([0-9A-F]{4}): (.+)$"
)


# beebjit's `debug_disass` always emits exactly 20 instructions. Used
# to know how many lines a single `d` call returns when accumulating
# longer requests.
_DISASS_LINES_PER_CALL: int = 20


# -----------------------------------------------------------------------
# Exceptions
# -----------------------------------------------------------------------

class BeebjitError(RuntimeError):
    """Raised for protocol or subprocess failures from beebjit.

    Wraps pipe-level failures (broken pipe, unexpected EOF) and
    protocol-level failures (unparseable register/memory output).
    The message always includes the stderr tail when available to
    keep post-mortem diagnostics self-contained.
    """


# -----------------------------------------------------------------------
# Driver
# -----------------------------------------------------------------------

class BeebjitDriver:
    """One beebjit subprocess + its debugger REPL, wrapped in Python.

    One instance per BBC session. Thread-safe only in the sense
    that the reader threads are internal; external callers must
    serialise their own access.
    """

    # ---- key-timing defaults -------------------------------------------
    #
    # The BBC MOS keyboard ISR takes surprisingly long (in BBC cycles)
    # to latch a matrix press into the OS input buffer, and longer
    # still to settle the system VIA back to "ready for next key"
    # after a release. See `untracked/keypress-debug.md` for the
    # investigation.
    #
    # Empirical floor (probe_timings.py): 3M HOLD has a ~40% drop rate
    # on a 7-char unshifted sequence; 5M HOLD / 5M GAP is 100% reliable
    # across dozens of trials including HELLO. Do not lower without
    # replacing the scheme with active OS-buffer verification.
    DEFAULT_KEY_HOLD_CYCLES: int = 5_000_000
    DEFAULT_KEY_GAP_CYCLES: int = 5_000_000

    def __init__(
        self,
        binaryPath: Path,
        discPath: Path | None = None,
        model: str = "b",
        cycles: int = 10**12,
    ) -> None:
        """Configure a driver; does not spawn the subprocess until `start()`.

        `cycles` is beebjit's total cycle cap (`-cycles` flag). The
        default is effectively unbounded for short-lived sessions
        but still guards against runaway CPU time if the client
        forgets to destroy the session.
        """

        # Paths and session config are immutable for the lifetime of
        # this driver; changing model or disc mid-session would need
        # a restart and is not supported.
        self._binaryPath: Path = Path(binaryPath)
        self._discPath: Path | None = (
            Path(discPath) if discPath is not None else None
        )
        self._model: str = model
        self._cycles: int = cycles

        # Subprocess and reader-thread handles are set by `start()`.
        # Kept as Optional so the "configured but not started" state
        # is explicit and checkable.
        self._process: subprocess.Popen[bytes] | None = None
        self._stdoutThread: threading.Thread | None = None
        self._stderrThread: threading.Thread | None = None

        # Reader-to-main synchronisation. The Condition guards both
        # the stdout buffer and the EOF flag; reader threads notify
        # after every chunk so `sendCommand` wakes promptly.
        self._cond: threading.Condition = threading.Condition()
        self._buf: bytes = b""

        # Stderr is a ring: keep the tail only, so a long-running
        # session does not balloon memory on a chatty log stream.
        self._stderrBuf: bytes = b""
        self._eof: bool = False

    # -----------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------

    def start(self, initialPromptTimeout: float = 10.0) -> None:
        """Spawn beebjit and block until the first debugger prompt.

        Raises `BeebjitError` if the subprocess exits before the
        prompt arrives (usually a config issue surfaced on stderr)
        or `TimeoutError` if beebjit is slow to reach cycle zero.
        """

        # `-debug` alone (no `-run`) gives control from cycle zero
        # with the debugger blocked at the first prompt. The plan
        # originally spec'd `-debug -run`; Stage 1 recon showed that
        # combination bypasses the initial prompt and makes framing
        # unreliable.
        argv: list[str] = [
            str(self._binaryPath),
            "-headless",
            "-debug",
            "-log-stderr",
            "-fast",
            "-cycles",
            str(self._cycles),
        ]

        # Disc mode: add `-0 <path>` and `-autoboot` so SHIFT+BREAK
        # equivalent boot runs automatically. Only set when the
        # caller supplied a disc; the no-disc path leaves the Beeb
        # at the BASIC prompt after ROM boot.
        if self._discPath is not None:
            argv.extend(["-0", str(self._discPath), "-autoboot"])

        # cwd must be the binary's directory: beebjit loads its OS
        # and language ROMs from `roms/` relative to cwd, not
        # relative to the binary. Running from anywhere else exits
        # with "BAILING: couldn't open roms/os12.rom".
        self._process = subprocess.Popen(
            argv,
            cwd=str(self._binaryPath.parent),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )

        # Reader threads are daemons: if the main thread crashes
        # before a clean `close()`, they go away with the process
        # rather than hang the interpreter shutdown.
        self._stdoutThread = threading.Thread(
            target=self._readStdout, name="beebjit-stdout", daemon=True
        )
        self._stderrThread = threading.Thread(
            target=self._readStderr, name="beebjit-stderr", daemon=True
        )
        self._stdoutThread.start()
        self._stderrThread.start()

        # Block here until the first prompt arrives (or timeout).
        # This is the "machine is up and ready for commands" gate
        # that every other method depends on.
        self._waitForFirstPrompt(initialPromptTimeout)

    def close(self) -> None:
        """Send `q`, wait for exit, join readers. Idempotent.

        Uses a bounded wait before hard-killing: five seconds is
        enough for beebjit's clean shutdown under any reasonable
        host load, and beyond that we prefer to guarantee process
        reclamation over a polite exit.
        """

        # Idempotent: if we never started, or a previous close()
        # already ran, do nothing. Makes this safe to call from
        # both __exit__ and explicit teardown paths.
        if self._process is None:
            return

        proc = self._process

        # Polite quit first. stdin may already be closed if beebjit
        # exited on its own (e.g. -cycles cap hit); swallow the
        # resulting error and fall through to wait/kill.
        if proc.poll() is None and proc.stdin is not None:
            try:
                proc.stdin.write(b"q\n")
                proc.stdin.flush()
                proc.stdin.close()
            except (BrokenPipeError, ValueError, OSError):
                pass

        # Bounded wait then forced kill: whichever happens first,
        # the process is reaped. Long hangs here almost always mean
        # beebjit is stuck in a JIT compile or similar; we prefer
        # SIGKILL over a wedged test run.
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

        # Readers are daemons but joining here keeps test-harness
        # resource leaks out of the output. Short join timeouts
        # guard against any os.read() that is still mid-syscall.
        if self._stdoutThread is not None:
            self._stdoutThread.join(timeout=2)
        if self._stderrThread is not None:
            self._stderrThread.join(timeout=2)

        self._process = None
        self._stdoutThread = None
        self._stderrThread = None

    # -----------------------------------------------------------------
    # Reader threads and framing
    # -----------------------------------------------------------------

    def _readStdout(self) -> None:
        """Drain stdout into `self._buf`. Runs in a dedicated thread.

        Uses raw `os.read` rather than `readline` / iteration: the
        prompt has no newline, so a line-based reader would never
        return until the *next* command's output arrives.
        """

        proc = self._process
        assert proc is not None and proc.stdout is not None
        fd = proc.stdout.fileno()

        try:
            while True:
                chunk = os.read(fd, 4096)
                # Zero-length read means EOF on the pipe. Any
                # outstanding waiter needs to learn we are done.
                if not chunk:
                    break

                # Hold the Condition for both the append and the
                # notify so a waiter cannot miss the wakeup.
                with self._cond:
                    self._buf += chunk
                    self._cond.notify_all()
        except OSError:
            # Pipe closed mid-read during subprocess teardown is
            # normal; swallow and let the finally block flag EOF.
            pass
        finally:
            # Always flag EOF so `sendCommand` does not hang forever
            # after the subprocess dies.
            with self._cond:
                self._eof = True
                self._cond.notify_all()

    def _readStderr(self) -> None:
        """Drain stderr into a bounded ring. Runs in a dedicated thread."""

        proc = self._process
        assert proc is not None and proc.stderr is not None
        fd = proc.stderr.fileno()

        try:
            while True:
                chunk = os.read(fd, 4096)
                if not chunk:
                    break

                # Bounded ring: keep only the last 16KB of stderr.
                # Plenty for "what went wrong at the end" diagnostics,
                # and caps memory use for very long sessions.
                self._stderrBuf = (self._stderrBuf + chunk)[-16384:]
        except OSError:
            pass

    def _waitForFirstPrompt(self, timeout: float) -> None:
        """Block until stdout ends with `_PROMPT` or raise.

        The initial prompt arrives after beebjit has completed its
        ROM/JIT warmup. Ten seconds default is comfortably above
        the observed ~100ms cold start.
        """

        with self._cond:
            deadline = time.monotonic() + timeout

            while not self._buf.endswith(_PROMPT):

                # Early exit if the subprocess died before printing
                # its prompt. Surfacing the stderr tail here is the
                # difference between a useful failure and a silent
                # hang until timeout.
                if self._eof:
                    raise BeebjitError(
                        "beebjit exited before first prompt. stderr tail:\n"
                        + self._stderrBuf.decode("utf-8", errors="replace")
                    )

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        "no initial (6502db) prompt within timeout"
                    )
                self._cond.wait(timeout=remaining)

            # Consume the banner and prompt: subsequent commands
            # start from a clean buffer.
            self._buf = b""

    def sendCommand(self, cmd: str, timeout: float = 5.0) -> list[str]:
        """Send one debugger command, return its output lines.

        Command framing: write `<cmd>\\n`, wait for the next prompt,
        return everything between. The prompt itself is stripped.

        `timeout` is generous for most commands; `runCycles` passes
        a much larger one to cover long `c` operations.
        """

        if self._process is None or self._process.stdin is None:
            raise BeebjitError("driver not started")

        # Write the command. Broken-pipe here means beebjit exited
        # between commands (e.g. `-cycles` cap reached); surface as
        # BeebjitError rather than leak BrokenPipeError to callers.
        try:
            self._process.stdin.write((cmd + "\n").encode())
            self._process.stdin.flush()
        except (BrokenPipeError, ValueError, OSError) as exc:
            raise BeebjitError(f"beebjit stdin closed: {exc}") from exc

        # Wait for the trailing prompt. The Condition gets signalled
        # by the reader thread on every chunk, so this wakes promptly
        # as output arrives.
        with self._cond:
            deadline = time.monotonic() + timeout

            while not self._buf.endswith(_PROMPT):

                # EOF during a command means beebjit crashed or was
                # killed. Diagnose with the stderr tail so callers
                # do not have to separately scrape `stderrTail()`.
                if self._eof:
                    raise BeebjitError(
                        f"beebjit exited during command {cmd!r}. stderr tail:\n"
                        + self._stderrBuf.decode("utf-8", errors="replace")
                    )

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        f"no prompt within {timeout}s after {cmd!r}"
                    )
                self._cond.wait(timeout=remaining)

            # Slice off the trailing prompt and clear the buffer for
            # the next command. Done inside the lock so the reader
            # thread cannot append between slice and clear.
            payload = self._buf[: -len(_PROMPT)]
            self._buf = b""

        return payload.decode("utf-8", errors="replace").splitlines()

    # -----------------------------------------------------------------
    # Structured reads
    # -----------------------------------------------------------------

    def readRegisters(self) -> dict[str, int | str]:
        """Return 6502 register state from `r`.

        Integer values for numeric registers, string for flags `F`.
        The flags field preserves beebjit's literal "nvdizc" form so
        callers can re-display it unchanged.
        """

        lines = self.sendCommand("r")

        # Scan until the line matching _REG_RE: beebjit may emit
        # banner or breakpoint-info lines before the regs line on
        # some commands, so we do not assume a fixed position.
        for line in lines:
            match = _REG_RE.search(line.encode())
            if match is not None:
                return {
                    "A": int(match.group(1), 16),
                    "X": int(match.group(2), 16),
                    "Y": int(match.group(3), 16),
                    "S": int(match.group(4), 16),
                    "F": match.group(5).decode(),
                    "PC": int(match.group(6), 16),
                    "cycles": int(match.group(7)),
                }

        raise BeebjitError(f"could not parse registers from: {lines!r}")

    def readMemory(self, addr: int, length: int) -> bytes:
        """Peek `length` bytes starting at 16-bit address `addr`.

        Each `m` command dumps 4 rows x 16 bytes = 64 bytes. We
        loop, issuing further `m` commands at the next unread
        address, until the requested length has been accumulated.
        """

        # Defensive bounds: the 6502 address space is 16-bit, and a
        # length that straddles 0xFFFF should be rejected rather
        # than silently wrapping.
        if not 0 <= addr <= 0xFFFF:
            raise ValueError(f"addr out of range: {addr:#x}")
        if length < 0:
            raise ValueError(f"negative length: {length}")
        if length == 0:
            return b""
        if addr + length > 0x10000:
            raise ValueError("read would exceed address space")

        out = bytearray()
        cur = addr

        # Loop until we have collected at least `length` bytes. Each
        # `m` may return more than we need on the last iteration;
        # we trim at the end.
        while len(out) < length:
            lines = self.sendCommand(f"m {cur:x}")
            gotBytes = 0

            for line in lines:
                match = _MEM_LINE_RE.match(line.encode())
                if match is None:
                    continue

                # Each matched line contributes 16 bytes. Accumulate
                # and stop as soon as we have enough.
                hexBytes = _HEX_BYTE_RE.findall(match.group(2))
                out += bytes(int(b, 16) for b in hexBytes)
                gotBytes += len(hexBytes)

                if len(out) >= length:
                    break

            # If a command returned no parseable memory lines we
            # have a protocol drift (command rejected, beebjit
            # crashed, etc.). Better to fail loud here than to
            # silently loop.
            if gotBytes == 0:
                raise BeebjitError(
                    f"no memory lines parsed at {cur:#x}: {lines!r}"
                )

            cur += gotBytes

        # Trim to exactly the requested length (the last `m` likely
        # over-reads past `addr + length`).
        return bytes(out[:length])

    def disassemble(
        self, addr: int, count: int = _DISASS_LINES_PER_CALL
    ) -> list[dict[str, int | str]]:
        """Disassemble `count` 6502 instructions starting at `addr`.

        beebjit's `d` always emits 20 lines, so `count` is capped
        at 20 here to avoid fencepost errors re-anchoring across
        multiple calls. Callers wanting a longer run can loop by
        reading `result[-1]["addr"]` plus the displayed opcode
        length and issuing a second `disassemble`.

        Each entry is a dict with `addr` (int), `info` (the
        `[ITRP]`/`[JIT]`/... tag with brackets stripped; empty
        string if beebjit emitted empty brackets), and `text`
        (the mnemonic and operands exactly as beebjit printed them).
        """

        if not 0 <= addr <= 0xFFFF:
            raise ValueError(f"addr out of range: {addr:#x}")
        if not 1 <= count <= _DISASS_LINES_PER_CALL:
            raise ValueError(
                f"count must be 1..{_DISASS_LINES_PER_CALL}, got {count}"
            )

        lines = self.sendCommand(f"d {addr:x}")
        out: list[dict[str, int | str]] = []

        for line in lines:
            match = _DISASS_LINE_RE.match(line.encode())
            if match is None:
                continue
            out.append(
                {
                    "addr": int(match.group(2), 16),
                    "info": match.group(1).decode(),
                    "text": match.group(3).decode(),
                }
            )

        if not out:
            raise BeebjitError(
                f"no disassembly lines parsed at {addr:#x}: {lines!r}"
            )

        return out[:count]

    def captureMode7Bytes(self) -> bytes:
        """Return 1000 bytes of MODE 7 in display order.

        Handles hardware scroll: reads the full 1024-byte page at
        `&7C00` plus the MOS screen-start pointer at `&0350/&0351`,
        then rotates the page so byte 0 of the return value is the
        top-left cell as painted by the CRTC. Callers can pass the
        result straight to `screen.decodeMode7` regardless of how
        many scrolls have occurred.

        Pre-MOS-init the pointer at `&0350/&0351` is uninitialised
        RAM (typically `0xFFFF`). In that state we fall back to the
        page base address -- the decoded text will be arbitrary but
        callers polling during boot (e.g. `run_until_prompt`) can
        keep iterating without raising.
        """

        page = self.readMemory(MODE7_BASE_ADDR, MODE7_PAGE_BYTES)

        # `&0350/&0351` holds the screen-top CPU address low byte
        # first. On cold boot this is `&7C00`; each text-mode scroll
        # advances it by 40, wrapping within the 1024-byte page.
        ptr = self.readMemory(0x0350, 2)
        startAddr = ptr[0] | (ptr[1] << 8)

        # Clamp an uninitialised pointer back to the page base rather
        # than propagate a ValueError out of `rotateMode7Page`. The
        # MOS writes a valid pointer well before the BASIC prompt
        # arrives, so this only kicks in on the earliest poll cycles.
        if not (
            MODE7_BASE_ADDR
            <= startAddr
            < MODE7_BASE_ADDR + MODE7_PAGE_BYTES
        ):
            startAddr = MODE7_BASE_ADDR

        return rotateMode7Page(page, startAddr)

    # -----------------------------------------------------------------
    # Writes and execution
    # -----------------------------------------------------------------

    def writeMemory(self, addr: int, data: bytes) -> None:
        """Poke `data` into memory starting at `addr`.

        Each `writem` command lists its bytes inline, so very long
        writes would produce unwieldy command lines. We chunk into
        16-byte pieces, matching the natural row width of the read
        side and keeping the subprocess pipe well-behaved.
        """

        # Same bounds policy as readMemory: reject obvious caller
        # errors rather than wrapping around or splitting.
        if not 0 <= addr <= 0xFFFF:
            raise ValueError(f"addr out of range: {addr:#x}")
        if addr + len(data) > 0x10000:
            raise ValueError("write would exceed address space")
        if len(data) == 0:
            return

        chunkSize = 16

        # Emit one `writem` per chunk. beebjit processes each
        # silently (no output between prompt and prompt), so
        # latency is dominated by the prompt round-trip.
        for offset in range(0, len(data), chunkSize):
            chunk = data[offset : offset + chunkSize]
            hexArgs = " ".join(f"{b:x}" for b in chunk)
            self.sendCommand(f"writem {addr + offset:x} {hexArgs}")

    def runCycles(self, n: int, timeout: float = 30.0) -> None:
        """Advance the emulator by exactly `n` BBC cycles.

        Uses a cycle-anchored `breakat`: we read the current cycles
        register, set a breakpoint at `current + n`, and `c`ontinue.
        This keeps repeated calls accurate without drift, which
        matters for keypress-timing helpers that chain several
        short runs together.

        The default `timeout` covers a one-second BBC-time run at
        reasonable host speed; callers who schedule very long runs
        (tens of millions of cycles) should override.
        """

        if n <= 0:
            return

        # Anchor to current cycles rather than tracking a local
        # counter: beebjit is the source of truth and may advance
        # a few extra cycles between our `breakat` and its own
        # breakpoint check. Reading live avoids accumulated drift.
        regs = self.readRegisters()
        target = int(regs["cycles"]) + n

        self.sendCommand(f"breakat {target}")
        self.sendCommand("c", timeout=timeout)

    # -----------------------------------------------------------------
    # Keyboard input
    # -----------------------------------------------------------------

    def keyDown(self, key: int) -> None:
        """Low-level: inject a raw BBC keydown event into the matrix."""
        self.sendCommand(f"keydown {key}")

    def keyUp(self, key: int) -> None:
        """Low-level: inject a raw BBC keyup event into the matrix."""
        self.sendCommand(f"keyup {key}")

    def tapKey(
        self,
        key: int,
        holdCycles: int | None = None,
        gapCycles: int | None = None,
    ) -> None:
        """Press, hold for HOLD cycles, release, then idle GAP cycles.

        HOLD and GAP default to values proven reliable in the
        keypress investigation; callers can override for test
        acceleration but must not shorten without replacing the
        wait strategy (see `untracked/keypress-debug.md`).
        """

        # Resolve defaults lazily so the class-level constants stay
        # canonical and subclasses can override them.
        hold = holdCycles if holdCycles is not None else self.DEFAULT_KEY_HOLD_CYCLES
        gap = gapCycles if gapCycles is not None else self.DEFAULT_KEY_GAP_CYCLES

        # Four-step tap: down, hold, up, gap. The GAP phase lets
        # the BBC MOS clear its CA2-mask state so the next press
        # can raise a fresh interrupt.
        self.keyDown(key)
        self.runCycles(hold)
        self.keyUp(key)
        self.runCycles(gap)

    def tapShiftedKey(
        self,
        key: int,
        holdCycles: int | None = None,
        gapCycles: int | None = None,
    ) -> None:
        """Like `tapKey`, but with left-SHIFT held across the key's hold.

        SHIFT lives on row 0 of the BBC matrix and does not itself
        raise the keyboard CA2 interrupt. That means SHIFT only
        needs to be in the matrix at the moment the scan sees
        `key` pressed; we do not need a separate hold/gap dance
        for it.
        """

        hold = holdCycles if holdCycles is not None else self.DEFAULT_KEY_HOLD_CYCLES
        gap = gapCycles if gapCycles is not None else self.DEFAULT_KEY_GAP_CYCLES

        # Bracket the key's hold/release with SHIFT events. The gap
        # is applied once at the end, after SHIFT is released, so
        # the next tap sees a clean matrix.
        self.keyDown(BBC_KEY_SHIFT_LEFT)
        self.keyDown(key)
        self.runCycles(hold)
        self.keyUp(key)
        self.keyUp(BBC_KEY_SHIFT_LEFT)
        self.runCycles(gap)

    def typeText(
        self,
        text: str,
        holdCycles: int | None = None,
        gapCycles: int | None = None,
    ) -> None:
        """Type an ASCII string, taking care of SHIFT as needed.

        Translation is delegated to `keyboard.asciiToKeys` so the
        driver does not embed a keyboard layout. The driver is the
        only place that knows about cycle timing; the keyboard
        module is the only place that knows about character maps.
        """

        # Iterate key-by-key. A single `typeText` call may mix
        # shifted and unshifted taps; each tuple selects the right
        # helper. No batching: one tap per char keeps the BBC OS
        # between presses in its settled state.
        for key, shifted in asciiToKeys(text):
            if shifted:
                self.tapShiftedKey(key, holdCycles, gapCycles)
            else:
                self.tapKey(key, holdCycles, gapCycles)

    def typeTextRaw(
        self,
        text: str,
        holdCycles: int | None = None,
        gapCycles: int | None = None,
    ) -> None:
        """Case-preserving typeText. Requires CAPS LOCK to be OFF.

        Uses `keyboard.asciiToKeysRaw`, which shifts letters based on
        the input case. The caller is responsible for arranging
        CAPS LOCK OFF first (via `set_caps_lock(False)` at the MCP
        layer); calling this with CAPS LOCK ON inverts every letter.
        """

        for key, shifted in asciiToKeysRaw(text):
            if shifted:
                self.tapShiftedKey(key, holdCycles, gapCycles)
            else:
                self.tapKey(key, holdCycles, gapCycles)

    # -----------------------------------------------------------------
    # Diagnostics
    # -----------------------------------------------------------------

    def stderrTail(self) -> str:
        """Return the bounded stderr ring as a decoded string.

        Intended for post-mortem on BeebjitError. The ring is
        capped at 16KB so the return value is safe to log even
        after a long session.
        """

        return self._stderrBuf.decode("utf-8", errors="replace")

    # -----------------------------------------------------------------
    # Context-manager sugar
    # -----------------------------------------------------------------

    def __enter__(self) -> "BeebjitDriver":
        """Start on entry so `with BeebjitDriver(...) as drv:` is usable."""

        self.start()
        return self

    def __exit__(
        self,
        excType: type[BaseException] | None,
        excVal: BaseException | None,
        excTb: TracebackType | None,
    ) -> None:
        """Always close on exit, even on exception."""

        self.close()
