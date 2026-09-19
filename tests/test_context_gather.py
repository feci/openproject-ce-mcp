"""Regression coverage for context_gather.gather_in_current_context.

Found during a full-branch security review (2026-09): plain `asyncio.gather`
silently loses any ContextVar write made inside a gathered coroutine, since
asyncio gives every spawned Task its own COPY of the current context. This
affected `http_request_counter`/`policy_observation` for any tool call that
fans out through `asyncio.gather` (e.g. WorkPackageResolver.project_links_
allowed's concurrent per-href project-scope checks, WorkPackageService's
search() and get_batch()) -- the structured log's `http_requests`/
`project_scope`/`policy_decision` fields silently came back wrong (typically
0/None) for exactly those calls, with no error raised.
"""

from __future__ import annotations

import asyncio
from contextvars import ContextVar

import pytest

from openproject_ce_mcp.context_gather import gather_in_current_context

_var: ContextVar[int] = ContextVar("test_counter", default=0)


@pytest.mark.asyncio
async def test_plain_asyncio_gather_loses_contextvar_writes() -> None:
    """Documents the bug this module exists to fix -- if this test ever
    starts failing, asyncio's Task-context-copying semantics have changed
    and context_gather's whole rationale needs re-examining."""
    _var.set(0)

    async def child() -> None:
        _var.set(_var.get() + 1)

    await asyncio.gather(child(), child(), child())
    assert _var.get() == 0


@pytest.mark.asyncio
async def test_gather_in_current_context_preserves_contextvar_writes() -> None:
    _var.set(0)

    async def child() -> None:
        _var.set(_var.get() + 1)

    await gather_in_current_context(child(), child(), child())
    assert _var.get() == 3


@pytest.mark.asyncio
async def test_gather_in_current_context_merges_before_reraising_on_exception() -> None:
    _var.set(0)

    async def increments_then_raises() -> None:
        _var.set(_var.get() + 1)
        raise ValueError("boom")

    async def just_increments() -> None:
        _var.set(_var.get() + 1)

    with pytest.raises(ValueError, match="boom"):
        await gather_in_current_context(increments_then_raises(), just_increments())

    # Both children ran and wrote before the exception propagated; the
    # finally-block merge must have happened despite the raise.
    assert _var.get() == 2


@pytest.mark.asyncio
async def test_gather_in_current_context_with_return_exceptions() -> None:
    _var.set(0)

    async def increments_then_raises() -> None:
        _var.set(_var.get() + 1)
        raise ValueError("boom")

    async def just_increments() -> int:
        _var.set(_var.get() + 1)
        return 42

    results = await gather_in_current_context(increments_then_raises(), just_increments(), return_exceptions=True)
    assert isinstance(results[0], ValueError)
    assert results[1] == 42
    assert _var.get() == 2


@pytest.mark.asyncio
async def test_gather_in_current_context_returns_results_in_order() -> None:
    async def value(n: int) -> int:
        await asyncio.sleep(0)
        return n

    results = await gather_in_current_context(value(3), value(1), value(2))
    assert results == [3, 1, 2]


@pytest.mark.asyncio
async def test_concurrent_children_see_each_others_writes_consistently() -> None:
    """The shared context copy means concurrent children observe a single,
    consistent view among themselves -- not full isolation, matching
    ordinary (non-Task) sequential contextvar semantics within one context."""
    _var.set(0)
    order: list[int] = []

    async def child(n: int) -> None:
        await asyncio.sleep(0)
        _var.set(_var.get() + n)
        order.append(_var.get())

    await gather_in_current_context(child(1), child(10), child(100))
    assert _var.get() == 111
