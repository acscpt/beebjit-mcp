# SPDX-FileCopyrightText: 2026 Heisenberg (acscpt)
# SPDX-License-Identifier: MIT

"""Pytest fixtures and the --report plugin for beebjit-mcp.

The beebjitBinary fixture locates the user-installed beebjit binary,
skipping tests cleanly when one is not present.

The --report flag generates TEST_REPORT.md after a run, including a
structured listing of every test grouped by module and class,
pass/fail/skip status, duration, and (when pytest-cov is active) a
per-file code coverage summary.

    pytest tests/ --report

The report is written to tests/TEST_REPORT.md at the repository root.
"""

from __future__ import annotations

import ast
import datetime
import inspect
import os
import re
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest


# -----------------------------------------------------------------------
# beebjit binary discovery
# -----------------------------------------------------------------------

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


# -----------------------------------------------------------------------
# --report plugin registration
# -----------------------------------------------------------------------

def pytest_addoption(parser: Any) -> None:
    """Register the --report flag."""
    parser.addoption(
        "--report",
        action="store_true",
        default=False,
        help="Generate tests/TEST_REPORT.md after the test run.",
    )


def pytest_configure(config: Any) -> None:
    """Attach the report collector when --report is set."""
    if config.getoption("--report", default=False):
        plugin = ReportCollector(config)
        config._report_collector = plugin
        config.pluginmanager.register(plugin, "report_collector")


# -----------------------------------------------------------------------
# Report collector
# -----------------------------------------------------------------------

class ReportCollector:
    """Collects test results and writes the markdown report."""

    def __init__(self, config: Any) -> None:
        self._config = config
        self._results: List[Dict[str, Any]] = []
        self._descriptions: Dict[str, str] = {}

    def pytest_collection_modifyitems(
        self,
        session: Any,
        config: Any,
        items: List[Any],
    ) -> None:
        """Capture per-test descriptions from docstrings during collection."""
        del session
        del config

        for item in items:
            self._descriptions[item.nodeid] = _describeTestItem(item)

    def pytest_runtest_logreport(self, report: Any) -> None:
        """Capture the final outcome of each test."""

        # Record only the final outcome: "call" for pass/fail, "setup" for
        # setup-time skips, anything failing in setup/teardown as an error.
        if report.when == "call":
            outcome = report.outcome
        elif report.when == "setup" and report.outcome == "skipped":
            outcome = "skipped"
        elif report.failed:
            outcome = "error"
        else:
            return

        self._results.append({
            "nodeid": report.nodeid,
            "outcome": outcome,
            "duration": report.duration,
            "longrepr": str(report.longrepr) if report.failed else "",
            "description": self._descriptions.get(report.nodeid, ""),
        })

    def pytest_sessionfinish(self, session: Any, exitstatus: int) -> None:
        """Write the report after all tests complete."""
        del session
        del exitstatus

        root = str(self._config.rootpath)
        report_path = os.path.join(root, "tests", "TEST_REPORT.md")
        coverage = _extractCoverage(self._config)
        content = _buildReport(self._results, coverage)

        with open(report_path, "w") as f:
            f.write(content)

        # Mirror the report into the Actions job summary when present.
        summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary_path:
            with open(summary_path, "a") as f:
                f.write(content)


# -----------------------------------------------------------------------
# Coverage extraction
# -----------------------------------------------------------------------

def _extractCoverage(config: Any) -> Optional[List[Tuple[str, int, int, int]]]:
    """Pull per-file coverage data from pytest-cov.

    Returns a list of (filename, stmts, miss, cover_pct) tuples,
    or None if coverage data is unavailable.
    """
    cov_plugin = config.pluginmanager.getplugin("_cov")
    if cov_plugin is None:
        return None

    cov = getattr(cov_plugin, "cov_controller", None)
    if cov is None:
        return None

    cov_obj = getattr(cov, "cov", None)
    if cov_obj is None:
        return None

    results = []
    try:
        data = cov_obj.get_data()
        for filename in sorted(data.measured_files()):
            analysis = cov_obj._analyze(filename)
            stmts = len(analysis.statements)
            miss = len(analysis.missing)
            cover = int(analysis.numbers.pc_covered) if stmts > 0 else 100
            short = filename
            marker = os.sep + "beebjit_mcp" + os.sep
            idx = filename.rfind(marker)
            if idx >= 0:
                short = filename[idx + 1:]
            results.append((short, stmts, miss, cover))
    except Exception:
        return None

    return results if results else None


# -----------------------------------------------------------------------
# Rendering helpers
# -----------------------------------------------------------------------

def _statusBadge(outcome: str) -> str:
    """Return a shields.io image badge for the test outcome."""
    labels = {
        "passed": ("PASS", "2ea043"),
        "failed": ("FAIL", "cf222e"),
        "skipped": ("SKIP", "9a6700"),
        "error": ("ERROR", "a40e26"),
        "xfailed": ("XFAIL", "8250df"),
        "xpassed": ("XPASS", "0a7ea4"),
    }
    label, color = labels.get(outcome, (outcome.upper(), "57606a"))
    return f"![{label}](https://img.shields.io/badge/{label}-{color})"


def _coverageBar(pct: int) -> str:
    """Build an HTML progress bar for code coverage, color-coded by threshold."""
    clamped = max(0, min(100, pct))
    if clamped >= 80:
        color = "#2ea043"
    elif clamped >= 60:
        color = "#d29922"
    else:
        color = "#cf222e"
    # Always show at least 4% width so the bar is visible at very low coverage.
    visible_pct = max(4, clamped) if clamped > 0 else 0
    return (
        "<span style=\"display:inline-block;width:98px;background:#30363d;"
        "border-radius:4px;overflow:hidden;vertical-align:middle;\">"
        f"<span style=\"display:inline-block;width:{visible_pct}%;"
        f"background:{color};\">&nbsp;</span></span> {clamped}%"
    )


def _coverageFileLink(filename: str) -> str:
    """Link a coverage row filename to the source file under src/."""
    if filename.startswith("beebjit_mcp/"):
        return f"[{filename}](../src/{filename})"
    return filename


def _moduleDocstring(module: str) -> str:
    """Return the module-level docstring from a test file, or an empty string."""
    tests_dir = os.path.dirname(__file__)
    repo_root = os.path.dirname(tests_dir)
    filepath = os.path.join(repo_root, module)
    if not os.path.isfile(filepath):
        return ""
    try:
        with open(filepath, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        doc = ast.get_docstring(tree)
        return doc or ""
    except (OSError, SyntaxError):
        return ""


def _moduleLink(module: str) -> str:
    """Link a test module heading to its source file."""
    if module.startswith("tests/"):
        relative = module[len("tests/"):]
        return f"[{module}](./{relative})"
    return module


def _normalizeWhitespace(text: str) -> str:
    """Collapse whitespace and trim to a single readable line."""
    return re.sub(r"\s+", " ", text).strip()


def _humanizeTestName(test_name: str) -> str:
    """Convert internal test names to readable sentence case."""
    if "[" in test_name and test_name.endswith("]"):
        base, param = test_name.split("[", 1)
        suffix = f" [{param[:-1]}]"
    else:
        base = test_name
        suffix = ""

    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", base)
    spaced = spaced.replace("_", " ")
    spaced = re.sub(r"(?i)^test\s+", "", spaced)
    pretty = _normalizeWhitespace(spaced)

    if not pretty:
        return test_name

    return pretty[0].upper() + pretty[1:] + suffix


def _describeTestItem(item: Any) -> str:
    """Build a test description using docstring first, then name fallback."""
    parts: List[str] = []

    cls = getattr(item, "cls", None)
    if cls is not None:
        class_doc = inspect.getdoc(cls)
        if class_doc:
            first = _normalizeWhitespace(class_doc).split(". ")[0]
            parts.append(first.rstrip("."))

    obj = getattr(item, "obj", None)
    if obj is not None:
        doc = inspect.getdoc(obj)
        if doc:
            parts.append(_normalizeWhitespace(doc))

    module_obj = getattr(item, "module", None)
    if module_obj is not None and not parts:
        module_doc = inspect.getdoc(module_obj)
        if module_doc:
            first = _normalizeWhitespace(module_doc).split(". ")[0]
            parts.append(first.rstrip("."))

    if parts:
        return " - ".join(parts)

    return _humanizeTestName(item.name)


def _escapeTableCell(text: str) -> str:
    """Escape markdown table delimiters in user-controlled strings."""
    return text.replace("|", "\\|")


def _badgeUrl(label: str, message: str, color: str) -> str:
    """Build a shields.io badge URL for summary counters."""
    safe_label = label.replace(" ", "%20")
    safe_message = message.replace(" ", "%20")
    return f"https://img.shields.io/badge/{safe_label}-{safe_message}-{color}"


# -----------------------------------------------------------------------
# Markdown report builder
# -----------------------------------------------------------------------

def _buildReport(
    results: List[Dict[str, Any]],
    coverage: Optional[List[Tuple[str, int, int, int]]],
) -> str:
    """Build the full TEST_REPORT.md content."""
    lines: List[str] = []
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines.append("# Test Report")
    lines.append("")
    lines.append(f"Generated: {timestamp}")
    lines.append("")
    lines.append("## Overview")
    lines.append("")
    lines.append("This report summarizes the latest pytest run for this repository.")
    lines.append("It includes pass and fail outcomes, code coverage highlights, and")
    lines.append("per-test descriptions sourced from test docstrings when available.")
    lines.append("")

    # -- Summary -------------------------------------------------------

    total = len(results)
    passed = sum(1 for r in results if r["outcome"] == "passed")
    failed = sum(1 for r in results if r["outcome"] == "failed")
    skipped = sum(1 for r in results if r["outcome"] == "skipped")
    errors = sum(1 for r in results if r["outcome"] == "error")
    duration = sum(r["duration"] for r in results)
    pass_rate = int((passed / total) * 100) if total else 100

    lines.append(
        " ".join([
            f"![Total tests]({_badgeUrl('tests', str(total), '0366d6')})",
            f"![Passed]({_badgeUrl('passed', str(passed), '2ea043')})",
            f"![Failed]({_badgeUrl('failed', str(failed), 'cf222e')})",
            f"![Skipped]({_badgeUrl('skipped', str(skipped), '9a6700')})",
            f"![Pass rate]({_badgeUrl('pass%20rate', f'{pass_rate}%25', '2ea043')})",
        ])
    )
    lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append(f"| Metric | Count |")
    lines.append(f"| --- | ---: |")
    lines.append(f"| Total tests | {total} |")
    lines.append(f"| Passed | {passed} |")
    lines.append(f"| Failed | {failed} |")
    lines.append(f"| Skipped | {skipped} |")
    if errors:
        lines.append(f"| Errors | {errors} |")
    lines.append(f"| Pass rate | {pass_rate}% |")
    lines.append(f"| Duration | {duration:.2f}s |")
    lines.append("")

    lines.append("```mermaid")
    lines.append("pie title Test outcomes")
    lines.append(f"    \"Passed\" : {passed}")
    lines.append(f"    \"Failed\" : {failed}")
    lines.append(f"    \"Skipped\" : {skipped}")
    if errors:
        lines.append(f"    \"Errors\" : {errors}")
    lines.append("```")
    lines.append("")

    # -- Coverage summary (if available) -------------------------------

    if coverage:
        total_stmts = sum(s for _, s, _, _ in coverage)
        total_miss = sum(m for _, _, m, _ in coverage)
        overall = int(
            ((total_stmts - total_miss) / total_stmts * 100) if total_stmts else 100
        )
        covered = total_stmts - total_miss

        lines.append("## Code Coverage")
        lines.append("")
        lines.append(f"**Overall: {overall}%**")
        lines.append("")
        lines.append(_coverageBar(overall))
        lines.append("")
        lines.append("```mermaid")
        lines.append("pie title Covered vs missed statements")
        lines.append(f"    \"Covered\" : {covered}")
        lines.append(f"    \"Missed\" : {total_miss}")
        lines.append("```")
        lines.append("")

        lines.append("### Per-file Coverage")
        lines.append("")
        lines.append("| File | Stmts | Miss | Coverage |")
        lines.append("| --- | ---: | ---: | --- |")
        for filename, stmts, miss, cover in coverage:
            link = _coverageFileLink(filename)
            lines.append(
                f"| {link} | {stmts} | {miss} | {_coverageBar(cover)} |"
            )
        lines.append("")

        worst = sorted(coverage, key=lambda row: (-row[2], row[3], row[0]))[:8]
        lines.append("### Coverage Priorities")
        lines.append("")
        lines.append("| File | Missing lines | Cover |")
        lines.append("| --- | ---: | ---: |")
        for filename, _stmts, miss, cover in worst:
            lines.append(f"| {_coverageFileLink(filename)} | {miss} | {cover}% |")
        lines.append("")

    # -- Detailed results grouped by module/class ----------------------

    lines.append("## Test Results")
    lines.append("")

    grouped = _groupResults(results)

    for module, classes in grouped.items():
        lines.append(f"### {_moduleLink(module)}")
        lines.append("")

        doc = _moduleDocstring(module)
        if doc:
            for paragraph in doc.split("\n\n"):
                line = paragraph.replace("\n", " ").strip()
                if line:
                    lines.append(f"> {line}")
                    lines.append(">")
            if lines[-1] == ">":
                lines[-1] = ""
            else:
                lines.append("")

        for classname, tests in classes.items():
            if classname:
                lines.append(f"**{classname}**")
                lines.append("")

            lines.append("| Status | Test | Description | Time |")
            lines.append("| --- | --- | --- | ---: |")
            for test in tests:
                icon = _statusBadge(test["outcome"])
                desc = _escapeTableCell(test["description"])
                lines.append(
                    f"| {icon} | {test['name']} | {desc} | {test['duration']:.3f}s |"
                )
            lines.append("")

    # -- Failures (if any) ---------------------------------------------

    failures = [r for r in results if r["outcome"] in ("failed", "error")]
    if failures:
        lines.append("## Failures")
        lines.append("")
        for f in failures:
            lines.append(f"### {f['nodeid']}")
            lines.append("")
            lines.append("```")
            lines.append(f["longrepr"])
            lines.append("```")
            lines.append("")

    return "\n".join(lines) + "\n"


def _groupResults(
    results: List[Dict[str, Any]],
) -> "OrderedDict[str, OrderedDict[str, List[Dict[str, Any]]]]":
    """Group results by module and class, preserving insertion order."""
    grouped: OrderedDict[str, OrderedDict[str, List[Dict[str, Any]]]] = OrderedDict()

    for r in results:
        nodeid = r["nodeid"]

        # nodeid looks like "tests/test_foo.py::TestClass::testMethod"
        # or "tests/test_foo.py::test_function".
        parts = nodeid.split("::")
        module = parts[0]

        if len(parts) == 3:
            classname = parts[1]
            testname = parts[2]
        elif len(parts) == 2:
            classname = ""
            testname = parts[1]
        else:
            classname = ""
            testname = nodeid

        if module not in grouped:
            grouped[module] = OrderedDict()
        if classname not in grouped[module]:
            grouped[module][classname] = []

        grouped[module][classname].append({
            "name": testname,
            "outcome": r["outcome"],
            "duration": r["duration"],
            "description": r.get("description", ""),
        })

    return grouped
