# beebjit-mcp documentation

This section contains deeper diving documents and background information.

The new reader is directed towards the [Quickstart](quickstart.md) guide. The other docs go deeper on one topic each.

## Getting started

- [Quickstart](quickstart.md) - build beebjit, install this server, register with Claude Code, and run a live HELLO demo. Start here.

- [Tool reference](tool-reference.md) - every MCP tool the server exposes, with parameters, return format, and when to reach for it.

- [MCP worked example](mcp-example.md) - the agent prompt, the tool call sequence it triggers, and the screen capture, for an end-to-end MCP-driven demo.

- [Python API](python-api.md) - the same operations as a Python library, for in-process callers who do not need MCP/JSON-RPC framing.

- [Python worked example](python-example.md) - one annotated end-to-end function that boots a BBC, runs a coloured MODE 7 BASIC program, decodes the screen, and writes a PNG of the result.

- [Troubleshooting](troubleshooting.md) - common failures, their likely causes, and the fix.

## Internals

- [Architecture](architecture.md) - the what and how big picture.

- [Binary discovery](binary-discovery.md) - how the server locates the `beebjit` executable, why installation is BYO, and what the error messages mean.

- [Session lifecycle](session-lifecycle.md) - `create_machine` to `destroy_machine`, what holds a session open, what happens on client disconnect, concurrency semantics.

- [Debugger protocol](debugger-protocol.md) - the subset of beebjit's `(6502db)` REPL the server drives, with per-command framing notes.

- [Keypress timing](keypress-timing.md) - why `type_input` spends 10M BBC cycles per character, tracing back to the BBC MOS keyboard ISR and the system VIA CA2 interrupt.

- [MODE 7 decode](mode7-decode.md) - how `read_mode7_text` renders the teletext framebuffer, including the CRTC-scroll rotation applied before decoding.
