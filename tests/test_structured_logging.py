"""OPM-2709: structured stderr logging of per-tool-call diagnostics.

Covers, table-driven where possible:
- every one of the 9 ToolCallLogRecord fields is populated correctly on a
  representative success and a representative failure of each error-code
  family (validation / policy / http_mapper / transport / internal);
- the closed-schema/PII-safety guarantee: a work-package body containing a
  sensitive marker never reaches the emitted JSON log line;
- the token-safety guarantee: the configured API token never appears in any
  captured log record, structured or not.

All exercised directly against `_categorize_tool_errors`-wrapped functions
(the same house pattern as tests/unit/test_tool_validation.py's existing
`_categorize_tool_errors` coverage) rather than through a real HTTP call --
these tests are about the *logging* wrapper's own behavior, not about any
particular client method.
"""

from __future__ import annotations

import json
import logging

import pytest

from openproject_ce_mcp.client import (
    CapabilityDisabledError,
    ConflictError,
    InvalidInputError,
    NotFoundError,
    OpenProjectPermissionDeniedError,
    RateLimitedError,
    TransportError,
)
from openproject_ce_mcp.logging_support import build_formatter
from openproject_ce_mcp.tools_runtime import LOGGER, _categorize_tool_errors


def _structured_records(caplog: pytest.LogCaptureFixture) -> list[dict]:
    return [record.structured for record in caplog.records if hasattr(record, "structured")]


class _FakeCtx:
    def __init__(self, request_id: str | None) -> None:
        self.request_id = request_id


@pytest.mark.asyncio
async def test_success_call_logs_status_success_with_no_error_fields(caplog: pytest.LogCaptureFixture) -> None:
    @_categorize_tool_errors
    async def ok_tool(_ctx) -> str:
        return "fine"

    with caplog.at_level(logging.INFO, logger=LOGGER.name):
        result = await ok_tool(_FakeCtx("req-1"))

    assert result == "fine"
    [record] = _structured_records(caplog)
    assert record["tool"] == "ok_tool"
    assert record["status"] == "success"
    assert record["error_code"] is None
    assert record["layer"] is None
    assert record["request_id"] == "req-1"
    assert isinstance(record["duration_ms"], int)
    assert record["duration_ms"] >= 0


@pytest.mark.asyncio
async def test_request_id_is_none_when_no_context_argument_is_passed(caplog: pytest.LogCaptureFixture) -> None:
    @_categorize_tool_errors
    async def no_ctx_tool() -> str:
        return "fine"

    with caplog.at_level(logging.INFO, logger=LOGGER.name):
        await no_ctx_tool()

    [record] = _structured_records(caplog)
    assert record["request_id"] is None


@pytest.mark.asyncio
async def test_request_id_is_read_from_the_ctx_kwarg_matching_real_mcp_dispatch(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The real MCP SDK dispatch path (func_metadata.call_fn_with_arg_validation)
    calls every tool as `fn(**kwargs)` -- purely by keyword, never positionally --
    with the context always passed under the tool's own parameter name, which is
    `ctx` for every tool function in this codebase. A wrapper that only ever reads
    `args[0]` would see an empty `args` tuple on every real call and silently
    produce `request_id: None` for every single tool call in production."""

    @_categorize_tool_errors
    async def ctx_kwarg_tool(*, ctx) -> str:
        return "fine"

    with caplog.at_level(logging.INFO, logger=LOGGER.name):
        await ctx_kwarg_tool(ctx=_FakeCtx("req-kwarg-1"))

    [record] = _structured_records(caplog)
    assert record["request_id"] == "req-kwarg-1"


# ── error-code-family table: (exception, expected code, expected layer) ────────

_ERROR_FAMILY_CASES = [
    pytest.param(ValueError("bad shape"), "VALIDATION_FAILED", "validation", id="bare-valueerror"),
    pytest.param(InvalidInputError("bad field"), "VALIDATION_FAILED", "http_mapper", id="invalid-input"),
    pytest.param(CapabilityDisabledError("off"), "CAPABILITY_DISABLED", "policy", id="capability-disabled"),
    pytest.param(NotFoundError("gone"), "RESOURCE_NOT_FOUND", "http_mapper", id="not-found"),
    pytest.param(ConflictError("conflict"), "CONFLICT", "http_mapper", id="conflict"),
    pytest.param(RateLimitedError("slow down"), "RATE_LIMITED", "http_mapper", id="rate-limited"),
    pytest.param(
        OpenProjectPermissionDeniedError("no"), "OPENPROJECT_PERMISSION_DENIED", "http_mapper", id="permission"
    ),
    pytest.param(TransportError("network down"), "NETWORK_ERROR", "transport", id="transport"),
]


@pytest.mark.parametrize(("exc", "expected_code", "expected_layer"), _ERROR_FAMILY_CASES)
@pytest.mark.asyncio
async def test_error_family_logs_its_own_code_and_layer(
    caplog: pytest.LogCaptureFixture, exc: Exception, expected_code: str, expected_layer: str
) -> None:
    @_categorize_tool_errors
    async def failing_tool(_ctx) -> str:
        raise exc

    with caplog.at_level(logging.WARNING, logger=LOGGER.name):
        with pytest.raises((ValueError, RuntimeError)):
            await failing_tool(_FakeCtx("req-2"))

    [record] = _structured_records(caplog)
    assert record["status"] == "error"
    assert record["error_code"] == expected_code
    assert record["layer"] == expected_layer
    assert record["request_id"] == "req-2"


def test_json_formatter_includes_traceback_for_logger_exception_calls(caplog: pytest.LogCaptureFixture) -> None:
    """The INTERNAL_ERROR sanitization backstop's LOGGER.exception(...) call
    is the one place the real stack trace survives (the client-facing error
    is deliberately generic) -- the JSON formatter must not silently drop it,
    or an operator debugging a real bug has nothing to go on."""
    with caplog.at_level(logging.ERROR, logger=LOGGER.name):
        try:
            raise KeyError("boom")
        except KeyError:
            LOGGER.exception("Unhandled exception in tool buggy_tool")

    [record] = caplog.records
    formatter = build_formatter("json")
    rendered = json.loads(formatter.format(record))
    assert "boom" in rendered["exception"]
    assert "KeyError" in rendered["exception"]


def test_json_formatter_omits_exception_key_when_no_exc_info(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger=LOGGER.name):
        LOGGER.info("plain message, no exception")

    [record] = caplog.records
    formatter = build_formatter("json")
    rendered = json.loads(formatter.format(record))
    assert "exception" not in rendered


@pytest.mark.asyncio
async def test_unhandled_exception_logs_internal_error(caplog: pytest.LogCaptureFixture) -> None:
    @_categorize_tool_errors
    async def buggy(_ctx) -> str:
        raise KeyError("programmer error")

    with caplog.at_level(logging.WARNING, logger=LOGGER.name):
        with pytest.raises(RuntimeError, match=r"\[INTERNAL_ERROR\]"):
            await buggy(_FakeCtx("req-3"))

    [record] = [r for r in _structured_records(caplog) if r["tool"] == "buggy"]
    assert record["status"] == "error"
    assert record["error_code"] == "INTERNAL_ERROR"
    assert record["layer"] == "internal"


@pytest.mark.asyncio
async def test_runtime_error_path_from_run_tool_still_logs_its_real_code(caplog: pytest.LogCaptureFixture) -> None:
    """Regression coverage for the gap caught during implementation: an
    OpenProjectError translated by _run_tool/_categorize_openproject_error
    into a plain RuntimeError before it reaches this wrapper's `except
    RuntimeError` branch must still produce a real, coded log line -- not
    silently emit nothing, which the very first version of this branch did."""
    from openproject_ce_mcp.tools_runtime import _categorize_openproject_error

    @_categorize_tool_errors
    async def via_run_tool(_ctx) -> str:
        raise _categorize_openproject_error(NotFoundError("missing"))

    with caplog.at_level(logging.WARNING, logger=LOGGER.name):
        with pytest.raises(RuntimeError, match=r"\[RESOURCE_NOT_FOUND\]"):
            await via_run_tool(_FakeCtx("req-4"))

    [record] = _structured_records(caplog)
    assert record["error_code"] == "RESOURCE_NOT_FOUND"
    assert record["layer"] == "http_mapper"


@pytest.mark.asyncio
async def test_cancelled_error_is_not_logged_as_a_tool_call_error(caplog: pytest.LogCaptureFixture) -> None:
    """asyncio.CancelledError must propagate untouched -- and, since it's
    never caught by any branch that calls _emit_tool_call_log, no structured
    record is produced for it at all."""
    import asyncio

    @_categorize_tool_errors
    async def cancelled(_ctx) -> str:
        raise asyncio.CancelledError()

    with caplog.at_level(logging.WARNING, logger=LOGGER.name):
        with pytest.raises(asyncio.CancelledError):
            await cancelled(_FakeCtx("req-5"))

    assert _structured_records(caplog) == []


# ── PII-safety: a sensitive value in the tool's own arguments/return must
#    never leak into the structured log line, since ToolCallLogRecord's
#    schema has no field capable of carrying it ──────────────────────────────


@pytest.mark.asyncio
async def test_sensitive_argument_and_return_value_never_appear_in_log_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sensitive_marker = "SENSITIVE_WORK_PACKAGE_BODY_MARKER_xyz123"

    @_categorize_tool_errors
    async def create_work_package_like(_ctx, description: str) -> dict:
        return {"description": description, "id": 42}

    with caplog.at_level(logging.INFO, logger=LOGGER.name):
        result = await create_work_package_like(_FakeCtx("req-6"), description=sensitive_marker)

    assert result["description"] == sensitive_marker  # the tool's own return value is untouched
    [record] = _structured_records(caplog)
    serialized = json.dumps(record)
    assert sensitive_marker not in serialized
    assert set(record.keys()) == {
        "tool",
        "status",
        "duration_ms",
        "error_code",
        "layer",
        "http_requests",
        "project_scope",
        "policy_decision",
        "request_id",
    }


@pytest.mark.asyncio
async def test_sensitive_value_in_a_raised_exception_message_never_appears_in_log_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Even when the exception message itself contains sensitive-looking
    content (e.g. a client library echoing part of a request body into an
    error message), the structured record carries only the coded
    classification, never the free-text message."""
    sensitive_marker = "SECRET_TOKEN_LOOKALIKE_abc987"

    @_categorize_tool_errors
    async def failing_with_sensitive_message(_ctx) -> str:
        raise NotFoundError(f"resource containing {sensitive_marker} not found")

    with caplog.at_level(logging.WARNING, logger=LOGGER.name):
        with pytest.raises(RuntimeError):
            await failing_with_sensitive_message(_FakeCtx("req-7"))

    [record] = _structured_records(caplog)
    assert sensitive_marker not in json.dumps(record)


@pytest.mark.asyncio
async def test_configured_api_token_never_appears_in_any_captured_log_record(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Scans every record emitted during a representative success + failure
    pair for the literal configured token value -- the structural
    ToolCallLogRecord schema makes this true by construction (no field could
    carry it), but this test exercises the real wrapper end-to-end rather
    than only asserting the schema shape."""
    api_token = "opapi-super-secret-token-should-never-be-logged"  # noqa: S105 -- test fixture value, not a real credential

    @_categorize_tool_errors
    async def ok_tool(_ctx) -> str:
        return f"used token {api_token} internally"

    @_categorize_tool_errors
    async def failing_tool(_ctx) -> str:
        raise NotFoundError(f"auth with {api_token} failed lookup")

    with caplog.at_level(logging.INFO, logger=LOGGER.name):
        await ok_tool(_FakeCtx("req-8"))
        with pytest.raises(RuntimeError):
            await failing_tool(_FakeCtx("req-9"))

    for record in caplog.records:
        assert api_token not in record.getMessage()
        structured = getattr(record, "structured", None)
        if structured is not None:
            assert api_token not in json.dumps(structured)
