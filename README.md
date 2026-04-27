# beebjit-MCP

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

`beebjit-MCP` is a Python based [model context protocol (MCP)](https://modelcontextprotocol.io/docs/getting-started/intro) server that enables an AI application to instantiate, connect, drive, capture output  and interrogate  a real [BBC Micro](https://en.wikipedia.org/wiki/BBC_Micro) emulator.

Ask an AI agent to boot a _BBC Model B_, then type `PRINT "HELLO"` at the BASIC prompt, and read the screen back. A couple of seconds later `HELLO` appears in the tool-result pane.

It's as easy as that.

The emulator that `beebjit-MCP` is a harness for is  [Chris Evans' beebjit](https://github.com/scarybeasts/beebjit), a cycle-accurate high performance BBC Micro emulator written in C.  It is required to download and configure `beebjit` before using `beebjit-MCP`.

## What the AI agent can do with it

- Boot a BBC B session, with or without a disc image (`.ssd` / `.dsd`).

- Type ASCII into the keyboard and have it land as real BBC keypresses -- SHIFT handling, CAPS LOCK control, and special keys like arrows and function keys are all wired.

- Wait for text to appear on the MODE 7 screen, or for the BASIC `>` prompt.

- Via the debug REPL interface `beebjit-MCP` can:
  - read any byte or bytes of BBC Micro RAM
  - write any byte of BBC RAM
  - read 6502 register state
    - A, X, Y, S, PC, P
  - disassemble instructions

- Run a whole BBC BASIC program one-shot and capture the final screen.

- Tear everything down cleanly when done and the client disconnects.

## Licence

MIT. See [LICENSE](LICENSE).

The server talks to beebjit exclusively via subprocess IPC, which the FSF [classifies as mere aggregation](https://www.gnu.org/licenses/gpl-faq.html#MereAggregation) -- an MIT tool calling a GPLv3 binary does not produce a derivative work. Compiled beebjit binaries are never bundled in this repository or its release artefacts; the user builds beebjit from source. See [Licensing](docs/licensing.md) for the full reasoning.

## Acknowledgements

This project provides an MCP server harness that uses [beebjit](https://github.com/scarybeasts/beebjit), a cycle-accurate BBC Micro emulator created and maintained by **Chris Evans** (<scarybeasts@gmail.com>) and licensed under the [GNU GPLv3](https://github.com/scarybeasts/beebjit/blob/master/COPYING).

None of this would exist without his work.

## Fork Notice

This repository references/directs to a _temporary_ fork of  [beebjit](https://github.com/scarybeasts/beebjit) that contains a small fix and a small feature flag addition that are necessary for this MCP harness.

The main documentation will refer to that [beebjit _fork_](https://github.com/acscpt/beebjit).

## Disclaimer

`beebjit-MCP` is a completely separate project to [beebjit](https://github.com/scarybeasts/beebjit).

It is not affiliated with, sponsored, or endorsed by [Chris Evans](scarybeasts@gmail.com)  or the [beebjit](https://github.com/scarybeasts/beebjit) project.

Please refer to [beebjit](https://github.com/scarybeasts/beebjit).
