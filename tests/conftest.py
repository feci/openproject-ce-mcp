"""Shared unit-test fixtures."""

from __future__ import annotations

import sys
from pathlib import Path

# The api-check scripts import each other as plain modules, which works when run
# as scripts (their directory is sys.path[0]) but not when a test loads one by file.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "api-check"))
