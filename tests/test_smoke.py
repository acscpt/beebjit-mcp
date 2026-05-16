# SPDX-FileCopyrightText: 2026 Heisenberg (acscpt)
# SPDX-License-Identifier: MIT

import beebjit_mcp
from beebjit_mcp import BeebjitDriver, BeebjitError, BeebModel


def testPackageImportable() -> None:
    assert beebjit_mcp.__version__ == "0.0.1"


def testTopLevelReExports() -> None:
    from beebjit_mcp.driver import BeebjitDriver as DriverDriver
    from beebjit_mcp.driver import BeebjitError as DriverError
    from beebjit_mcp.driver import BeebModel as DriverModel

    assert BeebjitDriver is DriverDriver
    assert BeebjitError is DriverError
    assert BeebModel is DriverModel
    assert set(beebjit_mcp.__all__) == {
        "BeebjitDriver",
        "BeebjitError",
        "BeebModel",
        "__version__",
    }
