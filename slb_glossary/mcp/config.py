"""
Configuration for `slb_glossary.mcp`'s MCP server (`slb_glossary.mcp.api.Application`).

Everything the server does - which sources it's allowed to read from, whether
it may write to the local database, which tools it exposes, timeouts, auth,
rate limiting, hooks, and logging - is controlled from one immutable
`MCPConfig` tree. Build one with keyword arguments, or start from
`MCPConfig.default()` and override just what you need with
`dataclasses.replace`:

```python
import dataclasses
from slb_glossary.mcp.config import MCPConfig, LocalAccessConfig

config = dataclasses.replace(
    MCPConfig.default(),
    local=LocalAccessConfig(enabled=True, allow_write=True),
)
```

Every nested config is a frozen, `slots=True`, keyword-only dataclass, so
instances are hashable-by-value-where-possible, cheap to copy with
`dataclasses.replace`, and cannot be mutated out from under a running server.
"""

import dataclasses
import enum
import typing
from collections.abc import Callable, Iterable, Mapping

from slb_glossary.config import BrowserSessionConfig, DatabaseConfig
from slb_glossary.errors import ConfigError
from slb_glossary.logging import LogSink
from slb_glossary.mcp.auth import AuthBackend
from slb_glossary.mcp.ratelimit import RateLimiter
from slb_glossary.query import Source

__all__ = [
    "ToolName",
    "SessionMode",
    "RateLimitScope",
    "SessionAccessConfig",
    "LocalAccessConfig",
    "SourcePolicyConfig",
    "TimeoutConfig",
    "AuthConfig",
    "RateLimitConfig",
    "HooksConfig",
    "MCPLoggingConfig",
    "StreamingConfig",
    "ServerInfoConfig",
    "MCPConfig",
    "BeforeToolHook",
    "AfterToolHook",
    "ToolErrorHook",
    "LifecycleHook",
    "resolve_tools",
]


class ToolName(enum.Flag):
    """
    Which `slb_glossary.query` operations the MCP server exposes as tools.

    An `IntFlag`-style set: combine members with `|` to build up a set of
    tools (`ToolName.SEARCH | ToolName.GET_TERM`), and test membership with
    `in`/`&`. Pass a `ToolName` combination, or any iterable of tool-name
    strings (see `resolve_tools`), to `MCPConfig(tools=...)`.
    """

    SEARCH = enum.auto()
    """`glossary_search` - free-text search, local and/or live."""

    GET_TERM = enum.auto()
    """`glossary_get_term` - exact-name or URL single-term lookup."""

    GET_TERMS_ON = enum.auto()
    """`glossary_get_terms_on` - every term filed under a topic."""

    GET_TERMS_URLS = enum.auto()
    """`glossary_get_terms_urls` - lightweight URL-only listing."""

    GET_TOPICS = enum.auto()
    """`glossary_get_topics` - topic name to term-count mapping."""

    RELATED_TERMS = enum.auto()
    """`glossary_related_terms` - related-term links for a single term."""

    RANDOM_TERM = enum.auto()
    """`glossary_random_term` - one randomly chosen term."""

    COMPARE = enum.auto()
    """`glossary_compare` - side-by-side lookup of several terms."""

    SYNC = enum.auto()
    """
    `glossary_sync` - fetch from the live glossary and write into the local
    database. The only tool that writes anything. Only ever registered when
    both this flag *and* `LocalAccessConfig.allow_write` are set - see
    `MCPConfig.resolved_tools`.
    """

    READ_ONLY = (
        SEARCH
        | GET_TERM
        | GET_TERMS_ON
        | GET_TERMS_URLS
        | GET_TOPICS
        | RELATED_TERMS
        | RANDOM_TERM
        | COMPARE
    )
    """Every tool that never writes to the local database. The default."""

    ALL = READ_ONLY | SYNC
    """Every tool this server knows how to build, including `SYNC`."""


_TOOL_NAME_ALIASES: dict[str, ToolName] = {
    member.name.lower(): member  # type: ignore[union-attr]
    for member in ToolName
    if member not in (ToolName.READ_ONLY, ToolName.ALL)
}
_TOOL_NAME_ALIASES["read_only"] = ToolName.READ_ONLY
_TOOL_NAME_ALIASES["all"] = ToolName.ALL


def resolve_tools(value: "ToolName | str | Iterable[str] | None") -> ToolName:
    """
    Normalize `value` into a `ToolName` flag combination.

    :param value: A `ToolName` (returned as-is), a single tool-name string
        (e.g. `"search"`, `"read_only"`), an iterable of such strings, or
        `None` for `ToolName.READ_ONLY`.
    :return: The resolved `ToolName` combination.
    :raises ConfigError: If any name in `value` isn't a known tool name.
    """
    if value is None:
        return ToolName.READ_ONLY
    if isinstance(value, ToolName):
        return value
    names = [value] if isinstance(value, str) else list(value)
    resolved = ToolName(0)
    for name in names:
        key = name.strip().lower()
        member = _TOOL_NAME_ALIASES.get(key)
        if member is None:
            choices = ", ".join(sorted(_TOOL_NAME_ALIASES))
            raise ConfigError(f"Unknown MCP tool name {name!r}. Expected one of: {choices}.")
        resolved |= member
    return resolved


class SessionMode(enum.Enum):
    """When the MCP server's live `BrowserSession` is opened and how long it lives."""

    EAGER = "eager"
    """Open one shared session at server startup, before any tool call. Lowest
    per-call latency, at the cost of always paying for a browser launch even
    if no live lookup is ever made."""

    LAZY = "lazy"
    """Open one shared session on the first tool call that needs it, then
    reuse it. Nothing is launched if every call is served locally. The
    default."""

    PER_CALL = "per_call"
    """Open a fresh session for every tool call that needs one, and close it
    immediately after. Slowest and heaviest, but gives every call full
    isolation - handy under multi-tenant auth where sessions shouldn't be
    shared across callers."""


class RateLimitScope(enum.Enum):
    """What key a `RateLimitConfig.limiter` is consulted under."""

    GLOBAL = "global"
    """One shared bucket for the whole server, across every client and tool."""

    CLIENT = "client"
    """One bucket per authenticated client (or `\"anonymous\"`), across all tools."""

    TOOL = "tool"
    """One bucket per tool name, shared by every client."""

    CLIENT_TOOL = "client_tool"
    """One bucket per `(client, tool)` pair. The default: the most granular."""


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class SessionAccessConfig:
    """Controls if/how/when the MCP server may open a live `BrowserSession`."""

    enabled: bool = True
    """Whether `Source.LIVE` (and `Source.AUTO` falling back to it) is
    available at all. `False` makes this a local-only server regardless of
    `SourcePolicyConfig`."""

    mode: SessionMode = SessionMode.LAZY
    """When the shared session is opened. See `SessionMode`."""

    idle_timeout: float | None = 300.0
    """Seconds an `EAGER`/`LAZY` session may sit unused before a background
    reaper closes it (a later call re-opens one). `None` disables the
    reaper, so a session lives until server shutdown. Ignored for `PER_CALL`."""

    max_concurrent: int = 1
    """Maximum number of live sessions (browser instances) open at once.
    Bounded with a semaphore; relevant mainly to `PER_CALL` mode, where
    concurrent tool calls can each want their own session."""

    browser: BrowserSessionConfig = dataclasses.field(default_factory=BrowserSessionConfig)
    """Options forwarded to `slb_glossary.browser.open_session` - language,
    browser type, headless, resource blocking, retry policy, and so on."""


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class LocalAccessConfig:
    """Controls if/how the MCP server may read and write the local database."""

    enabled: bool = True
    """Whether `Source.LOCAL` (and `Source.AUTO` preferring it) is available
    at all. `False` makes this a live-only server regardless of `SourcePolicyConfig`."""

    allow_write: bool = False
    """
    Whether any tool call may write to the local database. **Off by default**:
    with this `False`, every read tool's `persist` argument is silently
    ignored (never actually persists), and `ToolName.SYNC` is never
    registered even if requested in `MCPConfig.tools` - see
    `MCPConfig.resolved_tools`. Set this `True` deliberately to let the
    server cache live lookups, or run explicit syncs.
    """

    database: DatabaseConfig = dataclasses.field(default_factory=DatabaseConfig)
    """Options for the local database itself - storage location, filename,
    staleness threshold. See `slb_glossary.config.DatabaseConfig`."""


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class SourcePolicyConfig:
    """Controls which `slb_glossary.query.Source` values callers may request."""

    allowed: frozenset[Source] = frozenset({Source.AUTO, Source.LOCAL, Source.LIVE})
    """The set of `Source` values a tool call's `source` argument may
    resolve to. Narrow this (e.g. to `{Source.LOCAL}`) to hard-pin every
    tool to one source regardless of what a caller asks for."""

    default: Source = Source.AUTO
    """`Source` used when a tool call doesn't specify one."""

    expose_choice: bool = True
    """Whether tool schemas even include a `source` argument. `False` hides
    it entirely from callers/LLMs; every call then uses `default` (still
    narrowed by `allowed`, `SessionAccessConfig.enabled`, and
    `LocalAccessConfig.enabled`)."""


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class TimeoutConfig:
    """Per-call execution time caps, enforced by FastMCP's own tool `timeout=`."""

    global_seconds: float | None = 60.0
    """Default seconds a foreground tool call may run before being
    cancelled. `None` means tools run with no cap unless overridden per-tool
    in `per_tool`."""

    per_tool: Mapping[str, float | None] = dataclasses.field(default_factory=dict)
    """Tool name (e.g. `\"glossary_search\"`) to timeout override in
    seconds, taking precedence over `global_seconds` for that tool. A value
    of `None` here explicitly disables the timeout for that tool."""

    def for_tool(self, name: str) -> float | None:
        """Resolve the effective timeout, in seconds, for tool `name`."""
        if name in self.per_tool:
            return self.per_tool[name]
        return self.global_seconds


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class AuthConfig:
    """Controls token-based authentication/authorization for tool calls."""

    backend: AuthBackend | None = None
    """The `slb_glossary.mcp.auth.AuthBackend` used to resolve a caller's
    bearer token into a `Principal`. `None` disables authentication - every
    caller is treated as an anonymous `Principal`."""

    required: bool = False
    """If `True` and `backend` is set, calls with no token, or a token that
    doesn't resolve to a `Principal`, are rejected. If `False`, an
    unresolved token just falls back to the anonymous principal (still
    subject to rate limiting/hooks under whatever key that resolves to)."""


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class RateLimitConfig:
    """Controls optional per-tool/per-client request-rate limiting."""

    enabled: bool = False
    """Whether rate limiting is enforced at all. Off by default."""

    limiter: RateLimiter | None = None
    """The `slb_glossary.mcp.ratelimit.RateLimiter` to consult. `None` while
    `enabled=True` builds a default in-memory
    `slb_glossary.mcp.ratelimit.SlidingWindowRateLimiter` from
    `requests_per_minute`/`window_seconds` - see `MCPConfig.__post_init__`."""

    requests_per_minute: int = 60
    """Requests allowed per `window_seconds` per rate-limit key, used only
    when `limiter` is left `None` for the default limiter to be built from."""

    window_seconds: float = 60.0
    """Sliding window size, in seconds, used only when `limiter` is left
    `None`."""

    scope: RateLimitScope = RateLimitScope.CLIENT_TOOL
    """What key `limiter` is consulted under. See `RateLimitScope`."""


ToolRunContextT = typing.Any
"""Alias for `slb_glossary.mcp.runtime.ToolRunContext`, spelled as `Any`
here to avoid a circular import; hooks receive the real type at call time."""

BeforeToolHook = Callable[[ToolRunContextT], typing.Awaitable[None]]
"""`async def hook(run: ToolRunContext) -> None`, called just before a tool's
body executes. Raise to abort the call (surfaced to the caller as a tool error)."""

AfterToolHook = Callable[[ToolRunContextT, typing.Any], typing.Awaitable[None]]
"""`async def hook(run: ToolRunContext, result: Any) -> None`, called after a
tool's body returns successfully, with its result."""

ToolErrorHook = Callable[[ToolRunContextT, BaseException], typing.Awaitable[None]]
"""`async def hook(run: ToolRunContext, error: BaseException) -> None`,
called when a tool's body raises. The error still propagates afterward."""

LifecycleHook = Callable[[], typing.Awaitable[None]]
"""`async def hook() -> None`, called once on server startup/shutdown."""


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class HooksConfig:
    """Caller-supplied hooks run around every tool call and around the server's lifecycle."""

    before_tool: tuple[BeforeToolHook, ...] = ()
    """Run in order, just before each tool call's body. See `BeforeToolHook`."""

    after_tool: tuple[AfterToolHook, ...] = ()
    """Run in order, after each successful tool call. See `AfterToolHook`."""

    on_error: tuple[ToolErrorHook, ...] = ()
    """Run in order, when a tool call's body raises. See `ToolErrorHook`."""

    on_startup: tuple[LifecycleHook, ...] = ()
    """Run in order, once, before the server starts accepting calls."""

    on_shutdown: tuple[LifecycleHook, ...] = ()
    """Run in order, once, while the server is shutting down (after every
    resource `slb_glossary.mcp.runtime.Runtime` opened has been closed)."""


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class MCPLoggingConfig:
    """Controls where/how `slb_glossary`'s logging is routed for this server process."""

    sink: LogSink | type[LogSink] | str | None = None
    """Where to route logging - see `slb_glossary.logging.resolve_sink`.
    `None` leaves whatever logging setup is already in place untouched."""

    level: int | str | None = None
    """Logging level for the `slb_glossary` logger. `None` leaves the
    current level untouched."""

    log_tool_calls: bool = True
    """Whether the server's own middleware logs each tool call's name,
    caller, duration, and outcome at `INFO`/`WARNING` level."""


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class StreamingConfig:
    """Controls the optional `stream` argument tools that can stream expose."""

    default: bool = False
    """Default value of the `stream` argument on tools that support it
    (`glossary_search`, `glossary_get_terms_on`). When enabled, the tool
    reports incremental MCP progress notifications (via `Context.report_progress`)
    as results are found, in addition to still returning the full result at
    the end - MCP tool results are not itself partial/incremental, so this
    is progress reporting, not a change in what's ultimately returned."""

    allow_override: bool = True
    """Whether a tool call may override `default` with its own `stream`
    argument. `False` hides the argument and always uses `default`."""


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class ServerInfoConfig:
    """Identity metadata for the MCP server itself."""

    name: str = "slb-glossary"
    """Server name advertised to MCP clients."""

    version: str | None = None
    """Server version advertised to MCP clients. `None` uses
    `slb_glossary.__version__`."""

    instructions: str | None = None
    """Free-text instructions shown to connecting clients/LLMs about how to
    use this server as a whole. `None` uses a sensible built-in default -
    see `slb_glossary.mcp.tools.DEFAULT_INSTRUCTIONS`."""


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class MCPConfig:
    """
    Top-level, fully composable configuration for `slb_glossary.mcp.api.Application`.

    ```python
    from slb_glossary.mcp.config import MCPConfig, LocalAccessConfig, ToolName

    config = MCPConfig(
        local=LocalAccessConfig(allow_write=True),
        tools=ToolName.ALL,
    )
    ```

    Every field has a default, so `MCPConfig()` alone is a valid,
    read-only, local-and-live, unauthenticated, unlimited-rate server
    configuration. Validated at construction time by `__post_init__`;
    build with `dataclasses.replace` to change one field without
    re-specifying the rest.
    """

    server: ServerInfoConfig = dataclasses.field(default_factory=ServerInfoConfig)
    """Server identity metadata."""

    session: SessionAccessConfig = dataclasses.field(default_factory=SessionAccessConfig)
    """Live `BrowserSession` access."""

    local: LocalAccessConfig = dataclasses.field(default_factory=LocalAccessConfig)
    """Local database access."""

    source_policy: SourcePolicyConfig = dataclasses.field(default_factory=SourcePolicyConfig)
    """Which `Source` values tool calls may resolve to."""

    tools: ToolName = ToolName.READ_ONLY
    """Which tools to build. See `ToolName`, `resolve_tools`, and
    `resolved_tools` for how this interacts with `local.allow_write`."""

    timeouts: TimeoutConfig = dataclasses.field(default_factory=TimeoutConfig)
    """Per-call execution time caps."""

    auth: AuthConfig = dataclasses.field(default_factory=AuthConfig)
    """Token-based authentication/authorization."""

    rate_limit: RateLimitConfig = dataclasses.field(default_factory=RateLimitConfig)
    """Per-tool/per-client request-rate limiting."""

    hooks: HooksConfig = dataclasses.field(default_factory=HooksConfig)
    """Caller-supplied lifecycle and per-call hooks."""

    logging: MCPLoggingConfig = dataclasses.field(default_factory=MCPLoggingConfig)
    """Logging routing for this server process."""

    streaming: StreamingConfig = dataclasses.field(default_factory=StreamingConfig)
    """Progress-reporting behavior for tools that support it."""

    def __post_init__(self) -> None:
        if not self.session.enabled and not self.local.enabled:
            raise ConfigError(
                "MCPConfig: at least one of `session.enabled`/`local.enabled` must be True - "
                "a server with neither can't read anything."
            )
        if not self.source_policy.allowed:
            raise ConfigError("MCPConfig: `source_policy.allowed` must not be empty.")
        if self.source_policy.default not in self.source_policy.allowed:
            raise ConfigError(
                f"MCPConfig: `source_policy.default` ({self.source_policy.default}) must be "
                f"a member of `source_policy.allowed` ({self.source_policy.allowed})."
            )
        if Source.LOCAL in self.source_policy.allowed and not self.local.enabled:
            raise ConfigError(
                "MCPConfig: `source_policy.allowed` includes Source.LOCAL but `local.enabled` is False."
            )
        if Source.LIVE in self.source_policy.allowed and not self.session.enabled:
            raise ConfigError(
                "MCPConfig: `source_policy.allowed` includes Source.LIVE but `session.enabled` is False."
            )
        if self.rate_limit.enabled and self.rate_limit.requests_per_minute <= 0:
            raise ConfigError("MCPConfig: `rate_limit.requests_per_minute` must be positive.")
        if self.session.max_concurrent < 1:
            raise ConfigError("MCPConfig: `session.max_concurrent` must be at least 1.")

    def resolved_tools(self) -> ToolName:
        """
        The actual set of tools to build, after gating `ToolName.SYNC` on write access.

        `ToolName.SYNC` is stripped out unless *both* `ToolName.SYNC` is in
        `tools` *and* `local.allow_write` is `True` - so flipping on a
        write-capable tool always requires an explicit, deliberate
        `local.allow_write=True` in addition to requesting the tool itself.

        :return: `self.tools`, with `ToolName.SYNC` cleared if write access isn't granted.
        """
        tools = self.tools
        if ToolName.SYNC in tools and not self.local.allow_write:
            tools &= ~ToolName.SYNC
        return tools

    def effective_default_source(self) -> Source:
        """The `Source` used when a tool call doesn't specify one, narrowed to what's enabled."""
        return self.source_policy.default

    @classmethod
    def default(cls) -> "MCPConfig":
        """Return a fresh, all-defaults `MCPConfig`. Equivalent to `MCPConfig()`."""
        return cls()
