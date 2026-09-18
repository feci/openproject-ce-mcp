"""Per-tool-call HTTP request counter (OPM-2709's `http_requests` log field).

A `contextvars.ContextVar`, not an instance attribute on `HttpxTransport` or
`OpenProjectClient`: `RetryTransport.handle_async_request` -- the one place
every real wire-level HTTP attempt actually happens, including each
individual retry attempt, not just each logical `client.request()` call --
has no reference to "the current tool call" to attribute a count to. A
contextvar is this codebase's own established idiom for exactly this shape
of request-scoped state (see `WorkPackageResolver`'s bounded semaphore and
`WorkPackageAllowedContext`'s per-call cache for the same "state scoped to
one in-flight call, not to the transport object's lifetime" pattern).

Counting at `RetryTransport` (not `HttpxTransport._request`/`_send_stream`)
is deliberate: a retried request is a REAL HTTP request that reached the
network, and undercounting it as "1" per logical operation would misreport
the actual request volume a tool call generated.
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
