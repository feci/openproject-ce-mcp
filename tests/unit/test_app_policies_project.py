from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp import policy_observation
from openproject_ce_mcp.app.errors import ProjectScopeDeniedError
from openproject_ce_mcp.app.policies import project_policy


def test_ensure_project_read_allowed_raises_when_no_candidate_matches() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("other",))
    with pytest.raises(ProjectScopeDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        project_policy.ensure_project_read_allowed(
            {"id": 1, "identifier": "demo", "name": "Demo"}, settings=settings, project_id_to_identifier={}
        )


def test_ensure_project_read_allowed_noop_under_wildcard_scope() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",))
    project_policy.ensure_project_read_allowed(
        {"id": 1, "identifier": "demo", "name": "Demo"}, settings=settings, project_id_to_identifier={}
    )  # must not raise


def test_ensure_project_write_allowed_checks_read_before_write() -> None:
    # read_projects excludes it -> must fail on the read check, not the write one
    settings = dataclasses.replace(make_settings(), read_projects=("other",), write_projects=("*",))
    with pytest.raises(ProjectScopeDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        project_policy.ensure_project_write_allowed(
            {"id": 1, "identifier": "demo", "name": "Demo"}, settings=settings, project_id_to_identifier={}
        )


def test_ensure_project_write_allowed_raises_for_write_restricted_scope() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("other",))
    with pytest.raises(ProjectScopeDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
        project_policy.ensure_project_write_allowed(
            {"id": 1, "identifier": "demo", "name": "Demo"}, settings=settings, project_id_to_identifier={}
        )


def test_ensure_project_write_allowed_noop_under_wildcard_scope() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("*",))
    project_policy.ensure_project_write_allowed(
        {"id": 1, "identifier": "demo", "name": "Demo"}, settings=settings, project_id_to_identifier={}
    )  # must not raise


def test_ensure_project_create_target_allowed_rejects_when_read_scope_excludes_it() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("other",), write_projects=("*",))
    with pytest.raises(ProjectScopeDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        project_policy.ensure_project_create_target_allowed(
            identifier="demo", name="Demo", settings=settings, project_id_to_identifier={}
        )


def test_ensure_project_create_target_allowed_rejects_when_write_scope_excludes_it() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("other",))
    with pytest.raises(ProjectScopeDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
        project_policy.ensure_project_create_target_allowed(
            identifier="demo", name="Demo", settings=settings, project_id_to_identifier={}
        )


def test_ensure_project_create_target_allowed_noop_under_wildcard_scope() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("*",))
    project_policy.ensure_project_create_target_allowed(
        identifier="demo", name="Demo", settings=settings, project_id_to_identifier={}
    )  # must not raise


def test_ensure_project_read_allowed_matches_via_project_ref_not_present_in_payload() -> None:
    # payload's own fields don't match the scope, but the ref used to resolve it does
    # -- client.py's _ensure_project_allowed always includes project_ref as a candidate.
    settings = dataclasses.replace(make_settings(), read_projects=("legacy-ref",))
    project_policy.ensure_project_read_allowed(
        {"id": 1, "identifier": "demo", "name": "Demo"},
        project_ref="legacy-ref",
        settings=settings,
        project_id_to_identifier={},
    )  # must not raise


def test_ensure_project_write_allowed_matches_via_project_ref_not_present_in_payload() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("legacy-ref",), write_projects=("legacy-ref",))
    project_policy.ensure_project_write_allowed(
        {"id": 1, "identifier": "demo", "name": "Demo"},
        project_ref="legacy-ref",
        settings=settings,
        project_id_to_identifier={},
    )  # must not raise


# ── OPM-2709 regression: policy_observation instrumentation ────────────────
#
# Found during a Codex review of release/0.5.0: this module's three
# ensure_*_allowed functions are a SEPARATE family from scope.py's
# link-based ensure_project_link_allowed(_write)?(_if_present)? functions
# (whose policy_observation instrumentation is covered by
# test_app_policies_scope.py) -- calling one of these directly (as
# project_service.py/project_resolver.py/project_query.py/
# status_priority_type_service.py all do) previously left
# policy_observation completely un-updated: a denial here raised
# ProjectScopeDeniedError (a real PROJECT_SCOPE_DENIED error code) while the
# structured log's policy_decision field stayed at whatever an unrelated,
# earlier check on the same call had last set it to (often "allowed"),
# misleading anyone debugging the denial from the log alone.


def test_ensure_project_read_allowed_records_denied_decision_and_scope() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("other",))
    policy_observation.reset()
    with pytest.raises(ProjectScopeDeniedError):
        project_policy.ensure_project_read_allowed(
            {"id": 1, "identifier": "demo", "name": "Demo"}, settings=settings, project_id_to_identifier={}
        )
    assert policy_observation.current_policy_decision() == "project_read_denied"
    assert policy_observation.current_project_scope() == "demo"


def test_ensure_project_read_allowed_records_allowed_decision_and_scope() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",))
    policy_observation.reset()
    project_policy.ensure_project_read_allowed(
        {"id": 1, "identifier": "demo", "name": "Demo"}, settings=settings, project_id_to_identifier={}
    )
    assert policy_observation.current_policy_decision() == "project_read_allowed"
    assert policy_observation.current_project_scope() == "demo"


def test_ensure_project_write_allowed_records_write_flavored_decision_on_success() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("*",))
    policy_observation.reset()
    project_policy.ensure_project_write_allowed(
        {"id": 1, "identifier": "demo", "name": "Demo"}, settings=settings, project_id_to_identifier={}
    )
    assert policy_observation.current_policy_decision() == "project_write_allowed"
    assert policy_observation.current_project_scope() == "demo"


def test_ensure_project_write_allowed_records_denied_decision_when_write_scope_excludes_it() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("other",))
    policy_observation.reset()
    with pytest.raises(ProjectScopeDeniedError):
        project_policy.ensure_project_write_allowed(
            {"id": 1, "identifier": "demo", "name": "Demo"}, settings=settings, project_id_to_identifier={}
        )
    assert policy_observation.current_policy_decision() == "project_write_denied"


def test_ensure_project_create_target_allowed_records_scope_and_denied_decision() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("other",), write_projects=("*",))
    policy_observation.reset()
    with pytest.raises(ProjectScopeDeniedError):
        project_policy.ensure_project_create_target_allowed(
            identifier="newproj", name="New Project", settings=settings, project_id_to_identifier={}
        )
    assert policy_observation.current_policy_decision() == "project_read_denied"
    assert policy_observation.current_project_scope() == "newproj"


def test_ensure_project_create_target_allowed_records_allowed_decision() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("*",))
    policy_observation.reset()
    project_policy.ensure_project_create_target_allowed(
        identifier="newproj", name="New Project", settings=settings, project_id_to_identifier={}
    )
    assert policy_observation.current_policy_decision() == "project_write_allowed"
    assert policy_observation.current_project_scope() == "newproj"
