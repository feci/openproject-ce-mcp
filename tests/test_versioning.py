"""Cross-checks that pyproject.toml's version and the runtime __version__
agree, guarding against the two independently-hardcoded strings this
project used to carry silently drifting apart again.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from openproject_ce_mcp import __version__

_needs_tomllib = pytest.mark.skipif(sys.version_info < (3, 11), reason="tomllib requires Python 3.11+")


@_needs_tomllib
def test_version_matches_pyproject_toml() -> None:
    import tomllib

    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text())
    assert __version__ == data["project"]["version"]
