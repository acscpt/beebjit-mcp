# Python library worked example

A single end-to-end function that boots a BBC, polls for the BASIC `>` prompt, types and runs a BASIC program that exercises MODE 7 colour and double-height text, decodes the resulting screen, and writes the rendered framebuffer to a PNG on disk.

The API reference for every method used here is at [python-api.md](python-api.md).

## The program

```python
from pathlib import Path

from beebjit_mcp.driver import BeebjitDriver, BeebModel
from beebjit_mcp.screen import decodeMode7, mode7TextContains
from beebjit_mcp.image import bgraToPng


PROGRAM = (
    '10 CLS\n'
    '20 PRINT CHR$(141)CHR$(131)"  BEEBJIT-MCP"\n'
    '30 PRINT CHR$(141)CHR$(131)"  BEEBJIT-MCP"\n'
    '40 PRINT\n'
    '50 PRINT CHR$(129)" C";CHR$(131)" O";CHR$(130)" L";\n'
    '60 PRINT CHR$(134)" O";CHR$(132)" U";CHR$(133)" R";CHR$(135)" S"\n'
    '70 FOR I=1 TO 7\n'
    '80 PRINT CHR$(128+I);"BBC ";\n'
    '90 NEXT\n'
    '100 PRINT\n'
    '110 PRINT CHR$(135)"BBC MICRO MODEL B   MOS 1.20"\n'
)


def runProgramAndCapture(program: str, outputPng: Path) -> list[str]:
    """Boot a BBC, run `program`, write a PNG, return the decoded screen."""

    with BeebjitDriver.fromEnvironment(model=BeebModel.B) as bbc:

        # Poll for the BASIC `>` prompt in half-million-cycle chunks,
        # capped at twenty million so a stuck boot fails loudly rather
        # than hanging the caller.
        budget = 20_000_000
        chunk = 500_000
        while budget > 0 and not mode7TextContains(bbc.captureMode7Bytes(), ">"):
            bbc.runCycles(chunk)
            budget -= chunk
        if budget <= 0:
            raise RuntimeError("BASIC prompt did not appear within budget")

        bbc.typeText("NEW\n")
        bbc.runCycles(1_000_000)
        bbc.typeText(program)
        bbc.typeText("RUN\n")
        bbc.runCycles(15_000_000)

        rows = decodeMode7(bbc.captureMode7Bytes())

        bgra, width, height = bbc.captureScreen()
        outputPng.write_bytes(bgraToPng(bgra, width, height))

        return rows


if __name__ == "__main__":
    rows = runProgramAndCapture(PROGRAM, Path("/tmp/beebjit_demo.png"))
    for row in rows:
        print(row)

    assert "BEEBJIT-MCP" in "\n".join(rows)
```

## The rendered screen

The `bgraToPng` output, saved to `outputPng`:

![Worked example: yellow double-height BEEBJIT-MCP, the word COLOURS with each letter in a different MODE 7 colour, seven colour bands of BBC, and a white BBC MICRO MODEL B line](images/python-api-worked-example.png)

## How it works

This is the flow a test harness would adopt:

1. Construct a driver via [`fromEnvironment`](python-api.md#fromenvironment).

2. Poll until a known marker appears with [`mode7TextContains`](python-api.md#mode7textcontains).

3. Type with [`typeText`](python-api.md#typetext) and advance with [`runCycles`](python-api.md#runcycles).

4. Read state with [`captureMode7Bytes`](python-api.md#capturemode7bytes) and [`captureScreen`](python-api.md#capturescreen).

5. Encode with [`bgraToPng`](python-api.md#bgratopng).

6. Return decoded rows so the caller can assert on them.

The context manager guarantees teardown including the exception path, so a failed `assert` does not leak a beebjit subprocess.

## On the BASIC

The teletext control bytes (`CHR$(129)` and friends) take one column on screen, which is why each rainbow letter is preceded by a space. `CHR$(141)` is double-height, and the BBC convention of printing a double-height line twice (once for the top half, once for the bottom) is what makes the title render fully.
