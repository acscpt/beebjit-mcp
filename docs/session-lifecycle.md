# Session lifecycle

A session represents one running BBC Micro emulator instance. The client opens a session by calling `create_machine`, which spawns a fresh beebjit subprocess and returns a UUID. The client closes it with `destroy_machine`. In between, the session is long-lived: the same subprocess handles every tool call made with that `session_id`.

The server keeps a session dictionary keyed by UUID. There is no persistence across server restarts and no shared state between concurrent sessions. Each session owns its own subprocess and its own pipes. Sessions do not interfere with each other even when multiple clients share one server process.

A session can leave the steady state in one of three ways: the client calls `destroy_machine`, the subprocess exits unexpectedly (crash, `-cycles` cap, assertion), or the client disconnects without cleanup and the session is left orphaned. Each route has a distinct recovery path.

## States

```mermaid
stateDiagram-v2
    [*] --> None: server startup
    None --> Created: create_machine
    Created --> Created: run_for_cycles,<br/>type_input,<br/>read_*,<br/>run_until_text
    Created --> Created: reset
    Created --> None: destroy_machine
    Created --> Crashed: subprocess exits<br/>mid-command
    Crashed --> None: destroy_machine<br/>(idempotent)
```

"None" means the UUID is absent from the session dictionary. It is not a stored state. `Crashed` means the dictionary still holds an entry whose underlying beebjit subprocess has exited.

## `create_machine`

```mermaid
sequenceDiagram
    participant C as client
    participant S as server
    participant B as beebjit

    C->>S: create_machine
    S->>S: discover binary ($BEEBJIT / PATH)
    S->>B: spawn subprocess
    S->>S: start stdout + stderr reader threads
    B-->>S: banner
    B-->>S: prompt
    S->>S: store driver under new uuid
    S-->>C: {"session_id": uuid}
```

The server blocks until the first `(6502db)` prompt arrives. Typical host time is under 100 ms. A 10-second internal timeout trips only on a genuinely stuck beebjit.

If `disc` is passed to `create_machine`, the server holds SHIFT in the keyboard matrix from cycle zero, mounts the disc image into drive 0, and lets MOS init read SHIFT during its boot keyboard scan. This is the same gesture as a real user holding SHIFT before powering on with a disc inserted. The disc's `!BOOT` runs and `create_machine` returns once a 20M-cycle settle window has elapsed.

Initialisation stops at the first prompt. Anything past the spawn is the caller's responsibility.

## Steady state

After `create_machine` returns, the client drives the session with any combination of `run_for_cycles`, `type_input`, `read_memory`, `read_registers`, `read_mode7_text`, and `run_until_text`. Each tool call looks up the driver by `session_id` (an unknown id surfaces as an MCP tool-call error), invokes the corresponding driver method, and returns the result.

The driver handles one command at a time. `type_input("A")`, for example, expands into a fixed sequence of debugger commands that runs synchronously inside a single MCP call:

```mermaid
sequenceDiagram
    participant C as client
    participant S as server
    participant D as driver
    participant B as beebjit

    C->>S: type_input "A"
    S->>D: typeText("A")
    loop one tap
        D->>B: keydown 65
        B-->>D: prompt
        D->>B: r
        B-->>D: regs line + prompt
        D->>B: breakat X
        B-->>D: prompt
        D->>B: c
        Note over B: BBC runs 5M cycles
        B-->>D: trace line + prompt
        D->>B: keyup 65
        B-->>D: prompt
        Note over B: same, 5M cycle gap
    end
    D-->>S: done
    S-->>C: {"ok": true, "chars": 1}
```

Tool calls against the same session are serialised. MCP tool calls are request and response anyway, so the serialisation matches the transport.

## `destroy_machine`

```mermaid
sequenceDiagram
    participant C as client
    participant S as server
    participant D as driver
    participant B as beebjit

    C->>S: destroy_machine id
    S->>S: pop driver from session dict
    alt id not in dict
        S-->>C: {"ok": false}
    else driver found
        S->>D: close()
        D->>B: q
        B-->>D: EOF (stdin / stdout close)
        D->>D: wait up to 5 seconds for exit
        alt timeout
            D->>B: SIGKILL
            D->>D: wait unconditionally
        end
        D->>D: join reader threads
        S-->>C: {"ok": true}
    end
```

`destroy_machine` is idempotent. Calling it twice for the same id returns `{"ok": false}` the second time, which signals "already gone". Double-destroy on a retried client is safe.

On the clean path, the server sends `q`, beebjit calls `exit(0)`, stdout closes, and the driver reaps the child within 5 seconds. If beebjit does not exit in that window (for example, if it is deadlocked mid-instruction), the driver escalates to `SIGKILL` and waits unconditionally. Reader threads are joined last, so a returning `destroy_machine` means the subprocess and all its pipes are fully released.

## `reset`

`reset` hard-resets the BBC without ending the session. The subprocess and its pipes are unaffected; the same `session_id` continues to work after the call returns. From the client's point of view the BBC has been freshly booted: the 6502 cycle counter has wrapped near zero, BASIC variables and the program are gone, and the boot banner is back at row 1 of MODE 7 screen RAM.

```mermaid
sequenceDiagram
    participant C as client
    participant S as server
    participant D as driver
    participant B as beebjit

    C->>S: reset id (autoboot?)
    S->>D: reset(autoboot)
    opt autoboot
        D->>B: keydown 133 (SHIFT)
    end
    D->>B: keydown 152 (F12 = BREAK)
    D->>B: breakat X; c
    Note over B: F12 hold,<br/>RES asserted
    B-->>D: prompt
    D->>B: keyup 152
    D->>B: breakat Y; c
    Note over B: MOS init runs;<br/>boot keyboard scan<br/>reads SHIFT (if held)
    B-->>D: prompt
    opt autoboot
        D->>B: keyup 133
    end
    D-->>S: done
    S-->>C: {"ok": true}
```

The mechanism is keypress synthesis. F12 is what beebjit accepts for the BBC BREAK key, so injecting `keydown 152` and running briefly with it asserted puts the 6502 into RES. Releasing it lets the OS reset path run, and a generous open-loop cycle window covers MOS init's settle on every supported model.

`autoboot=true` brackets the BREAK with SHIFT, matching the BBC SHIFT+BREAK convention that runs an inserted disc's `!BOOT`. SHIFT is held through the post-BREAK cycle window so MOS reads it during the boot keyboard scan. SHIFT held during reset is harmless on a session created without a disc; the OS comes up at the BASIC prompt regardless.

Total wallclock time is on the order of a few hundred milliseconds at `-fast`.

After `reset` returns, the session is back in steady state. Any prior tool call's effect on the BBC (typed input, written memory, set breakpoints) is gone; everything outside the BBC (the driver, the subprocess, the session id, the per-session temp directory used by `screenshot`) survives.

## Error modes

### Crashed subprocess

beebjit may exit mid-command: the `-cycles` cap trips, a C-level assertion fires, or emulated BBC code wedges the emulator. The driver detects the subprocess exit and surfaces it as a tool-call error with the stderr tail attached for diagnosis.

The session dictionary still holds an entry for the dead session. `destroy_machine` cleans it out, after which a fresh `create_machine` starts over with a new subprocess.

### Stuck subprocess

beebjit stops producing output without crashing (an infinite loop in emulated BBC code, or a bare `c` with no armed stop condition). The driver's per-command timeout (5 seconds for short commands, longer for cycle-bounded runs) trips and surfaces as a tool-call error. The subprocess is still alive. The client can retry, but if the cause is in BBC code the retry will hit the same wall. The reliable recovery is `destroy_machine`, which escalates to `SIGKILL` after 5 seconds if `q` does not bring beebjit down.

### Orphaned process

The MCP client dies without calling `destroy_machine`. The server process still holds the subprocess. If the server itself exits cleanly, the subprocess's stdin pipe closes and beebjit exits when it next tries to read. If the server is SIGKILLed, beebjit processes linger until their `-cycles` cap trips (~14 host hours at default 1e12 at `-fast`) or until someone kills them manually.

The `-cycles` cap is the backstop against indefinite leakage. The server's default is large enough that the cap rarely trips during normal use.

## Capacity

A single server process can hold any number of sessions. They are independent: each owns its own subprocess and its own pipes. Memory cost is dominated by beebjit itself, roughly 30 MB RSS per subprocess. Ten concurrent sessions are on the order of 300 MB.

For details on how the server handles concurrent tool calls, see [architecture: behaviours](architecture.md#behaviours).
