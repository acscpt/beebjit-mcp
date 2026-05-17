# Keypress timing

`type_input` sends each character as a single BBC keypress. The keypress emits a keydown, runs the BBC for HOLD cycles, emits a keyup, then runs the BBC for GAP cycles before the next keypress. Default HOLD and GAP are both 5 million BBC cycles.

Ten million cycles per character looks extravagant on paper. At the real 2 MHz BBC clock it would be 5 seconds per key. The unit matters: those are BBC cycles, not host cycles. The driver always runs beebjit with `-fast`, so each character completes in a few milliseconds of host wall time. The reason the BBC-side budget is that big is the BBC MOS keyboard ISR. Processing a keypress (latching CA2 on the system VIA, walking the matrix, debouncing, placing a byte in the OS keyboard buffer, clearing IFR, and re-arming IER for the next press) takes millions of emulated cycles to run to completion. A shorter HOLD or GAP leaves that work unfinished and the key is silently dropped.

The 5M/5M default is tuned for 100% reliability against the stock MOS keyboard path from a clean boot. Any reduction below 5M without a corresponding poll-for-VIA-ready strategy will drop keys on some fraction of runs. The measurements below show where the thresholds are and what the failure modes look like.

## The defaults

| Parameter | Default value |
| --- | --- |
| HOLD | 5,000,000 BBC cycles |
| GAP  | 5,000,000 BBC cycles |

Per character typed: 10M BBC cycles total, plus the host-time cost of four debugger commands (`keydown`, `breakat; c` for the HOLD run, `keyup`, `breakat; c` for the GAP run). At `-fast` that is a few ms of host wall time per character.

## Why HOLD and GAP need to be this large

The BBC MOS keyboard ISR is the gatekeeper. From the moment a key is pressed to the moment the OS is ready for the next press, the following happens in emulated BBC cycles:

1. CA2 on the system VIA latches, raising an interrupt.

2. The ISR enters and immediately masks CA2 in IER, so the ongoing matrix scan does not re-fire the interrupt on every held key.

3. The ISR walks the keyboard matrix to identify which key is down.

4. Debounce settles.

5. On release, the character is placed in the OS keyboard buffer at `&03E0`.

6. The ISR clears IFR and re-enables CA2 in IER.

Until step 6 completes, a subsequent `keydown` can latch on the VIA side, but CA2 is masked, so the 6502 never sees the interrupt and the key is silently dropped. HOLD must cover step 1, allowing the press to persist long enough for the ISR to notice. GAP must cover steps 5 and 6, allowing the release to persist long enough for the ISR to clear and re-arm.

## Evidence

The thresholds were measured directly, driving beebjit through the debugger and reading the VIA registers and the keyboard buffer after each step.

### Single-character HOLD threshold

Binary search on HOLD, press read immediately after `keyup`, keyboard buffer byte 0 and MODE 7 row 7 inspected:

| HOLD | GAP | kbd buf byte 0 | MODE 7 row 7 |
| --- | --- | --- | --- |
| 100k | 100k | FF | `>` |
| 500k | 500k | FF | `>` |
| 1M   | 500k | FF | `>` |
| 2M   | 1M   | FF | `>` |
| 3M   | 1M   | P  | `>P` |
| 5M   | 1M   | P  | `>P` |

The threshold is sharp at 3M cycles for a single press from a clean boot. Below that the press never reaches the buffer; at or above 3M, it latches every time.

### Inter-key GAP threshold

Two-key sequence (P then R), HOLD fixed at 3M, GAP varied. IFR and IER read on the system VIA immediately after the first `keyup`:

| GAP | row 7 | IFR after P release | IER after P release |
| --- | --- | --- | --- |
| 1M  | `>P`  | 01 | F2 |
| 5M  | `>PR` | 00 | F3 |

At GAP=1M, IFR bit 0 (CA2 flag) is still set and IER bit 0 (CA2 enable) is still cleared. The ISR is mid-matrix-walk with CA2 masked. A second `keydown` in this window latches on the VIA but the 6502 never sees the interrupt. At GAP=5M, IFR is clear and IER has CA2 re-armed, so the next `keydown` fires the interrupt normally.

### Multi-character reliability

Typing `ABCDEFG` five times at each HOLD/GAP combination:

| HOLD | GAP | pass rate (n=5) |
| --- | --- | --- |
| 3M   | 5M  | 3/5 |
| 5M   | 5M  | 5/5 |
| 8M   | 8M  | 5/5 |
| 10M  | 10M | 5/5 |

HOLD=3M works for a single clean-boot press but drops roughly 40% of keys in a multi-character sequence. The OS takes longer than 3M cycles to settle the matrix between consecutive keys. If the next release arrives before the scan + debounce for the previous one has finished, the OS conflates matrix states and drops at least one key. HOLD=5M gives the ISR the headroom to finish a complete per-key walk before the release that ends the keypress.

## Implications for callers

- **`type_input`** uses the 5M/5M defaults unconditionally. Callers never see the tunables, and typing is reliable on a clean-boot BBC in the stock MOS keyboard path.

- **Long scripted input** scales linearly: 1000 characters is 10 billion BBC cycles, roughly 5 seconds of host time at `-fast`. If the screen scroll between keystrokes matters to the test, break the input with `run_for_cycles` calls between chunks.

- **Non-standard keyboard handlers** (programs that hook their own routines rather than going through OSBYTE or OSRDCH) may observe different thresholds. The 5M/5M numbers are tuned for the stock MOS path; the MCP tools do not currently expose per-call cycle overrides. Use `key_down` / `key_up` and `run_for_cycles` directly to assemble timing tailored to the target program.

- **Autorepeat** is not a concern at these defaults. The BBC OS autorepeat threshold is longer than 5M cycles; a held key at HOLD=5M never triggers it.
