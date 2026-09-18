"""Structured stderr logging (OPM-2709).

`ToolCallLogRecord` is a closed schema -- the ONLY nine fields a tool-call log
line may ever carry. This is enforced structurally, not by convention: the one
call site that constructs one (`tools_runtime.py`'s `_categorize_tool_errors`
wrapper) is a TypedDict literal, so a future contributor cannot add a tenth
key or assign a non-primitive value (e.g. raw tool kwargs, which could carry
a work-package body, `custom_fields`, or other caller-supplied data) without
a type-checker-visible change to this file. Every value is sourced from
something already known to be safe to log: a tool's own `__name__`, a
monotonic-clock duration, an exception's own `code`/`layer` class attributes
(app/errors.py), an HTTP-request counter, or the MCP protocol's own
per-call `request_id` -- never free-text exception messages, never kwargs,
never the API token/Authorization header (which never appears in a tool's
own kwargs at all -- see client.py's Settings-to-httpx.AsyncClient wiring).

`_JsonLogFormatter` renders BOTH structured tool-call records (passed via
`extra={"structured": record}`, never string-interpolated) and ordinary
free-text log calls from elsewhere in the codebase (the 8 modules with their
own `LOGGER.warning(...)`-style calls that predate this ticket) -- so
`OPENPROJECT_LOG_FORMAT=json` doesn't silently break existing log statements
that were never touched.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal, TypedDict


class ToolCallLogRecord(TypedDict):
    tool: str
    status: Literal["success", "error"]
    duration_ms: int
    error_code: str | None
    layer: str | None
    http_requests: int
    project_scope: str | None
    policy_decision: str | None
    request_id: str | None


class _JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        structured: ToolCallLogRecord | None = getattr(record, "structured", None)
        if structured is not None:
            payload: dict[str, Any] = {
                "level": record.levelname,
                "logger": record.name,
                **structured,
            }
        else:
            payload = {
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
        # LOGGER.exception(...) (the INTERNAL_ERROR sanitization backstop's own
        # local diagnostic, never sent to the client) attaches exc_info -- the
        # JSON formatter must surface it same as the plain-text formatter does
        # by default, or an operator loses the one stack trace the sanitized
        # client-facing error deliberately withholds.
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def build_formatter(log_format: str) -> logging.Formatter:
    if log_format == "json":
        return _JsonLogFormatter()
    return logging.Formatter("%(levelname)s %(name)s %(message)s")
