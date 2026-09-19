"""Coverage for app/errors.py's code/layer ClassVar contract.

Found during a full-branch security review (2026-09): the module's own
docstring claimed a subclass that forgets to declare `code`/`layer` is "a
class-definition-time omission a type checker can catch" -- verified false.
mypy --strict happily type-checks a subclass that declares neither and just
silently inherits the parent's values, which is actively misleading (looks
like a deliberate choice, e.g. reusing PROJECT_SCOPE_DENIED, when it's
actually a forgotten override) rather than a caught mistake. Fixed with a
runtime `__init_subclass__` guard instead.
"""

from __future__ import annotations

import pytest

from openproject_ce_mcp.app.errors import OpenProjectError


def test_every_leaf_exception_declares_its_own_code_and_layer() -> None:
    """Walks the real exception hierarchy (not a hand-maintained list, so
    this can't silently drift as new exception classes are added) and
    asserts each one declares its own code/layer in __dict__, not just
    inherited. Redundant with the __init_subclass__ guard for any class
    defined AFTER this test file is written, but still valuable: it directly
    documents the invariant and would catch a guard that got weakened or
    bypassed (e.g. via `type.__new__` directly)."""

    def walk(cls: type) -> list[type]:
        subclasses = cls.__subclasses__()
        return subclasses + [grandchild for sub in subclasses for grandchild in walk(sub)]

    for cls in walk(OpenProjectError):
        assert "code" in cls.__dict__, f"{cls.__name__} does not declare its own `code`"
        assert "layer" in cls.__dict__, f"{cls.__name__} does not declare its own `layer`"


def test_subclass_forgetting_code_and_layer_raises_at_definition_time() -> None:
    with pytest.raises(TypeError, match="must declare its own"):

        class _Forgotten(OpenProjectError):
            pass


def test_subclass_declaring_only_code_still_raises() -> None:
    from typing import ClassVar

    with pytest.raises(TypeError, match="must declare its own"):

        class _OnlyCode(OpenProjectError):
            code: ClassVar[str] = "SOMETHING"


def test_subclass_declaring_only_layer_still_raises() -> None:
    from typing import ClassVar

    with pytest.raises(TypeError, match="must declare its own"):

        class _OnlyLayer(OpenProjectError):
            layer: ClassVar[str] = "transport"


def test_subclass_declaring_both_succeeds() -> None:
    from typing import ClassVar

    class _WellFormed(OpenProjectError):
        code: ClassVar[str] = "SOMETHING"
        layer: ClassVar[str] = "transport"

    assert _WellFormed.code == "SOMETHING"
    assert _WellFormed.layer == "transport"


def test_grandchild_subclass_must_also_declare_its_own_code_and_layer() -> None:
    """The guard must fire at every level of the hierarchy, not just
    directly under OpenProjectError -- a grandchild (like
    ProjectScopeDeniedError under PermissionDeniedError in the real
    hierarchy) copy-pasting its parent without overriding must be caught
    too."""
    from typing import ClassVar

    class _Parent(OpenProjectError):
        code: ClassVar[str] = "PARENT_CODE"
        layer: ClassVar[str] = "policy"

    with pytest.raises(TypeError, match="must declare its own"):

        class _Grandchild(_Parent):
            pass
