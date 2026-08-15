"""
The main entry point of `slb_glossary.mcp`: `Application`, which turns an
`MCPConfig` into a ready-to-serve `fastmcp.FastMCP` server for the SLB
Energy Glossary.

```python
import asyncio

from slb_glossary.mcp import Application, MCPConfig

app = Application(MCPConfig.default())
asyncio.run(app.run_async())  # stdio by default
```

Or reach for the underlying `fastmcp.FastMCP` server directly (e.g. to
mount it inside a larger ASGI app, or drive it from `fastmcp`'s own CLI):

```python
server = app.to_server()
```

`Application` itself stays a thin, mostly stateless wrapper: config
validation lives in `MCPConfig`, resource lifecycle lives in
`slb_glossary.mcp.runtime.Runtime`, tool bodies live in
`slb_glossary.mcp.tools`, and cross-cutting concerns (auth, rate limiting,
hooks, logging) live in `slb_glossary.mcp.middleware`. This module's only
job is wiring those together onto a `FastMCP` instance.
"""

import dataclasses
import logging
import typing

from fastmcp import Context, FastMCP

from slb_glossary import __version__
from slb_glossary.logging import configure_logging
from slb_glossary.mcp.config import MCPConfig
from slb_glossary.mcp.middleware import GlossaryMiddleware
from slb_glossary.mcp.ratelimit import SlidingWindowRateLimiter
from slb_glossary.mcp.runtime import Runtime
from slb_glossary.mcp.tools import DEFAULT_INSTRUCTIONS, ToolSpec, build_tool_specs

logger = logging.getLogger(__name__)

__all__ = ["Application"]


class Application:
    """
    A configured, buildable MCP server for the SLB Energy Glossary.

    Construction (`Application(config)`) is cheap and does no I/O; the
    underlying `FastMCP` server and its tools are assembled lazily on first
    `to_server()`/`run()`/`run_async()` call. Resource startup (opening the
    local database, eagerly opening a live session if configured) happens
    in `run_async`/`run`, or explicitly via `start()` for callers embedding
    the server in their own event loop / lifespan management.
    """

    def __init__(self, config: MCPConfig | None = None) -> None:
        """
        :param config: The server's `MCPConfig`. Defaults to `MCPConfig.default()`.
        """
        self.config = config if config is not None else MCPConfig.default()
        self.runtime = Runtime(self.config)
        self._server: FastMCP | None = None

    @classmethod
    def from_config(cls, config: MCPConfig) -> "Application":
        """Build an `Application` from `config`. Equivalent to `Application(config)`."""
        return cls(config)

    def to_server(self) -> FastMCP:
        """
        Build (if not already built) and return the underlying `fastmcp.FastMCP` server.

        Idempotent: repeated calls return the same instance. Building
        registers every tool `self.config.resolved_tools()` selects and
        attaches `slb_glossary.mcp.middleware.GlossaryMiddleware`, but does
        **not** open any database/session - that happens in `start()`.
        """
        if self._server is not None:
            return self._server

        self._resolve_default_rate_limiter()

        server = FastMCP(
            name=self.config.server.name,
            version=self.config.server.version or __version__,
            instructions=self.config.server.instructions or DEFAULT_INSTRUCTIONS,
        )
        server.add_middleware(GlossaryMiddleware(self.config))

        for spec in build_tool_specs(self.config):
            self._register_tool(server, spec)

        self._server = server
        return server

    def _resolve_default_rate_limiter(self) -> None:
        """Fill in `RateLimitConfig.limiter` with a default in-memory limiter if left unset."""
        rate_limit = self.config.rate_limit
        if rate_limit.enabled and rate_limit.limiter is None:
            limiter = SlidingWindowRateLimiter(
                rate_limit.requests_per_minute, rate_limit.window_seconds
            )
            self.config = dataclasses.replace(
                self.config, rate_limit=dataclasses.replace(rate_limit, limiter=limiter)
            )
            self.runtime.config = self.config

    def _register_tool(self, server: FastMCP, spec: ToolSpec) -> None:
        """Wrap `spec.handler` into a FastMCP tool function and register it on `server`."""
        args_type = spec.args_type
        timeout = self.config.timeouts.for_tool(spec.name)
        annotations = {"readOnlyHint": not spec.writes, "destructiveHint": spec.writes}

        async def _tool(args: args_type, ctx: Context) -> dict[str, typing.Any]:  # type: ignore[valid-type]
            async def report_progress(count: int, total: int | None) -> None:
                await ctx.report_progress(progress=count, total=total)

            return await spec.handler(
                args, self.runtime, self.config, report_progress=report_progress
            )

        _tool.__name__ = spec.name
        _tool.__doc__ = spec.description

        server.tool(
            _tool,
            name=spec.name,
            description=spec.description,
            tags=set(spec.tags),
            timeout=timeout,
            annotations=annotations,
        )

    async def start(self) -> None:
        """
        Perform startup-time resource work (open the local DB, eagerly open a
        live session if configured) and run `HooksConfig.on_startup` hooks.

        Idempotent - safe to call before `run_async`, which also calls this.
        """
        self._configure_logging()
        await self.runtime.start()
        for hook in self.config.hooks.on_startup:
            await hook()

    async def aclose(self) -> None:
        """Tear down every resource opened by `start()` and run `HooksConfig.on_shutdown` hooks."""
        await self.runtime.aclose()
        for hook in self.config.hooks.on_shutdown:
            await hook()

    def _configure_logging(self) -> None:
        logging_config = self.config.logging
        if logging_config.sink is None and logging_config.level is None:
            return
        configure_logging(sinks=logging_config.sink, level=logging_config.level)

    async def run_async(self, **transport_kwargs: typing.Any) -> None:
        """
        Start resources, serve until the transport stops, then always clean up.

        :param transport_kwargs: Forwarded to `fastmcp.FastMCP.run_async`,
            e.g. `transport=\"http\", host=\"0.0.0.0\", port=8000`. Defaults
            to FastMCP's own default (stdio) when omitted.
        """
        server = self.to_server()
        await self.start()
        try:
            await server.run_async(**transport_kwargs)
        finally:
            await self.aclose()

    def run(self, **transport_kwargs: typing.Any) -> None:
        """
        Synchronous convenience wrapper around `run_async`, for simple entry points.

        :param transport_kwargs: Forwarded to `fastmcp.FastMCP.run_async` -
            see `run_async`.
        """
        import asyncio

        asyncio.run(self.run_async(**transport_kwargs))
