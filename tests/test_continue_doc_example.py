"""Validates the Continue MCP client example in docs/continue.md.

Continue isn't wired into setup_cli.py's Client/configure machinery (its
standalone-file YAML shape is an array of server objects rather than a dict
keyed by server name, unlike this package's other clients) — this is the only
automated check for its documented example. Extracts the JSON block directly
from the doc rather than duplicating it as a literal, so the doc and the test
cannot silently drift apart.

The documented example uses a dict keyed by server name (like every other
client's config in this project) — verified live against Continue's Agent
Mode: the YAML array shape config.yaml itself uses is rejected by the
standalone JSON file with "doesn't match a supported MCP JSON configuration
format".
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"


def _first_json_fence(markdown: str) -> dict:
    match = re.search(r"```json\n(.*?)\n```", markdown, re.DOTALL)
    assert match, "docs/continue.md must contain a ```json fenced code block"
    return json.loads(match.group(1))


def test_continue_mcp_json_example_is_valid_with_expected_shape() -> None:
    data = _first_json_fence((_DOCS_DIR / "continue.md").read_text())

    servers = data["mcpServers"]
    assert isinstance(servers, dict)

    entry = servers["openproject"]
    assert entry["command"]

    env = entry["env"]
    assert env["OPENPROJECT_BASE_URL"]
    assert env["OPENPROJECT_READ_PROJECTS"]
    assert env["OPENPROJECT_WRITE_PROJECTS"]


def test_continue_mcp_json_example_has_no_real_token() -> None:
    data = _first_json_fence((_DOCS_DIR / "continue.md").read_text())
    assert data["mcpServers"]["openproject"]["env"]["OPENPROJECT_API_TOKEN"] == "replace-with-your-token"
