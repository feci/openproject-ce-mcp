from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp import policy_observation
from openproject_ce_mcp.app.errors import CapabilityDisabledError
from openproject_ce_mcp.app.policies import access


def test_ensure_read_enabled_raises_with_env_var_hint_when_disabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_version_read=False)
    with pytest.raises(CapabilityDisabledError, match="OPENPROJECT_ENABLE_VERSION_READ"):
        access.ensure_read_enabled("version", settings=settings)


def test_ensure_read_enabled_noop_when_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_version_read=True)
    access.ensure_read_enabled("version", settings=settings)  # must not raise


def test_ensure_write_enabled_raises_with_env_var_hint_when_disabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_version_write=False)
    with pytest.raises(CapabilityDisabledError, match="OPENPROJECT_ENABLE_VERSION_WRITE"):
        access.ensure_write_enabled("version", settings=settings)


def test_ensure_write_enabled_noop_when_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_version_write=True)
    access.ensure_write_enabled("version", settings=settings)  # must not raise


# ── OPM-2709: policy_decision observation ──────────────────────────────────


def test_ensure_read_enabled_records_denied_decision() -> None:
    settings = dataclasses.replace(make_settings(), enable_version_read=False)
    policy_observation.reset()
    with pytest.raises(CapabilityDisabledError):
        access.ensure_read_enabled("version", settings=settings)
    assert policy_observation.current_policy_decision() == "version_read_denied"


def test_ensure_read_enabled_records_allowed_decision() -> None:
    settings = dataclasses.replace(make_settings(), enable_version_read=True)
    policy_observation.reset()
    access.ensure_read_enabled("version", settings=settings)
    assert policy_observation.current_policy_decision() == "version_read_allowed"


def test_ensure_write_enabled_records_denied_decision() -> None:
    settings = dataclasses.replace(make_settings(), enable_version_write=False)
    policy_observation.reset()
    with pytest.raises(CapabilityDisabledError):
        access.ensure_write_enabled("version", settings=settings)
    assert policy_observation.current_policy_decision() == "version_write_denied"


def test_ensure_write_enabled_records_allowed_decision() -> None:
    settings = dataclasses.replace(make_settings(), enable_version_write=True)
    policy_observation.reset()
    access.ensure_write_enabled("version", settings=settings)
    assert policy_observation.current_policy_decision() == "version_write_allowed"
