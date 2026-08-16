"""
MCP (Model Context Protocol) server for the SLB Energy Glossary.

Exposes `slb_glossary.query`'s search/lookup functions as MCP tools an LLM
agent can call directly, backed by [FastMCP](https://gofastmcp.com).

The MCP application is fully configurable through `MCPConfig`.
You can configure which sources are reachable, whether
local writes are allowed, which tools are built, timeouts, auth, rate
limiting, hooks, logging, and streaming - see `slb_glossary.mcp.config`.

```python
import asyncio

from slb_glossary.mcp import MCPApp, MCPConfig

app = MCPApp(MCPConfig.default())
asyncio.run(app.run_async())
```

Or from the command line: `slb mcp serve` (see `slb_glossary.cli.commands.mcp`).

Requires the `mcp` extra: `pip install slb-glossary[mcp]`.
"""

from slb_glossary.mcp.api import MCPApp
from slb_glossary.mcp.auth import (
    ANONYMOUS,
    AuthBackend,
    AuthRequest,
    NullAuth,
    Principal,
    StaticTokenAuth,
    import_backend,
)
from slb_glossary.mcp.config import (
    AuthConfig,
    HooksConfig,
    LocalAccessConfig,
    MCPConfig,
    MCPLoggingConfig,
    RateLimitConfig,
    RateLimitScope,
    ServerInfo,
    SessionAccessConfig,
    SessionMode,
    SourcePolicyConfig,
    StreamingConfig,
    TimeoutConfig,
    Tool,
    resolve_tools,
)
from slb_glossary.mcp.errors import (
    AuthenticationError,
    MCPConfigError,
    MCPError,
    RateLimitExceededError,
)
from slb_glossary.mcp.ratelimit import RateLimiter, SlidingWindowRateLimiter
from slb_glossary.mcp.runtime import Runtime
from slb_glossary.mcp.types import (
    AfterToolHook,
    BeforeToolHook,
    LifecycleHook,
    NamedComponent,
    ToolErrorHook,
    ToolRunContext,
)

__all__ = [
    "MCPApp",
    "MCPConfig",
    "ServerInfo",
    "SessionAccessConfig",
    "SessionMode",
    "LocalAccessConfig",
    "SourcePolicyConfig",
    "TimeoutConfig",
    "AuthConfig",
    "RateLimitConfig",
    "RateLimitScope",
    "HooksConfig",
    "MCPLoggingConfig",
    "StreamingConfig",
    "Tool",
    "resolve_tools",
    "AuthBackend",
    "AuthRequest",
    "Principal",
    "ANONYMOUS",
    "StaticTokenAuth",
    "NullAuth",
    "import_backend",
    "RateLimiter",
    "SlidingWindowRateLimiter",
    "Runtime",
    "NamedComponent",
    "ToolRunContext",
    "BeforeToolHook",
    "AfterToolHook",
    "ToolErrorHook",
    "LifecycleHook",
    "MCPError",
    "MCPConfigError",
    "AuthenticationError",
    "RateLimitExceededError",
]
