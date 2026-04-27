# Changelog

All notable changes to beebjit-mcp. Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

This project is pre-alpha. The tool surface, return shapes, and defaults may change without warning until v1.0.

## [Unreleased]

### Added

- First public `v0.1.0-alpha` tag pending.

- **Lifecycle tools**: `create_machine` (spawns a BBC B session with optional disc autoboot), `destroy_machine` (clean teardown with SIGKILL fallback).

- **Execution tools**: `run_for_cycles` (advance by exactly N BBC cycles, anchored on the current cycles register), `run_until_text` (chunk-based run until a needle appears in the MODE 7 screen).

- **Input tool**: `type_input` (ASCII string to keypress sequence with automatic SHIFT handling). HOLD=5M, GAP=5M BBC cycles per character, tuned for 100% reliability against the BBC MOS keyboard ISR.

- **Inspection tools**: `read_memory` (peek contiguous bytes with hex + ASCII gutter), `read_registers` (6502 state decoded to integers), `read_mode7_text` (25x40 teletext decode).

- **Binary discovery**: `$BEEBJIT` environment variable or `beebjit` on `$PATH`. Server refuses to start without a discoverable binary.

- **Threading model in the driver**: main thread is sole writer, two reader threads drain stdout and stderr. Daemon threads so abandoned drivers do not hang interpreter shutdown.

- **Cycle-anchored runs**: `runCycles(n)` reads current cycles, computes absolute target, issues `breakat target; c`. No drift across chained calls.

- **Teletext decode**: `screen.decodeMode7` converts raw framebuffer bytes to 25 rows of 40-char strings. Non-printable bytes become space to preserve column alignment.

- **Scroll-aware MODE 7 capture**: `driver.captureMode7Bytes` reads the 1024-byte physical page and the MOS screen-start pointer at `&0350/&0351`, then rotates via `screen.rotateMode7Page` so decoded output matches the displayed screen after BBC hardware scrolling.

- **`reload_module` MCP tool**: hot-reload `keyboard` or `screen` without restarting the server. Rebinds exported names in `driver` and `server` so `from X import Y` callers pick up the new values. Refuses `driver` and `server` because reloading them would invalidate live session objects.

- **Keyboard PC-carrier mapping**: BBC keys whose physical position does not match their ASCII character are routed through the underlying PC scancode. `:` typed as PC `'`, `@` as PC `` ` ``, `*` as PC `'` shifted. Before this, `:` was silently dropped. See `project_beebjit_keyboard_matrix.md`.

- **`write_memory` MCP tool**: poke bytes at an address. Accepts a hex string with optional whitespace (`"DE AD BE EF"` or `"DEADBEEF"`), symmetric to the `hex` field returned by `read_memory`.

- **`key_down` / `key_up` MCP tools**: low-level composable matrix events. Accept raw integer key codes, single-character strings (upcased for letters), or symbolic names (`"CAPS_LOCK"`, `"ESCAPE"`, `"F1"`, `"LEFT_ARROW"`, ...). Callers pair these with `run_for_cycles` for custom HOLD/GAP timing.

- **`press_caps_lock` and `set_caps_lock` MCP tools**: `press_caps_lock` is a pure toggle (taps key 135); `set_caps_lock(on: bool)` reads the MOS caps-lock flag at `&025A` bit 4 and taps only if the current state differs from the requested one. Idempotent. Enables deterministic case control.

- **`type_input_raw` MCP tool**: case-preserving variant of `type_input`. Requires CAPS LOCK to be OFF. `asciiToKeysRaw` in `keyboard.py` uses the input character's case to decide SHIFT rather than silently upper-casing.

- **Named special keys in `keyboard.py`**: `SPECIAL_KEYS` dict and `resolveKeyName` helper covering codes 128-157 plus the 255 release-all pseudo-key.

- **`disassemble` MCP tool**: returns `count` 6502 instructions starting at a given address, each as `{addr, info, text}` where `info` is beebjit's per-line tag (`"ITRP"`, `"JIT"`, ...). `count` is capped at 20 (beebjit's native batch size); longer runs should loop at the caller level.

- **`run_until_prompt` MCP tool**: row-anchored variant of `run_until_text` that waits for a prompt character at the start of a MODE 7 row (default `">"`). Avoids false matches on the prompt character embedded mid-line.

- **`run_basic` MCP tool**: one-shot convenience. Issues `NEW`, types the BASIC source, `RUN`s it, and returns the MODE 7 screen after `settle_cycles`. Caller owns line numbering.

- **Pre-MOS-init screen capture**: `captureMode7Bytes` now tolerates an uninitialised `&0350/&0351` pointer (typical value `0xFFFF` at cold boot) by clamping to the page base. Lets `run_until_prompt` poll through the boot phase without raising.

- **Tests**: pytest suite covering driver-level primitives, MODE 7 decode, keyboard matrix, and end-to-end HELLO round trip over both driver and MCP.

- **Documentation**: `docs/` directory with architecture, tool reference, session lifecycle, debugger protocol, emulator modes, keypress timing, MODE 7 decode, troubleshooting, development, licensing. README covers install and quickstart.

### Known limitations

- Only BBC B is wired. `model="master"` fails.

- Upstream beebjit is not supported; the server requires the fork's `-log-stderr` flag. See [binary discovery](docs/binary-discovery.md).

- `screenshot`, `reset`, and `load_disc` (post-boot) are not yet wired through the MCP surface. `reset` is blocked on the absence of a beebjit debugger reset command; `load_disc` would require a subprocess respawn because beebjit only accepts discs via the `-0` spawn flag (use `destroy_machine` + `create_machine(disc=...)` for now). `screenshot` is deferred until the per-mode bitmap decoders are in. See `docs/tool-reference.md#unavailable-tools`.

- `type_input` runs ~10M BBC cycles per character (HOLD=5M + GAP=5M). At `-fast` that is a few ms per character on a modern host; long scripted input (~1000 chars) takes low-single-digit seconds of host time.

- `read_mode7_text` is MODE-7-only. In a bitmapped mode (e.g. MODE 1) the returned rows are not meaningful.

- `create_machine` does not accept a `cycles` parameter; session lifetime is capped at the driver default of 1e12 BBC cycles (~14 host hours at `-fast`). Orphaned processes linger until the cap expires.

- FastMCP has no shutdown hook; abandoned sessions in `_sessions` leak on server exit. Client-side `destroy_machine` in a `finally` block is the mitigation.

- No Windows or macOS CI. Linux x86-64 is the primary target; other platforms may work but are not continuously tested.
