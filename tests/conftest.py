# SPDX-FileCopyrightText: 2026 Heisenberg (acscpt)
# SPDX-License-Identifier: MIT

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture
def beebjitBinary() -> Path:
    env = os.environ.get("BEEBJIT")
    candidates: list[Path] = []
    if env:
        candidates.append(Path(env))
    candidates.append(Path.home() / "programming/bbc/beebjit/beebjit")
    for c in candidates:
        if c.is_file() and os.access(c, os.X_OK):
            return c
    pytest.skip(
        "beebjit binary not found; set $BEEBJIT or install at "
        "~/programming/bbc/beebjit/beebjit"
    )
