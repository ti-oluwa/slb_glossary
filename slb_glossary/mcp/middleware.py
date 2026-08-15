"""
FastMCP middleware for `slb_glossary.mcp`: authentication, rate limiting,
call hooks, and call logging - everything that wraps *every* tool call
regardless of which tool it is.

Per-tool concerns (timeouts, argument validation, resolving `db`/`session`)
live on the tool registration itself (`slb_glossary.mcp.api`) and in
`slb_glossary.mcp.tools`, since FastMCP's own `@mcp.tool(timeout=...)`
already covers timeouts without needing middleware for it.
"""

import logging
import time
import typing

from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import Middleware, MiddlewareContext

from slb_glossary.mcp.auth import ANONYMOUS, Principal
from slb_glossary.mcp.config import MCPConfig, RateLimitScope
from slb_glossary.mcp.runtime import ToolRunContext
from slb_glossary.query import Source

logger = logging.getLogger(__name__)

__all__ = ["GlossaryMiddleware"]


def _extract_bearer_token() -> str | None:
    """Best-effort extraction of a bearer token from the current HTTP request, if any.

    Returns `None` outside an HTTP transport (e.g. stdio), where there are
    no per-request headers to read.
    """
    try:
        headers = get_http_headers()
    except Exception:
        return None
    authorization = headers.get("authorization") or headers.get("Authorization")
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token


def _rate_limit_key(scope: RateLimitScope, principal: Principal, tool_name: str) -> str:
    if scope is RateLimitScope.GLOBAL:
        return "global"
    if scope is RateLimitScope.CLIENT:
        return principal.id
    if scope is RateLimitScope.TOOL:
        return tool_name
    return f"{principal.id}:{tool_name}"


class GlossaryMiddleware(Middleware):
    """
    Single middleware wiring up auth, rate limiting, hooks, and call logging.

    One instance is added per `slb_glossary.mcp.api.Application`; it reads
    everything it needs from the `MCPConfig` it's built with, so behavior
    is entirely config-driven rather than requiring several middleware
    instances to be composed by hand.
    """

    def __init__(self, config: MCPConfig) -> None:
        self.config = config

    async def on_call_tool(
        self,
        context: MiddlewareContext,
        call_next: typing.Callable[[MiddlewareContext], typing.Awaitable[typing.Any]],
    ) -> typing.Any:
        tool_name: str = getattr(context.message, "name", "<unknown>")
        arguments: dict[str, typing.Any] = dict(getattr(context.message, "arguments", None) or {})

        principal = await self._authenticate()

        if self.config.rate_limit.enabled:
            await self._enforce_rate_limit(principal, tool_name)

        run_context = ToolRunContext(
            tool_name=tool_name,
            principal=principal,
            arguments=arguments,
            source=_source_from_arguments(arguments),
        )
        if context.fastmcp_context is not None:
            context.fastmcp_context.set_state("glossary_principal", principal)

        for hook in self.config.hooks.before_tool:
            await hook(run_context)

        started_at = time.monotonic()
        try:
            result = await call_next(context)
        except Exception as exc:
            for hook in self.config.hooks.on_error:
                await hook(run_context, exc)
            if self.config.logging.log_tool_calls:
                logger.warning(
                    "MCP tool %s failed for %s after %.3fs: %s",
                    tool_name,
                    principal.id,
                    time.monotonic() - started_at,
                    exc,
                )
            raise

        for hook in self.config.hooks.after_tool:
            await hook(run_context, result)

        if self.config.logging.log_tool_calls:
            logger.info(
                "MCP tool %s called by %s in %.3fs",
                tool_name,
                principal.id,
                time.monotonic() - started_at,
            )
        return result

    async def _authenticate(self) -> Principal:
        auth_config = self.config.auth
        if auth_config.backend is None:
            return ANONYMOUS

        token = _extract_bearer_token()
        principal = await auth_config.backend.authenticate(token)
        if principal is not None:
            return principal
        if auth_config.required:
            raise ToolError("Authentication required or the provided token is invalid.")
        return ANONYMOUS

    async def _enforce_rate_limit(self, principal: Principal, tool_name: str) -> None:
        limiter = self.config.rate_limit.limiter
        if limiter is None:
            # MCPConfig construction never leaves this None when enabled=True
            # for the built-in default (see slb_glossary.mcp.api.Application);
            # guard here anyway in case a caller enabled rate limiting without one.
            return
        key = _rate_limit_key(self.config.rate_limit.scope, principal, tool_name)
        allowed = await limiter.acquire(key)
        if not allowed:
            raise ToolError(f"Rate limit exceeded for {key!r}. Try again shortly.")


def _source_from_arguments(arguments: typing.Mapping[str, typing.Any]) -> Source | None:
    """Best-effort parse of a `source` MCP argument into a `Source`, for `ToolRunContext`."""
    raw = arguments.get("source")
    if raw is None:
        return None
    try:
        return Source(raw)
    except ValueError:
        return None
