"""OPM-2709: stdout is reserved for MCP JSON-RPC traffic; all logging --
including the new structured tool-call log line -- must go to stderr only.

This is a real, previously-unverified invariant: nothing before OPM-2709
asserted it anywhere in the test suite. A regression here (e.g. a future
`print()` debug statement, or a logging handler accidentally attached to
`sys.stdout`) would corrupt the JSON-RPC stream for every client, silently.

Drives a full client-server roundtrip over `mcp`'s in-memory streams (same
house pattern as test_strict_mcpserver.py's
test_unknown_argument_rejected_over_a_real_client_server_roundtrip), with a
success call, a validation-failure call, and a genuine unhandled-exception
call -- each one exercises a different branch of
_categorize_tool_errors's wrapper and therefore a different
_emit_tool_call_log call site.
"""

from __future__ import annotations

import asyncio
import logging
import sys

import pytest
from mcp import types
from mcp.client.session import ClientSession
from mcp.shared.memory import create_client_server_memory_streams

from openproject_ce_mcp.logging_support import build_formatter
from openproject_ce_mcp.strict_mcpserver import StrictMCPServer
from openproject_ce_mcp.tools_runtime import _categorize_tool_errors


def _text(result: types.CallToolResult) -> str:
    return "".join(getattr(block, "text", "") for block in result.content)


@pytest.fixture
def logging_mcp() -> StrictMCPServer:
    """A minimal server exercising every _categorize_tool_errors branch,
    independent of any real OpenProject client/network -- purely to drive
    real MCP dispatch through the structured-logging wrapper."""
    mcp = StrictMCPServer("test-stdout-purity")

    @mcp.tool()
    @_categorize_tool_errors
    async def ok_tool(name: str) -> str:
        return f"ok {name}"

    @mcp.tool()
    @_categorize_tool_errors
    async def validation_failure_tool() -> str:
        raise ValueError("bad input")

    @mcp.tool()
    @_categorize_tool_errors
    async def crashing_tool() -> str:
        raise KeyError("boom")

    return mcp


async def _run_roundtrip(mcp: StrictMCPServer) -> None:
    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams
        init_options = mcp._lowlevel_server.create_initialization_options()

        async def run_server() -> None:
            await mcp._lowlevel_server.run(server_read, server_write, init_options)

        server_task = asyncio.create_task(run_server())
        try:
            async with ClientSession(client_read, client_write) as session:
                await session.initialize()
                ok = await session.call_tool("ok_tool", {"name": "World"})
                assert ok.is_error is not True
                assert "ok World" in _text(ok)

                validation = await session.call_tool("validation_failure_tool", {})
                assert validation.is_error is True
                assert "[VALIDATION_FAILED]" in _text(validation)

                crash = await session.call_tool("crashing_tool", {})
                assert crash.is_error is True
                assert "[INTERNAL_ERROR]" in _text(crash)
        finally:
            server_task.cancel()
            try:
                await server_task
            except asyncio.CancelledError:
                pass


def test_no_logging_handler_targets_stdout() -> None:
    """A logging handler wired to sys.stdout would interleave arbitrary log
    text into the JSON-RPC stream every real MCP client reads from stdout.
    Every handler on the root logger must target something other than
    sys.stdout (typically sys.stderr)."""
    for handler in logging.getLogger().handlers:
        stream = getattr(handler, "stream", None)
        assert stream is not sys.stdout, f"handler {handler!r} writes to stdout"


@pytest.mark.asyncio
async def test_structured_logging_roundtrip_never_writes_to_stdout(logging_mcp: StrictMCPServer, capsys) -> None:
    """The success/validation-failure/unhandled-exception branches of
    _categorize_tool_errors's wrapper each call _emit_tool_call_log --
    none of that JSON output may reach stdout, only stderr."""
    root = logging.getLogger()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(build_formatter("json"))
    root.addHandler(handler)
    previous_level = root.level
    root.setLevel(logging.INFO)
    try:
        await _run_roundtrip(logging_mcp)
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)

    captured = capsys.readouterr()
    assert captured.out == ""


@pytest.mark.asyncio
async def test_structured_logging_roundtrip_emits_json_lines_to_stderr_only(
    logging_mcp: StrictMCPServer, capsys
) -> None:
    """Complements the stdout-purity check: confirms the JSON log lines
    actually land on stderr (not merely that stdout stays clean), so a
    future refactor that accidentally drops the handler entirely wouldn't
    pass the stdout-purity test above by omission."""
    import io

    stream = io.StringIO()
    root = logging.getLogger()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(build_formatter("json"))
    root.addHandler(handler)
    previous_level = root.level
    root.setLevel(logging.INFO)
    try:
        await _run_roundtrip(logging_mcp)
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)

    lines = stream.getvalue().splitlines()
    assert any('"tool": "ok_tool"' in line and '"status": "success"' in line for line in lines)
    assert any('"tool": "validation_failure_tool"' in line and '"status": "error"' in line for line in lines)
    assert any('"tool": "crashing_tool"' in line and '"status": "error"' in line for line in lines)

    captured = capsys.readouterr()
    assert captured.out == ""
