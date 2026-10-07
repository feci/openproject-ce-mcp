"""The pinned OpenProject source checkouts under ``op-sources/``.

``fetch-sources.sh`` holds the only list of audited versions. The check
scripts read that list from here instead of trusting whatever directories
happen to exist, because a missing or stale checkout must fail the audit
rather than silently shrink it.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCES = ROOT.parent / "op-sources"
FETCH_SCRIPT = Path(__file__).resolve().parent / "fetch-sources.sh"

_PIN = re.compile(r'^\s*"(?P<version>\d+\.\d+):(?P<tag>v[^"]+)"\s*$')


class MissingCheckoutError(RuntimeError):
    """A pinned source checkout is absent or does not sit on the pinned tag."""


def version_key(version: str) -> tuple[int, ...]:
    """Sort key for a version label like "16.6" (16.6 < 17.0 < 17.5)."""
    return tuple(int(part) for part in version.split("."))


def pinned_versions(script: Path = FETCH_SCRIPT) -> dict[str, str]:
    """Version label -> git tag, in ascending version order, as pinned in fetch-sources.sh."""
    pins = {m["version"]: m["tag"] for m in map(_PIN.match, script.read_text().splitlines()) if m}
    if not pins:
        raise ValueError(f"no version pins found in {script}")
    return dict(sorted(pins.items(), key=lambda item: version_key(item[0])))


def checked_out_tag(checkout: Path) -> str | None:
    """The tag the checkout sits on, or None when it is not a git checkout at a tag."""
    result = subprocess.run(
        ["git", "-C", str(checkout), "describe", "--tags", "--exact-match"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() or None


def checkout_problems(pins: dict[str, str], sources: Path = SOURCES) -> list[str]:
    """Why the audit cannot run against every pinned version; empty when it can."""
    problems = []
    for version, tag in pins.items():
        checkout = sources / version
        if not checkout.is_dir():
            problems.append(f"{version}: missing checkout {checkout}")
            continue
        actual = checked_out_tag(checkout)
        if actual != tag:
            problems.append(
                f"{version}: checkout is at {actual or 'no tag'}, pin is {tag} -- delete {checkout} and re-run"
            )
    return problems


def require_checkouts(pins: dict[str, str], sources: Path = SOURCES) -> None:
    problems = checkout_problems(pins, sources)
    if problems:
        raise MissingCheckoutError("\n".join(problems) + "\nRun: tools/api-check/fetch-sources.sh")
