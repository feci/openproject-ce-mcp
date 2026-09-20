"""Tests for CountingTransport: http_request_counter must reflect every
real wire-level HTTP attempt, independent of whether retries are enabled.

Regression (Codex review round 8, OPM-2709): the counter used to increment
inside RetryTransport itself, which client.py only installs when
OPENPROJECT_MAX_RETRIES > 0 -- a valid, documented configuration with
MAX_RETRIES=0 meant every real request went uncounted (http_requests: 0 in
the structured log, despite a real network round-trip happening). Moved the
counting responsibility to its own, unconditionally-installed transport.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from openproject_ce_mcp import http_request_counter
from openproject_ce_mcp.client import OpenProjectClient
from openproject_ce_mcp.config import Settings
from openproject_ce_mcp.counting_transport import CountingTransport
from openproject_ce_mcp.retry_transport import RetryTransport


def _settings(**overrides: object) -> Settings:
    return Settings.from_env(
        {
            "OPENPROJECT_BASE_URL": "https://op.example.com",
            "OPENPROJECT_API_TOKEN": "token",
            **{f"OPENPROJECT_{k.upper()}": str(v) for k, v in overrides.items()},
        }
    )


@pytest.mark.asyncio
async def test_counts_a_single_successful_get_as_one() -> None:
    mock_transport = AsyncMock(spec=httpx.AsyncBaseTransport)
    mock_transport.handle_async_request.return_value = httpx.Response(200, request=httpx.Request("GET", "http://test"))

    counting = CountingTransport(mock_transport)
    request = httpx.Request("GET", "http://test/api")

    http_request_counter.reset()
    await counting.handle_async_request(request)

    assert http_request_counter.current() == 1


@pytest.mark.asyncio
async def test_counts_a_non_idempotent_post_as_one() -> None:
    mock_transport = AsyncMock(spec=httpx.AsyncBaseTransport)
    mock_transport.handle_async_request.return_value = httpx.Response(200, request=httpx.Request("POST", "http://test"))

    counting = CountingTransport(mock_transport)
    request = httpx.Request("POST", "http://test/api")

    http_request_counter.reset()
    await counting.handle_async_request(request)

    assert http_request_counter.current() == 1


@pytest.mark.asyncio
async def test_counts_every_retry_attempt_when_retry_transport_is_layered_outside() -> None:
    """Matches client.py's actual wiring: CountingTransport wraps the
    innermost real transport, RetryTransport wraps CountingTransport -- so
    each individual retry attempt still counts as its own real request, not
    "1" per logical operation."""
    mock_transport = AsyncMock(spec=httpx.AsyncBaseTransport)
    mock_transport.handle_async_request.side_effect = [
        httpx.Response(503, request=httpx.Request("GET", "http://test")),
        httpx.Response(503, request=httpx.Request("GET", "http://test")),
        httpx.Response(200, request=httpx.Request("GET", "http://test")),
    ]

    counting = CountingTransport(mock_transport)
    retry_transport = RetryTransport(counting, max_retries=3, base_delay=0.01)
    request = httpx.Request("GET", "http://test/api")

    http_request_counter.reset()
    response = await retry_transport.handle_async_request(request)

    assert response.status_code == 200
    assert mock_transport.handle_async_request.call_count == 3
    assert http_request_counter.current() == 3


@pytest.mark.asyncio
async def test_aclose_closes_the_wrapped_transport() -> None:
    mock_transport = AsyncMock(spec=httpx.AsyncBaseTransport)
    counting = CountingTransport(mock_transport)

    await counting.aclose()

    mock_transport.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_client_counts_a_real_request_with_max_retries_zero() -> None:
    """The actual regression this whole file exists for: MAX_RETRIES=0 is a
    valid configuration (client.py only installs RetryTransport when
    max_retries > 0), and a real request through OpenProjectClient must
    still be counted -- it used to come back as 0 despite a genuine network
    round-trip happening, because counting lived inside RetryTransport."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": 1, "name": "Someone"})

    client = OpenProjectClient(_settings(max_retries=0), transport=httpx.MockTransport(handler))
    http_request_counter.reset()
    try:
        await client.current_user.get_current_user()
    finally:
        await client.aclose()

    assert http_request_counter.current() == 1


@pytest.mark.asyncio
async def test_client_counts_a_real_request_with_retries_enabled() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": 1, "name": "Someone"})

    client = OpenProjectClient(_settings(max_retries=3), transport=httpx.MockTransport(handler))
    http_request_counter.reset()
    try:
        await client.current_user.get_current_user()
    finally:
        await client.aclose()

    assert http_request_counter.current() == 1
