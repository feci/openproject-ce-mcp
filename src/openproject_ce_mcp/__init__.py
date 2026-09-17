"""OpenProject CE MCP Server - Model Context Protocol integration for OpenProject Community Edition."""

from importlib.metadata import version

# No PackageNotFoundError fallback: every supported install path (editable
# dev install, uv tool, pip, pipx) publishes dist-info; a raise here means
# the package genuinely isn't installed, which is worth surfacing directly.
__version__ = version("openproject-ce-mcp")
