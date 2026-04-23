# SPDX-FileCopyrightText: 2026 Heisenberg (acscpt)
# SPDX-License-Identifier: MIT

import beebjit_mcp


def testPackageImportable() -> None:
    assert beebjit_mcp.__version__ == "0.0.1"
