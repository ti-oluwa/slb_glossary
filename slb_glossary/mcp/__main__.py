"""
`slb-glossary-mcp` - a small CLI wrapper around `slb_glossary.mcp.Application`.

```
slb-glossary-mcp serve                          # stdio, read-only, local+live
slb-glossary-mcp serve --transport http --port 8000
slb-glossary-mcp serve --allow-write --tools all # enable glossary_sync too
slb-glossary-mcp serve --config glossary.toml    # reuse an slb_glossary Config file
```

Only a thin translation layer from CLI flags to `MCPConfig` lives here;
all the actual behavior lives in `slb_glossary.mcp`.
"""

import dataclasses
import pathlib
import typing

import click

from slb_glossary.config import Config
from slb_glossary.mcp.api import Application
from slb_glossary.mcp.auth import StaticTokenAuth
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
from slb_glossary.query import Source

__all__ = ["cli", "main"]


@click.group("slb-glossary-mcp")
def cli() -> None:
    """Run an MCP server exposing the SLB Energy Glossary to LLM agents."""


@cli.command("serve")
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
    help="Restrict which source(s) tools may use. May be given more than once. Default: all.",
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
    help="A 'token' or 'token:principal_id' pair to accept as a valid caller. "
    "May be given more than once. If any are given, auth becomes required.",
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
    requests_per_minute: int | None,
    log_level: str | None,
) -> None:
    """Build an `MCPConfig` from flags and serve it."""
    glossary_config = Config.load(config_path) if config_path is not None else Config()

    session = SessionAccessConfig(enabled=not no_live, browser=glossary_config.session)
    local = LocalAccessConfig(
        enabled=not no_local, allow_write=allow_write, database=glossary_config.local
    )
    allowed_sources = frozenset(Source(value) for value in source) or frozenset(Source)
    source_policy = SourcePolicyConfig(allowed=allowed_sources)

    auth_config = AuthConfig()
    if auth_tokens:
        token_map: dict[str, str] = {}
        for entry in auth_tokens:
            token, _, principal_id = entry.partition(":")
            token_map[token] = principal_id or token
        auth_config = AuthConfig(backend=StaticTokenAuth(token_map), required=True)

    rate_limit = RateLimitConfig()
    if requests_per_minute is not None:
        rate_limit = RateLimitConfig(enabled=True, requests_per_minute=requests_per_minute)

    config = MCPConfig(
        session=session,
        local=local,
        source_policy=source_policy,
        tools=resolve_tools(tools.split(",")),
        timeouts=TimeoutConfig(global_seconds=timeout or None),
        auth=auth_config,
        rate_limit=rate_limit,
        logging=dataclasses.replace(MCPConfig.default().logging, level=log_level),
    )

    app = Application(config)
    transport_kwargs: dict[str, typing.Any] = {"transport": transport}
    if transport != "stdio":
        transport_kwargs.update(host=host, port=port)
    app.run(**transport_kwargs)


def main() -> None:
    """`slb-glossary-mcp` console-script entry point."""
    cli()


if __name__ == "__main__":
    main()
