"""Cross-checks that pyproject.toml's version and the runtime __version__
agree, guarding against the two independently-hardcoded strings this
project used to carry silently drifting apart again.
"""

from __future__ import annotations

import importlib
import tomllib
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from unittest.mock import patch

import pytest

from openproject_ce_mcp import __version__


def test_version_matches_pyproject_toml() -> None:
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text())
    assert __version__ == data["project"]["version"]


def test_missing_dist_info_raises_a_remediation_hint_not_a_bare_package_not_found() -> None:
    """Regression: a stale/broken editable install (e.g. a venv whose
    symlinks survived a `brew upgrade python`) previously surfaced as a
    bare `PackageNotFoundError: openproject-ce-mcp` -- true, but with no
    hint that `uv sync --dev` is the fix. Simulates the missing-dist-info
    condition by patching `importlib.metadata.version` and re-importing the
    package fresh."""

    def fake_version(name: str) -> str:
        raise PackageNotFoundError(name)

    with patch("importlib.metadata.version", side_effect=fake_version):
        with pytest.raises(RuntimeError, match=r"uv sync --dev"):
            importlib.reload(importlib.import_module("openproject_ce_mcp"))

    # Reload once more with the patch lifted so later tests in the same
    # process see the real, correctly-populated __version__ again.
    importlib.reload(importlib.import_module("openproject_ce_mcp"))
