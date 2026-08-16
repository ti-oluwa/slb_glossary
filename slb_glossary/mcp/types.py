"""
Small types shared across `slb_glossary.mcp` that would otherwise create an
import cycle: `slb_glossary.mcp.config.HooksConfig`'s hook signatures need
`ToolRunContext`, but `ToolRunContext` naturally belongs next to
`slb_glossary.mcp.runtime.Runtime`, which itself imports `MCPConfig` from
`slb_glossary.mcp.config`. Living here, both sides can import the real type
instead of falling back to `typing.Any`.

`NamedComponent` is unrelated to that cycle - it's just a small mixin so
`Application` and `Runtime` share one `name` (taken from
`MCPConfig.server.name`) for logging and task naming, rather than each
hardcoding its own.
"""

import dataclasses
import time
import typing
from collections.abc import Awaitable, Callable, Mapping

from slb_glossary.mcp.auth import Principal
from slb_glossary.query import Source

__all__ = [
    "NamedComponent",
    "ToolRunContext",
    "BeforeToolHook",
    "AfterToolHook",
    "ToolErrorHook",
    "LifecycleHook",
]


class NamedComponent:
    """
    Mixin giving a component a human-readable `name` for use in logs, task names, and `repr`.

    `slb_glossary.mcp.api.Application` and `slb_glossary.mcp.runtime.Runtime`
    both inherit this and are constructed with the same
    `MCPConfig.server.name`, so log lines and background-task names from
    either one are identifiable as belonging to the same server instance
    without each hardcoding its own prefix.
    """

    def __init__(self, name: str) -> None:
        """:param name: Human-readable name for this component - typically `MCPConfig.server.name`."""
        self.name = name

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.name!r})"


@dataclasses.dataclass(slots=True, kw_only=True)
class ToolRunContext:
    """
    Everything a tool call's hooks (see `slb_glossary.mcp.config.HooksConfig`) get to see.

    Built fresh per call by `slb_glossary.mcp.middleware.GlossaryMiddleware`
    and passed to `before_tool`/`after_tool`/`on_error` hooks, and also
    stashed in the FastMCP `Context` state (see
    `GlossaryMiddleware.on_call_tool`) so tool bodies can read it too.
    Read-only in practice - hooks are meant to observe/veto (by raising),
    not mutate call state.
    """

    tool_name: str
    """The MCP tool name being called, e.g. `\"glossary_search\"`."""

    principal: Principal
    """The resolved caller identity - `slb_glossary.mcp.auth.ANONYMOUS` if
    no auth backend is configured or the call carried no token."""

    arguments: Mapping[str, typing.Any]
    """The tool call's raw arguments, as a plain mapping."""

    source: Source | None
    """The `Source` this call resolved to, if applicable to this tool."""

    started_at: float = dataclasses.field(default_factory=time.monotonic)
    """`time.monotonic()` reading taken when the call began."""


BeforeToolHook = Callable[[ToolRunContext], Awaitable[None]]
"""`async def hook(run: ToolRunContext) -> None`, called just before a tool's
body executes. Raise to abort the call (surfaced to the caller as a tool error)."""

AfterToolHook = Callable[[ToolRunContext, typing.Any], Awaitable[None]]
"""`async def hook(run: ToolRunContext, result: Any) -> None`, called after a
tool's body returns successfully, with its result. `result` is typed `Any`
because it's whatever JSON-serializable value the tool produced -
there's no one shared result type across tools to name here."""

ToolErrorHook = Callable[[ToolRunContext, BaseException], Awaitable[None]]
"""`async def hook(run: ToolRunContext, error: BaseException) -> None`,
called when a tool's body raises. The error still propagates afterward."""

LifecycleHook = Callable[[], Awaitable[None]]
"""`async def hook() -> None`, called once on server startup/shutdown."""
