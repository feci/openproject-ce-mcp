"""Diagnostic command for OpenProject MCP setup.

Checks binary resolution, client configs, environment configuration, API
connectivity, and tool registration to diagnose "server doesn't show up" issues.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import os
import platform
import shutil
import stat
import sys

import httpx

from . import __version__
from .client import AuthenticationError, OpenProjectClient, OpenProjectError, TransportError
from .config import ConfigError, Settings
from .models import CurrentUser

EXIT_SUCCESS = 0
EXIT_FAILURE = 1

_IS_WINDOWS = sys.platform == "win32"  # mirrors setup_cli.py's own module-level idiom


def run_doctor() -> int:
    """CLI entry point for doctor command."""
    return _run_doctor()


def _run_doctor(
    *,
    settings_override: Settings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> int:
    """Run all diagnostic checks and return exit code.

    Args:
        settings_override: For tests. If None, loads from discovered configs or env.
        transport: For tests. If None, uses real HTTP client.

    Returns:
        EXIT_SUCCESS if all checks pass, EXIT_FAILURE if any fail.
    """
    print("Running OpenProject MCP diagnostics...\n")

    failures = 0

    if not _check_binary():
        failures += 1

    client_configs = _discover_clients()

    config_ok, client_env = _check_config_parsing(client_configs)
    if not config_ok:
        failures += 1

    _check_config_permissions(client_configs)

    env_ok, settings = _check_env_config(settings_override, client_env)
    if not env_ok:
        failures += 1
        # Can't proceed with API checks without valid settings
        print(f"\n{failures} check(s) failed.")
        return EXIT_FAILURE
    # _check_env_config's `True` result always pairs with a resolved Settings
    # (only the `(False, None)` failure path omits it).
    assert settings is not None

    async def _api_check() -> bool:
        api_ok, _ = await _check_api_connectivity(settings, transport)
        return api_ok

    api_ok = asyncio.run(_api_check())
    if not api_ok:
        failures += 1

    if not _check_tool_registration(settings):
        failures += 1

    if not asyncio.run(_check_stdio_handshake(settings)):
        failures += 1

    if client_configs:
        _print_restart_hints(client_configs)

    if failures == 0:
        print("\nAll checks passed.")
        return EXIT_SUCCESS
    else:
        print(f"\n{failures} check(s) failed.")
        return EXIT_FAILURE


_MIN_PYTHON = (3, 11)  # pyproject.toml's own requires-python floor


def _check_binary() -> bool:
    """Check binary path, package version, and Python runtime."""
    path = shutil.which("openproject-ce-mcp") or sys.argv[0]
    print(f"[OK] Binary: {path} (v{__version__})")
    if sys.version_info[:2] < _MIN_PYTHON:
        print(
            f"[FAIL] Python: {platform.python_version()} ({sys.executable}) "
            f"-- requires >= {'.'.join(map(str, _MIN_PYTHON))}"
        )
        return False
    print(f"[OK] Python: {platform.python_version()} ({sys.executable})")
    return True


def _discover_clients() -> list[tuple]:
    """Find all MCP client configs (detected or not)."""
    from .setup_cli import _clients

    clients = _clients()
    found: list[tuple] = []

    for c in clients:
        detected = c.detected()
        status = "detected" if detected else "not detected"

        if c.target.exists():
            print(f"  - {c.label} (global, {status}): {c.target}")
            found.append((c, c.target))

        if c.project_target and c.project_target.exists():
            print(f"  - {c.label} (project, {status}): {c.project_target}")
            found.append((c, c.project_target))

    if found:
        print(f"[OK] Clients: {len(found)} config(s) found")
    else:
        print("[WARN] Clients: no MCP client configs discovered", file=sys.stderr)

    return found


def _check_config_parsing(client_configs: list[tuple]) -> tuple[bool, dict[str, str]]:
    """Parse each config, extract openproject env.

    When multiple configs have openproject entries, env vars are merged in order
    (later configs override earlier ones). Client config env wins over process env
    (applied in _check_env_config) — this is what the MCP client will actually use.
    """
    from .setup_cli import _read_client_env, _tomllib

    all_ok = True
    merged_env: dict[str, str] = {}
    env_sources: list[str] = []

    for client, target in client_configs:
        try:
            if client.fmt == "json":
                config = json.loads(target.read_text())
                root_key = client.root_key or "mcpServers"
                has_entry = "openproject" in config.get(root_key, {})
            elif client.fmt == "toml":
                config = _tomllib.loads(target.read_text())
                has_entry = "openproject" in config.get("mcp_servers", {})
            else:
                print(f"[FAIL] {client.label}: unknown format {client.fmt} ({target.name})", file=sys.stderr)
                all_ok = False
                continue
        except json.JSONDecodeError as e:
            print(f"[FAIL] {client.label}: invalid JSON - {e} ({target.name})", file=sys.stderr)
            all_ok = False
            continue
        except OSError as e:
            print(f"[FAIL] {client.label}: cannot read file - {e} ({target.name})", file=sys.stderr)
            all_ok = False
            continue
        except Exception as e:
            print(f"[FAIL] {client.label}: unexpected error - {type(e).__name__} ({target.name})", file=sys.stderr)
            all_ok = False
            continue

        if not has_entry:
            print(f"[WARN] {client.label}: no openproject entry ({target.name})", file=sys.stderr)
            continue

        env = _read_client_env(client, target=target)
        if env:
            print(f"[OK] {client.label}: openproject entry valid ({target.name})")
            merged_env.update(env)
            env_sources.append(f"{client.label} ({target.name})")
        else:
            print(f"[WARN] {client.label}: openproject entry has no env ({target.name})", file=sys.stderr)

    if env_sources:
        print(f"  Environment from: {', '.join(env_sources)}")

    return (all_ok, merged_env)


def _check_config_permissions(client_configs: list[tuple]) -> None:
    """Warn about POSIX permission bits that grant group/other access to
    config files containing OPENPROJECT_API_TOKEN. Read-only: stats the path,
    never opens or reads file contents, so it cannot itself leak a token.
    Matches the 0o600-is-safe convention setup_cli.py's writers already
    enforce (_backup/_atomic_write chmod to 0o600); this is the reader side.
    """
    if _IS_WINDOWS:
        print("[SKIP] Permissions: not checked on Windows (POSIX mode bits do not apply)")
        return

    seen: set[str] = set()
    for _client, target in client_configs:
        key = str(target)
        if key in seen:
            continue
        seen.add(key)
        try:
            mode = stat.S_IMODE(target.stat().st_mode)
        except OSError:
            continue  # already reported elsewhere if unreadable
        if mode & 0o077:
            print(
                f"[WARN] Permissions: {target} is readable/writable by group or "
                f"other (mode {oct(mode)}); run `chmod 600 {target}` to restrict "
                "it to your user only",
                file=sys.stderr,
            )


def _check_env_config(
    settings_override: Settings | None,
    client_env: dict[str, str],
) -> tuple[bool, Settings | None]:
    """Load Settings from override, client config env, or process env."""
    if settings_override:
        print("[OK] Environment: test override")
        return (True, settings_override)

    # Client config env wins over process env on conflicts: it's what the
    # MCP client will actually use.
    combined_env = dict(os.environ)
    combined_env.update(client_env)

    try:
        settings = Settings.from_env(environ=combined_env)
        source = "client configs" if client_env else "process env"
        print(f"[OK] Environment: loaded from {source}")
        _warn_insecure(settings)
        _print_project_scope_summary(settings)
        return (True, settings)
    except ConfigError as e:
        print(f"[FAIL] Environment: {e}", file=sys.stderr)
        return (False, None)


def _warn_insecure(settings: Settings) -> None:
    """Print warnings for insecure configuration."""
    if not settings.verify_ssl:
        print("[WARN] SSL verification disabled (OPENPROJECT_VERIFY_SSL=false)", file=sys.stderr)
    if settings.base_url.startswith("http://"):
        print("[WARN] Unencrypted HTTP connection", file=sys.stderr)


def _print_project_scope_summary(settings: Settings) -> None:
    """Make the fail-closed project-scope default and write-group state diagnosable."""
    read_summary = ", ".join(settings.read_projects) or "none (fail-closed — nothing readable)"
    write_summary = ", ".join(settings.write_projects) or "none (fail-closed — nothing writable)"
    print(f"  Read projects: {read_summary}")
    print(f"  Write projects: {write_summary}")
    print(f"  Work-package writes: {settings.enable_work_package_write}")
    print(f"  Project writes: {settings.enable_project_write}")
    print(f"  Membership writes: {settings.enable_membership_write}")
    print(f"  Version writes: {settings.enable_version_write}")
    print(f"  Board writes: {settings.enable_board_write}")
    print(f"  Personal-data writes: {settings.enable_personal_write}")
    print(f"  Admin writes: {settings.enable_admin_write}")


def _is_tls_failure(exc: BaseException) -> bool:
    """Real TLS/cert failures always embed CPython's stable "[SSL: ...]" ssl-module
    error text. OpenProjectClient's transport layer wraps every httpx transport
    exception (including a TLS handshake failure, which httpx itself raises as
    httpx.ConnectError with no separate public SSL exception type) into
    TransportError via `raise TransportError(...) from exc` — so the original
    httpx exception, and its own "[SSL: ...]" text, survives on __cause__.
    Verified empirically: httpx.ConnectError's __cause__ is httpcore's own
    ConnectError, never ssl.SSLError itself at any depth, but its stringified
    message still contains the OpenSSL error text, so substring matching (not
    isinstance-walking __cause__) is the reliable mechanism here.
    """
    seen: set[int] = set()
    cause: BaseException | None = exc
    while cause is not None and id(cause) not in seen:
        if "[SSL:" in str(cause):
            return True
        seen.add(id(cause))
        cause = cause.__cause__
    return False


async def _check_api_connectivity(
    settings: Settings,
    transport: httpx.AsyncBaseTransport | None,
) -> tuple[bool, CurrentUser | None]:
    """Test API connectivity via get_current_user.

    Uses reduced timeout and no retries for fast diagnostic feedback.
    """
    # Shorter timeout, no retries, for fast diagnostic feedback — but every
    # other flag (enable_*_read/write, tool scopes, etc.) is preserved from
    # the real settings, matching setup_cli.py's equivalent check, so the
    # connectivity result reflects what the running server would actually
    # enforce rather than the Settings dataclass defaults.
    diagnostic_settings = dataclasses.replace(settings, timeout=5.0, max_retries=0)

    client = OpenProjectClient(diagnostic_settings, transport=transport)
    try:
        user = await client.current_user.get_current_user()
        print(f"[OK] API: connected ({user.name})")
        return (True, user)
    except TransportError as e:
        if _is_tls_failure(e):
            print(
                f"[FAIL] API: TLS/certificate error connecting to {settings.base_url} "
                "(check the server's certificate, or OPENPROJECT_VERIFY_SSL if this is "
                "a trusted internal CA)",
                file=sys.stderr,
            )
        elif "timed out" in str(e).lower():
            print(
                "[FAIL] API: connection timeout (server reachable but slow, or a "
                "firewall is silently dropping packets)",
                file=sys.stderr,
            )
        else:
            print(
                f"[FAIL] API: cannot connect to {settings.base_url} (check the URL and that the server is reachable)",
                file=sys.stderr,
            )
    except AuthenticationError:
        print(
            "[FAIL] API: authentication failed (check OPENPROJECT_API_TOKEN is current and has not been revoked)",
            file=sys.stderr,
        )
    except OpenProjectError as e:
        print(f"[FAIL] API: {e}", file=sys.stderr)
    except Exception as e:
        print(f"[FAIL] API: unexpected error - {type(e).__name__}", file=sys.stderr)
    finally:
        await client.aclose()
    return (False, None)


async def _build_and_verify_dispatch(settings: Settings) -> None:
    from .server import create_app
    from .strict_mcpserver import verify_strict_dispatch

    app = create_app(settings)
    await verify_strict_dispatch(app)


async def _check_stdio_handshake(settings: Settings, *, timeout: float = 5.0) -> bool:
    """Verify the MCP stdio dispatch path in-process, with a strict timeout.

    Never starts the stdio transport loop or spawns a process: create_app()
    only builds the server object (its lifespan, which does the real API
    client initialization, only runs inside app.run() — never here), and
    verify_strict_dispatch() probes the low-level dispatch handler directly
    in memory (see strict_mcpserver.py). Structurally cannot hang on real
    I/O; the timeout guards only against an unexpected SDK-internal issue.
    """
    try:
        await asyncio.wait_for(_build_and_verify_dispatch(settings), timeout=timeout)
        print("[OK] MCP: stdio dispatch handshake verified")
        return True
    except TimeoutError:
        print(
            f"[FAIL] MCP: stdio handshake did not complete within {timeout}s "
            "(this indicates an SDK-internal issue, not a network problem)",
            file=sys.stderr,
        )
        return False
    except Exception as e:
        print(f"[FAIL] MCP: stdio handshake failed - {type(e).__name__}", file=sys.stderr)
        return False


def _check_tool_registration(settings: Settings) -> bool:
    """Preview which tools would register (without network I/O).

    Uses register_tools() directly, not create_app(), to avoid feature flag
    fetch. This shows what tools are enabled by your settings, not necessarily
    what a live server would register (which may vary based on instance features).
    """
    from mcp.server.mcpserver import MCPServer

    from .tools import register_tools

    # MCPServer sets up logging — temporarily suppress
    prev_level = logging.root.level
    logging.root.setLevel(logging.CRITICAL)

    try:
        # Plain MCPServer, not StrictMCPServer: this preview path only registers
        # tools and lists them, it never calls call_tool(), so the strict
        # argument-validation override has nothing to intercept here.
        mcp = MCPServer("doctor-preview", log_level="CRITICAL")
        register_tools(mcp, settings)
        tools = list(mcp._tool_manager.list_tools())

        print(f"[OK] Tools: {len(tools)} would register (based on settings)")
        if tools:
            sample = ", ".join(t.name for t in tools[:5])
            print(f"  {sample}, ...")
        return True
    finally:
        logging.root.setLevel(prev_level)


def _print_restart_hints(client_configs: list[tuple]) -> None:
    """Show restart hints for found client configs."""
    # Deduplicate by client (may have both global + project configs)
    seen_clients = {client for client, _ in client_configs}

    hints = [c for c in seen_clients if c.restart_hint]
    if hints:
        print("\nRestart needed for:")
        for client in hints:
            print(f"  - {client.label}: {client.restart_hint}")
