"""`slb-glossary mcp` - run the SLB Energy Glossary as an MCP server for LLM agents."""

import dataclasses
import pathlib
import typing

import click

from slb_glossary.cli.errors import cli_command
from slb_glossary.cli.runtime import run_async
from slb_glossary.config import Config
from slb_glossary.query import Source

__all__ = ["mcp"]


@click.group("mcp")
def mcp() -> None:
    """Run the SLB Energy Glossary as an MCP server for LLM agents."""


@mcp.command("serve")
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=pathlib.Path),
    default=None,
    help="An slb_glossary Config file (JSON/TOML/YAML) to source session/local settings from.",
)
@click.option(
    "--transport",
    type=click.Choice(["stdio", "http", "sse"], case_sensitive=False),
    default="stdio",
    show_default=True,
    help="MCP transport to serve over.",
)
@click.option("--host", default="127.0.0.1", show_default=True, help="Bind host (http/sse only).")
@click.option("--port", type=int, default=8000, show_default=True, help="Bind port (http/sse only).")
@click.option(
    "--tools",
    default="read_only",
    show_default=True,
    help="Comma-separated tool set to build, e.g. 'search,get_term' or 'all'/'read_only'.",
)
@click.option(
    "--source",
    type=click.Choice([s.value for s in Source]),
    multiple=True,
    default=(),
    help="Restrict which source(s) tools may use. May be given more than once. Default: all enabled.",
)
@click.option("--no-local", is_flag=True, help="Disable local database access entirely.")
@click.option("--no-live", is_flag=True, help="Disable live glossary access entirely.")
@click.option(
    "--allow-write",
    is_flag=True,
    help="Allow local-database writes (glossary_sync, and read tools' `persist` argument).",
)
@click.option(
    "--timeout",
    type=float,
    default=60.0,
    show_default=True,
    help="Global per-tool-call timeout in seconds. 0 disables it.",
)
@click.option(
    "--auth-token",
    "auth_tokens",
    multiple=True,
    help="A 'token' or 'token:principal_id' pair to accept as a valid caller, backed by "
    "StaticTokenAuth. May be given more than once. Mutually exclusive with --auth-backend.",
)
@click.option(
    "--auth-backend",
    "auth_backend_path",
    default=None,
    help="Dotted import path ('module:ClassName' or 'package.module.ClassName') to a custom "
    "AuthBackend, instantiated with no constructor arguments. For a backend that needs "
    "constructor arguments (a DB pool, API client, etc.), build the Application in Python "
    "yourself instead of going through this flag. Mutually exclusive with --auth-token.",
)
@click.option(
    "--rate-limit",
    "requests_per_minute",
    type=int,
    default=None,
    help="Enable rate limiting: max requests per client per tool per minute.",
)
@click.option(
    "--log-level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], case_sensitive=False),
    default=None,
    help="Verbosity of slb_glossary's own logging output.",
)
@cli_command
def serve(
    config_path: pathlib.Path | None,
    transport: str,
    host: str,
    port: int,
    tools: str,
    source: tuple[str, ...],
    no_local: bool,
    no_live: bool,
    allow_write: bool,
    timeout: float,
    auth_tokens: tuple[str, ...],
    auth_backend_path: str | None,
    requests_per_minute: int | None,
    log_level: str | None,
) -> None:
    """Build an `MCPConfig` from flags and serve it."""
    try:
        from slb_glossary.mcp.api import Application
        from slb_glossary.mcp.auth import StaticTokenAuth, import_backend
        from slb_glossary.mcp.config import (
            AuthConfig,
            LocalAccessConfig,
            MCPConfig,
            RateLimitConfig,
            SessionAccessConfig,
            SourcePolicyConfig,
            TimeoutConfig,
            resolve_tools,
        )
    except ImportError as exc:
        raise click.ClickException(
            "The MCP server needs the 'mcp' extra: `pip install slb-glossary[mcp]`."
        ) from exc

    if auth_tokens and auth_backend_path:
        raise click.UsageError("--auth-token and --auth-backend are mutually exclusive.")

    glossary_config = Config.load(config_path) if config_path is not None else Config()

    session = SessionAccessConfig(enabled=not no_live, browser=glossary_config.session)
    local = LocalAccessConfig(
        enabled=not no_local, allow_write=allow_write, database=glossary_config.local
    )
    allowed_sources = frozenset(Source(value) for value in source) or None
    source_policy = SourcePolicyConfig(allowed=allowed_sources)

    auth_config = AuthConfig()
    if auth_tokens:
        token_map: dict[str, str] = {}
        for entry in auth_tokens:
            token, _, principal_id = entry.partition(":")
            token_map[token] = principal_id or token
        auth_config = AuthConfig(backend=StaticTokenAuth(token_map), required=True)
    elif auth_backend_path:
        auth_config = AuthConfig(backend=import_backend(auth_backend_path), required=True)

    rate_limit = RateLimitConfig()
    if requests_per_minute is not None:
        rate_limit = RateLimitConfig(enabled=True, requests_per_minute=requests_per_minute)

    config = MCPConfig(
        session=session,
        local=local,
        source_policy=source_policy,
        tools=resolve_tools(tools.split(",")),
        timeouts=TimeoutConfig(global_=timeout or None),
        auth=auth_config,
        rate_limit=rate_limit,
        logging=dataclasses.replace(MCPConfig.default().logging, level=log_level),
    )

    app = Application(config)
    transport_kwargs: dict[str, typing.Any] = {"transport": transport}
    if transport != "stdio":
        transport_kwargs.update(host=host, port=port)
    run_async(app.run_async(**transport_kwargs))
