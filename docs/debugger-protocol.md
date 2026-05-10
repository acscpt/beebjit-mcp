# Debugger protocol

The beebjit debugger is a line-oriented REPL reached by launching beebjit with `-debug`. Every command is one or more words on stdin terminated by a newline. Every response is zero or more lines of output followed by the fixed nine-byte prompt `(6502db)` plus a trailing space (no newline). The driver writes commands, reads from the stream, and splits responses on the prompt boundary.

This REPL is the only channel between the driver side and beebjit. Register reads, memory dumps, keypress timing, and cycle-bounded runs are all built from the commands in this reference.

The commands listed here are the ones the driver issues, although beebjit's debugger has other commands the driver does not currently use.

## Invocation

beebjit is launched with the following command line:

```bash
beebjit -headless -debug -log-stderr -fast -cycles <N> \
        [-0 <disc>]
```

| Flag | Purpose |
| --- | --- |
| `-headless` | No graphical window. All IO through the debugger REPL. |
| `-debug` | Start in the debugger, not in free-run. The first prompt is the session's entry point. |
| `-log-stderr` | Route diagnostic log output to stderr. Fork-only. Upstream beebjit mixes log lines into stdout and breaks prompt framing. |
| `-fast` | Run the emulated CPU flat-out between timer callbacks. |
| `-cycles N` | Cap on total session lifetime in BBC cycles. Use a large value (the server default is 1e12) so the cap acts as a backstop rather than a frequent constraint. |
| `-0 <path>` | Insert disc image into drive 0. |

The working directory must contain a `roms/` directory alongside the beebjit binary. The server sets `cwd` to the binary's parent directory on spawn. See [ROMs directory](binary-discovery.md#roms-directory) for detail.

Flags the driver does not pass: `-run` (would start beebjit free-running and suppress the first prompt) and `-terminal` (incompatible with `-debug`).

## Prompt framing

The debugger prints the prompt `(6502db)` followed by a single space, and flushes stdout after every command. The driver treats that nine-byte sequence as the command-complete marker:

```text
write("r\n")
read stdout until buffer ends with b"(6502db) "
strip trailing prompt from buffer -> payload
```

Subtleties the driver handles:

- Commands that produce no output (most of them) result in two prompts back-to-back: `(6502db) (6502db)`. The line-framing code handles an empty payload.

- On startup, beebjit prints one instruction-trace line before the first prompt. The driver consumes both the trace and the prompt so subsequent commands see a clean buffer.

- Sending just `\n` repeats the previous command on beebjit's side. The driver never does this.

- Commands can be chained with `;` on one line (`breakat 100; c`), but the driver always emits them as separate `sendCommand` calls, one prompt round-trip per command.

## Per-command reference

### `r`

Registers and cycle count.

```text
6502 [A=AA X=00 Y=00 S=FD F=  I  1 N PC=D9CD cycles=8]
sys  [ticks=0 countdown=1]
```

The flags field is eight characters wide, one slot per flag. Unset flags show as a space, set flags carry their letter. The unused `B` slot holds a literal `1`. The driver's regex captures the named fields. The `sys` line is ignored.

### `m <addr>`

Memory dump starting at `<addr>`.

```text
7C00: FF FF FF FF FF FF FF FF FF FF FF FF FF FF FF FF  ................
```

One call prints four lines of 16 bytes each, 64 bytes total. Address is four hex digits, upper case. Bytes are two hex digits, upper case. The trailing gutter renders non-printable bytes as `.`.

`m` with no argument auto-advances by 64 bytes from the previous call. The driver always passes an explicit address. For reads longer than 64 bytes, the driver loops `m` by contiguous address until it has the requested length.

### `writem <addr> <byte> [<byte>...]`

Poke bytes at `<addr>`. No output. The driver chunks into 16-byte pieces so command lines stay manageable.

### `breakat <cycles>`

Set a one-shot cycle breakpoint. No output. Breaks when the cycle counter reaches the given absolute value. The break fires during a subsequent `c`. beebjit then prints the instruction-trace line for the stopped PC, followed by the prompt.

There is no "breakpoint hit" message, unlike the named breakpoints (`b`, `bm`). The `c`-returns pattern is indistinguishable between "named breakpoint hit" and "breakat expired".

### `c`

Continue execution. The BBC thread runs until:

- a breakpoint fires,
- a `breakat` expires,
- the `-cycles` limit is reached (beebjit exits, no prompt returns), or
- the process is killed.

A bare `c` with no armed stop condition lets the BBC run forever. The driver never issues `c` without first issuing `breakat`.

### `keydown <k>` and `keyup <k>`

Key matrix events. No output. `<k>` is a decimal key code that addresses beebjit's keyboard matrix. This is not ASCII. `keydown 65` happens to be `A` only because the matrix position for `A` is at code 65. For digits and punctuation the mapping is matrix-positional, not ASCII-aligned.

Special codes at and above 128:

| Code | Key |
| --- | --- |
| 128 | escape |
| 129 | backspace |
| 130 | tab |
| 131 | enter (RETURN) |
| 132 | ctrl |
| 133 | shift left |
| 134 | shift right |
| 135 | caps lock |
| 136..152 | f0..f12 |
| 146..149 | arrows |
| 156 | delete |
| 157 | home |
| 255 | release-all |

### `q`

Quit. No output. beebjit calls `exit(0)`, stdout closes, and the driver's reader threads see EOF and terminate.

## Failure symptoms

- **Unparseable register output**. The `r` command returns text that does not contain a `6502 [A=... cycles=...]` line. The usual cause is upstream beebjit (no `-log-stderr`, info lines interleave with debugger output). The fallback is a mid-command beebjit crash, where the stderr stream carries the crash message.

- **No prompt after a command**. beebjit accepts the command bytes but never emits the prompt. The usual cause is a bare `c` without an armed stop condition. The fallback is a deadlocked subprocess.

- **No first prompt at startup**. beebjit exits before emitting its first prompt. Usually the `-log-stderr` flag is unavailable (upstream binary), or `roms/` is missing from the working directory. The stderr stream contains the BAILING line.

- **`???` returned**. beebjit's response to a command it does not recognise. The driver issues only the commands documented in this reference, so a `???` indicates that communication has fallen out of sync. The only recovery is to terminate beebjit and start fresh.
