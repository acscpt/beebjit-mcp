# SPDX-FileCopyrightText: 2026 Heisenberg (acscpt)
# SPDX-License-Identifier: MIT

from __future__ import annotations

import pytest

from beebjit_mcp import driver, keyboard, screen, server


def testReloadKeyboardRebindsDriver() -> None:
    originalFn = driver.asciiToKeys
    result = server.reload_module("keyboard")

    assert result["ok"] is True
    assert result["reloaded"] == "beebjit_mcp.keyboard"
    assert "beebjit_mcp.driver" in result["rebound_in"]

    # Post-reload, keyboard.asciiToKeys is a fresh function object and
    # driver.asciiToKeys must point at the same fresh object.
    assert driver.asciiToKeys is keyboard.asciiToKeys
    assert driver.asciiToKeys is not originalFn


def testReloadScreenRebindsDriverAndServer() -> None:
    result = server.reload_module("screen")

    assert result["ok"] is True
    assert result["reloaded"] == "beebjit_mcp.screen"
    assert "beebjit_mcp.driver" in result["rebound_in"]
    assert "beebjit_mcp.server" in result["rebound_in"]

    assert driver.MODE7_BASE_ADDR == screen.MODE7_BASE_ADDR
    assert server.decodeMode7 is screen.decodeMode7


def testReloadUnsupportedModuleRaises() -> None:
    with pytest.raises(ValueError, match="not supported"):
        server.reload_module("driver")
