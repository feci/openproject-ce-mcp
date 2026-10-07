from __future__ import annotations

from pathlib import Path

import op_sources
import pytest


@pytest.fixture
def fetch_script(tmp_path: Path) -> Path:
    script = tmp_path / "fetch-sources.sh"
    script.write_text(
        """VERSIONS=(
    "17.0:v17.0.7"
    "16.6:v16.6.10"
    "17.9:v17.9.1"
)
SPARSE_PATHS=(
    "lib/api/v3"
)
"""
    )
    return script


def test_pinned_versions_are_parsed_in_version_order(fetch_script):
    assert op_sources.pinned_versions(fetch_script) == {"16.6": "v16.6.10", "17.0": "v17.0.7", "17.9": "v17.9.1"}


def test_pinned_versions_rejects_a_script_without_pins(tmp_path):
    script = tmp_path / "fetch-sources.sh"
    script.write_text("VERSIONS=()\n")
    with pytest.raises(ValueError):
        op_sources.pinned_versions(script)


def test_real_fetch_script_pins_parse():
    pins = op_sources.pinned_versions()
    assert "16.0" in pins
    assert all(tag.startswith("v") for tag in pins.values())


def test_checkout_problems_reports_missing_and_mismatched_checkouts(tmp_path, monkeypatch):
    (tmp_path / "17.0").mkdir()
    (tmp_path / "17.9").mkdir()
    (tmp_path / "pr-24770").mkdir()
    monkeypatch.setattr(
        op_sources, "checked_out_tag", lambda checkout: {"17.0": "v17.0.7", "17.9": "v17.9.0"}[checkout.name]
    )

    problems = op_sources.checkout_problems({"16.6": "v16.6.10", "17.0": "v17.0.7", "17.9": "v17.9.1"}, tmp_path)

    assert problems == [
        f"16.6: missing checkout {tmp_path / '16.6'}",
        f"17.9: checkout is at v17.9.0, pin is v17.9.1 -- delete {tmp_path / '17.9'} and re-run",
    ]


def test_checkout_problems_is_empty_when_every_pin_is_checked_out(tmp_path, monkeypatch):
    (tmp_path / "17.9").mkdir()
    monkeypatch.setattr(op_sources, "checked_out_tag", lambda checkout: "v17.9.1")

    assert op_sources.checkout_problems({"17.9": "v17.9.1"}, tmp_path) == []


def test_checkout_without_a_tag_is_reported(tmp_path, monkeypatch):
    (tmp_path / "17.9").mkdir()
    monkeypatch.setattr(op_sources, "checked_out_tag", lambda checkout: None)

    assert op_sources.checkout_problems({"17.9": "v17.9.1"}, tmp_path) == [
        f"17.9: checkout is at no tag, pin is v17.9.1 -- delete {tmp_path / '17.9'} and re-run"
    ]


def test_require_checkouts_raises_with_every_problem(tmp_path):
    with pytest.raises(op_sources.MissingCheckoutError, match=r"(?s)16\.6: missing checkout.*fetch-sources\.sh"):
        op_sources.require_checkouts({"16.6": "v16.6.10"}, tmp_path)


def test_checked_out_tag_reads_the_exact_tag_of_a_git_checkout(tmp_path, monkeypatch):
    import os
    import subprocess

    # Under a git hook, GIT_DIR and friends point every git call at the hooked
    # repository instead of tmp_path.
    for name in [key for key in os.environ if key.startswith("GIT_")]:
        monkeypatch.delenv(name)

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    identity = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.org",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.org",
    }
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-q", "--allow-empty", "-m", "x"],
        check=True,
        env={**os.environ, **identity},
    )
    assert op_sources.checked_out_tag(tmp_path) is None
    subprocess.run(["git", "-C", str(tmp_path), "tag", "v1.2.3"], check=True)
    assert op_sources.checked_out_tag(tmp_path) == "v1.2.3"
