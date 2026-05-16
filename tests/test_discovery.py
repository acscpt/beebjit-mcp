# SPDX-FileCopyrightText: 2026 Heisenberg (acscpt)
# SPDX-License-Identifier: MIT

"""Unit tests for binary discovery and the fromEnvironment classmethod."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from beebjit_mcp.driver import BeebjitDriver, BeebModel, discoverBinary


def _makeFakeBinary(tmpPath: Path) -> Path:
    fake = tmpPath / "beebjit"
    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return fake


def testDiscoverBinaryHonoursBeebjitEnvVar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _makeFakeBinary(tmp_path)
    monkeypatch.setenv("BEEBJIT", str(fake))
    assert discoverBinary() == fake


def testDiscoverBinaryRaisesWhenBeebjitEnvVarBroken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bogus = tmp_path / "does-not-exist"
    monkeypatch.setenv("BEEBJIT", str(bogus))
    with pytest.raises(FileNotFoundError, match="BEEBJIT"):
        discoverBinary()


def testDiscoverBinaryFallsBackToPath(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _makeFakeBinary(tmp_path)
    monkeypatch.delenv("BEEBJIT", raising=False)
    monkeypatch.setattr(
        "beebjit_mcp.driver.shutil.which", lambda name: str(fake)
    )
    assert discoverBinary() == fake


def testDiscoverBinaryRaisesWhenNothingResolves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BEEBJIT", raising=False)
    monkeypatch.setattr("beebjit_mcp.driver.shutil.which", lambda name: None)
    with pytest.raises(FileNotFoundError, match="not found"):
        discoverBinary()


def testFromEnvironmentReturnsConfiguredDriver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _makeFakeBinary(tmp_path)
    monkeypatch.setenv("BEEBJIT", str(fake))
    drv = BeebjitDriver.fromEnvironment(model=BeebModel.MASTER, cycles=42)
    assert drv._binaryPath == fake
    assert drv._model == BeebModel.MASTER
    assert drv._cycles == 42


def testFromEnvironmentPropagatesDiscoveryError(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BEEBJIT", raising=False)
    monkeypatch.setattr("beebjit_mcp.driver.shutil.which", lambda name: None)
    with pytest.raises(FileNotFoundError):
        BeebjitDriver.fromEnvironment()
