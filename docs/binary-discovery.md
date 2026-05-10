# Binary discovery

beebjit-MCP locates the beebjit executable at runtime, not at install time. This document covers the priority order the server uses, the working-directory contract beebjit imposes, and the failure modes a misconfigured install will hit at runtime. For setup, see the [installation guide](installation.md).

When [`create_machine`](tool-reference.md#create_machine) is invoked, the server resolves a path to a beebjit binary in a fixed priority order, spawns it as a subprocess, and sets the working directory to the binary's parent directory:

1. The `$BEEBJIT` environment variable, if set and pointing at an executable file.

2. The `beebjit` command on the host `$PATH`.

If neither resolves, the call fails with a clear error.

## `$BEEBJIT`

The easiest way to point to the beebjit executable is to set the `$BEEBJIT` environment variable.

> [!IMPORTANT]
> `$BEEBJIT` must point at the beebjit executable, not the directory containing it:

```bash
export BEEBJIT=/home/you/beebjit/beebjit         # correct
export BEEBJIT=/home/you/beebjit                 # wrong (directory)
```

If the path does not resolve to an executable file, the server exits with:

```text
$BEEBJIT points at '/home/you/beebjit' which is not an executable file
```

In an MCP client config, the same value is set under the server's `env` key rather than as a shell export. See the [client wire-up](installation.md#wire-up-an-mcp-client) section of the installation guide for the JSON shape.

## ROMs directory

beebjit loads its OS and language ROMs from a `roms/` directory relative to its working directory at launch. The server sets `cwd=<binary directory>` when spawning, so a binary sitting next to its `roms/` directory works without further setup. Both [install](installation.md#install-beebjit) methods produce that layout.

If beebjit cannot find its ROMs (for example, because the binary was copied somewhere without a `roms/` directory), it exits with:

```text
BAILING: couldn't open roms/os12.rom
```

Two ways to fix this:

- Move or symlink the `roms/` directory next to wherever `$BEEBJIT` points.

- Wrap beebjit in a shell script that `cd`s into the correct directory first, and point `$BEEBJIT` at the script. beebjit inherits its cwd from the script.

## Minimum binary requirements

beebjit-MCP launches every session with the flags `-log-stderr`, `-headless-render`, and `-opt video:always-render`, and the [`screenshot`](tool-reference.md#screenshot) tool also depends on the `savescreen` debugger command. The minimum binary version of beebjit that ships all of these is `v0.9.8-acscpt.2`.

See the [installation guide](installation.md) for the supported binary.
