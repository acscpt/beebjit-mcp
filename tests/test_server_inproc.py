# SPDX-FileCopyrightText: 2026 Heisenberg (acscpt)
# SPDX-License-Identifier: MIT

"""In-process tests for the MCP tool function bodies."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from beebjit_mcp import server
from beebjit_mcp.screen import Mode7Controls


_PNG_SIG: bytes = b"\x89PNG\r\n\x1a\n"


def testInProcessLifecycleCoversToolSurface(
    beebjitBinary: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BEEBJIT", str(beebjitBinary))

    created = server.create_machine(model="b")
    sessionId = created["session_id"]
    assert sessionId

    try:
        regs = server.read_registers(sessionId)
        assert "A" in regs and "PC" in regs and "cycles" in regs

        server.write_memory(sessionId, 0x7100, "DE AD BE EF")
        read = server.read_memory(sessionId, 0x7100, 4)
        assert read["hex"].replace(" ", "").upper().startswith("DEADBEEF")

        ran = server.run_for_cycles(sessionId, 5_000_000)
        assert ran["cycles_ran"] == 5_000_000
        assert ran["cycles_total"] >= 5_000_000

        text = server.read_mode7_text(sessionId)
        assert isinstance(text["rows"], list) and len(text["rows"]) == 25
        assert isinstance(text["text"], str)

        textEscape = server.read_mode7_text(sessionId, controls=Mode7Controls.ESCAPE)
        assert isinstance(textEscape["rows"], list)

        d = server.disassemble(sessionId, addr=0xE000, count=4)
        assert len(d["instructions"]) == 4
        assert all("addr" in i and "text" in i for i in d["instructions"])

        server.key_down(sessionId, "A")
        server.run_for_cycles(sessionId, 100_000)
        server.key_up(sessionId, "A")

        toggle = server.press_caps_lock(sessionId)
        assert toggle["ok"] is True

        # Drive both branches of set_caps_lock: the "tap needed" path
        # and the idempotent "already in state" early return.
        first = server.set_caps_lock(sessionId, on=True)
        assert first["caps_lock_on"] is True
        second = server.set_caps_lock(sessionId, on=True)
        assert second["tapped"] is False

        server.type_input(sessionId, "X")
        server.set_caps_lock(sessionId, on=False)
        server.type_input_raw(sessionId, "y")

        # Boot banner contains "BBC" on every supported model, so
        # run_until_text resolves immediately at a tiny budget.
        found = server.run_until_text(
            sessionId, needle="BBC", max_cycles=2_000_000, chunk_cycles=500_000
        )
        assert found["found"] is True

        prompt = server.run_until_prompt(
            sessionId, prompt=">", max_cycles=5_000_000, chunk_cycles=500_000
        )
        assert "found" in prompt

        shot = server.screenshot(sessionId)
        png = base64.b64decode(shot["bytes"])
        assert png.startswith(_PNG_SIG)
        assert shot["width"] > 0 and shot["height"] > 0
        assert shot["format"] == "png"

        basic = server.run_basic(
            sessionId,
            program='10 PRINT "HI"\n',
            boot_cycles=2_000_000,
            settle_cycles=5_000_000,
        )
        assert "rows" in basic and "text" in basic

        server.reset(sessionId, autoboot=False)

    finally:
        result = server.destroy_machine(sessionId)
        assert result["ok"] is True


def testGetDriverRaisesOnUnknownSession() -> None:
    with pytest.raises(KeyError, match="no such session"):
        server._getDriver("not-a-session")


def testCreateMachineRejectsMissingDisc(
    beebjitBinary: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BEEBJIT", str(beebjitBinary))
    with pytest.raises(FileNotFoundError, match="disc image not found"):
        server.create_machine(model="b", disc="/no/such/file.ssd")


def testReloadModuleAcceptsKeyboard() -> None:
    result = server.reload_module("keyboard")
    assert result["ok"] is True
    assert result["reloaded"] == "beebjit_mcp.keyboard"
    assert "beebjit_mcp.driver" in result["rebound_in"]


def testReloadModuleRejectsDriverWithClearError() -> None:
    with pytest.raises(ValueError, match="not supported"):
        server.reload_module("driver")


def testCreateMachineWithDiscAutoboots(
    beebjitBinary: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("BEEBJIT", str(beebjitBinary))
    discPath = tmp_path / "blank.ssd"
    discPath.touch()

    created = server.create_machine(model="b", disc=str(discPath))
    sessionId = created["session_id"]
    try:
        regs = server.read_registers(sessionId)
        assert regs["cycles"] > 0
    finally:
        server.destroy_machine(sessionId)


def testLoadDiscInProcess(
    beebjitBinary: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("BEEBJIT", str(beebjitBinary))
    discPath = tmp_path / "blank.ssd"
    discPath.touch()

    created = server.create_machine(model="b")
    sessionId = created["session_id"]
    try:
        result = server.load_disc(sessionId, disc=str(discPath))
        assert result == {
            "ok": True,
            "drive": 0,
            "disc": str(discPath),
            "writeable": False,
            "mutable": False,
        }
    finally:
        server.destroy_machine(sessionId)


def testLoadDiscMissingFileRaises(
    beebjitBinary: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BEEBJIT", str(beebjitBinary))
    created = server.create_machine(model="b")
    sessionId = created["session_id"]
    try:
        with pytest.raises(FileNotFoundError, match="disc image not found"):
            server.load_disc(sessionId, disc="/no/such/file.ssd")
    finally:
        server.destroy_machine(sessionId)


def testBootDiscInProcess(
    beebjitBinary: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("BEEBJIT", str(beebjitBinary))
    discPath = tmp_path / "blank.ssd"
    discPath.touch()

    created = server.create_machine(model="b")
    sessionId = created["session_id"]
    try:
        result = server.boot_disc(sessionId, disc=str(discPath))
        assert result["ok"] is True
        assert result["disc"] == str(discPath)
    finally:
        server.destroy_machine(sessionId)


def testBootDiscMissingFileRaises(
    beebjitBinary: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BEEBJIT", str(beebjitBinary))
    created = server.create_machine(model="b")
    sessionId = created["session_id"]
    try:
        with pytest.raises(FileNotFoundError, match="disc image not found"):
            server.boot_disc(sessionId, disc="/no/such/file.ssd")
    finally:
        server.destroy_machine(sessionId)


def testDestroyMachineUnknownSessionReturnsOkFalse() -> None:
    assert server.destroy_machine("not-a-session") == {"ok": False}


def testRunUntilTextReturnsFoundFalseOnTimeout(
    beebjitBinary: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BEEBJIT", str(beebjitBinary))
    created = server.create_machine(model="b")
    sessionId = created["session_id"]
    try:
        result = server.run_until_text(
            sessionId,
            needle="ZZZNOMATCHZZZ",
            max_cycles=1_000_000,
            chunk_cycles=500_000,
        )
        assert result["found"] is False
        assert result["ok"] is False
    finally:
        server.destroy_machine(sessionId)


def testRunUntilPromptReturnsFoundFalseOnTimeout(
    beebjitBinary: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BEEBJIT", str(beebjitBinary))
    created = server.create_machine(model="b")
    sessionId = created["session_id"]
    try:
        result = server.run_until_prompt(
            sessionId,
            prompt="ZZZ",
            max_cycles=1_000_000,
            chunk_cycles=500_000,
        )
        assert result["found"] is False
    finally:
        server.destroy_machine(sessionId)


def testRunBasicNormalisesProgramWithoutTrailingNewline(
    beebjitBinary: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BEEBJIT", str(beebjitBinary))
    created = server.create_machine(model="b")
    sessionId = created["session_id"]
    try:
        # No trailing newline so the normalisation branch runs.
        result = server.run_basic(
            sessionId,
            program='10 PRINT "HI"',
            boot_cycles=2_000_000,
            settle_cycles=5_000_000,
        )
        assert "rows" in result
    finally:
        server.destroy_machine(sessionId)


def testWriteMemoryRejectsInvalidHex(
    beebjitBinary: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BEEBJIT", str(beebjitBinary))
    created = server.create_machine(model="b")
    sessionId = created["session_id"]
    try:
        with pytest.raises(ValueError, match="invalid hex"):
            server.write_memory(sessionId, 0x7100, "ZZ NOT HEX")
    finally:
        server.destroy_machine(sessionId)


def testMainCallsMcpRunOverStdio(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fakeRun(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(server.mcp, "run", fakeRun)
    server.main()
    assert captured == {"transport": "stdio"}
