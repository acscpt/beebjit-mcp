# beebjit-MCP

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Tests](https://github.com/acscpt/beebjit-mcp/actions/workflows/tests.yml/badge.svg)](https://github.com/acscpt/beebjit-mcp/actions/workflows/tests.yml)
[![codecov](https://codecov.io/gh/acscpt/beebjit-mcp/branch/main/graph/badge.svg)](https://codecov.io/gh/acscpt/beebjit-mcp)

beebjit-MCP is a Python-based [Model Context Protocol (MCP)](https://modelcontextprotocol.io/docs/getting-started/intro) server that lets an AI application instantiate, connect to, drive, capture output from, and interrogate a real [BBC Micro](https://en.wikipedia.org/wiki/BBC_Micro) emulator.

Ask an AI agent something like:

> Boot a BBC Model B, then type `PRINT "HELLO"` at the BASIC prompt, and read the screen back.

A couple of seconds later `HELLO` appears in the tool-result pane. That's it.

beebjit-MCP drives [Chris Evans' beebjit](https://github.com/scarybeasts/beebjit), a cycle-accurate, high-performance BBC Micro emulator written in C. Install and configure beebjit before using beebjit-MCP. The [installation guide](docs/installation.md) walks through it.

## What the AI agent can do with it

- Boot a BBC B, Master 128 (MOS 3.20 or 3.50), or Master Compact session, with or without a disc image. DFS images use `.ssd` / `.dsd`; ADFS images use `.adl` / `.adf`.

- Type ASCII into the keyboard and have it land as real BBC keypresses. SHIFT handling, CAPS LOCK control, and special keys like arrows and function keys are all wired.

- Wait for text to appear on the MODE 7 screen, or for the BASIC `>` prompt.

- Via the debug REPL interface beebjit-MCP can:
  - read any byte or bytes of BBC Micro RAM
  - write any byte of BBC RAM
  - read 6502 register state
    - A, X, Y, S, PC, P
  - disassemble instructions

- Run a whole BBC BASIC program one-shot and capture the final screen.

- Tear everything down cleanly when the client disconnects.

## Licence

MIT. See [LICENSE](LICENSE).

beebjit is GPLv3 and is never bundled in this repository or its release artefacts; the user installs beebjit themselves.

## Acknowledgements

Thanks to **Chris Evans** (<scarybeasts@gmail.com>), creator and maintainer of [beebjit](https://github.com/scarybeasts/beebjit). Without his work, none of this would exist.

## Fork Notice

This repository points to a _temporary_ [fork of beebjit](https://github.com/acscpt/beebjit) that adds the small set of fixes and flags this MCP harness needs. See [installation](docs/installation.md#install-beebjit) for the exact list.

The main documentation refers to the fork throughout.

## Disclaimer

beebjit-MCP is a separate project from [beebjit](https://github.com/scarybeasts/beebjit), and is not affiliated with, sponsored, or endorsed by [Chris Evans](mailto:scarybeasts@gmail.com) or the beebjit project.

For the canonical beebjit source and documentation, see [scarybeasts/beebjit](https://github.com/scarybeasts/beebjit).
