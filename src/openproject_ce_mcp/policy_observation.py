"""Per-tool-call policy-decision/project-scope observation (OPM-2709's
`policy_decision`/`project_scope` log fields).

`access.py`'s `ensure_write_enabled`/`ensure_read_enabled` and `scope.py`'s
`ensure_project_link_allowed`/`ensure_project_write_link_allowed` (+ their
`_if_present` variants) are pure "return None or raise" functions with
~260 total call sites across every domain -- there is no proportionate way
to add an explicit log call at every call site without touching all of them.
Recording the OUTCOME (allowed/denied, and which check) at the six RAISING
FUNCTIONS themselves instead means zero call sites change; every one of the
~260 callers already goes through one of these six functions unmodified.

Two separate contextvars, not one combined record: a single top-level tool
call can touch more than one project-scope check (e.g. a relation's source
AND target work package, each independently checked) or more than one
policy gate (a capability check followed by a project-scope check) -- the
LAST one to run before the call either succeeds or raises is what a human
debugging a denial actually wants to see, so each write overwrites the
previous value for this call, deliberately (not accumulated into a list),
matching how a single tool call produces exactly one log line, not one per
internal check.

Reset once per tool call by the same wrapper that resets `http_request_counter`
(`tools_runtime.py`'s `_categorize_tool_errors`), so a value observed
during one call never leaks into the next call's log line on the same
worker (contextvars are otherwise task-scoped, but the reset makes this
independent of scheduler details).
"""

from __future__ import annotations

from contextvars import ContextVar

_policy_decision: ContextVar[str | None] = ContextVar("policy_decision", default=None)
_project_scope: ContextVar[str | None] = ContextVar("project_scope", default=None)


def reset() -> None:
    _policy_decision.set(None)
    _project_scope.set(None)


def record_policy_decision(decision: str) -> None:
    """`decision` is one of: `"<scope>_read_allowed"`, `"<scope>_write_allowed"`,
    `"<scope>_read_denied"`, `"<scope>_write_denied"` -- see access.py/scope.py's
    own call sites for the exact strings used."""
    _policy_decision.set(decision)


def record_project_scope(value: str | None) -> None:
    """Overwrites unconditionally, including with None -- matching
    record_policy_decision's semantics. A guarded `if value:` write would
    leave a stale value from an earlier, unrelated check on the same call
    standing next to this check's own (correctly updated) policy_decision,
    which is worse than an honest None: e.g. a relation create that checks
    source (resolves, allowed) then target (denied, unresolvable link) must
    not still show the source's project_scope next to the target's denial."""
    _project_scope.set(value)


def current_policy_decision() -> str | None:
    return _policy_decision.get()


def current_project_scope() -> str | None:
    return _project_scope.get()
