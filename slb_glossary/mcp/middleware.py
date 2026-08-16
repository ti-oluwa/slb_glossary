"""
`FastMCP` middleware for `slb_glossary.mcp`. Incorporates authentication, rate limiting,
call hooks, and call logging. Basically everything that wraps *every* tool call
regardless of which tool it is.
"""

import logging
import time
from collections.abc import Awaitable, Callable

from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.tools.base import ToolResult

from slb_glossary.mcp.auth import ANONYMOUS, AuthRequest, Principal
from slb_glossary.mcp.config import MCPConfig, RateLimitScope
from slb_glossary.mcp.errors import AuthenticationError, RateLimitExceededError
from slb_glossary.mcp.types import ToolRunContext
from slb_glossary.query import Source

logger = logging.getLogger(__name__)

__all__ = ["MCPMiddleware"]


def get_current_http_headers() -> dict[str, str]:
    """
    Best-effort read of the current HTTP request's headers, lower-cased keys.

    Returns an empty mapping outside an HTTP transport (e.g. stdio), where
    there are no per-request headers to read.
    """
    try:
        headers = get_http_headers()
    except Exception:
        return {}
    return {key.lower(): value for key, value in headers.items()}


def get_bearer_token(headers: dict[str, str]) -> str | None:
    """Parse a `Authorization: Bearer <token>` header out of `headers`, if present."""
    authorization = headers.get("authorization")
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token


def get_rate_limit_key(scope: RateLimitScope, principal: Principal, tool_name: str) -> str:
    if scope is RateLimitScope.GLOBAL:
        return "global"
    if scope is RateLimitScope.CLIENT:
        return principal.id
    if scope is RateLimitScope.TOOL:
        return tool_name
    assert scope is RateLimitScope.CLIENT_TOOL, f"Unexpected RateLimitScope member {scope!r}."
    return f"{principal.id}:{tool_name}"


def get_source_from_arguments(arguments: dict) -> Source | None:
    """Best-effort parse of a `source` MCP argument into a `Source`, for `ToolRunContext`."""
    raw = arguments.get("source")
    if raw is None:
        return None
    try:
        return Source(raw)
    except ValueError:
        return None


class MCPMiddleware(Middleware):
    """
    Single middleware wiring up auth, rate limiting, hooks, and call logging.

    One instance is added per `slb_glossary.mcp.api.MCPApp`.

    It reads everything it needs from the `MCPConfig` it's built with, so behavior
    is entirely config-driven rather than requiring several middleware instances
    to be composed by hand.
    """

    def __init__(self, config: MCPConfig) -> None:
        self.config = config

    async def on_call_tool(
        self,
        context: MiddlewareContext,
        call_next: Callable[[MiddlewareContext], Awaitable[ToolResult]],
    ) -> ToolResult:
        tool_name: str = getattr(context.message, "name", "<unknown>")
        arguments: dict = dict(getattr(context.message, "arguments", None) or {})

        principal = await self.authenticate(tool_name, arguments)
        if self.config.rate_limit.enabled:
            await self.enforce_rate_limit(principal, tool_name)

        run_context = ToolRunContext(
            tool_name=tool_name,
            principal=principal,
            arguments=arguments,
            source=get_source_from_arguments(arguments),
        )
        if context.fastmcp_context is not None:
            # The full ToolRunContext is a superset of just the principal (it
            # also carries the tool name, arguments, resolved source, and call
            # start time), so tool bodies that pull state back out via
            # ctx.get_state get everything in one read. The bare principal is
            # kept alongside it too, for the common case of only wanting "who
            # is calling" without needing to know/import ToolRunContext's shape.
            await context.fastmcp_context.set_state(
                "glossary_run_context", run_context, serializable=False
            )
            await context.fastmcp_context.set_state(
                "glossary_principal", principal, serializable=False
            )

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

    async def authenticate(self, tool_name: str, arguments: dict) -> Principal:
        auth_config = self.config.auth
        if auth_config.backend is None:
            return ANONYMOUS

        headers = get_current_http_headers()
        request = AuthRequest(
            token=get_bearer_token(headers),
            headers=headers,
            tool_name=tool_name,
            arguments=arguments,
        )
        principal = await auth_config.backend.authenticate(request)
        if principal is not None:
            return principal
        if auth_config.required:
            exc = AuthenticationError(
                "Authentication required, or the provided credentials are invalid."
            )
            raise ToolError(exc) from exc
        return ANONYMOUS

    async def enforce_rate_limit(self, principal: Principal, tool_name: str) -> None:
        limiter = self.config.rate_limit.limiter
        if limiter is None:
            # slb_glossary.mcp.api.MCPApp always resolves a default limiter
            # before this middleware can run whenever rate_limit.enabled is True;
            # reaching this branch means that wiring was bypassed somehow.
            logger.warning(
                "RateLimit.enabled is True but no limiter was resolved; "
                "skipping rate limiting for this call."
            )
            return
        key = get_rate_limit_key(self.config.rate_limit.scope, principal, tool_name)
        wait_ms = await limiter.hit(key)
        if wait_ms > 0:
            exc = RateLimitExceededError(key, wait_ms=wait_ms)
            raise ToolError(exc) from exc
