"""
The main entry point of `slb_glossary.mcp`. Holds `MCPApp`, which turns an
`MCPConfig` into a ready-to-serve `fastmcp.FastMCP` server for the SLB
Energy Glossary.

```python
import asyncio

from slb_glossary.mcp import MCPApp, MCPConfig

app = MCPApp(MCPConfig.default())
asyncio.run(app.run_async())  # stdio by default
```

Or reach for the underlying `fastmcp.FastMCP` server directly (e.g. to
mount it inside a larger ASGI app, or drive it from `fastmcp`'s own CLI):

```python
server = app.to_server()
```
"""

import asyncio
import contextlib
import dataclasses
import logging
import sys
import typing

from fastmcp import Context, FastMCP

from slb_glossary import __version__
from slb_glossary.logging import DEFAULT_LOG_FORMAT, configure_logging, resolve_sink
from slb_glossary.mcp.config import MCPConfig
from slb_glossary.mcp.middleware import MCPMiddleware
from slb_glossary.mcp.ratelimit import SlidingWindowRateLimiter
from slb_glossary.mcp.runtime import Runtime
from slb_glossary.mcp.tools import DEFAULT_INSTRUCTIONS, ToolSpec, build_tool_specs
from slb_glossary.mcp.types import NamedComponent

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

logger = logging.getLogger(__name__)

__all__ = ["MCPApp"]


class MCPApp(NamedComponent):
    """
    A configured, buildable MCP server for the SLB Energy Glossary.

    Construction (`MCPApp(config)`) is cheap and does no I/O; the
    underlying `FastMCP` server and its tools are assembled lazily on first
    `to_server()`/`run()`/`run_async()` call.

    Resource startup happens in `run_async`/`run`, or explicitly via `start()`
    for callers embedding the server in their own event loop / lifespan management.
    """

    def __init__(self, config: MCPConfig | None = None) -> None:
        """
        Initialize the MCP application.

        :param config: The server's `MCPConfig`. Defaults to `MCPConfig.default()`.
        """
        self.config = config if config is not None else MCPConfig.default()
        super().__init__(self.config.server.name)
        self.runtime = Runtime(self.config)
        self._server: FastMCP | None = None

    @classmethod
    def from_config(cls, config: MCPConfig) -> Self:
        """Build an `MCPApp` from `config`. Equivalent to `MCPApp(config)`."""
        return cls(config)

    def to_server(self) -> FastMCP:
        """
        Build (if not already built) and return the underlying `fastmcp.FastMCP` server.

        Idempotent: repeated calls return the same instance. Building
        registers every tool `self.config.resolved_tools()` selects and
        attaches `slb_glossary.mcp.middleware.MCPMiddleware`, but does
        not open any resources yet (database/session). That happens in `start()`.
        """
        if self._server is not None:
            return self._server

        self._resolve_default_rate_limiter()

        server = FastMCP(
            name=self.config.server.name,
            version=self.config.server.version or __version__,
            instructions=self.config.server.instructions or DEFAULT_INSTRUCTIONS,
            auth=self.config.auth.provider,
        )
        server.add_middleware(MCPMiddleware(self.config))

        for spec in build_tool_specs(self.config):
            self._register_tool(server, spec)

        self._server = server
        return server

    def _resolve_default_rate_limiter(self) -> None:
        """Fill in `RateLimitConfig.limiter` with a default in-memory limiter if left unset."""
        rate_limit = self.config.rate_limit
        if rate_limit.enabled and rate_limit.limiter is None:
            limiter = SlidingWindowRateLimiter(limit=rate_limit.limit, window=rate_limit.window)
            self.config = dataclasses.replace(
                self.config, rate_limit=dataclasses.replace(rate_limit, limiter=limiter)
            )
            self.runtime.config = self.config

    def _register_tool(self, server: FastMCP, spec: ToolSpec) -> None:
        """Wrap `spec.handler` into a `fastmcp` tool function and register it on `server`."""
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

        Idempotent: safe to call before `run_async`, which also calls this.
        """
        self._configure_logging()
        await self.runtime.start()
        for hook in self.config.hooks.on_startup:
            await hook()
        logger.info("[%s] MCPApp started", self.name)

    async def aclose(self) -> None:
        """Tear down every resource opened by `start()` and run `HooksConfig.on_shutdown` hooks."""
        await self.runtime.aclose()
        for hook in self.config.hooks.on_shutdown:
            await hook()
        logger.info("[%s] MCPApp closed", self.name)

    def _configure_logging(self) -> None:
        """
        Apply `MCPConfig.logging` via `slb_glossary.logging.configure_logging`.
        """
        logging_config = self.config.logging
        if logging_config.sinks is None and logging_config.level is None:
            return

        spec = logging_config.sinks
        if spec is None:
            resolved_sinks = None
        elif isinstance(spec, (list, tuple, set, frozenset)):
            resolved_sinks = [resolve_sink(item) for item in spec]
        else:
            resolved_sinks = [resolve_sink(spec)]  # type: ignore[arg-type]

        configure_logging(
            sinks=resolved_sinks,
            level=logging_config.level,
            logger_name=logging_config.logger_name,
            fmt=logging_config.fmt or DEFAULT_LOG_FORMAT,
            propagate=logging_config.propagate,
        )

    async def run_async(self, **transport_kwargs: typing.Any) -> None:
        """
        Start resources, serve until the transport stops, then always clean up.

        :param transport_kwargs: Forwarded to `fastmcp.FastMCP.run_async`,
            e.g. `transport="http", host="0.0.0.0", port=8000`. Defaults
            to FastMCP's own default (stdio) when omitted.
        """
        server = self.to_server()
        await self.start()
        async with contextlib.aclosing(self):
            await server.run_async(**transport_kwargs)

    def run(self, **transport_kwargs: typing.Any) -> None:
        """
        Synchronous convenience wrapper around `run_async`, for simple entry points.

        :param transport_kwargs: Forwarded to `fastmcp.FastMCP.run_async` - see `run_async`.
        """
        asyncio.run(self.run_async(**transport_kwargs))
