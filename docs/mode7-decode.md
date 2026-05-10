# MODE 7 decode

`read_mode7_text` captures the current BBC screen as text. MODE 7 stores teletext character codes in a 1024-byte page at `&7C00-&7FFF`. The CRTC displays 1000 of those bytes per frame, starting from a display-start pointer the MOS caches at `&0350/&0351`. The server reads the full page plus the pointer, rotates into display order, and runs the result through `screen.decodeMode7` to produce 25 rows of 40 characters each.

MODE 7 is the one BBC display mode where text capture is straightforward. The bitmapped modes (0-6) store pixel data, which would need per-mode rendering and glyph tables to turn back into characters. MODE 7, by contrast, stores teletext character codes directly in screen memory, so extracting text is a memory read plus a byte-to-character map on the Python side. No emulator cooperation is needed beyond the `m` (memory dump) debugger command.

The decoder is text-only. Printable ASCII passes through untouched. Teletext control codes, graphics glyphs, uninitialised memory, and any other non-printable byte render per the `controls` parameter (default `space`). That is enough for BASIC prompt output, INPUT lines, PRINT-driven text, and any other text-mode BBC output. Visual teletext features such as colour, flash, and double-height are not preserved.

## MODE 7 on the BBC

MODE 7 is the BBC Micro's teletext display mode, driven by the SAA5050 teletext chip and the BBC's CRTC. The framebuffer layout is:

- 40 columns x 25 rows = 1000 bytes displayed per frame
- Physical page is 1024 bytes at `&7C00-&7FFF`. The CRTC masks its address counter with `0x3FF`, so hardware scroll wraps at `&8000` back to `&7C00`
- Each byte is a teletext character code, not a pixel bitmap
- The CRTC and SAA5050 render glyphs on the fly. The CPU only writes codes

## Hardware scroll

BBC MODE 7 scrolls by advancing the CRTC's display-start address, not by copying 40 bytes of memory per row. After the first scroll, the byte at `&7C00` is no longer in the top-left cell. It has wrapped to somewhere else in the page. The MOS caches the current CPU-space display start at `&0350/&0351` (little-endian), and the display is always `1000` contiguous bytes starting from that pointer, wrapping at the end of the 1024-byte page.

The server handles this in `driver.captureMode7Bytes` and `screen.rotateMode7Page`:

1. Read the full 1024-byte page from `&7C00`.

2. Read the 2-byte display-start pointer from `&0350`.

3. Compute `offset = (pointer - 0x7C00) & 0x3FF`.

4. Rotate: `display = page[offset:] + page[:offset]`, then trim to 1000 bytes.

A flat read of 1000 bytes from `&7C00` matches the display only before any scroll has happened. Once the screen starts scrolling, the rows come back in the wrong order.

During cold boot, before the MOS has written the pointer, `&0350/&0351` holds uninitialised RAM (typically `0xFFFF`). The driver detects an out-of-range pointer and falls back to `&7C00` so callers polling the screen during boot (for example `run_until_prompt`) get arbitrary but exception-free output rather than a hard failure.

## Character encoding

The teletext character set overlaps ASCII but is not identical. Three ranges matter to the decoder:

- `0x20..0x7E` is printable. `chr(b)` produces the right character for text matching. A few cells differ from their ASCII equivalents (`\` and `_` are teletext-specific glyphs), but the difference is cosmetic for string search.

- `0x00..0x1F` and `0x80..0x9F` are teletext control codes. They set colour, flash, double-height, graphics/alphanumeric mode, and similar side effects. They occupy screen cells and display as blank on real hardware.

- `0xA0..0xFF` are teletext graphics glyphs (mosaic blocks used when the surrounding row is in graphics mode).

## Decoder behaviour

`decodeMode7` is a pure function from 1000 bytes to 25 rows. Printable ASCII passes through. Every other byte renders per the `controls` parameter, a `Mode7Controls` enum member from `screen.py`:

- `Mode7Controls.SPACE` (default): single space per non-printable byte. Every row stays exactly 40 characters wide. Best for substring assertions and column-indexing callers; covers teletext control codes, uninitialised memory (`0xFF` after boot, before the first screen paint), graphics glyphs, and non-printable ASCII in one stroke. With this mode any non-space character in the output is real BBC-written content.

- `Mode7Controls.QUESTION`: single `?` per non-printable byte. Rows stay 40-wide. Lets callers spot non-printable cells visually without decoding the byte value.

- `Mode7Controls.ESCAPE`: four-character `\xNN` escape per non-printable byte. Row widths become variable. Use when callers need to round-trip the original byte value out of the decoded string.

```json
// Default behaviour: control bytes render as space, rows stay 40 wide
{"session_id": "<uuid>"}

// Round-trip raw bytes by switching the `controls` parameter
{"session_id": "<uuid>", "controls": "escape"}
```

`Mode7Controls` is a `(str, Enum)`, so the JSON wire format `"space"` / `"question"` / `"escape"` is accepted directly by the MCP tool and converted to the matching member before the decoder runs.

## What the decoder does not render

`read_mode7_text` captures text content only. Visual teletext features are collapsed to space or ignored:

- **Colour**. Colour-set control codes (e.g. `ALPHA RED = 0x81`) render as space. Text content underneath is unaffected.

- **Graphics glyphs** (`0xA0..0xFF`). Mosaic blocks render as space. Programs that mix text and teletext graphics (such as CEEFAX mockups) keep their text content but lose the graphics.

- **Double-height**. A `DOUBLE HEIGHT` control code causes the next row on real hardware to render the top half of the previous row's characters. The decoder reads each row independently, so the second row renders its own underlying bytes rather than a repeat of the row above.

- **Flash and conceal**. The control codes are dropped. The character underneath is rendered unchanged.

- **Graphics/alphanumeric mode state across a row**. The decoder does not track whether a row is currently in graphics or alphanumeric mode. It emits printable ASCII as ASCII and everything else as space.

## Return shape

```json
{
  "rows": ["                                        ", "..."],
  "text": "                                        \n...\n..."
}
```

`rows` is a list of 25 strings, each exactly 40 characters wide. `text` is `"\n".join(rows)`. Both come from the same read and never drift. The newline join matters for `run_until_text`: without it, a needle like `END` at the end of row 0 followed by a space at the start of row 1 would spuriously match `END ` across the row boundary.

## Non-MODE-7 machines

If the BBC is in a bitmapped mode when `read_mode7_text` is called, the bytes at `&7C00` are pixel data rather than teletext character codes. The tool still returns 25 rows of 40 characters, but the content is not meaningful text. Bytes that happen to fall in the printable-ASCII range pass through as noise. Everything else renders as space. Callers that change mode should track the current mode and invoke this tool only while the machine is in MODE 7.

## When to use which memory-read tool

Three MCP tools read BBC memory, each suited to a different use case:

- `run_until_text(needle)` is the right choice for waiting on specific output. It runs the emulator in chunks and calls `decodeMode7` between chunks until the needle appears, short-circuiting as soon as the text is found. Cheaper than polling `read_mode7_text` in a client-side loop.

- `read_mode7_text` is the one-shot capture after the machine has settled. Returns decoded text.

- `read_memory(addr=0x7C00, length=1024)` returns the raw physical page in memory order (hex + ASCII gutter). Use this when you suspect the decoder is dropping information you need, or when inspecting a non-MODE-7 screen. Read `&0350` for two bytes to see the current display-start pointer if you need to match what the CRTC is painting.
