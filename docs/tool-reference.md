# Tool reference

This is the human-facing reference for the MCP tools the server exposes. An AI agent's actual view comes from the live schema served at runtime via `tools/list`.

- Every tool takes a JSON object and returns a JSON object.

- `session_id` identifies which emulator instance to act on and is returned from a call to `create_machine`.

- Calls are synchronous: each tool call is one request and awaits the response. The server does not run two tool bodies in parallel against the same session.

## Index

| Tool | Category | Purpose |
| --- | --- | --- |
| [`create_machine`](#create_machine) | Lifecycle | Boot a fresh BBC Micro session |
| [`destroy_machine`](#destroy_machine) | Lifecycle | Tear a session down and release the subprocess |
| [`reset`](#reset) | Lifecycle | Hard-reset the BBC without destroying the session |
| [`load_disc`](#load_disc) | Lifecycle | Mount a disc image into a drive at runtime |
| [`boot_disc`](#boot_disc) | Lifecycle | Mount a disc and SHIFT+BREAK autoboot it |
| [`run_for_cycles`](#run_for_cycles) | Execution | Advance the emulator by exactly N BBC cycles |
| [`run_until_text`](#run_until_text) | Execution | Run until a substring appears in the MODE 7 screen |
| [`run_until_prompt`](#run_until_prompt) | Execution | Run until a prompt character at the start of a row |
| [`type_input`](#type_input) | Input | Type an ASCII string (CAPS LOCK on) |
| [`type_input_raw`](#type_input_raw) | Input | Type an ASCII string preserving case (CAPS LOCK off) |
| [`key_down`](#key_down-and-key_up) | Input | Low-level matrix key-down event |
| [`key_up`](#key_down-and-key_up) | Input | Low-level matrix key-up event |
| [`press_caps_lock`](#press_caps_lock) | Input | Tap CAPS LOCK to toggle the current state |
| [`set_caps_lock`](#set_caps_lock) | Input | Set CAPS LOCK to a specific state (idempotent) |
| [`read_memory`](#read_memory) | Inspection | Read a contiguous block of BBC RAM |
| [`write_memory`](#write_memory) | Inspection | Poke bytes into memory |
| [`read_registers`](#read_registers) | Inspection | Return 6502 register state |
| [`read_mode7_text`](#read_mode7_text) | Inspection | Capture the MODE 7 screen as 25 rows of 40 chars |
| [`screenshot`](#screenshot) | Inspection | Capture the rendered BBC screen as a PNG |
| [`disassemble`](#disassemble) | Inspection | Disassemble 6502 instructions |
| [`run_basic`](#run_basic) | Composition | Type a BBC BASIC program, run it, return the final screen |
| [`reload_module`](#reload_module) | Dev | Hot-reload a pure module without restarting the server |

## Conventions

- Addresses and cycle counts are JSON integers. Both `31744` (decimal) and `0x7C00` (hex) parse to the same value.

- `session_id` is an opaque UUID string returned by `create_machine`. Every tool except `create_machine` and `reload_module` takes one as its first parameter. The per-tool **Parameters** sections below list only the additional parameters.

- Every tool returns a JSON object, never a bare value, so fields can be added backwards-compatibly.

- Errors surface through the MCP tool-call error channel, not through a payload `ok` flag. Catch them with your client's usual error-handling path.

- This documentation uses `&ADDR` for BBC memory addresses, matching the BBC Micro User Guide. Source code uses `0x`.

## Lifecycle

---

### `create_machine`

Boot a fresh BBC Micro session.

**Parameters**

- `model` *(string, default `"b"`)*: BBC hardware configuration. One of:
  - `"b"`: BBC B with MOS 1.20 and the 8271 floppy controller.
  - `"master"`: Master 128 with MOS 3.20.
  - `"mos35"`: Master 128 with MOS 3.50.
  - `"compact"`: Master Compact.

  Disc-image format follows from the model. BBC B and the two Master 128 variants read DFS images (`.ssd` and `.dsd`); Master Compact reads ADFS images (`.adl` and `.adf`). Mounting an unsupported format on a model leaves the OS at the BASIC prompt because its filing system rejects the layout it sees.

- `disc` *(string | null, default `null`)*: Absolute path to a disc image (DFS `.ssd` or `.dsd`, or ADFS `.adl` or `.adf`). When set, SHIFT is held in the keyboard matrix from cycle zero, the disc is mounted into drive 0 read-only, and MOS init reads SHIFT during its boot keyboard scan and runs the disc's `!BOOT`. The gesture matches a real user holding SHIFT before powering on with a disc inserted. For a writeable mount or for non-default drive selection, omit this parameter and call [`load_disc`](#load_disc) directly after `create_machine`.

**Returns**

- `session_id` *(string)*: Opaque UUID identifying the new session. Pass this on every subsequent call against this BBC Micro.

**Errors**

- beebjit binary not found (`$BEEBJIT` unset and no `beebjit` on `$PATH`).

- Subprocess dies before the first prompt. The error message includes the stderr tail.

- Cold start exceeds the 10-second initial-prompt timeout.

**Example**

```json
// Request
{"model": "b", "disc": null}

// Response
{"session_id": "550e8400-e29b-41d4-a716-446655440000"}
```

**Notes**

The spawn is synchronous: the tool returns once beebjit has reached its first `(6502db)` debugger prompt, typically under 100 ms on a modern host.

[^ Index](#index)

---

### `destroy_machine`

Tear a session down and release the beebjit subprocess.

**Returns**

- `ok` *(boolean)*: `true` on clean teardown, `false` if the session id is not recognised.

**Example**

```json
// Request
{"session_id": "<uuid>"}

// Response
{"ok": true}
```

**Notes**

The teardown sends `q` to the debugger, waits up to five seconds for beebjit to exit cleanly, and escalates to `SIGKILL` if the process is still alive. The `false` path is not an error condition. Double-destroy from a retrying client returns `{"ok": false}` without crashing the server.

[^ Index](#index)

---

### `reset`

Hard-reset the running BBC without tearing down the session. Equivalent to a user pressing the BREAK key on the real keyboard. The 6502 cycle counter wraps, BASIC variables and the current program are cleared, and the boot banner reappears. The MCP session id stays valid; subsequent tool calls hit the same session.

**Parameters**

- `autoboot` *(boolean, default `false`)*: hold SHIFT across the BREAK so an inserted disc's `!BOOT` runs as the OS comes up, matching the BBC SHIFT+BREAK convention.

**Returns**

- `ok` *(boolean)*: always `true` on completion.

**Example**

```json
// Request
{"session_id": "<uuid>"}

// Response
{"ok": true}
```

```json
// Disc autoboot variant
{"session_id": "<uuid>", "autoboot": true}

// Response
{"ok": true}
```

**Notes**

The reset taps F12 to assert the 6502 RESET line, then advances the BBC for a fixed cycle budget that is generous enough for MOS init to settle on every supported model. The call returns with the BBC at a fresh BASIC prompt (or, with `autoboot=true`, with the disc's `!BOOT` already running).

`autoboot=true` injects SHIFT before the BREAK and holds it through the autoboot keyboard-scan window, matching the BBC SHIFT+BREAK convention that runs an inserted disc's `!BOOT`. SHIFT held during reset is harmless on a session without a disc; the OS comes up at the BASIC prompt regardless.

[^ Index](#index)

---

### `load_disc`

Mount a disc image into a drive at runtime. The BBC keeps its current state; the new disc becomes available for the next OS read.

**Parameters**

- `disc` *(string)*: Absolute path to a disc image (DFS `.ssd` or `.dsd`, or ADFS `.adl` or `.adf`). The MCP layer checks the path exists before sending the command.

- `drive` *(integer, default `0`)*: BBC disc drive to mount into. Either `0` or `1`.

- `writeable` *(boolean, default `false`)*: Cut the write-protect notch so the BBC can write to the in-memory image. Default keeps the disc read-only.

- `mutable` *(boolean, default `false`)*: Flush in-memory writes back to the host file. Requires `writeable=true`. Default leaves the host file untouched.

**Returns**

- `ok` *(boolean)*: `true` on success.
- `drive` *(integer)*: Drive the disc was mounted into.
- `disc` *(string)*: Absolute path of the mounted disc image.
- `writeable`, `mutable` *(boolean)*: Echo of the requested flags.

**Errors**

- `FileNotFoundError` if `disc` is not a readable file. Surfaced as an MCP tool-call error.

- `BeebjitError` if beebjit's own pre-checks reject the mount (extension, slot count, file readability). The error message includes beebjit's own `loaddisc: failed (see log) for ...` line.

- `BeebjitError` if the running beebjit binary does not support runtime disc mounting. See [binary discovery](binary-discovery.md) for the minimum binary requirements.

**Example**

```json
// Request
{"session_id": "<uuid>", "disc": "/path/to/game.ssd"}

// Response
{
  "ok": true,
  "drive": 0,
  "disc": "/path/to/game.ssd",
  "writeable": false,
  "mutable": false
}
```

**Notes**

The mount does not trigger a reset or autoboot. The BBC keeps its current state and the new disc is available for the next OS read. For mount + autoboot in one call, use [`boot_disc`](#boot_disc); for mount with explicit reset, compose `load_disc` with [`reset`](#reset)`(autoboot=true)`.

`writeable` controls whether the BBC can modify the in-memory image; `mutable` controls whether those modifications persist back to the host file. The two flags compose: `writeable=true, mutable=false` is "writes survive in this session only, never reach disk", which is useful for save-game probes that should not perturb the source file.

[^ Index](#index)

---

### `boot_disc`

Mount a disc and SHIFT+BREAK autoboot it in one call.

**Parameters**

Same shape as [`load_disc`](#load_disc): `disc`, `drive` (default `0`), `writeable` (default `false`), `mutable` (default `false`).

**Returns**

Same shape as [`load_disc`](#load_disc): `ok`, `drive`, `disc`, `writeable`, `mutable`.

**Errors**

- Same errors as [`load_disc`](#load_disc).

**Example**

```json
// Request
{"session_id": "<uuid>", "disc": "/path/to/game.ssd"}

// Response
{
  "ok": true,
  "drive": 0,
  "disc": "/path/to/game.ssd",
  "writeable": false,
  "mutable": false
}
```

**Notes**

Equivalent to [`load_disc`](#load_disc) followed by [`reset`](#reset)`(autoboot=true)`. The gesture matches a real user holding SHIFT and pressing BREAK on a running BBC after inserting a disc; the running BBC's state is otherwise preserved through the soft reset. The call returns once the post-reset settle window has elapsed, so the disc's `!BOOT` is already running (or already finished) by then.

[^ Index](#index)

## Execution

---

### `run_for_cycles`

Advance the emulator by exactly N BBC cycles.

**Parameters**

- `cycles` *(integer)*: Number of BBC cycles to advance.

**Returns**

- `ok` *(boolean)*: `true` on success.
- `cycles_ran` *(integer)*: Number of cycles requested.
- `cycles_total` *(integer)*: Post-run value of beebjit's 6502-relative cycle counter (`cycles=` from `r`). Rebases near zero on every BBC Break, so this is "BBC time since last reset" rather than wallclock-since-spawn.

**Errors**

- 30-second host-side timeout on the underlying `c` (continue). Covers many billions of BBC cycles at `-fast` on a modern host. For longer runs, chunk from the client side.

**Example**

```json
// Request
{"session_id": "<uuid>", "cycles": 5000000}

// Response
{"ok": true, "cycles_ran": 5000000, "cycles_total": 5000017}
```

**Notes**

Cycle counting is anchored against beebjit's global `total_timer_ticks` counter (read live via `eval ticks` on each call). The driver reads ticks, computes `target = ticks + cycles`, sets `breakat target`, and issues `c`. Anchoring against ticks rather than the 6502-relative `cycles=` field is what makes the call survive a soft reset, since `cycles=` rebases on Break while ticks are monotonic. Chained calls do not accumulate drift.

beebjit can overshoot the breakpoint by a handful of instructions. `cycles_total` reports the exact 6502-relative stopping point and may differ from the requested target by a few cycles.

[^ Index](#index)

---

### `run_until_text`

Run in chunks until a substring appears anywhere in the MODE 7 screen, or until the cycle budget is exhausted.

**Parameters**

- `needle` *(string)*: Substring to search for in the joined MODE 7 screen.
- `max_cycles` *(integer, default `20000000`)*: Maximum BBC cycles to run before giving up.
- `chunk_cycles` *(integer, default `500000`)*: BBC cycles per chunk between screen checks.

**Returns**

- `ok` *(boolean)*: `true` if the needle was found, `false` if the budget was exhausted.
- `found` *(boolean)*: Mirrors `ok`. Explicit so callers can branch on the search result alone.
- `cycles_ran` *(integer)*: Total cycles consumed before stopping.

**Example**

```json
// Request
{
  "session_id": "<uuid>",
  "needle": "HELLO",
  "max_cycles": 20000000,
  "chunk_cycles": 500000
}

// Response (success)
{"ok": true, "found": true, "cycles_ran": 1500000}

// Response (exhaustion)
{"ok": false, "found": false, "cycles_ran": 20000000}
```

**Notes**

The tool runs one chunk, captures the MODE 7 screen, searches the `\n`-joined rows for the needle, and returns on a match. The newline join prevents spurious cross-row hits: a `HELLO` split across rows 12 and 13 will not match the needle `HELLO`.

The first screen check happens after running one chunk, not at cycle zero, so uninitialised framebuffer bytes from before the first BBC screen paint cannot produce a false positive.

Smaller `chunk_cycles` checks the screen more often at the cost of one framebuffer read per chunk. The default balances responsiveness against overhead.

[^ Index](#index)

---

### `run_until_prompt`

Run in chunks until a prompt character appears at the start of a MODE 7 row.

**Parameters**

- `prompt` *(string, default `">"`)*: Prompt string to match at the start of a row. The default is the standard BBC BASIC prompt.
- `max_cycles` *(integer, default `20000000`)*: Maximum BBC cycles to run before giving up.
- `chunk_cycles` *(integer, default `500000`)*: BBC cycles per chunk between screen checks.

**Returns**

- `ok` *(boolean)*: `true` if the prompt was found, `false` otherwise.
- `found` *(boolean)*: Mirrors `ok`.
- `cycles_ran` *(integer)*: Total cycles consumed.
- `prompt` *(string)*: The match target, echoed for debugging.

**Example**

```json
// Request
{
  "session_id": "<uuid>",
  "prompt": ">",
  "max_cycles": 20000000,
  "chunk_cycles": 500000
}

// Response
{"ok": true, "found": true, "cycles_ran": 6000000, "prompt": ">"}
```

**Notes**

The row-anchored cousin of [`run_until_text`](#run_until_text). The match requires the prompt string at the start of a (left-stripped) row, so a `>` embedded mid-line (inside the typed command, for example) does not count.

Use this when you want to wait for BASIC or the MOS to return control to the user, rather than just any appearance of text on screen.

[^ Index](#index)

## Input

---

### `type_input`

Type an ASCII string as BBC keypresses.

**Parameters**

- `text` *(string)*: ASCII text to type. A trailing `\n` triggers RETURN.

**Returns**

- `ok` *(boolean)*: `true` on success.
- `chars` *(integer)*: Number of characters typed.

**Errors**

- `UnsupportedCharError` for characters without a BBC matrix mapping. Surfaced as an MCP tool-call error.

**Example**

```json
// Request
{"session_id": "<uuid>", "text": "PRINT \"HELLO\"\n"}

// Response
{"ok": true, "chars": 14}
```

**Notes**

Each character is translated to a BBC matrix key, tapped with SHIFT held where the BBC layout requires it, and separated from the next character by a cycle gap tuned for 100% reliability against the MOS keyboard ISR.

This tool assumes CAPS LOCK is ON (the cold-boot default). Lowercase input is upper-cased silently so a caller writing `print "hello"` still gets a working program. For deterministic case control, use [`set_caps_lock`](#set_caps_lock) first and [`type_input_raw`](#type_input_raw) instead.

Per-character cost is HOLD=5M + GAP=5M = 10M BBC cycles. A 14-character line like `PRINT "HELLO"\n` advances the emulator by ~140M cycles, a few hundred milliseconds of host time at `-fast`. See [keypress timing](keypress-timing.md) for why the numbers are what they are.

[^ Index](#index)

---

### `type_input_raw`

Type an ASCII string preserving case.

**Parameters**

- `text` *(string)*: ASCII text to type. A trailing `\n` triggers RETURN.

**Returns**

- `ok` *(boolean)*: `true` on success.
- `chars` *(integer)*: Number of characters typed.

**Errors**

- `UnsupportedCharError` for characters without a BBC matrix mapping. Surfaced as an MCP tool-call error.

**Example**

```json
// Request
{"session_id": "<uuid>", "text": "print \"hi\"\n"}

// Response
{"ok": true, "chars": 11}
```

**Notes**

Like [`type_input`](#type_input), but the case of each letter dictates whether SHIFT is applied. Lowercase stays lowercase on screen; uppercase becomes SHIFT-held so the BBC matrix produces uppercase.

This tool requires CAPS LOCK to be OFF. Call [`set_caps_lock`](#set_caps_lock) with `on: false` first; a cold-boot BBC has CAPS LOCK ON and will otherwise invert every letter.

[^ Index](#index)

---

### `key_down` and `key_up`

Low-level matrix events with no automatic timing.

**Parameters**

- `key`: One of:
  - A raw integer key code (0-255).
  - A single-character string; letters are upper-cased so `"a"` and `"A"` both hit matrix position 65.
  - A symbolic name from `SPECIAL_KEYS`: `ESCAPE`, `BACKSPACE`, `TAB`, `RETURN`, `CTRL`, `SHIFT_LEFT`, `SHIFT_RIGHT`, `CAPS_LOCK`, `F0`-`F9`, `F11`, `F12`, `UP_ARROW`, `DOWN_ARROW`, `LEFT_ARROW`, `RIGHT_ARROW`, `DELETE`, `HOME`, `RELEASE_ALL`. Case-insensitive.

**Returns**

- `ok` *(boolean)*: `true` on success.
- `key` *(integer)*: Resolved BBC key code (0-255) that was sent to the matrix.

**Example**

```json
// Request
{"session_id": "<uuid>", "key": "CAPS_LOCK"}

// Response
{"ok": true, "key": 135}
```

**Notes**

These events go straight to the BBC matrix. No cycle advance, no SHIFT handling, no gap. Pair with [`run_for_cycles`](#run_for_cycles) for timing, or use [`type_input`](#type_input) if you just want a reliable tap.

`RELEASE_ALL` (code 255) clears every held key in one event. Send it via `key_up` at the end of a composed sequence where tracking each individual key-up is tedious.

[^ Index](#index)

---

### `press_caps_lock`

Tap CAPS LOCK once to toggle the current state.

**Returns**

- `ok` *(boolean)*: `true` on success.
- `key` *(integer)*: BBC key code for CAPS LOCK (`135`).

**Example**

```json
// Request
{"session_id": "<uuid>"}

// Response
{"ok": true, "key": 135}
```

**Notes**

Pure toggle. The tool does not read the current state. If you need a deterministic final state, use [`set_caps_lock`](#set_caps_lock) instead.

[^ Index](#index)

---

### `set_caps_lock`

Set CAPS LOCK to a specific state.

**Parameters**

- `on` *(boolean)*: Desired CAPS LOCK state.

**Returns**

- `ok` *(boolean)*: `true` on success.
- `tapped` *(boolean)*: `true` if the tool tapped the key, `false` if the desired state was already in effect.
- `caps_lock_on` *(boolean)*: Resulting CAPS LOCK state.

**Example**

```json
// Request
{"session_id": "<uuid>", "on": false}

// Response
{"ok": true, "tapped": true, "caps_lock_on": false}
```

**Notes**

Idempotent. The tool reads the MOS caps-lock flag at `&025A` bit 4 and taps key 135 only if the current state differs from `on`. Calling `set_caps_lock(on: true)` twice does not flip the state. Use this as the setup for [`type_input_raw`](#type_input_raw) when you need lowercase on screen.

[^ Index](#index)

## Inspection

---

### `read_memory`

Read a contiguous block of BBC RAM.

**Parameters**

- `addr` *(integer)*: 16-bit BBC address (0-65535).
- `length` *(integer)*: Number of bytes to read.

**Returns**

- `hex` *(string)*: Lower-case hex string of the bytes, contiguous, no separators.
- `ascii` *(string)*: ASCII view of the same bytes, non-printable bytes replaced with `.` (matches `hexdump -C` convention).

**Errors**

- Refuses if `addr + length` exceeds `0x10000`. The driver does not wrap silently.

**Example**

```json
// Request
{"session_id": "<uuid>", "addr": 32256, "length": 40}

// Response
{
  "hex": "20202020...",
  "ascii": "                                        "
}
```

**Notes**

`hex` and `ascii` are computed from the same read so they cannot diverge. Each beebjit `m` call returns 64 bytes. The driver loops with the next unread address until it has the requested length, then trims.

[^ Index](#index)

---

### `write_memory`

Poke bytes into memory starting at `addr`.

**Parameters**

- `addr` *(integer)*: 16-bit BBC address (0-65535).
- `data` *(string)*: Hex string of bytes. Whitespace between bytes is tolerated; `"DE AD BE EF"` and `"DEADBEEF"` write the same four bytes.

**Returns**

- `ok` *(boolean)*: `true` on success.
- `addr` *(integer)*: Address echoed back.
- `length` *(integer)*: Number of bytes written.

**Example**

```json
// Request
{"session_id": "<uuid>", "addr": 32256, "data": "DEADBEEF"}

// Response
{"ok": true, "addr": 32256, "length": 4}
```

**Notes**

The `data` shape is symmetric with [`read_memory`](#read_memory)'s `hex` field, so a read can be round-tripped straight back through a write. Writes longer than 16 bytes are chunked internally to keep command lines manageable.

[^ Index](#index)

---

### `read_registers`

Return 6502 register state.

**Returns**

- `A`, `X`, `Y`, `S` *(integer)*: Standard 6502 register values, decoded as integers.
- `F` *(string)*: beebjit's whitespace-padded 8-character flag string verbatim. Each slot is one flag; unset flags show as space, set flags carry their letter, and the unused B slot holds a literal `1`. Scan for the letter of interest rather than relying on fixed column positions.
- `PC` *(integer)*: 16-bit program counter.
- `cycles` *(integer)*: 6502-relative cycle counter (`cycles=` from `r`). Rebases near zero on every BBC Break, the same field reported by [`run_for_cycles`](#run_for_cycles)'s `cycles_total`. For cross-call cycle arithmetic that survives a soft reset, use [`run_for_cycles`](#run_for_cycles) which anchors against beebjit's monotonic tick counter internally.

**Example**

```json
// Request
{"session_id": "<uuid>"}

// Response
{
  "A": 0,
  "X": 0,
  "Y": 0,
  "S": 253,
  "F": "  I  1  ",
  "PC": 55757,
  "cycles": 5000017
}
```

[^ Index](#index)

---

### `read_mode7_text`

Capture the MODE 7 screen as 25 rows of teletext text.

**Parameters**

- `controls` *(string, default `"space"`)*: Selects how non-printable bytes render. One of:
  - `"space"`: single space per non-printable byte. Every row stays exactly 40 characters wide. Best for substring assertions and any caller that indexes into rows by column.
  - `"question"`: single `?` per non-printable byte. Rows stay 40-wide. Useful when callers want non-printable cells visually distinct without decoding the byte value.
  - `"escape"`: four-character `\xNN` escape per non-printable byte. Row widths become variable. Use when callers need the original byte value preserved in the decoded string.

**Returns**

- `rows` *(array of strings)*: Always exactly 25 strings. Width is exactly 40 characters under `"space"` and `"question"`; variable under `"escape"`.
- `text` *(string)*: The same content with `\n` between rows, for convenient substring searching.

**Errors**

- Unknown `controls` value returns a structured error. Use one of the three documented strings.

**Example**

```json
// Request
{"session_id": "<uuid>", "controls": "space"}

// Response
{
  "rows": ["BBC Computer 32K", "", "Acorn DFS", "..."],
  "text": "BBC Computer 32K\n\nAcorn DFS\n..."
}
```

```json
// Request: same screen, escape mode
{"session_id": "<uuid>", "controls": "escape"}

// Response: a control byte 0x80 followed by 'A' renders as `\x80A`
{
  "rows": ["\\x80A...", "..."],
  "text": "\\x80A...\n..."
}
```

**Notes**

The decode is CRTC-scroll-aware. On a BBC the MODE 7 framebuffer sits in a 1024-byte page at `&7C00-&7FFF`. Only 1000 bytes are visible at any time. Hardware scrolling advances the display-start pointer, and the MOS caches it at `&0350/&0351`. The driver reads the whole 1024-byte page plus the pointer, rotates the page into display order, and feeds the 1000 display bytes to the decoder. See [MODE 7 decode](mode7-decode.md) for detail.

This tool is MODE-7-only. In a bitmapped mode (MODE 0-6) the returned rows are not meaningful text. Use [`screenshot`](#screenshot) for the rendered display in any mode.

[^ Index](#index)

---

### `screenshot`

Capture the current rendered BBC screen as a PNG.

**Returns**

A single MCP `image` content block with `mimeType: "image/png"` and `data` containing the base64-encoded PNG bytes. Clients that recognise image content (Claude Desktop, Claude Code, Cursor, and so on) render the screenshot natively and can save it via their own file tools. Width and height (currently 768 and 640 for the standard BBC display) are available in the PNG header eight bytes after the `IHDR` marker for callers that need to read them.

**Errors**

- "no render buffer" surfaced from beebjit itself when the binary lacks the render buffer (typically: launched without `-headless-render`, or running a build that does not support the screen-capture debugger command). See [binary discovery](binary-discovery.md) for the minimum binary requirements.

**Example**

```json
// Request
{"session_id": "<uuid>"}

// Response content
[
  {
    "type": "image",
    "data": "iVBORw0KGgoAAAANSUhEUgAAA...",
    "mimeType": "image/png"
  }
]
```

**Notes**

beebjit renders the BBC screen into a BGRA framebuffer. The driver asks for the buffer via the `savescreen` debugger command, parses the dimensions from beebjit's own output line, and the server converts the BGRA pixel data into a PNG. This is mode-agnostic, so MODE 7, MODE 1, MODE 4 all return a complete rendered screen with no MCP-side per-mode logic.

The PNG is the rendered display, not the raw BBC framebuffer bytes. Hardware scroll, palette, and any video ULA effects are baked in at capture time. Callers wanting the raw screen RAM should use [`read_memory`](#read_memory) at the appropriate mode-base address instead.

[^ Index](#index)

---

### `disassemble`

Disassemble 6502 instructions starting at `addr`.

**Parameters**

- `addr` *(integer)*: 16-bit address to start disassembly at.
- `count` *(integer, default `20`)*: Number of instructions to return. Capped at 20 (beebjit's native batch size).

**Returns**

- `ok` *(boolean)*: `true` on success.
- `instructions` *(array of objects)*: Each object has:
  - `addr` *(integer)*: Address of the instruction.
  - `info` *(string)*: beebjit's per-line tag (`"ITRP"` for interrupt, `"JIT"` for compiled code, sometimes empty).
  - `text` *(string)*: Mnemonic and operands as beebjit prints them.

**Example**

```json
// Request
{"session_id": "<uuid>", "addr": 57344, "count": 5}

// Response
{
  "ok": true,
  "instructions": [
    {"addr": 57344, "info": "ITRP", "text": "JSR $E004"},
    {"addr": 57347, "info": "ITRP", "text": "RTI"}
  ]
}
```

**Notes**

For longer disassembly, loop from the caller side by re-dispatching at the next unread address.

beebjit does not emit raw opcode bytes in its disassembly output. If you need them, pair with [`read_memory`](#read_memory) at the same address.

[^ Index](#index)

## Composition helpers

---

### `run_basic`

Type a BBC BASIC program, run it, and return the final screen.

**Parameters**

- `program` *(string)*: BASIC source. Each line must carry its own line number.
- `boot_cycles` *(integer, default `5000000`)*: Cycles to advance before typing the program (lets the BBC reach the BASIC prompt).
- `settle_cycles` *(integer, default `20000000`)*: Cycles to advance after `RUN` before capturing the screen.

**Returns**

- `ok` *(boolean)*: `true` on success.
- `rows` *(array of strings)*: 25 rows of 40 characters from the MODE 7 screen.
- `text` *(string)*: Newline-joined version of `rows`.

**Example**

```json
// Request
{
  "session_id": "<uuid>",
  "program": "10 PRINT \"HELLO\"\n20 END\n",
  "boot_cycles": 5000000,
  "settle_cycles": 20000000
}

// Response
{
  "ok": true,
  "rows": ["...", "HELLO", ">", "..."],
  "text": "...\nHELLO\n>\n..."
}
```

**Notes**

A convenience wrapper. The same effect is achievable with explicit [`type_input`](#type_input) and [`run_for_cycles`](#run_for_cycles) calls. Use it when the program is a one-shot and the final screen is all you need.

The tool issues `NEW` first to clear any existing program, types the BASIC source, types `RUN`, and runs for `settle_cycles` before capturing.

Does not poll for the prompt after `RUN` because not every program terminates at `>`. Some loop forever, others wait for keypresses. Pair with [`run_until_prompt`](#run_until_prompt) if the program is expected to return to BASIC.

[^ Index](#index)

## Development aids

---

### `reload_module`

Hot-reload a pure beebjit-MCP module without restarting the server.

**Parameters**

- `module_name` *(string)*: Module to reload. Must be `"keyboard"` or `"screen"`.

**Returns**

- `ok` *(boolean)*: `true` on success.
- `reloaded` *(string)*: Fully qualified module name that was reloaded.
- `rebound_in` *(array of strings)*: Modules where `from X import Y` names were rebound to the new module.

**Errors**

- `"driver"` and `"server"` are refused because reloading either would invalidate live session objects. The only safe path for driver or server changes is a full server restart.

**Example**

```json
// Request
{"module_name": "keyboard"}

// Response
{
  "ok": true,
  "reloaded": "beebjit_mcp.keyboard",
  "rebound_in": ["beebjit_mcp.driver", "beebjit_mcp.server"]
}
```

**Notes**

Intended for in-session development: edit `keyboard.py` or `screen.py`, call this tool, and subsequent tool calls pick up the new code.

The reload performs two steps: `importlib.reload` on the target module, then a rebind pass that updates the names dependent modules imported with `from X import Y`. Without the rebind, `driver.asciiToKeys` would still point at the pre-reload function object even after the module was replaced.

Class method bodies are a known limitation. Editing a method on `BeebjitDriver` and reloading `driver` would orphan every live session.

[^ Index](#index)

## Worked example: HELLO round trip

A six-call end-to-end sequence that boots a session, runs a one-line BBC BASIC program, captures the screen, and tears the session down:

```text
1. create_machine {}
   -> {"session_id": "<uuid>"}

2. run_for_cycles {"session_id": s, "cycles": 5000000}
   -> {"ok": true, "cycles_ran": 5000000, "cycles_total": 5000017}

3. type_input {"session_id": s, "text": "PRINT \"HELLO\"\n"}
   -> {"ok": true, "chars": 14}

4. run_until_text {"session_id": s, "needle": "HELLO", "max_cycles": 20000000}
   -> {"ok": true, "found": true, "cycles_ran": 1500000}

5. read_mode7_text {"session_id": s}
   -> {"rows": [..., ">PRINT \"HELLO\"", "HELLO", ">", ...], "text": "..."}

6. destroy_machine {"session_id": s}
   -> {"ok": true}
```

The exact cycle counts vary: `run_for_cycles` may overshoot by a handful of instructions, and `run_until_text` rounds up to the nearest `chunk_cycles` boundary. Treat the numbers here as illustrative.

Step 2 carries the BBC past the ROM banner to the BASIC `>` prompt. Step 3 types the statement and RETURN. Step 4 runs until the echoed `HELLO` appears in MODE 7. Step 5 captures the screen. Step 6 releases the subprocess.

For the full narrative from zero, see [Quickstart](quickstart.md).
