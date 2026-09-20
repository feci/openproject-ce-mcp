"""Per-tool-call HTTP request counter (OPM-2709's `http_requests` log field).

A `contextvars.ContextVar`, not an instance attribute on `HttpxTransport` or
`OpenProjectClient`: `CountingTransport.handle_async_request`
(`counting_transport.py`) -- the one place every real wire-level HTTP attempt
actually happens, including each individual retry attempt when
`RetryTransport` is layered on top, not just each logical `client.request()`
call -- has no reference to "the current tool call" to attribute a count to.
A contextvar is this codebase's own established idiom for this shape of
request-scoped state.

Counting in its own dedicated `CountingTransport`, installed unconditionally
(not inside `RetryTransport`, which is only installed when
`OPENPROJECT_MAX_RETRIES > 0`), is deliberate: a retried request is a REAL
HTTP request that reached the network, and undercounting it as "1" per
logical operation would misreport the actual request volume a tool call
generated -- and MAX_RETRIES=0 is a valid configuration that must still
count every request it makes.

A plain ContextVar write is invisible across `asyncio.gather`/`create_task`,
since each new Task gets its own COPY of the context, not a shared
reference -- a write inside a gathered coroutine never reaches the caller
that awaited it. Any code path that increments this counter (or writes
`policy_observation`) inside a `gather`-ed coroutine must go through
`context_gather.gather_in_current_context` instead of `asyncio.gather`
directly, or the count silently comes back wrong (typically too low, never
an error) for that tool call. See `context_gather.py`'s own docstring.
"""

from __future__ import annotations

from contextvars import ContextVar

_count: ContextVar[int] = ContextVar("http_request_count", default=0)


def reset() -> None:
    _count.set(0)


def increment() -> None:
    _count.set(_count.get() + 1)


def current() -> int:
    return _count.get()
