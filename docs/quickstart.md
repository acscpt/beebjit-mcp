# Quickstart

This walks you from nothing to a live `HELLO` on a BBC Micro screen driven by an AI agent.

## Install

Follow the [installation guide](installation.md). It covers the beebjit emulator, beebjit-MCP itself, and wiring the server up to your MCP client (Claude Code, Claude Desktop, Cursor, or any other stdio MCP client).

## A Ghost in the machine

A 1981 microcomputer driven directly by a 2026 AI agent.

Ask the agent to drive the emulator. The natural-language prompt does not matter much, and the agent picks tools off the MCP server regardless.

Something like:

> Start a BBC Micro and type a BASIC program to print "HELLO FROM BEEBJIT-MCP", wait for it to appear, then capture the screen.

Under the hood the agent issues this sequence:

1. `create_machine`. Spawns a BBC B and returns a `session_id`.

2. `run_for_cycles` with 5M cycles. Lets the MOS ROMs boot past the banner to the `>` prompt.

3. `type_input` with `PRINT "HELLO FROM BEEBJIT-MCP"\n`. Keys the statement in; the trailing `\n` is RETURN.

4. `run_until_text` looking for `HELLO`. Gives BASIC time to tokenise and run.

5. `read_mode7_text`. Captures the 25x40 teletext screen as text.

6. `destroy_machine`. Releases the beebjit subprocess.

The captured screen comes back looking like this:

```text

BBC Computer 32K

Acorn DFS

BASIC

>PRINT "HELLO FROM BEEBJIT-MCP"
HELLO FROM BEEBJIT-MCP
>
```

Everything else in the [Tool reference](tool-reference.md) composes from these same primitives.

## Where to go next

- [Tool reference](tool-reference.md) for every MCP tool and its JSON return format.

- [Session lifecycle](session-lifecycle.md) for how concurrent sessions behave, what holds one open, and how teardown works.

- [Keypress timing](keypress-timing.md) if `type_input` feels slow or you want to understand why it is metered in millions of cycles per character.

- [Troubleshooting](troubleshooting.md) for common failure modes and their fixes.
