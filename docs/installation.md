# Installation guide

beebjit-MCP runs as an MCP server that your MCP client (Claude Desktop, Claude Code, Cursor, and so on) spawns over stdio. Once installed and wired up, the client can call tools like `create_machine`, `type_input`, and `run_basic` to drive a live BBC Micro session.

The steps to get there are:

1. Install the beebjit emulator binary.
2. Install beebjit-MCP itself.
3. Configure your MCP client to spawn the server.

## Prerequisites

- Python 3.10 or newer.

- An MCP client. [Claude Desktop](https://claude.ai/download), [Claude Code](https://claude.com/claude-code), and [Cursor](https://cursor.sh) are tested. Any client that speaks the [Model Context Protocol](https://modelcontextprotocol.io) over stdio will work.

- Linux x86-64 or Windows x86-64. Other platforms may work when built from source but are not currently published as release binaries.

- `git`, `gcc`, and standard build tools, needed only for the build-from-source option below.

## Install beebjit

beebjit-MCP requires the [acscpt/beebjit](https://github.com/acscpt/beebjit) fork. The fork carries the following changes against upstream beebjit:

1. A `-log-stderr` flag that routes beebjit's internal logging to stderr instead of stdout, leaving the stdout stream as a clean source of debugger output for the MCP driver to parse.

2. A fix to beebjit's memory allocation that resolves intermittent allocation failures observed at certain segment sizes.

3. A `-headless-render` flag that allocates the BGRA render buffer in headless mode, which the [`screenshot`](tool-reference.md#screenshot) tool requires.

4. A `savescreen <path>` debugger command that dumps the current render buffer as a raw BGRA file. The MCP server reads this file, converts to PNG, and returns the bytes through `screenshot`.

The minimum fork version that ships these changes is `v0.9.8-acscpt.2`.

There are two ways to obtain [acscpt/beebjit](https://github.com/acscpt/beebjit).

### Download a release binary

Tagged releases are published at [github.com/acscpt/beebjit/releases](https://github.com/acscpt/beebjit/releases).

| Artifact | Use for beebjit-MCP |
| --- | --- |
| `beebjit-headless-linux-x86_64` | **Recommended for Linux.** No GUI dependencies. |
| `beebjit-headless-windows-x86_64.exe` | **Recommended for Windows.** No GUI dependencies. |
| `beebjit-linux-x86_64` | Linux, GUI build. |
| `beebjit-windows-x86_64.exe` | Windows, GUI build. |

> [!IMPORTANT]
> beebjit-MCP runs the emulator headlessly so only the headless variants can be used.

The downloaded binary also needs a `roms/` directory next to it at runtime. The simplest way to get both into one place:

```bash
# Clone the fork next to where you want it
git clone --depth 1 https://github.com/acscpt/beebjit.git ~/beebjit

# Pull down the headless release binary alongside the roms/ directory
cd ~/beebjit
wget https://github.com/acscpt/beebjit/releases/latest/download/beebjit-headless-linux-x86_64 -O beebjit

# Make it executable
chmod +x beebjit
```

This puts the released binary alongside the `roms/` directory shipped in the repository.

### Build from source

Building the fork requires gcc, and cross-compiling the Windows binary on Linux requires gcc-mingw.

Clone the fork and build:

```bash
# Clone the fork
git clone https://github.com/acscpt/beebjit.git

# Build the headless binary
cd beebjit
./build_headless_opt.sh
```

The resulting `beebjit` binary sits in the repository root next to its `roms/` directory.

## Install beebjit-MCP

For a standard install, use PyPI:

```bash
# Create and activate a venv
python -m venv ~/.venvs/beebjit-mcp
source ~/.venvs/beebjit-mcp/bin/activate

# Install beebjit-MCP from PyPI
pip install beebjit-mcp
```

For a development install:

```bash
# Clone the repo
git clone https://github.com/acscpt/beebjit-mcp.git
cd beebjit-mcp

# Create and activate a venv
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install in editable mode with dev extras
pip install -e ".[dev]"
```

Both paths install the `beebjit-mcp` command-line entry point inside the venv.

## Wire up an MCP client

MCP clients learn about servers from a JSON config file. The format is the same across clients (an `mcpServers` object keyed by server name); only the file location differs.

A typical entry:

```json
{
  "mcpServers": {
    "beebjit": {
      "command": "/absolute/path/to/beebjit-mcp/.venv/bin/beebjit-mcp",
      "args": [],
      "env": {
        "BEEBJIT": "/absolute/path/to/beebjit/beebjit"
      }
    }
  }
}
```

Two paths must be absolute:

- `command` is the path to the `beebjit-mcp` entry point inside the venv where you installed beebjit-MCP.

- `BEEBJIT` is the path to the beebjit binary you installed in the first step. The MCP client spawns the server in an unspecified working directory, so a relative path will not resolve.

### Claude Code

Project-level config lives in `.mcp.json` at the project root:

```text
project-root/
├── .mcp.json
├── src/
├── tests/
└── ...
```

To register the server across all your projects (user scope) or just this project for just you (local scope), use the `claude mcp add` command:

```bash
claude mcp add --scope user beebjit \
  -e BEEBJIT=/absolute/path/to/beebjit \
  -- /absolute/path/to/.venv/bin/beebjit-mcp
```

`--scope` accepts `local`, `project`, or `user`. Run `claude mcp add --help` for the full set of options.

### Claude Desktop

Edit `claude_desktop_config.json`:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

Restart Claude Desktop after editing.

### Other clients

Any MCP client that speaks stdio JSON-RPC accepts the same `mcpServers` entry format with its own config location. Consult the client's documentation for where the config file lives.

## Verify

With the venv activated, start the server manually to confirm the install:

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"smoke","version":"0.1"}}}' | beebjit-mcp
```

A JSON-RPC response containing `"serverInfo":{"name":"beebjit-mcp", ...}` confirms the server is running.

The handshake does not exercise the beebjit binary. The first `create_machine` call from your MCP client confirms `$BEEBJIT` resolves correctly. For an end-to-end walk-through, see the [quickstart](quickstart.md).
