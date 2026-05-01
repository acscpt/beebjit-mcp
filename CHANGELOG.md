# Changelog

All notable changes to beebjit-mcp. Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

This project is pre-alpha. The tool surface, return shapes, and defaults may change without warning until v1.0.

## [Unreleased]

### Added

- **Lifecycle tools**: `create_machine` (spawns a BBC B session with optional disc autoboot), `destroy_machine` (clean teardown with SIGKILL fallback).

- **Execution tools**: `run_for_cycles` (advance by exactly N BBC cycles, anchored on the current cycles register), `run_until_text` (chunk-based run until a needle appears in the MODE 7 screen).

- **Input tool**: `type_input` (ASCII string to keypress sequence with automatic SHIFT handling). HOLD=5M, GAP=5M BBC cycles per character, tuned for 100% reliability against the BBC MOS keyboard ISR.

- **Inspection tools**: `read_memory` (peek contiguous bytes with hex + ASCII gutter), `read_registers` (6502 state decoded to integers), `read_mode7_text` (25x40 teletext decode).

- **Binary discovery**: `$BEEBJIT` environment variable or `beebjit` on `$PATH`. Server refuses to start without a discoverable binary.

- **Threading model in the driver**: main thread is sole writer, two reader threads drain stdout and stderr. Daemon threads so abandoned drivers do not hang interpreter shutdown.

- **Cycle-anchored runs**: `runCycles(n)` reads beebjit's global `total_timer_ticks` counter via `eval ticks`, computes an absolute target, and issues `breakat target; c`. Anchoring against ticks (the same unit `breakat` operates in) rather than the 6502-relative `cycles=` field is what makes the call survive a soft reset. No drift across chained calls.

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

- **`screenshot` MCP tool**: capture the current rendered BBC screen as a base64-encoded PNG, in any display mode. The driver spawns beebjit with `-headless-render` and `-opt video:always-render`, asks the debugger for a BGRA dump via `savescreen`, and a stdlib `_png` module turns those bytes into a PNG with no third-party dependency. Width and height come from beebjit's own savescreen output line so a future render-geometry change flows through automatically.

- **`read_mode7_text` controls parameter**: optional `controls` selects how non-printable bytes render. `"space"` (default) and `"question"` keep rows at 40 chars wide; `"escape"` emits `\xNN` per non-printable byte for callers needing the original byte value preserved in the decoded string.  Mode7Controls enum added.

- **`reset` MCP tool**: hard-reset the BBC without destroying the session, equivalent to a user pressing BREAK on the real keyboard. The 6502 cycle counter wraps, BASIC state is cleared, and the boot banner reappears, the MCP session id stays valid. `autoboot=true` holds SHIFT across the BREAK so an inserted disc's `!BOOT` runs (the BBC SHIFT+BREAK convention). Driven by injecting an F12 keypress at the matrix, then arming a conditional memory-write breakpoint over the banner row at `&7C28` that fires on the first printable character (filtering out MOS's two screen-init passes which write zeros then spaces). The banner row is pre-cleared so the breakpoint can only catch the fresh post-reset banner-print; with autoboot, SHIFT stays held for an extra 1.5M cycles after the breakpoint fires to span the autoboot dispatch window.

- **`load_disc` and `boot_disc` MCP tools**: mid-session disc handling. `load_disc(session_id, disc, drive=0, writeable=False, mutable=False)` mounts a disc image into drive 0 or 1 via the fork's `loaddisc` debugger command. `boot_disc` is the mount + SHIFT+BREAK autoboot one-shot. `writeable` cuts the write-protect notch; `mutable` flushes BBC writes back to the host file and requires `writeable`. Disc paths are checked Python-side before the debugger sees them, so a typo surfaces as a clean `FileNotFoundError`. Old binaries that lack the `loaddisc` command surface a `BeebjitError` pointing at the install docs.

- **`create_machine` runtime mount**: `create_machine(disc=...)` now cold-boots the BBC, mounts the disc via the new `loaddisc` debugger command, then triggers SHIFT+BREAK from a runtime keypress. The argv-time `-autoboot` flag is no longer used. Side effect: `reset(autoboot=False)` on a disc-mounted session now reliably lands at the BASIC prompt; the previously-documented stickiness is gone.

- **Tests**: pytest suite covering driver-level primitives, MODE 7 decode, keyboard matrix, screenshot capture, and end-to-end HELLO round trip over both driver and MCP.

- **Documentation**: `docs/` directory with architecture, tool reference, session lifecycle, debugger protocol, emulator modes, keypress timing, MODE 7 decode, troubleshooting, development, licensing. README covers install and quickstart.

### Fixed

- **`runCycles` no longer hangs after a soft reset.** Previously, `runCycles` anchored its `breakat` target against the 6502-relative `cycles=` field from `r`. That counter rebases near zero on every BBC Break, while `breakat` matches against the global `total_timer_ticks`. Post-Break, the computed target landed in the past relative to ticks, beebjit silently dropped the breakpoint as a no-op, and the subsequent `c` ran with no break condition and never returned. `runCycles` now reads ticks directly via `eval ticks`, so calls work correctly across any number of resets. Empirically confirmed by re-running the original probe across all five chunk shapes and four conditions, all clean. Diagnosis credit to the sibling beebjit fork project.

- **`reset(autoboot=True)` actually fires `!BOOT`.** The previous implementation released SHIFT immediately after F12 release, before MOS's keyboard-matrix scan window. Calls that mounted a disc via `boot_disc` then invoked autoboot ended up at the bare cold-boot BASIC prompt because MOS never saw SHIFT held during its autoboot detection. `reset()` now arms a conditional memory-write breakpoint on the banner row that fires on the first printable character (skipping MOS's zero-clear and space-fill passes), then in the autoboot path holds SHIFT for an extra 1.5M cycles after the breakpoint fires to span the dispatch window. Verified end-to-end with a Nightworld smoke that lands on the in-game title screen.

### Known limitations

- Only BBC B is wired. `model="master"` fails.

- Upstream beebjit is not supported; the server requires the fork's `-log-stderr` flag. See [binary discovery](docs/binary-discovery.md).

- `type_input` runs ~10M BBC cycles per character (HOLD=5M + GAP=5M). At `-fast` that is a few ms per character on a modern host; long scripted input (~1000 chars) takes low-single-digit seconds of host time.

- `read_mode7_text` is MODE-7-only. In a bitmapped mode (e.g. MODE 1) the returned rows are not meaningful.

- `create_machine` does not accept a `cycles` parameter; session lifetime is capped at the driver default of 1e12 BBC cycles (~14 host hours at `-fast`). Orphaned processes linger until the cap expires.

- FastMCP has no shutdown hook; abandoned sessions in `_sessions` leak on server exit. Client-side `destroy_machine` in a `finally` block is the mitigation.

- No Windows or macOS CI. Linux x86-64 is the primary target; other platforms may work but are not tested.
