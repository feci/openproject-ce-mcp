"""OpenProject CE MCP Server - Model Context Protocol integration for OpenProject Community Edition."""

from importlib.metadata import PackageNotFoundError, version

# No silent fallback: every supported install path (editable dev install, uv
# tool, pip, pipx) publishes dist-info; a raise here means the package
# genuinely isn't installed, which is worth surfacing directly -- but the
# bare PackageNotFoundError's fixed "No package metadata was found for
# {name}" message gives no hint that a stale/broken editable install (e.g. a
# venv whose symlinks survived a `brew upgrade python`, see this project's
# own CLAUDE.md) is the most likely real-world cause, not a from-scratch
# missing install. A plain RuntimeError (not PackageNotFoundError itself,
# whose __str__ ignores any message and always renders that fixed template
# from a single `name` arg) carries the actual remediation hint instead.
try:
    __version__ = version("openproject-ce-mcp")
except PackageNotFoundError as exc:
    raise RuntimeError(
        "openproject-ce-mcp is not installed in this Python environment (no dist-info found). "
        "If this is a source checkout with a previously-working editable install, the venv is "
        "likely stale (e.g. after a Python upgrade) -- run `uv sync --dev` to rebuild it."
    ) from exc
