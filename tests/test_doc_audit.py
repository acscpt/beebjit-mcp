# SPDX-FileCopyrightText: 2026 Heisenberg (acscpt)
# SPDX-License-Identifier: MIT

"""Meta-tests that keep documentation in sync with the live tool surface.

Every tool registered via `@mcp.tool()` in `server.py` must have a
matching section heading in `docs/tool-reference.md`. New tools that
ship without a doc entry trip this test, so the doc cannot drift
silently as the surface evolves.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from beebjit_mcp.server import mcp


_DOCS_ROOT = Path(__file__).resolve().parents[1] / "docs"
_TOOL_REFERENCE = _DOCS_ROOT / "tool-reference.md"


def _liveToolNames() -> set[str]:
    """Return the names FastMCP itself reports for the live server."""

    tools = asyncio.run(mcp.list_tools())
    return {t.name for t in tools}


def _documentedToolNames() -> set[str]:
    """Names appearing as `### `tool_name`` headings in tool-reference.md.

    Also captures combined headings like `### `key_down` and `key_up``,
    which document two tools in one section.
    """

    pattern = re.compile(r"^###\s+`([a-z0-9_]+)`(?:\s+and\s+`([a-z0-9_]+)`)?", re.MULTILINE)
    text = _TOOL_REFERENCE.read_text(encoding="utf-8")
    names: set[str] = set()
    for match in pattern.finditer(text):
        for group in match.groups():
            if group:
                names.add(group)
    return names


def testEveryLiveToolHasDocSection() -> None:
    live = _liveToolNames()
    documented = _documentedToolNames()
    missing = live - documented
    assert not missing, (
        f"tools registered with @mcp.tool() but absent from "
        f"docs/tool-reference.md: {sorted(missing)}"
    )


def testNoOrphanDocSections() -> None:
    live = _liveToolNames()
    documented = _documentedToolNames()
    orphans = documented - live
    assert not orphans, (
        f"docs/tool-reference.md sections without a live tool: "
        f"{sorted(orphans)}"
    )
