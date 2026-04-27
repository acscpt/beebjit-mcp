# Troubleshooting

If something goes wrong when calling one of the server's MCP tools then an error is returned. The error message usually identifies the cause on its own. When beebjit itself misbehaves, an attached stderr tail captures what it printed before stopping.

## Index

| Symptom | Likely cause |
| --- | --- |
| [beebjit binary not found](#beebjit-binary-not-found) | `$BEEBJIT` unset and `beebjit` not on `$PATH` |
| [`$BEEBJIT` points at a non-executable](#beebjit-points-at-a-non-executable) | Path is missing, a directory, or lacks the executable bit |
| [`create_machine` fails immediately](#create_machine-fails-immediately) | Missing `roms/`, upstream binary, or wrong CPU/glibc |
| [Register read returns unparseable text](#register-read-returns-unparseable-text) | Upstream beebjit, or mid-command crash |
| [Command times out without a prompt](#command-times-out-without-a-prompt) | Bare `c` without stop condition, or deadlocked subprocess |
| [Character has no BBC key mapping](#character-has-no-bbc-key-mapping) | ASCII char outside the keyboard matrix table |
| [`???` returned by beebjit](#-returned-by-beebjit) | Reader and writer drifted out of step |
| [`type_input` drops characters](#type_input-drops-characters) | Program hooks its own keyboard ISR |
| [`read_mode7_text` returns garbage](#read_mode7_text-returns-garbage) | Not in MODE 7, or called pre-init |
| [`type_input_raw` produces the wrong case](#type_input_raw-produces-the-wrong-case) | CAPS LOCK still ON |
| [`run_for_cycles` returns higher `cycles_total`](#run_for_cycles-returns-a-higher-cycles_total-than-expected) | Breakpoint overshoot, bounded under ten cycles |
| [`run_until_text` returns false with text visible](#run_until_text-returns-found-false-with-the-needle-visible-on-screen) | Transient text, wrong mode, or row boundary |
| [`destroy_machine` returns `{"ok": false}`](#destroy_machine-returns-ok-false) | Session id already gone (idempotent, safe) |
| [Server died, beebjit still running](#server-process-died-beebjit-subprocesses-still-running) | Server SIGKILLed without cleanup |
| [Multiple sessions consuming memory](#multiple-sessions-consuming-memory) | Orphaned sessions from disconnected clients |
| [`claude mcp list` shows disconnected](#claude-mcp-list-shows-beebjit-as-disconnected) | Server failed to launch from `.mcp.json` |
| [New tools not visible in the client](#new-tools-not-visible-in-the-client) | Client caches tool surface at session start |
| [Tool call hangs for 30+ seconds](#tool-call-hangs-for-30-seconds) | Internal per-command timeout exceeded |

## Server will not start

### beebjit binary not found

The server could not resolve `$BEEBJIT` and did not find a `beebjit` executable on `$PATH`.

Check:

```bash
echo $BEEBJIT
which beebjit
```

At least one needs to point at an executable file. See [binary discovery](binary-discovery.md) for the resolution order.

[^ Index](#index)

### `$BEEBJIT` points at a non-executable

Error message: `$BEEBJIT points at '<path>' which is not an executable file`.

`$BEEBJIT` is set but the target is missing, is a directory, or lacks the executable bit. The most common cause is setting it to the parent directory rather than the binary itself:

```bash
export BEEBJIT=/home/you/beebjit/beebjit         # correct
export BEEBJIT=/home/you/beebjit                 # wrong
```

[^ Index](#index)

### `create_machine` fails immediately

The binary exists and is executable, but exits before printing its first `(6502db)` prompt. The error includes a stderr tail. Run beebjit manually from the same cwd the server uses to see the full output:

```bash
cd "$(dirname "$BEEBJIT")"
"$BEEBJIT" -headless -debug -log-stderr -fast -cycles 100000
```

Three common causes:

- `BAILING: couldn't open roms/os12.rom`. The `roms/` directory is not next to the binary. Either move the binary alongside `roms/`, or symlink `roms/` to the binary's directory.

- `unknown option -log-stderr`. The binary is upstream beebjit, not the fork. The server depends on the fork's `-log-stderr` patch. See [installation](installation.md#install-beebjit) for fork acquisition.

- Silent exit with no stderr output. Usually a binary built for a different CPU or glibc. Rebuild from source on the target host.

[^ Index](#index)

## Tools return errors

### Register read returns unparseable text

Error message: `could not parse registers from: ...`. The `r` command's output did not include a parseable `6502 [...]` line. Two typical causes:

- Upstream beebjit (no `-log-stderr` flag). Info lines interleave with debugger output and break the parser. Switch to the fork.

- A mid-command beebjit crash. The subprocess exited while the driver was waiting for `r` to return. The error's stderr tail contains the crash message (BAILING line or assertion).

[^ Index](#index)

### Command times out without a prompt

Error message: `no prompt within <N>s after '<cmd>'`. The driver wrote a command to beebjit and did not receive a prompt before the timeout. Two typical causes:

- A bare `c` with no armed stop condition, which lets the BBC run forever. This should not surface from the MCP tool surface. If it does, that indicates a server bug.

- A deadlocked subprocess. A beebjit assertion or an infinite loop in emulated code that does not produce stdout output. The subprocess is still alive. `destroy_machine` escalates to `SIGKILL` and starts fresh.

[^ Index](#index)

### Character has no BBC key mapping

Error message: `no BBC key for '?'`. `type_input` was given an ASCII character that is not in the keyboard matrix table. Lowercase letters are upper-cased silently to match the BBC's cold-boot CAPS-LOCK-ON default. The characters at risk are non-alphanumeric symbols that differ between layouts. For case-preserving input, use `type_input_raw` after `set_caps_lock(on: false)`.

[^ Index](#index)

### `???` returned by beebjit

beebjit parsed a debugger command it did not recognise. The driver only issues commands that beebjit's parser accepts, so a `???` indicates the reader and writer have drifted out of step. Recovery requires `destroy_machine` followed by a fresh `create_machine`.

[^ Index](#index)

## Emulator runs but behaves oddly

### `type_input` drops characters

The 5M/5M HOLD/GAP defaults are tuned for reliability against the stock MOS keyboard path from a clean boot. If the BBC program under test hooks its own keyboard routines (bypassing OSBYTE or OSRDCH), those defaults may not fit the program's timing. See [keypress timing](keypress-timing.md) for the measurement methodology.

Mitigation: interleave `run_for_cycles` between keystrokes to let the target program process each press before the next arrives.

[^ Index](#index)

### `read_mode7_text` returns garbage

Two usual causes:

- The BBC is not in MODE 7. In a bitmapped mode the bytes at `&7C00` are pixel data, not teletext character codes, so the decoder returns meaningless rows. BASIC defaults to MODE 7 on boot. A program under test may have switched. Issue `MODE 7` via `type_input` to put it back. See [MODE 7 decode](mode7-decode.md).

- The tool was called very early in the boot before the MOS initialised the display-start pointer at `&0350/&0351`. The driver detects this and falls back to the page base, so output is arbitrary but not crashing. Run a few million cycles first, then retry.

[^ Index](#index)

### `type_input_raw` produces the wrong case

CAPS LOCK is still ON. `type_input_raw` assumes CAPS LOCK OFF so that unshifted letter keys produce lowercase. If the session is at its cold-boot default, call `set_caps_lock(session_id, on: false)` before the first `type_input_raw`. That tool reads `&025A` bit 4 and taps key 135 only if the current state does not match the requested one, so repeated calls are idempotent.

[^ Index](#index)

### `run_for_cycles` returns a higher `cycles_total` than expected

beebjit may overshoot a breakpoint by a few instructions because the break fires between instructions and beebjit can be partway through one when it notices. The overshoot is bounded to under ten cycles in practice. The returned `cycles_total` is the exact stopping point. Use it if the cycle budget needs to be spent accurately.

[^ Index](#index)

### `run_until_text` returns `found: false` with the needle visible on screen

Three candidate causes:

- The needle appeared transiently and the screen scrolled before the next check. The default `chunk_cycles` is 500k. For transient output, reduce the chunk size so checks happen more often.

- The BBC is in a bitmapped mode, so MODE 7 decoding does not return teletext. Switch to MODE 7 or fall back to `read_memory` on the framebuffer bytes the program actually uses.

- The needle crosses a row boundary. The decoder joins rows with `\n`, so `HELLO` split across rows 12 and 13 does not match the needle `HELLO`. Shorten the needle, or use `read_memory` directly to inspect the raw layout.

[^ Index](#index)

## Session management

### `destroy_machine` returns `{"ok": false}`

The session id is not in the server's dict. Either it was destroyed already, or it was never created. Idempotent by design, safe to ignore.

[^ Index](#index)

### Server process died, beebjit subprocesses still running

When the server exits cleanly, the subprocess's stdin pipe closes and beebjit exits when it next tries to read. When the server is SIGKILLed, the beebjit subprocesses are reparented and run until their `-cycles` cap trips (~14 host hours at default 1e12 at `-fast`) or until something kills them:

```bash
pkill -f beebjit
```

[^ Index](#index)

### Multiple sessions consuming memory

Each beebjit subprocess is roughly 30 MB RSS. Ten concurrent sessions is ~300 MB. Subprocesses do not share memory. Growth beyond the session count times per-process RSS usually indicates an orphaned session rather than a server-side leak. `ps aux | grep beebjit` against the active session set identifies orphans.

[^ Index](#index)

## Claude Code and other MCP clients

### `claude mcp list` shows beebjit as disconnected

The server did not launch from the client's `.mcp.json`. Verify the `command` path in the config points at the installed `beebjit-mcp` entry script, and that the `BEEBJIT` environment variable in the config points at the beebjit binary. Smoke test the server manually:

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"smoke","version":"0.1"}}}' | <command-from-mcp-json>
```

A working server returns a JSON-RPC `serverInfo` response within a second.

[^ Index](#index)

### New tools not visible in the client

Claude Code and similar clients cache the tool surface at session start. Changes to the server, such as added tools or renamed parameters, require a client-side restart, not just a server restart.

[^ Index](#index)

### Tool call hangs for 30+ seconds

Most likely a `run_for_cycles` call with a cycle count large enough to exceed the internal per-command timeout. Break the work into smaller chunks on the client side.

[^ Index](#index)
