"""HTTP transport wrapper that counts every real wire-level request.

Deliberately its own transport layer, separate from `RetryTransport`: the
`http_requests` structured-log field (OPM-2709) must reflect every real
network attempt regardless of whether retries are configured at all.
`RetryTransport` is only installed when `OPENPROJECT_MAX_RETRIES > 0`
(`client.py`) -- counting inside it, as an earlier version of this code did,
meant `OPENPROJECT_MAX_RETRIES=0` (a valid, documented configuration) never
counted a single request, even though every call still hit the network.
`CountingTransport` is installed unconditionally as the innermost transport
`OpenProjectClient` builds, so the count is correct independent of the retry
configuration layered on top of it.
"""

from __future__ import annotations

import httpx

from . import http_request_counter


class CountingTransport(httpx.AsyncBaseTransport):
    """Wraps another transport, incrementing `http_request_counter` once per
    real `handle_async_request` call -- including each individual retry
    attempt when `RetryTransport` is layered on top of this, since a retried
    request is a real HTTP request that reached the network, not a no-op."""

    def __init__(self, wrapped_transport: httpx.AsyncBaseTransport) -> None:
        # Public, matching RetryTransport.wrapped_transport (same rename
        # rationale: client.py's transport_chain.find_in_chain walks this
        # attribute name on any transport that has it, so both wrapper
        # transports in this codebase expose their inner transport the same,
        # externally-visible way -- not for any caller outside this module to
        # rely on directly.
        self.wrapped_transport = wrapped_transport

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        http_request_counter.increment()
        return await self.wrapped_transport.handle_async_request(request)

    async def aclose(self) -> None:
        await self.wrapped_transport.aclose()
