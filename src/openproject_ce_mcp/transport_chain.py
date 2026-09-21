"""Walks a chain of nested `httpx.AsyncBaseTransport` wrappers.

`OpenProjectClient`'s own `CountingTransport`/`RetryTransport` layering (see
`client.py`'s construction block) previously used a single `isinstance`
check against whatever `transport` the caller passed in directly. That is
only correct for the two orderings that check happens to test for -- a
caller-supplied transport chain can nest these two wrappers in either order,
or the caller can pass an object that already contains one, wrapped inside
something else entirely (their own logging/metrics transport, for example).
A single top-level `isinstance` check sees only the outermost layer and
either misses an already-present inner wrapper (causing a duplicate) or
fails to recognize one that IS present but not on top (causing client.py to
add a redundant extra layer next to it). Two real bugs of exactly this
shape were found in successive review rounds (a Codex round 9 double-wrap,
then a round 10 finding that the round 9 fix itself missed two more
orderings) before this module existed -- walking the whole chain, not just
the top, is what actually closes the class of bug, not just the two
specific orderings each successive patch happened to test for.

Every transport this walks must expose its inner transport as a public
`wrapped_transport` attribute (both `CountingTransport` and `RetryTransport`
do, deliberately, for this reason) -- a transport with no such attribute is
necessarily a leaf (the real network transport, or a caller's own opaque
wrapper this module has no way to see inside), so the walk stops there.
"""

from __future__ import annotations

from typing import Protocol, TypeVar, runtime_checkable

import httpx

_T = TypeVar("_T", bound=httpx.AsyncBaseTransport)


@runtime_checkable
class _WrapsAnotherTransport(Protocol):
    """Structural type for a transport wrapper that exposes its inner
    transport as a public, reassignable `wrapped_transport` attribute
    (both `CountingTransport` and `RetryTransport` do). A transport that
    does NOT satisfy this (a bare `httpx.AsyncHTTPTransport`/`MockTransport`,
    or a caller's own opaque wrapper) is necessarily a leaf as far as this
    module is concerned -- it cannot be walked into further."""

    wrapped_transport: httpx.AsyncBaseTransport


def find_in_chain(transport: httpx.AsyncBaseTransport, wrapper_type: type[_T]) -> _T | None:
    """Return the OUTERMOST instance of `wrapper_type` found by walking
    `transport` and then its `.wrapped_transport` chain, or `None` if no
    layer in the chain is an instance of it."""
    current: httpx.AsyncBaseTransport | None = transport
    while current is not None:
        if isinstance(current, wrapper_type):
            return current
        current = current.wrapped_transport if isinstance(current, _WrapsAnotherTransport) else None
    return None


def find_innermost_in_chain(transport: httpx.AsyncBaseTransport, wrapper_type: type[_T]) -> _T | None:
    """Return the INNERMOST instance of `wrapper_type` in the chain (the one
    closest to the real network), or `None` if none is present.

    Matters specifically for `RetryTransport`: a chain can validly nest more
    than one (`RetryTransport(RetryTransport(...))`, however unusual), and
    `CountingTransport` must sit inside the innermost one to count every
    real network attempt that innermost layer's own retries make -- placed
    at the outermost `RetryTransport` instead (what `find_in_chain` alone
    would find), it only counts once per the OUTER layer's own attempts,
    each of which may itself trigger several real requests via the inner
    layer's retries, undercounting the true total the same way every prior
    round's bug did."""
    innermost: _T | None = None
    current: httpx.AsyncBaseTransport | None = transport
    while current is not None:
        if isinstance(current, wrapper_type):
            innermost = current
        current = current.wrapped_transport if isinstance(current, _WrapsAnotherTransport) else None
    return innermost


def remove_from_chain(transport: httpx.AsyncBaseTransport, wrapper_type: type) -> httpx.AsyncBaseTransport:
    """Return a chain equivalent to `transport` with every layer that is an
    instance of `wrapper_type` spliced out, preserving the relative order of
    every other layer.

    Used to re-home a `CountingTransport` a caller happened to place at the
    wrong position in their own chain (see this module's docstring): rather
    than trying to detect and patch every possible wrong position in place,
    `client.py` removes any existing `CountingTransport` layer(s) wherever
    they are, then adds exactly one back at the one position (inside the
    innermost `RetryTransport`, or innermost overall if there is none) that
    is actually guaranteed correct.
    """
    if isinstance(transport, wrapper_type):
        if not isinstance(transport, _WrapsAnotherTransport):
            raise ValueError(
                f"Cannot remove {wrapper_type.__name__} from the chain: it has no "
                "wrapped_transport to splice in its place (it would be the whole chain)."
            )
        return remove_from_chain(transport.wrapped_transport, wrapper_type)
    if isinstance(transport, _WrapsAnotherTransport):
        new_inner = remove_from_chain(transport.wrapped_transport, wrapper_type)
        if new_inner is not transport.wrapped_transport:
            transport.wrapped_transport = new_inner
    return transport
