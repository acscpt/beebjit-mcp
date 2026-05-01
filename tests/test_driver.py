# SPDX-FileCopyrightText: 2026 Heisenberg (acscpt)
# SPDX-License-Identifier: MIT

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from beebjit_mcp.driver import BeebjitDriver, BeebjitError, BeebModel
from beebjit_mcp.screen import decodeMode7


def testDriverSpawnAndQuit(beebjitBinary: Path) -> None:
    with BeebjitDriver(beebjitBinary) as drv:
        regs = drv.readRegisters()
        assert isinstance(regs["A"], int) and 0 <= regs["A"] <= 0xFF
        assert isinstance(regs["PC"], int) and 0 <= regs["PC"] <= 0xFFFF
        assert isinstance(regs["cycles"], int)


def testDriverMemoryRoundTrip(beebjitBinary: Path) -> None:
    with BeebjitDriver(beebjitBinary) as drv:
        payload = bytes([0x42, 0x69, 0xAB, 0xCD])
        drv.writeMemory(0x7100, payload)
        readBack = drv.readMemory(0x7100, len(payload))
        assert readBack == payload


def testDriverCaptureMode7Text(beebjitBinary: Path) -> None:
    with BeebjitDriver(beebjitBinary) as drv:
        drv.runCycles(5_000_000)
        screenRow0 = drv.readMemory(0x7C00, 40)
        printable = sum(1 for b in screenRow0 if 0x20 <= b <= 0x7E)
        assert printable > 0, f"row 0 all non-printable: {screenRow0.hex()}"


def testDriverDisassembleReturnsInstructionBatch(beebjitBinary: Path) -> None:
    # `&E000` is the start of the MOS ROM on a booted Model B. The
    # first instruction is always `JSR $E004` (the `OSFIND` entry
    # point); even if beebjit's opcode formatting shifts, the 4-hex
    # address and the JSR mnemonic are stable anchors.
    with BeebjitDriver(beebjitBinary) as drv:
        drv.runCycles(5_000_000)
        items = drv.disassemble(0xE000, count=5)
        assert len(items) == 5
        assert items[0]["addr"] == 0xE000
        assert "JSR" in items[0]["text"]
        # Each subsequent address is strictly greater (instructions
        # don't shrink or overlap).
        for earlier, later in zip(items, items[1:]):
            assert int(later["addr"]) > int(earlier["addr"])


def testDriverTapKeyTypesTwoChars(beebjitBinary: Path) -> None:
    with BeebjitDriver(beebjitBinary) as drv:
        drv.runCycles(5_000_000)
        bbcPromptRow = drv.readMemory(0x7C00 + 7 * 40, 40)
        assert bbcPromptRow.startswith(b">"), bbcPromptRow.hex()
        drv.tapKey(ord("P"))
        drv.tapKey(ord("R"))
        row7 = drv.readMemory(0x7C00 + 7 * 40, 40)
        text = row7.rstrip(b" ").decode("ascii", errors="replace")
        assert text.startswith(">PR"), f"expected >PR..., got {text!r}"


def testDriverCaptureScreenReturnsBgraBuffer(beebjitBinary: Path) -> None:
    with BeebjitDriver(beebjitBinary) as drv:
        drv.runCycles(5_000_000)
        bgra, width, height = drv.captureScreen()
        assert (width, height) == (768, 640)
        assert len(bgra) == 768 * 640 * 4
        # Border around the BBC display area is opaque black, so the
        # very first pixel reads as B=0,G=0,R=0,A=0xFF in BGRA byte
        # order. A regression that broke the byte order would change
        # the alpha or zero out the alpha channel.
        assert bgra[:4] == bytes([0x00, 0x00, 0x00, 0xFF])


def testDriverCaptureScreenRaisesOnNoRenderBuffer(tmp_path: Path) -> None:
    # No real beebjit needed: stub sendCommand to simulate the line
    # the binary emits when started without -headless-render.
    drv = BeebjitDriver(Path("/nonexistent/beebjit"))
    drv._tempDir = tmp_path
    with patch.object(
        drv,
        "sendCommand",
        return_value=[
            "no render buffer; start with -headless-render or -frame-cycles"
        ],
    ):
        with pytest.raises(BeebjitError, match="no render buffer"):
            drv.captureScreen()


def testDriverCaptureScreenRaisesIfNotStarted(tmp_path: Path) -> None:
    drv = BeebjitDriver(Path("/nonexistent/beebjit"))
    with pytest.raises(BeebjitError, match="not started"):
        drv.captureScreen()


def testDriverResetAutobootCompletesOnNoDiscSession(
    beebjitBinary: Path,
) -> None:
    # The autoboot variant adds a SHIFT-LEFT keydown/keyup around the
    # F12 BREAK. Without a disc inserted there is no `!BOOT` to run,
    # so the BBC ends up at a plain BASIC prompt either way; the
    # interesting invariant here is that the SHIFT injection does
    # not break the reset path itself.
    #
    # The 6502 cycle counter rebases near zero on every Break, then
    # advances through the reset's SHIFT-hold window (~10M cycles).
    # We pre-run 15M cycles before the reset so that the post-reset
    # value is unambiguously below the pre-reset value, giving a
    # clean cycle-wrap assertion.
    with BeebjitDriver(beebjitBinary) as drv:
        drv.runCycles(15_000_000)
        regsBefore = drv.readRegisters()
        cyclesBefore = int(regsBefore["cycles"])

        drv.reset(autoboot=True)

        regsAfter = drv.readRegisters()
        cyclesAfter = int(regsAfter["cycles"])
        assert cyclesAfter < cyclesBefore, (cyclesBefore, cyclesAfter)


def testDriverLoadDiscMountsEmptySsd(
    beebjitBinary: Path, tmp_path: Path
) -> None:
    # An empty file with a .ssd extension is enough for the fork's
    # pre-checks to accept the mount; we are exercising the command
    # plumbing, not the BBC's reaction to the disc contents.
    discPath = tmp_path / "blank.ssd"
    discPath.touch()
    with BeebjitDriver(beebjitBinary) as drv:
        drv.loadDisc(0, discPath)


def testDriverLoadDiscRaisesOnMissingFile(
    beebjitBinary: Path, tmp_path: Path
) -> None:
    # The driver does not pre-check existence (that lives in the
    # MCP layer). Pointing loaddisc at a non-existent path therefore
    # exercises the fork's own `loaddisc: failed` line.
    missing = tmp_path / "no-such.ssd"
    with BeebjitDriver(beebjitBinary) as drv:
        with pytest.raises(BeebjitError, match="loaddisc: failed"):
            drv.loadDisc(0, missing)


def testDriverLoadDiscRejectsBadDrive(beebjitBinary: Path) -> None:
    # Drive numbers outside {0, 1} are rejected Python-side before
    # the command ever leaves the process; the assertion must hold
    # without a real beebjit, but using the live driver keeps the
    # test honest about how callers actually use the API.
    with BeebjitDriver(beebjitBinary) as drv:
        with pytest.raises(ValueError, match="drive must be 0 or 1"):
            drv.loadDisc(5, "/dev/null")


def testDriverLoadDiscRequiresWriteableForMutable(
    beebjitBinary: Path,
) -> None:
    # The fork rejects `m` without `w`, but mirroring the check
    # Python-side gives a useful traceback before the round trip.
    with BeebjitDriver(beebjitBinary) as drv:
        with pytest.raises(ValueError, match="mutable=True requires"):
            drv.loadDisc(0, "/dev/null", mutable=True)


def testDriverResetWrapsCycleCounter(beebjitBinary: Path) -> None:
    # The 6502 cycle counter wraps near zero on a real RESET. Drive
    # the BBC well past the initial boot so the pre-reset cycle
    # count is high, then call reset and verify the counter has
    # restarted. A no-op reset would leave the counter monotonic.
    with BeebjitDriver(beebjitBinary) as drv:
        drv.runCycles(5_000_000)
        drv.typeText("LET A=42\n")
        drv.runCycles(2_000_000)

        regsBefore = drv.readRegisters()
        cyclesBefore = int(regsBefore["cycles"])
        assert cyclesBefore > 5_000_000, cyclesBefore

        drv.reset()

        regsAfter = drv.readRegisters()
        cyclesAfter = int(regsAfter["cycles"])
        assert cyclesAfter < cyclesBefore, (cyclesBefore, cyclesAfter)


@pytest.mark.parametrize(
    "model",
    ["b", "master", "mos35", "compact"],
)
def testDriverBootsAcrossModels(beebjitBinary: Path, model: str) -> None:
    # Each accepted model spawns cleanly and reaches a settled state
    # within five million cycles. The exact cycle count varies by OS
    # version, but each model's MOS finishes early-init well under
    # the budget; if any model failed to boot, runCycles would hang
    # or readRegisters would fail.
    with BeebjitDriver(beebjitBinary, model=model) as drv:
        drv.runCycles(5_000_000)
        regs = drv.readRegisters()
        assert int(regs["cycles"]) >= 5_000_000


def testDriverAcceptsBeebModelEnumValues(beebjitBinary: Path) -> None:
    # Passing an enum member is interchangeable with the wire string,
    # because `BeebModel` inherits from `str`. The driver normalises
    # both to the enum internally.
    with BeebjitDriver(beebjitBinary, model=BeebModel.MASTER) as drv:
        drv.runCycles(2_000_000)


def testDriverRejectsUnknownModel(beebjitBinary: Path) -> None:
    # Unknown model strings should fail at construction time with a
    # clear error rather than at spawn time with a beebjit usage line.
    with pytest.raises(ValueError, match="unknown model"):
        BeebjitDriver(beebjitBinary, model="electron")


@pytest.mark.parametrize(
    ("model", "expectedBanner"),
    [
        ("b", b"BBC Computer"),
        ("master", b"Acorn MOS"),
        ("mos35", b"ACORN MOS"),
        ("compact", b"Acorn MOS"),
    ],
)
def testDriverPerModelBoot(
    beebjitBinary: Path, model: str, expectedBanner: bytes
) -> None:
    # Each model writes a distinct banner during cold boot. Asserting
    # against the expected per-model string proves the right OS image
    # ran, not just that some boot-banner write happened. The bytes
    # land at row 1 of MODE 7 screen RAM (`&7C28`) on every model.
    with BeebjitDriver(beebjitBinary, model=model) as drv:
        drv.runCycles(10_000_000)
        bannerRow = drv.readMemory(0x7C28, len(expectedBanner))
        assert bannerRow == expectedBanner, (model, bannerRow)


@pytest.mark.parametrize(
    ("model", "expectedBanner"),
    [
        ("b", "BBC Computer"),
        ("master", "Acorn MOS"),
        ("mos35", "ACORN MOS"),
        ("compact", "Acorn MOS"),
    ],
)
def testDriverPerModelMode7Decode(
    beebjitBinary: Path, model: str, expectedBanner: str
) -> None:
    # The full MODE 7 capture path goes through `captureMode7Bytes`
    # (which reads the page and applies the scroll-pointer rotation)
    # and `decodeMode7` (which renders teletext bytes to text). Both
    # need to behave identically across models, since the framebuffer
    # location and the scroll-pointer address are hardware-fixed.
    with BeebjitDriver(beebjitBinary, model=model) as drv:
        drv.runCycles(10_000_000)
        rows = decodeMode7(drv.captureMode7Bytes())
        assert len(rows) == 25
        assert any(expectedBanner in row for row in rows), (
            model,
            expectedBanner,
            rows,
        )


@pytest.mark.parametrize(
    "model",
    ["b", "master", "mos35", "compact"],
)
def testDriverPerModelScreenshot(
    beebjitBinary: Path, model: str
) -> None:
    # Screenshot capture is rendered by beebjit, not by the MCP layer,
    # so the per-model story is "does beebjit render this model into
    # a sensible buffer". Geometry is fixed at 768x640 BGRA on every
    # model. The first pixel is the top-left border, which should be
    # opaque (alpha 0xFF), confirming the buffer was actually painted
    # and not left as zeroed memory.
    with BeebjitDriver(beebjitBinary, model=model) as drv:
        drv.runCycles(10_000_000)
        bgra, width, height = drv.captureScreen()
        assert (width, height) == (768, 640)
        assert len(bgra) == 768 * 640 * 4
        assert bgra[3] == 0xFF, (model, bgra[:4])


@pytest.mark.parametrize(
    "model",
    ["b", "master", "mos35", "compact"],
)
def testDriverColdBootAutobootOnEmptyDisc(
    beebjitBinary: Path, tmp_path: Path, model: str
) -> None:
    # `coldBootWithAutoboot` is the unified autoboot path used by
    # `create_machine(disc=)` and `boot_disc`. The cycle-zero SHIFT
    # injection fires autoboot uniformly across every supported
    # model, including Master 128 / MOS 3.50 which silently misses a
    # mid-session SHIFT+BREAK. An empty SSD (or an empty .adl on
    # Compact) is enough to exercise the SHIFT-during-boot-scan path:
    # the OS will end up at an error message because the disc has no
    # catalogue, but the assertion is that autoboot dispatched at all,
    # not that the disc booted to a useful state. We detect dispatch
    # by the cycle counter advancing past the settle window: the call
    # blocks for ~20M cycles inside `coldBootWithAutoboot`.
    extension = ".adl" if model == "compact" else ".ssd"
    discPath = tmp_path / f"blank{extension}"
    discPath.touch()
    with BeebjitDriver(beebjitBinary, model=model) as drv:
        drv.coldBootWithAutoboot(0, discPath)
        regs = drv.readRegisters()
        # 20M cycles in the settle window plus some MOS init slop.
        assert int(regs["cycles"]) >= 19_000_000


def testDriverScreenshotsDifferAcrossModels(beebjitBinary: Path) -> None:
    # Each model renders a distinct boot banner ("BBC Computer 32K",
    # "Acorn MOS", "ACORN MOS", "Acorn MOS / Acorn ADFS"), so the
    # rendered framebuffers must differ pairwise. Hashing rather than
    # full byte-comparison keeps the assertion compact and surfaces a
    # readable failure if two models ever start rendering the same
    # screen (which would mean the model flag silently degraded).
    import hashlib

    digests: dict[str, str] = {}
    for model in ("b", "master", "mos35", "compact"):
        with BeebjitDriver(beebjitBinary, model=model) as drv:
            drv.runCycles(10_000_000)
            bgra, _, _ = drv.captureScreen()
        digests[model] = hashlib.sha256(bgra).hexdigest()

    # Pairwise distinct: a set of all four digests must have size 4.
    assert len(set(digests.values())) == 4, digests


def testDriverMode7PatternRendersIdenticallyAcrossModels(
    beebjitBinary: Path,
) -> None:
    # MODE 7 rendering is hardware-defined (the SAA5050 teletext chip
    # is the same on every BBC variant beebjit emulates). Writing the
    # same byte pattern into MODE 7 screen RAM on every model and
    # screenshotting should therefore yield identical pixel content,
    # proving the rendering layer is model-agnostic.
    #
    # BBC B and both Master 128 variants produce byte-identical
    # framebuffers. The Master Compact's MOS programs CRTC R07 (the
    # vertical-sync position register) one row earlier than the other
    # models, which shifts its rendered frame UP by exactly twenty
    # pixel rows. The shifted-window comparison below proves the
    # underlying MODE 7 content is the same on every model and
    # documents the Compact-only vertical offset.
    #
    # The pattern is the line "beebjit-MCP I'm inside a beeb!" with
    # alpha-green, alpha-cyan, and alpha-red teletext control codes
    # tinting the segments. Each control byte occupies one MODE 7
    # cell as a space and shifts the colour of subsequent text on
    # the same row. Repeated for all twenty-five rows.
    import hashlib

    # 0x82 alpha-green, 0x86 alpha-cyan, 0x81 alpha-red.
    line = b"\x82beebjit-MCP \x86I'm inside a \x81beeb!       "
    assert len(line) == 40, len(line)
    pattern = line * 25  # 1000 bytes covering the visible MODE 7 page

    buffers: dict[str, bytes] = {}
    width = 0
    for model in ("b", "master", "mos35", "compact"):
        with BeebjitDriver(beebjitBinary, model=model) as drv:
            drv.runCycles(10_000_000)
            drv.writeMemory(0x7C00, pattern)
            # One 50Hz frame is 40k cycles at 2MHz; 200k gives the
            # renderer multiple frames to settle and pick up the
            # writes.
            drv.runCycles(200_000)
            bgra, width, _ = drv.captureScreen()
        buffers[model] = bgra

    # The three older models share a single hash.
    nonCompactHashes = {
        hashlib.sha256(buffers[m]).hexdigest()
        for m in ("b", "master", "mos35")
    }
    assert len(nonCompactHashes) == 1, nonCompactHashes

    # Compact's frame, shifted up by twenty pixel rows, byte-matches
    # the BBC B frame on the overlapping region.
    rowBytes = width * 4
    shiftBytes = 20 * rowBytes
    bRef = buffers["b"]
    compact = buffers["compact"]
    assert bRef[: len(bRef) - shiftBytes] == compact[shiftBytes:], (
        "Compact frame does not match BBC B at the expected 20-row shift; "
        "CRTC R07 may have changed."
    )
