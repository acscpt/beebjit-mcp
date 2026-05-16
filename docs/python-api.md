# API

beebjit-MCP is primarily an MCP server for AI agent clients, exposing BBC Micro emulation through stdio JSON-RPC. The same package also exposes a Python library, where the same operations are available as methods on an in-process driver class. Both share the same driver, the same beebjit subprocess, and the same per-operation behaviour. The MCP tool reference is at [tool-reference.md](tool-reference.md); this page covers the library.

## When to use

Use the beebjit-MCP server for:

- AI agent control. The tools and their docstrings are written for that case.

- Callers outside Python. MCP's stdio JSON-RPC works from any language.

Use the library for:

- Test harnesses. A pytest run that needs to boot a BBC, exercise a disc image, and assert on the result runs in-process with no JSON-RPC framing in between.

- Scripted automation. A Jupyter notebook, a CLI tool, a one-off batch job. The class is small and reads naturally as Python.

- Direct control over timing and command ordering. `sendCommand` accepts any debugger command beebjit understands, without waiting for a typed wrapper to land.

The two are not exclusive. Both can run against the same project; each beebjit subprocess is independent.

## Installation

The library ships in the `beebjit-mcp` package. There is no separate install.

```bash
pip install beebjit-mcp
```

The beebjit binary is still required, since the library spawns it as a subprocess. The [installation guide](installation.md) covers binary install and the `$BEEBJIT` environment variable that the library uses to find it.

## Quickstart

A complete session that boots a BBC B, types a one-line BASIC program, runs it, and reads the screen back:

```python
from beebjit_mcp.driver import BeebjitDriver, BeebModel
from beebjit_mcp.screen import decodeMode7

with BeebjitDriver.fromEnvironment(model=BeebModel.B) as bbc:
    bbc.runCycles(5_000_000)
    bbc.typeText('PRINT "HELLO"\n')
    bbc.runCycles(2_000_000)

    page = bbc.captureMode7Bytes()
    for row in decodeMode7(page):
        print(row)
```

`fromEnvironment` locates the beebjit binary from `$BEEBJIT` first and then `beebjit` on `$PATH`, mirroring the discovery the MCP server uses. To pin a specific binary in code, pass the path directly: `BeebjitDriver("/path/to/beebjit", model=BeebModel.B)`.

The `with` block guarantees teardown. The five-million-cycle wait gives the MOS time to finish booting and land at the BASIC `>` prompt before the first keypress arrives. `typeText` resolves each character to a matrix key event with the right SHIFT handling. `captureMode7Bytes` grabs the teletext framebuffer page; `decodeMode7` turns those bytes into 25 rows of 40 characters.

## Conventions

- Methods return native Python values, not JSON dicts. `readMemory` returns `bytes`, `readRegisters` returns `dict[str, int | str]`, `captureScreen` returns a `(bgra, width, height)` tuple. The MCP server wraps these into JSON shapes for its tool layer; library callers see the raw values.

- Addresses and cycle counts are Python ints. Both `31744` and `0x7C00` parse to the same value. Hex literal form keeps BBC addresses self-documenting.

- Errors raise exceptions, never an `ok` flag. `BeebjitError` for protocol or subprocess failures, `ValueError` for argument validation, `TimeoutError` for host-side waits. The MCP tool layer translates these to JSON-RPC errors; library callers catch them directly.

- One driver instance owns one beebjit subprocess. Methods on a single driver are not safe to call from multiple threads concurrently. See [Concurrency](#concurrency).

- This documentation uses `&ADDR` for BBC memory addresses, matching the BBC Micro User Guide. Source code uses `0x`.

## Index

| Method | Category | Purpose |
| --- | --- | --- |
| [`BeebjitDriver(...)`](#beebjitdriver) | Lifecycle | Configure a driver for a BBC session |
| [`BeebjitDriver.fromEnvironment`](#fromenvironment) | Lifecycle | Auto-discover the binary and construct a driver |
| [`start`](#start) | Lifecycle | Spawn the beebjit subprocess |
| [`close`](#close) | Lifecycle | Tear the subprocess down |
| [`reset`](#reset) | Lifecycle | Hard-reset the BBC, optionally SHIFT+BREAK autoboot |
| [`coldBootWithAutoboot`](#coldbootwithautoboot) | Lifecycle | Cold-boot autoboot from cycle zero |
| [`loadDisc`](#loaddisc) | Disc | Mount a disc image into a drive at runtime |
| [`runCycles`](#runcycles) | Execution | Advance the emulator by exactly N BBC cycles |
| [`typeText`](#typetext) | Input | Type an ASCII string (CAPS LOCK on) |
| [`typeTextRaw`](#typetextraw) | Input | Type an ASCII string preserving case (CAPS LOCK off) |
| [`tapKey`](#tapkey) | Input | Press, hold, release, idle for one key |
| [`tapShiftedKey`](#tapshiftedkey) | Input | `tapKey` with left-SHIFT held across the press |
| [`keyDown`](#keydown-and-keyup) | Input | Low-level matrix key-down event |
| [`keyUp`](#keydown-and-keyup) | Input | Low-level matrix key-up event |
| [`readRegisters`](#readregisters) | State reads | Return 6502 register state |
| [`readMemory`](#readmemory) | State reads | Read a contiguous block of BBC RAM |
| [`disassemble`](#disassemble) | State reads | Disassemble 6502 instructions |
| [`captureMode7Bytes`](#capturemode7bytes) | State reads | Capture the MODE 7 framebuffer in display order |
| [`captureScreen`](#capturescreen) | State reads | Capture the rendered framebuffer as raw BGRA |
| [`writeMemory`](#writememory) | State writes | Poke bytes into memory |
| [`stderrTail`](#stderrtail) | Diagnostics | Return the bounded ring of beebjit stderr |
| [`sendCommand`](#sendcommand) | Diagnostics | Send one raw debugger command |
| [`asciiToKeys`](#asciitokeys) | Keyboard helpers | Translate a string to `(key, shifted)` tuples (CAPS LOCK on) |
| [`asciiToKeysRaw`](#asciitokeysraw) | Keyboard helpers | Translate a string preserving case (CAPS LOCK off) |
| [`resolveKeyName`](#resolvekeyname) | Keyboard helpers | Resolve a symbolic key name to a BBC scancode |
| [`decodeMode7`](#decodemode7) | Screen helpers | Decode a 1000-byte MODE 7 framebuffer into 25 rows |
| [`rotateMode7Page`](#rotatemode7page) | Screen helpers | Rotate a 1024-byte teletext page into display order |
| [`mode7TextContains`](#mode7textcontains) | Screen helpers | True if a needle appears anywhere in the decoded screen |
| [`bgraToPng`](#bgratopng) | Image helpers | Encode raw BGRA pixels as PNG bytes |

## Lifecycle

---

### `BeebjitDriver`

Configure a driver for a BBC session. The constructor does not spawn beebjit; [`start`](#start) does, or the context manager calls it on entry.

**Parameters**

- `binaryPath` *(Path)*: Path to the beebjit executable. For automatic discovery from `$BEEBJIT` or `$PATH`, use [`fromEnvironment`](#fromenvironment) instead.

- `model` *(str | BeebModel, default `BeebModel.B`)*: BBC hardware configuration. Either a `BeebModel` member or its wire string. The four values are:
  - `BeebModel.B` (`"b"`): BBC B with MOS 1.20 and the 8271 floppy controller.
  - `BeebModel.MASTER` (`"master"`): Master 128 with MOS 3.20.
  - `BeebModel.MOS35` (`"mos35"`): Master 128 with MOS 3.50.
  - `BeebModel.COMPACT` (`"compact"`): Master Compact.

  Disc-image format follows from the model. BBC B and the two Master 128 variants read DFS images (`.ssd` and `.dsd`); Master Compact reads ADFS images (`.adl` and `.adf`).

- `cycles` *(int, default `10**12`)*: beebjit `-cycles` cap, a circuit-breaker against orphaned processes. The default is one trillion BBC cycles, effectively unbounded for normal sessions.

**Returns**

A configured `BeebjitDriver` instance. No subprocess is running yet.

**Errors**

- `ValueError` if `model` is neither a `BeebModel` member nor a recognised wire string.

**Example**

```python
import os
from pathlib import Path
from beebjit_mcp.driver import BeebjitDriver, BeebModel

bbc = BeebjitDriver(
    Path(os.environ["BEEBJIT"]),
    model=BeebModel.MASTER,
    cycles=100_000_000,
)
```

**Notes**

The constructor is cheap. The expensive work is in [`start`](#start), which spawns beebjit and blocks until the first debugger prompt. Use the context manager unless manual lifecycle is unavoidable.

[^ Index](#index)

---

### `fromEnvironment`

Construct a driver after locating the beebjit binary automatically. Classmethod alternative to the explicit-path constructor.

**Parameters**

- `model` *(str | BeebModel, default `BeebModel.B`)*: BBC hardware configuration. Same shape as the constructor; see [`BeebjitDriver`](#beebjitdriver) for the four values.

- `cycles` *(int, default `10**12`)*: beebjit `-cycles` cap. Same meaning as the constructor.

**Returns**

A configured `BeebjitDriver`, ready for [`start`](#start) or use as a context manager.

**Errors**

- `FileNotFoundError` if neither `$BEEBJIT` nor `beebjit` on `$PATH` resolves to an executable file.

- `ValueError` if `model` is neither a `BeebModel` member nor a recognised wire string.

**Example**

```python
from beebjit_mcp.driver import BeebjitDriver, BeebModel

with BeebjitDriver.fromEnvironment(model=BeebModel.B) as bbc:
    bbc.runCycles(5_000_000)
```

**Notes**

Discovery order: `$BEEBJIT` first, then `beebjit` on `$PATH`. Matches the discovery the MCP server runs at startup.

For callers that need the path without constructing a driver, the underlying `discoverBinary()` function is also available: `from beebjit_mcp.driver import discoverBinary`.

[^ Index](#index)

---

### `start`

Spawn the beebjit subprocess and block until the first debugger prompt.

**Parameters**

- `initialPromptTimeout` *(float, default `10.0`)*: seconds to wait for beebjit to reach its first `(6502db)` prompt before raising.

**Returns**

`None`. The driver is ready for commands when the call returns.

**Errors**

- `BeebjitError` if the subprocess exits before the prompt arrives. The error message includes the stderr tail.

- `TimeoutError` if beebjit is slow to reach cycle zero within `initialPromptTimeout`.

**Example**

```python
bbc = BeebjitDriver(Path(os.environ["BEEBJIT"]))
bbc.start()
try:
    bbc.runCycles(5_000_000)
finally:
    bbc.close()
```

**Notes**

The context manager calls `start` on entry and `close` on exit, including the exception path. Use `with BeebjitDriver(...) as bbc:` unless the surrounding code rules it out.

[^ Index](#index)

---

### `close`

Tear the beebjit subprocess down and join the reader threads. Idempotent.

**Returns**

`None`. The driver is left in a stopped state; a fresh `BeebjitDriver` is required for another session.

**Example**

```python
bbc = BeebjitDriver(Path(os.environ["BEEBJIT"]))
bbc.start()
bbc.close()
bbc.close()  # second call is a no-op
```

**Notes**

The teardown sends `q` to the debugger, waits up to five seconds for clean exit, escalates to `SIGKILL` if needed, and removes the per-session temp dir. Idempotency keeps retry paths and finally-blocks simple.

The driver does not implement `__del__`, so garbage collection does not reclaim the subprocess. An abandoned driver leaks a beebjit process until the `-cycles` cap trips.

[^ Index](#index)

---

### `reset`

Hard-reset the BBC, equivalent to a user pressing BREAK. The 6502 cycle counter wraps, BASIC variables clear, and the boot banner reappears. The driver and its session stay valid.

**Parameters**

- `autoboot` *(bool, default `False`)*: Hold left-SHIFT across BREAK and through MOS's keyboard-matrix scan window so the OS picks up SHIFT+BREAK and runs the inserted disc's `!BOOT`.

**Returns**

`None`. The BBC is at a fresh BASIC prompt (or, with `autoboot=True`, the disc's `!BOOT` has already run).

**Example**

```python
bbc.reset()                  # back to BASIC prompt
bbc.reset(autoboot=True)     # SHIFT+BREAK to autoboot a mounted disc
```

**Notes**

The reset taps F12 to assert the 6502 RESET line, then advances the BBC for a fixed cycle budget generous enough for MOS init to settle on every supported model.

For mid-session "load a new disc and boot it" in one gesture, compose [`loadDisc`](#loaddisc) with `reset(autoboot=True)`. For cold-boot autoboot from cycle zero, use [`coldBootWithAutoboot`](#coldbootwithautoboot).

[^ Index](#index)

---

### `coldBootWithAutoboot`

Hold SHIFT in the matrix from cycle zero, mount a disc, advance cycles. Mirrors a real user holding SHIFT before powering on with a disc in.

**Parameters**

- `drive` *(int)*: BBC disc drive to mount into. Either `0` or `1`.

- `path` *(Path | str)*: Absolute path to a disc image (DFS `.ssd` / `.dsd`, or ADFS `.adl` / `.adf`).

- `writeable` *(bool, default `False`)*: Cut the write-protect notch so the BBC can write to the in-memory image.

- `mutable` *(bool, default `False`)*: Flush in-memory writes back to the host file. Requires `writeable=True`.

- `settleCycles` *(int, default `20_000_000`)*: Cycles to advance after the SHIFT-hold so the autoboot keyboard scan and the disc's `!BOOT` finish.

**Returns**

`None`. SHIFT is released after the settle window; the BBC is in the post-autoboot state.

**Errors**

- `ValueError` if `mutable=True` and `writeable=False`, or `drive` is not 0 or 1.

- `BeebjitError` if the underlying `loadDisc` is rejected by the fork's pre-check.

**Example**

```python
with BeebjitDriver(Path(os.environ["BEEBJIT"])) as bbc:
    bbc.coldBootWithAutoboot(0, "/path/to/game.ssd")
```

**Notes**

Must be called immediately after [`start`](#start), while the CPU is still at cycle 0. Calling it on a session that has already advanced cycles silently misses the boot keyboard-scan window because MOS init has already run.

Works across every supported model, including Master 128 / MOS 3.50, which ignores a mid-session SHIFT+BREAK. For mid-session autoboot, use `loadDisc` followed by `reset(autoboot=True)` instead.

[^ Index](#index)

## Disc

---

### `loadDisc`

Mount a disc image into a drive at runtime. The BBC keeps its current state; the new disc becomes available for the next OS read.

**Parameters**

- `drive` *(int)*: BBC disc drive. Either `0` or `1`.

- `path` *(Path | str)*: Absolute path to a disc image (DFS `.ssd` / `.dsd`, or ADFS `.adl` / `.adf`).

- `writeable` *(bool, default `False`)*: Cut the write-protect notch so the BBC can write to the in-memory image.

- `mutable` *(bool, default `False`)*: Flush in-memory writes back to the host file. Requires `writeable=True`.

**Returns**

`None`. The disc is mounted on success.

**Errors**

- `ValueError` if `mutable=True` without `writeable=True`, or `drive` is not 0 or 1.

- `BeebjitError` if beebjit's own pre-checks reject the mount (extension, slot count, file readability), if the binary is too old to recognise the `loaddisc` command, or if the response cannot be parsed.

**Example**

```python
bbc.loadDisc(0, "/path/to/game.ssd")
bbc.reset(autoboot=True)
```

**Notes**

`writeable` controls whether the BBC can modify the in-memory image; `mutable` controls whether those modifications persist back to the host file. The two flags compose: `writeable=True, mutable=False` is "writes survive in this session only, never reach disk", useful for save-game probes that should not perturb the source file.

The mount does not trigger a reset or autoboot. For mount + autoboot in one call from cycle zero, use [`coldBootWithAutoboot`](#coldbootwithautoboot); for mid-session autoboot, compose with [`reset`](#reset)`(autoboot=True)`.

[^ Index](#index)

## Execution

---

### `runCycles`

Advance the emulator by exactly `n` BBC cycles using a tick-anchored breakpoint.

**Parameters**

- `n` *(int)*: BBC cycles to advance. Non-positive values return immediately.

- `timeout` *(float, default `30.0`)*: host-side timeout on the underlying `c` (continue). Covers many billions of BBC cycles at `-fast` on a modern host. For longer runs, chunk from the caller side.

**Returns**

`None`. The post-run cycle counter can be read separately via [`readRegisters`](#readregisters).

**Errors**

- `BeebjitError` on a pipe or protocol failure.

- `TimeoutError` if `c` does not return within `timeout`.

**Example**

```python
bbc.runCycles(5_000_000)
regs = bbc.readRegisters()
print(regs["cycles"])
```

**Notes**

Cycle counting is anchored against beebjit's global `total_timer_ticks` counter (read live via `eval ticks` on each call). The driver reads ticks, computes `target = ticks + n`, sets `breakat target`, and issues `c`. Anchoring against ticks rather than the 6502-relative `cycles=` field is what makes the call survive a soft reset, since `cycles=` rebases on Break while ticks are monotonic. Chained calls do not accumulate drift.

beebjit can overshoot the breakpoint by a handful of instructions. The `cycles` field in `readRegisters()` reports the exact 6502-relative stopping point and may differ from `n` by a few cycles.

For "run until something happens" patterns, the MCP server has `run_until_text` and `run_until_prompt` tools that wrap a polling loop over `captureMode7Bytes`. From Python, the same pattern is one short loop:

```python
from beebjit_mcp.screen import mode7TextContains

while not mode7TextContains(bbc.captureMode7Bytes(), "READY"):
    bbc.runCycles(500_000)
```

[^ Index](#index)

## Input

---

### `typeText`

Type an ASCII string as BBC keypresses. Assumes CAPS LOCK ON (the cold-boot default), so lowercase input is silently upper-cased on the way to the matrix.

**Parameters**

- `text` *(str)*: ASCII text to type. A trailing `\n` triggers RETURN.

- `holdCycles` *(int | None, default `None`)*: Per-key HOLD cycles. `None` resolves to `BeebjitDriver.DEFAULT_KEY_HOLD_CYCLES` (5,000,000).

- `gapCycles` *(int | None, default `None`)*: Per-key GAP cycles. `None` resolves to `BeebjitDriver.DEFAULT_KEY_GAP_CYCLES` (5,000,000).

**Returns**

`None`. The emulator has advanced by `len(text) * (hold + gap)` BBC cycles plus SHIFT overhead where applicable.

**Errors**

- `UnsupportedCharError` (a `ValueError` subclass, from `beebjit_mcp.keyboard`) for characters with no BBC matrix mapping.

**Example**

```python
bbc.typeText('PRINT "HELLO"\n')
```

**Notes**

Each character is translated to a BBC matrix key, tapped with SHIFT held where the BBC layout requires it, and separated from the next character by a cycle gap tuned for 100% reliability against the MOS keyboard ISR. See [keypress-timing.md](keypress-timing.md) for the reasoning behind the defaults.

For deterministic case control on screen, call `set_caps_lock(False)` at the MCP layer (or compose the equivalent matrix tap from Python) and use [`typeTextRaw`](#typetextraw) instead.

[^ Index](#index)

---

### `typeTextRaw`

Type an ASCII string preserving case. Requires CAPS LOCK OFF; a cold-boot BBC has CAPS LOCK ON and will otherwise invert every letter.

**Parameters**

- `text` *(str)*: ASCII text to type. A trailing `\n` triggers RETURN.

- `holdCycles` *(int | None, default `None`)*: Per-key HOLD cycles. `None` resolves to `BeebjitDriver.DEFAULT_KEY_HOLD_CYCLES`.

- `gapCycles` *(int | None, default `None`)*: Per-key GAP cycles. `None` resolves to `BeebjitDriver.DEFAULT_KEY_GAP_CYCLES`.

**Returns**

`None`.

**Errors**

- `UnsupportedCharError` for characters with no BBC matrix mapping.

**Example**

```python
bbc.typeTextRaw('print "hi"\n')
```

**Notes**

Like [`typeText`](#typetext), but the case of each letter dictates whether SHIFT is applied. Lowercase stays lowercase on screen; uppercase becomes SHIFT-held so the BBC matrix produces uppercase.

The driver does not flip CAPS LOCK for you. The MCP server's `set_caps_lock` tool reads `&025A` bit 4 and taps key 135 idempotently; from Python the same gesture is `bbc.readMemory(0x025A, 1)` plus a conditional `bbc.tapKey(135)` (CAPS LOCK).

[^ Index](#index)

---

### `tapKey`

Press, hold for HOLD cycles, release, then idle GAP cycles. The base building block for reliable matrix taps.

**Parameters**

- `key` *(int)*: BBC scancode. ASCII codes work for letters/digits/direct punctuation; symbolic keys live in `beebjit_mcp.keyboard` as `BBC_KEY_*` constants (`BBC_KEY_RETURN`, `BBC_KEY_ESCAPE`, `BBC_KEY_F0` etc.).

- `holdCycles` *(int | None, default `None`)*: Cycles to hold the key down. `None` resolves to `DEFAULT_KEY_HOLD_CYCLES`.

- `gapCycles` *(int | None, default `None`)*: Cycles to idle after release before returning. `None` resolves to `DEFAULT_KEY_GAP_CYCLES`.

**Returns**

`None`.

**Example**

```python
from beebjit_mcp.keyboard import BBC_KEY_RETURN

bbc.tapKey(BBC_KEY_RETURN)
bbc.tapKey(ord("Y"))
```

**Notes**

Four-step tap: down, hold, up, gap. The GAP phase lets the BBC MOS clear its CA2-mask state so the next press can raise a fresh interrupt. Shortening HOLD or GAP below the defaults risks the MOS keyboard ISR missing the press; the [keypress-timing](keypress-timing.md) page documents the empirical floor.

[^ Index](#index)

---

### `tapShiftedKey`

`tapKey` with left-SHIFT held across the key's hold window.

**Parameters**

- `key` *(int)*: BBC scancode for the non-SHIFT key.

- `holdCycles` *(int | None, default `None`)*: Cycles to hold the main key. Defaults as for [`tapKey`](#tapkey).

- `gapCycles` *(int | None, default `None`)*: Cycles to idle after release. Defaults as for [`tapKey`](#tapkey).

**Returns**

`None`.

**Example**

```python
bbc.tapShiftedKey(ord("2"))  # types " on a BBC layout
```

**Notes**

SHIFT lives on row 0 of the BBC matrix and does not itself raise the keyboard CA2 interrupt, so it only needs to be in the matrix at the moment the scan sees the main key pressed. The GAP is applied once at the end after SHIFT is released.

[^ Index](#index)

---

### `keyDown` and `keyUp`

Inject a raw matrix key event. No automatic timing, no SHIFT handling, no gap.

**Parameters**

- `key` *(int)*: BBC scancode (0-255). ASCII codes for letters/digits/direct punctuation; `BBC_KEY_*` constants from `beebjit_mcp.keyboard` for symbolic keys; `BBC_KEY_RELEASE_ALL` (255) to release every held key in one event.

**Returns**

`None`.

**Example**

```python
from beebjit_mcp.keyboard import BBC_KEY_SHIFT_LEFT, BBC_KEY_BREAK

bbc.keyDown(BBC_KEY_SHIFT_LEFT)
bbc.keyDown(BBC_KEY_BREAK)
bbc.runCycles(200_000)
bbc.keyUp(BBC_KEY_BREAK)
bbc.runCycles(10_000_000)
bbc.keyUp(BBC_KEY_SHIFT_LEFT)
```

**Notes**

These events go straight to the BBC matrix. Pair with [`runCycles`](#runcycles) for timing, or use [`tapKey`](#tapkey) for a reliable single press with sensible defaults. The example above is the cycle-anchored SHIFT+BREAK that [`reset`](#reset)`(autoboot=True)` performs internally.

[^ Index](#index)

## State reads

---

### `readRegisters`

Return 6502 register state.

**Returns**

A `dict[str, int | str]` with:

- `A`, `X`, `Y`, `S` *(int)*: Standard 6502 register values.

- `F` *(str)*: beebjit's whitespace-padded 8-character flag string verbatim. Each slot is one flag; unset flags show as space, set flags carry their letter, and the unused B slot holds a literal `1`. Scan for the letter of interest rather than relying on fixed column positions.

- `PC` *(int)*: 16-bit program counter.

- `cycles` *(int)*: 6502-relative cycle counter (`cycles=` from `r`). Rebases near zero on every BBC Break. For cross-call cycle arithmetic that survives a soft reset, use [`runCycles`](#runcycles) which anchors against beebjit's monotonic tick counter internally.

**Errors**

- `BeebjitError` if the register line cannot be parsed.

**Example**

```python
regs = bbc.readRegisters()
print(f"PC={regs['PC']:#06x} A={regs['A']:#04x} F={regs['F']!r}")
```

[^ Index](#index)

---

### `readMemory`

Read a contiguous block of BBC RAM.

**Parameters**

- `addr` *(int)*: 16-bit BBC address (0-65535).

- `length` *(int)*: Number of bytes to read.

**Returns**

`bytes`. Exactly `length` bytes starting at `addr`. The MCP server wraps this into a `{"hex": ..., "ascii": ...}` shape; the library hands back the raw bytes for direct slicing or feeding into a struct unpack.

**Errors**

- `ValueError` if `addr` is outside the 6502 address space, `length` is negative, or `addr + length` would exceed `0x10000`. The driver does not wrap silently.

- `BeebjitError` if a `m` command returns no parseable memory lines.

**Example**

```python
banner = bbc.readMemory(0x7C00, 40)
print(banner.decode("ascii", errors="replace"))
```

**Notes**

Each beebjit `m` call returns 64 bytes. The driver loops with the next unread address until it has the requested length, then trims.

[^ Index](#index)

---

### `disassemble`

Disassemble 6502 instructions starting at `addr`.

**Parameters**

- `addr` *(int)*: 16-bit address to start disassembly at.

- `count` *(int, default `20`)*: Number of instructions to return. Capped at 20 (beebjit's native batch size).

**Returns**

`list[dict[str, int | str]]`. Each dict has:

- `addr` *(int)*: Address of the instruction.
- `info` *(str)*: beebjit's per-line tag (`"ITRP"` for interrupt, `"JIT"` for compiled code, sometimes empty).
- `text` *(str)*: Mnemonic and operands as beebjit prints them.

**Errors**

- `ValueError` if `addr` is out of range or `count` is outside 1..20.

- `BeebjitError` if no disassembly lines are parsed.

**Example**

```python
for ins in bbc.disassemble(0xE000, count=5):
    print(f"{ins['addr']:#06x} {ins['info']:>5} {ins['text']}")
```

**Notes**

For longer runs, loop from the caller side by re-dispatching at the next unread address. beebjit does not emit raw opcode bytes in its disassembly output; pair with [`readMemory`](#readmemory) at the same address if needed.

[^ Index](#index)

---

### `captureMode7Bytes`

Capture the MODE 7 framebuffer in display order, handling hardware scroll.

**Returns**

`bytes`. Exactly 1000 bytes (`MODE7_BYTES`). Byte 0 is the top-left cell as painted by the CRTC; the result feeds directly into [`decodeMode7`](#decodemode7).

**Example**

```python
from beebjit_mcp.screen import decodeMode7

for row in decodeMode7(bbc.captureMode7Bytes()):
    print(row)
```

**Notes**

The MODE 7 framebuffer sits in a 1024-byte page at `&7C00`. Only 1000 bytes are visible at any time. Hardware scrolling advances the display-start pointer; the MOS caches it at `&0350/&0351`. The driver reads the whole 1024-byte page plus the pointer, rotates the page into display order, and returns the 1000 display bytes.

Pre-MOS-init the pointer at `&0350/&0351` is uninitialised RAM. In that state the driver falls back to the page base address, so polling during boot does not raise; the decoded text is arbitrary but the loop keeps iterating.

This is MODE-7-only. In a bitmapped mode (MODE 0-6) the returned bytes are not meaningful text. Use [`captureScreen`](#capturescreen) for the rendered display in any mode.

[^ Index](#index)

---

### `captureScreen`

Capture the rendered framebuffer as raw BGRA pixel bytes.

**Returns**

`tuple[bytes, int, int]`: `(bgra_bytes, width, height)`. For a PNG, pass these to [`bgraToPng`](#bgratopng). The raw form is the building block; callers who prefer Pillow, numpy, or a direct file write skip the PNG step entirely.

**Errors**

- `BeebjitError` if the binary lacks the render buffer (typically: launched without `-headless-render`, or a build that does not support the `savescreen` debugger command), or if the announced size disagrees with the file written.

**Example**

```python
bgra, width, height = bbc.captureScreen()
print(f"{width}x{height}, {len(bgra)} bytes")
```

**Notes**

`width` and `height` come from beebjit's announced render geometry, not an MCP-side guess. The pixel data is the rendered display, not the raw BBC framebuffer bytes: hardware scroll, palette, and any video ULA effects are baked in at capture time.

[^ Index](#index)

## State writes

---

### `writeMemory`

Poke bytes into memory starting at `addr`.

**Parameters**

- `addr` *(int)*: 16-bit BBC address (0-65535).

- `data` *(bytes)*: Bytes to write.

**Returns**

`None`.

**Errors**

- `ValueError` if `addr` is out of range or the write would exceed the 6502 address space.

**Example**

```python
bbc.writeMemory(0x7C00, b"HELLO" + b" " * 35)
```

**Notes**

Writes longer than 16 bytes are chunked internally into 16-byte `writem` commands to keep command lines manageable. The byte content round-trips through [`readMemory`](#readmemory) without translation.

[^ Index](#index)

## Diagnostics

---

### `stderrTail`

Return the bounded ring of beebjit's stderr as a decoded string.

**Returns**

`str`. The ring is capped at 16 KB, so the return value is safe to log even after a long session. Most useful for post-mortem after a `BeebjitError`.

**Example**

```python
try:
    bbc.loadDisc(0, "/path/that/does/not/exist.ssd")
except BeebjitError as exc:
    print("disc load failed:", exc)
    print("stderr tail:", bbc.stderrTail())
```

[^ Index](#index)

---

### `sendCommand`

Send one raw debugger command and return its output lines. The escape hatch for anything the driver does not yet wrap.

**Parameters**

- `cmd` *(str)*: Debugger command exactly as beebjit's `debug.c` accepts it.

- `timeout` *(float, default `5.0`)*: Host-side timeout on the prompt round-trip. Long-running commands (like `c` over many millions of cycles) need a much larger value, which is why [`runCycles`](#runcycles) passes its own.

**Returns**

`list[str]`. Output lines between the command echo and the next prompt, with the prompt stripped. Parsing is the caller's responsibility.

**Errors**

- `BeebjitError` if beebjit's stdin is closed, or if the subprocess exits during the command. The error message includes the stderr tail.

- `TimeoutError` if no prompt arrives within `timeout`.

**Example**

```python
lines = bbc.sendCommand("crtc")
for line in lines:
    print(line)
```

**Notes**

Useful for any debugger command beebjit supports that the driver does not yet wrap: `bm`, `bmr`, `bmw`, `bl`, `find`, `sys`, `crtc`, `vias`, `eval`, and similar. See `debug.c` lines 2165-2550 in the beebjit source for the full command grammar.

The driver itself is built on top of `sendCommand`; nothing else has a hotline to the subprocess.

[^ Index](#index)

## Errors

`BeebjitError` is the single exception class for anything the driver cannot complete. Pipe-level failures (broken pipe, unexpected EOF), protocol-level failures (unparseable register or memory output), and command-level failures (the debugger rejecting an argument) all surface as `BeebjitError`. The message always includes the stderr tail when available, so a caught exception carries enough context for post-mortem on its own.

```python
from beebjit_mcp.driver import BeebjitError

try:
    bbc.loadDisc(0, "/path/that/does/not/exist.ssd")
except BeebjitError as exc:
    print("disc load failed:", exc)
    print("stderr tail:", bbc.stderrTail())
```

Argument validation errors raise `ValueError` instead, before any debugger round trip. Examples: `addr` out of the 6502 range, `length` negative, `drive` not 0 or 1, `mutable=True` without `writeable=True`.

`UnsupportedCharError` (a `ValueError` subclass, from `beebjit_mcp.keyboard`) is raised when [`typeText`](#typetext) or [`typeTextRaw`](#typetextraw) is asked to type a character that has no BBC key mapping.

`TimeoutError` surfaces from [`start`](#start), [`runCycles`](#runcycles), and [`sendCommand`](#sendcommand) when the prompt does not arrive within the requested timeout.

## Concurrency

One driver instance owns one beebjit subprocess. The driver runs three threads internally (main, stdout reader, stderr reader), so callers do not see threading directly. From the outside, the contract is straightforward:

- One operation at a time per driver. The class is not thread-safe for concurrent calls. For overlapping work, use separate `BeebjitDriver` instances.

- Multiple drivers in the same process are fully independent. Each holds its own subprocess; nothing is shared between them.

- The driver does not implement `__del__`. Garbage collection does not clean up the subprocess. Use the context manager, or call [`close`](#close) explicitly.

## Lifecycle gotchas

- An abandoned driver leaks a beebjit subprocess. The `-cycles` cap (one trillion by default) eventually trips and beebjit exits on its own, but that can be hours later. Use `with`.

- [`start`](#start) is required before any operation. The context manager calls it automatically. Manual users sometimes forget after `__init__`, which results in a `BeebjitError("driver not started")`.

- A subprocess that exits between commands (cycles cap hit, host kill signal) surfaces on the next call as `BeebjitError("beebjit stdin closed: ...")` with the stderr tail attached.

## Keyboard helpers

Three pure helpers live in `beebjit_mcp.keyboard`. They run without a driver, so they are useful for offline keymap testing, custom input flows, and any caller that wants to inspect the translation before sending it.

---

### `asciiToKeys`

Translate an ASCII string to a list of `(bbcKey, shifted)` tuples, assuming CAPS LOCK ON.

**Parameters**

- `text` *(str)*: ASCII string to translate. `\n` becomes a `(BBC_KEY_RETURN, False)` tuple.

**Returns**

`list[tuple[int, bool]]`. Each tuple is one key-tap; the second field indicates whether the caller should hold SHIFT across the press.

**Errors**

- `UnsupportedCharError` for characters with no BBC matrix mapping.

**Example**

```python
from beebjit_mcp.keyboard import asciiToKeys

for key, shifted in asciiToKeys('PRINT "HI"\n'):
    print(key, shifted)
```

**Notes**

Under CAPS LOCK ON, uppercase and lowercase letters both translate to the same unshifted matrix tap. The translation is deterministic and pure: no driver, no subprocess.

[^ Index](#index)

---

### `asciiToKeysRaw`

Case-preserving variant of [`asciiToKeys`](#asciitokeys). Assumes CAPS LOCK OFF.

**Parameters**

- `text` *(str)*: ASCII string to translate.

**Returns**

`list[tuple[int, bool]]`.

**Errors**

- `UnsupportedCharError` for characters with no BBC matrix mapping.

**Example**

```python
from beebjit_mcp.keyboard import asciiToKeysRaw

asciiToKeysRaw("Hi")  # [(72, True), (73, False)] -> SHIFT+H, then i
```

**Notes**

Lowercase letters translate to unshifted taps; uppercase letters translate to shifted taps. The matrix key itself is always the uppercase ASCII code.

[^ Index](#index)

---

### `resolveKeyName`

Resolve a symbolic key name to a BBC scancode. Passes integer key codes through unchanged after a range check.

**Parameters**

- `name` *(str | int)*: Symbolic name (`"return"`, `"escape"`, `"caps_lock"`, `"f0"`-`"f9"`, `"up_arrow"`, etc., case-insensitive) or a raw integer 0-255.

**Returns**

`int`. The BBC scancode.

**Errors**

- `ValueError` if the name is not in `SPECIAL_KEYS`, or if an integer is outside 0-255.

**Example**

```python
from beebjit_mcp.keyboard import resolveKeyName

resolveKeyName("RETURN")     # 131
resolveKeyName("caps_lock")  # 135
resolveKeyName(65)           # 65
```

**Notes**

Designed for callers that accept either a friendly name or a raw code in the same parameter slot, such as the MCP `key_down` and `key_up` tools.

[^ Index](#index)

## Screen helpers

Three pure helpers live in `beebjit_mcp.screen`. They operate on byte buffers, not a live driver, so any 1000-byte MODE 7 framebuffer from any source can be decoded with them.

---

### `decodeMode7`

Decode a 1000-byte MODE 7 framebuffer into 25 rows of 40 characters.

**Parameters**

- `framebuffer` *(bytes)*: Exactly `MODE7_BYTES` (1000) bytes in display order. Typically the return value of [`captureMode7Bytes`](#capturemode7bytes).

- `controls` *(Mode7Controls, default `Mode7Controls.SPACE`)*: How to render non-printing teletext control bytes. One of:
  - `Mode7Controls.SPACE`: single space per non-printable byte. Rows stay 40 chars wide.
  - `Mode7Controls.QUESTION`: single `?` per non-printable byte. Rows stay 40 chars wide.
  - `Mode7Controls.ESCAPE`: four-character `\xNN` escape per non-printable byte. Row widths become variable.

**Returns**

`list[str]`. Always exactly 25 strings.

**Errors**

- `ValueError` if `framebuffer` is not exactly 1000 bytes.

**Example**

```python
from beebjit_mcp.screen import decodeMode7, Mode7Controls

rows = decodeMode7(bbc.captureMode7Bytes(), controls=Mode7Controls.ESCAPE)
```

**Notes**

Rows are not right-stripped, so column-indexing into the SPACE or QUESTION outputs stays straightforward. Use SPACE for substring assertions and column-indexing callers; ESCAPE when the original byte values matter (debugging control-code sequences, for example).

[^ Index](#index)

---

### `rotateMode7Page`

Rotate a 1024-byte MODE 7 page into display order.

**Parameters**

- `page` *(bytes)*: Exactly 1024 bytes of the raw teletext page (`&7C00-&7FFF`).

- `startAddr` *(int)*: CPU-space pointer to the first displayed byte, as the MOS keeps it at `&0350/&0351`. Must be in `&7C00-&7FFF`.

**Returns**

`bytes`. Exactly 1000 bytes in display order, ready for [`decodeMode7`](#decodemode7).

**Errors**

- `ValueError` if `page` is not 1024 bytes, or `startAddr` is outside the MODE 7 page range.

**Example**

```python
from beebjit_mcp.screen import rotateMode7Page

page = bbc.readMemory(0x7C00, 1024)
ptr = bbc.readMemory(0x0350, 2)
startAddr = ptr[0] | (ptr[1] << 8)
display = rotateMode7Page(page, startAddr)
```

**Notes**

Called internally by [`captureMode7Bytes`](#capturemode7bytes). Exposed for callers who already have a teletext page from elsewhere (a save state, a memory dump, a different emulator's frame).

[^ Index](#index)

---

### `mode7TextContains`

True if `needle` appears anywhere in the decoded screen. Rows are `\n`-joined so a needle does not accidentally span a row boundary.

**Parameters**

- `framebuffer` *(bytes)*: Exactly 1000 bytes in display order.

- `needle` *(str)*: Substring to search for in the joined rows.

**Returns**

`bool`. True if `needle` is found, False otherwise.

**Errors**

- `ValueError` propagated from [`decodeMode7`](#decodemode7) if `framebuffer` is the wrong length.

**Example**

```python
from beebjit_mcp.screen import mode7TextContains

while not mode7TextContains(bbc.captureMode7Bytes(), "READY"):
    bbc.runCycles(500_000)
```

**Notes**

The building block for "run until text appears" loops in Python, mirroring the MCP server's `run_until_text` tool. Use `\n`-aware needles when you need to assert on multi-row sequences.

[^ Index](#index)

## Image helpers

One pure helper lives in `beebjit_mcp.image`. It takes raw pixel bytes and returns PNG bytes.

---

### `bgraToPng`

Encode raw BGRA pixel data as a PNG.

**Parameters**

- `bgra` *(bytes)*: BGRA pixel data, exactly `width * height * 4` bytes. Typically the first element of a [`captureScreen`](#capturescreen) return value.

- `width` *(int)*: Image width in pixels.

- `height` *(int)*: Image height in pixels.

**Returns**

`bytes`. A complete PNG file, including the 8-byte signature and the IEND chunk. Ready to write to disk, base64-encode, or hand to any PNG viewer.

**Errors**

- `ValueError` if `len(bgra) != width * height * 4`, or if `width` or `height` is non-positive.

**Example**

```python
from beebjit_mcp.image import bgraToPng

bgra, width, height = bbc.captureScreen()
png = bgraToPng(bgra, width, height)
Path("screen.png").write_bytes(png)
```

**Notes**

The MCP `screenshot` tool composes [`captureScreen`](#capturescreen) and `bgraToPng` internally and base64-encodes the result. Library callers who want the same end product can call both directly and skip the base64 step.

[^ Index](#index)

## Cross-references

- [Tool reference](tool-reference.md) is the per-tool MCP detail. Many tools map one-to-one with a Python method; some (`run_until_text`, `set_caps_lock`, `read_mode7_text`, `screenshot`, `run_basic`) are server-side compositions, and the Python equivalent is shown in the relevant section above.

- [Architecture](architecture.md) covers how the driver, keyboard, screen, and rendering pieces fit together inside the package.

- [Keypress timing](keypress-timing.md) is the reasoning behind the five-million-cycle HOLD and GAP defaults.

- [MODE 7 decode](mode7-decode.md) covers teletext control codes and the hardware-scroll pointer.

- [Troubleshooting](troubleshooting.md) covers common failure modes; everything there applies here as well.
