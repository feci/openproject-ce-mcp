"""`asyncio.gather` replacement that preserves ContextVar writes.

`asyncio.gather` wraps every non-Task coroutine it's given in its own
`asyncio.Task`, and asyncio gives each new Task a **copy** of the current
context at creation time (`contextvars.copy_context()`) -- a write inside a
child task never propagates back to the caller. This silently breaks any
ContextVar meant to accumulate state across concurrent work (this project's
own `http_request_counter`/`policy_observation`, both written from inside
code that can run under `gather`, e.g. `WorkPackageResolver.project_links_
allowed`'s concurrent href resolution). A caller who forgets this footgun
gets no error -- just a wrong, usually-zero/None value read back afterwards.

`gather_in_current_context` fixes this generically, for any ContextVar,
without every call site needing to know which ones are in play: every
spawned task shares ONE context copy (so they see each other's writes
consistently among themselves, matching normal asyncio.gather semantics
for everything else), and every ContextVar touched in that shared copy is
copied back into the real caller's context once all tasks finish -- in a
`finally`, so a raised exception (including a re-raised one from
`return_exceptions=False`, the default) still triggers the merge before
propagating.

Requires Python 3.11+ for `asyncio.create_task`'s `context=` parameter.

`asyncio.TaskGroup` (also 3.11+) is NOT a substitute for this helper: its
`create_task` delegates to the same `loop.create_task` primitive, gets the
same per-task context copy by default, and its `__aexit__` never merges
child writes back into the parent context -- switching these call sites to
TaskGroup would just mean re-implementing this same merge-back logic on top
of it. TaskGroup's real benefit (prompt sibling cancellation on first
failure) is also not needed at any of this module's current call sites,
which either capture per-item failures themselves or already want all
siblings to run before the exception surfaces.
"""

from __future__ import annotations

import asyncio
import contextvars
from collections.abc import Awaitable
from typing import TypeVar, overload

_T1 = TypeVar("_T1")
_T2 = TypeVar("_T2")
_T3 = TypeVar("_T3")
_T = TypeVar("_T")


# Overloaded like asyncio.gather's own typeshed stub, for the same reason:
# a bare `*coros: Awaitable[_T]` signature unifies every argument to one
# common `_T`, losing per-position type information a caller with two or
# three differently-typed coroutines (this project's own call sites) relies
# on for tuple-unpacking (`a, b = await gather_in_current_context(...)`).
@overload
async def gather_in_current_context(
    coro1: Awaitable[_T1], coro2: Awaitable[_T2], /, *, return_exceptions: bool = False
) -> tuple[_T1, _T2]: ...
@overload
async def gather_in_current_context(
    coro1: Awaitable[_T1], coro2: Awaitable[_T2], coro3: Awaitable[_T3], /, *, return_exceptions: bool = False
) -> tuple[_T1, _T2, _T3]: ...
@overload
async def gather_in_current_context(*coros: Awaitable[_T], return_exceptions: bool = False) -> list[_T]: ...


async def gather_in_current_context(*coros: Awaitable[object], return_exceptions: bool = False) -> object:
    ctx = contextvars.copy_context()
    tasks: list[asyncio.Task[object]] = [asyncio.create_task(coro, context=ctx) for coro in coros]  # type: ignore[arg-type]
    try:
        return await asyncio.gather(*tasks, return_exceptions=return_exceptions)
    finally:
        for var, value in ctx.items():
            var.set(value)
