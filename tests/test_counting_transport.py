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


@pytest.mark.asyncio
async def test_client_does_not_double_wrap_a_caller_supplied_retry_transport() -> None:
    """Regression (Codex review round 9): a caller-supplied RetryTransport
    (a documented, supported construction path) used to be hidden inside an
    outer CountingTransport before the RetryTransport double-wrap check ran,
    so that check's isinstance(transport, RetryTransport) failed and a
    SECOND RetryTransport was installed on top -- multiplying real network
    attempts by (max_retries + 1) twice over, while the counter only
    recorded the outer layer's attempts, undercounting the real total.
    CountingTransport must instead be injected INSIDE the caller's own
    RetryTransport (via its public wrapped_transport attribute), so retries
    aren't duplicated and every real wire attempt is still counted."""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(503)

    caller_retry_transport = RetryTransport(httpx.MockTransport(handler), max_retries=2, base_delay=0.01)
    client = OpenProjectClient(_settings(max_retries=2), transport=caller_retry_transport)
    http_request_counter.reset()
    try:
        with pytest.raises(Exception):  # noqa: B017, PT011 -- OpenProjectServerError after exhausting retries
            await client.current_user.get_current_user()
    finally:
        await client.aclose()

    # max_retries=2 -> 1 initial attempt + 2 retries = 3 real network calls,
    # not 9 (which a (2+1) x (2+1) double-wrap would produce).
    assert call_count == 3
    assert http_request_counter.current() == 3


@pytest.mark.asyncio
async def test_client_recounts_correctly_when_caller_wraps_retry_transport_in_counting_transport() -> None:
    """Regression (Codex review round 10): a caller-supplied
    CountingTransport(RetryTransport(...)) -- the OPPOSITE nesting order
    from the case above -- is a valid chain a caller could build. Round 9's
    fix only recognized a bare RetryTransport at the top of the chain; here
    the top-level object is CountingTransport, so round 9's isinstance
    check took the "else" branch, correctly declined to add a second
    CountingTransport, but then still added an EXTRA RetryTransport on top
    of the caller's own retry-capable transport (since it never looked
    inside to find the existing RetryTransport), reproducing the exact same
    (max_retries+1)^2 network-attempt multiplication as the round 9 bug,
    just via a different nesting order."""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(503)

    inner_retry = RetryTransport(httpx.MockTransport(handler), max_retries=2, base_delay=0.01)
    caller_transport = CountingTransport(inner_retry)
    client = OpenProjectClient(_settings(max_retries=2), transport=caller_transport)
    http_request_counter.reset()
    try:
        with pytest.raises(Exception):  # noqa: B017, PT011
            await client.current_user.get_current_user()
    finally:
        await client.aclose()

    assert call_count == 3
    assert http_request_counter.current() == 3


@pytest.mark.asyncio
async def test_client_does_not_double_count_when_caller_wraps_counting_transport_in_retry_transport() -> None:
    """Regression (Codex review round 10): the opposite ordering,
    RetryTransport(CountingTransport(...)) -- a caller-supplied
    CountingTransport nested INSIDE their own RetryTransport. Round 9's fix
    unconditionally injected a second CountingTransport around the caller's
    existing one (`transport.wrapped_transport = CountingTransport(...)`
    with no check for an existing one), so every real attempt was counted
    twice even though the actual network call count was correct."""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={"id": 1, "name": "Someone"})

    inner_counting = CountingTransport(httpx.MockTransport(handler))
    caller_transport = RetryTransport(inner_counting, max_retries=2, base_delay=0.01)
    client = OpenProjectClient(_settings(max_retries=2), transport=caller_transport)
    http_request_counter.reset()
    try:
        await client.current_user.get_current_user()
    finally:
        await client.aclose()

    assert call_count == 1
    assert http_request_counter.current() == 1


@pytest.mark.asyncio
async def test_client_applies_own_retry_policy_over_a_bare_caller_counting_transport() -> None:
    """A caller can supply just a CountingTransport with no retry policy at
    all -- this codebase's own OPENPROJECT_MAX_RETRIES should still apply
    on top of it, without adding a second CountingTransport."""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={"id": 1, "name": "Someone"})

    caller_transport = CountingTransport(httpx.MockTransport(handler))
    client = OpenProjectClient(_settings(max_retries=2), transport=caller_transport)
    http_request_counter.reset()
    try:
        await client.current_user.get_current_user()
    finally:
        await client.aclose()

    assert call_count == 1
    assert http_request_counter.current() == 1


@pytest.mark.asyncio
async def test_client_with_no_transport_argument_at_all_still_counts_correctly() -> None:
    """The real default path (transport=None, hitting the actual network via
    httpx.AsyncHTTPTransport) must also construct cleanly and end up with
    exactly one CountingTransport in its chain."""
    from openproject_ce_mcp.transport_chain import find_in_chain

    client = OpenProjectClient(_settings(max_retries=2))
    try:
        inner = client._http._transport
        assert find_in_chain(inner, CountingTransport) is not None
        assert find_in_chain(inner, RetryTransport) is not None
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_client_with_no_transport_preserves_verify_ssl_false() -> None:
    """Regression (Codex review round 11): with no caller-supplied
    transport, an earlier version of this code always constructed its own
    bare httpx.AsyncHTTPTransport() (no verify= argument at all) rather than
    letting httpx.AsyncClient build its own verify_ssl-configured default --
    OPENPROJECT_VERIFY_SSL=false silently stopped having any effect on the
    transport actually used for real requests."""
    import ssl

    client = OpenProjectClient(_settings(max_retries=0, verify_ssl="false"))
    try:
        leaf = client._http._transport.wrapped_transport
        assert isinstance(leaf, httpx.AsyncHTTPTransport)
        ssl_context = leaf._pool._ssl_context
        assert ssl_context.verify_mode == ssl.CERT_NONE
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_client_with_no_transport_still_resolves_https_proxy_env_var(monkeypatch) -> None:
    """Regression (Codex review round 11): an earlier version of this code
    passed an explicit `transport=`/`mounts=` to httpx.AsyncClient's own
    constructor whenever no caller transport was supplied -- either one
    disabled httpx's own environment-variable-based proxy resolution
    (`allow_env_proxies = trust_env and transport is None` inside
    AsyncClient.__init__), or (for the `mounts={"all://": ...}` variant)
    let a real, more specific env-proxy mount like "https://" win over the
    wildcard and route proxied requests around CountingTransport entirely.
    Neither `transport=` nor `mounts=` may be passed to the AsyncClient
    constructor when there's no caller-supplied transport -- wrapping must
    happen by mutating `self._http._transport`/`_mounts` AFTER
    construction, so httpx's own proxy resolution runs unmodified first."""
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example.com:8080")

    client = OpenProjectClient(_settings(max_retries=0))
    try:
        selected = client._http._transport_for_url(httpx.URL("https://op.example.com/api/v3/x"))
        assert isinstance(selected, CountingTransport)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_client_counts_the_innermost_of_two_nested_caller_retry_transports() -> None:
    """Regression (Codex review round 11): find_in_chain returns the
    OUTERMOST match, but CountingTransport must sit inside the INNERMOST
    RetryTransport -- a chain can validly nest more than one (however
    unusual), and only the layer actually closest to the real network sees
    every genuine retry attempt. Placed at the outer layer instead, the
    inner layer's own retries (real network calls) go uncounted."""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"id": 1, "name": "Someone"})

    innermost_retry = RetryTransport(httpx.MockTransport(handler), max_retries=2, base_delay=0.01)
    outer_retry = RetryTransport(innermost_retry, max_retries=2, base_delay=0.01)
    client = OpenProjectClient(_settings(max_retries=2), transport=outer_retry)
    http_request_counter.reset()
    try:
        await client.current_user.get_current_user()
    finally:
        await client.aclose()

    assert call_count == 2
    assert http_request_counter.current() == 2
