"""Tests for transport_chain.find_in_chain / remove_from_chain.

See transport_chain.py's own module docstring for why a single top-level
isinstance check (two successive review-round bugs) isn't sufficient here.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from openproject_ce_mcp.counting_transport import CountingTransport
from openproject_ce_mcp.retry_transport import RetryTransport
from openproject_ce_mcp.transport_chain import find_in_chain, remove_from_chain


def _leaf() -> httpx.AsyncBaseTransport:
    return AsyncMock(spec=httpx.AsyncBaseTransport)


def test_find_in_chain_finds_the_transport_itself() -> None:
    leaf = _leaf()
    counting = CountingTransport(leaf)
    assert find_in_chain(counting, CountingTransport) is counting


def test_find_in_chain_finds_a_nested_layer() -> None:
    leaf = _leaf()
    retry = RetryTransport(leaf)
    counting = CountingTransport(retry)
    assert find_in_chain(counting, RetryTransport) is retry


def test_find_in_chain_returns_none_when_absent() -> None:
    leaf = _leaf()
    counting = CountingTransport(leaf)
    assert find_in_chain(counting, RetryTransport) is None


def test_find_in_chain_stops_at_a_leaf_with_no_wrapped_transport_attribute() -> None:
    leaf = _leaf()
    assert find_in_chain(leaf, CountingTransport) is None


def test_remove_from_chain_removes_the_outermost_layer() -> None:
    leaf = _leaf()
    counting = CountingTransport(leaf)
    result = remove_from_chain(counting, CountingTransport)
    assert result is leaf


def test_remove_from_chain_removes_a_nested_layer_preserving_outer_layers() -> None:
    leaf = _leaf()
    counting = CountingTransport(leaf)
    retry = RetryTransport(counting)
    result = remove_from_chain(retry, CountingTransport)
    assert result is retry
    assert result.wrapped_transport is leaf


def test_remove_from_chain_removes_every_matching_layer_not_just_the_first() -> None:
    leaf = _leaf()
    inner_counting = CountingTransport(leaf)
    retry = RetryTransport(inner_counting)
    outer_counting = CountingTransport(retry)
    result = remove_from_chain(outer_counting, CountingTransport)
    assert result is retry
    assert result.wrapped_transport is leaf
    assert find_in_chain(result, CountingTransport) is None


def test_remove_from_chain_is_a_no_op_when_absent() -> None:
    leaf = _leaf()
    retry = RetryTransport(leaf)
    result = remove_from_chain(retry, CountingTransport)
    assert result is retry


def test_remove_from_chain_raises_when_asked_to_remove_the_whole_chain() -> None:
    leaf = _leaf()
    counting = CountingTransport(leaf)
    with pytest.raises(ValueError, match="wrapped_transport"):
        remove_from_chain(counting, httpx.AsyncBaseTransport)
