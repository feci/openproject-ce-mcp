"""Shared exception vocabulary.

Package-root shared kernel: importable from every layer (policies, transport, ports,
adapters, resolvers, services) without creating a layering violation, since it sits
outside the layer hierarchy entirely, like `config.py`/`models.py`.
"""

from __future__ import annotations


class OpenProjectError(Exception):
    """Base error for safe OpenProject failures."""


class AuthenticationError(OpenProjectError):
    """Authentication failed."""


class PermissionDeniedError(OpenProjectError):
    """Access to the resource was denied. Base class -- prefer a subclass
    below at every new raise site; the bare base is only a fallback for
    catch sites written before the subclasses existed."""


class ProjectScopeDeniedError(PermissionDeniedError):
    """Denied by the OPENPROJECT_READ_PROJECTS/OPENPROJECT_WRITE_PROJECTS
    project allowlist -- the caller is authenticated and this deployment
    allows this kind of operation in general, but not against this
    particular project."""


class CapabilityDisabledError(PermissionDeniedError):
    """Denied by an OPENPROJECT_ENABLE_*_READ/_WRITE capability flag -- this
    deployment has this entire category of operation turned off, independent
    of which project is targeted."""


class OpenProjectPermissionDeniedError(PermissionDeniedError):
    """OpenProject itself returned 403 for an authenticated, in-scope
    request -- a permissions problem on the OpenProject side (e.g. the
    underlying API token's role lacks a permission), not something this
    server's own configuration controls."""


class NotFoundError(OpenProjectError):
    """The requested resource does not exist."""


class InvalidInputError(OpenProjectError):
    """A provided tool or request input is invalid."""


class ConflictError(OpenProjectError):
    """The request conflicts with the resource's current state (e.g. an
    optimistic-locking lockVersion mismatch)."""


class RateLimitedError(OpenProjectError):
    """OpenProject is rate-limiting this client."""


class OpenProjectServerError(OpenProjectError):
    """OpenProject returned an unexpected failure."""


class TransportError(OpenProjectError):
    """The request could not reach OpenProject safely."""
