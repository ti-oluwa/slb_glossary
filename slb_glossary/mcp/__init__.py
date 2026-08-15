"""
MCP (Model Context Protocol) server for the SLB Energy Glossary.

Exposes `slb_glossary.query`'s search/lookup functions as MCP tools an LLM
agent can call directly, backed by [FastMCP](https://gofastmcp.com). Fully
configurable through `MCPConfig` - which sources are reachable, whether
local writes are allowed, which tools are built, timeouts, auth, rate
limiting, hooks, logging, and streaming - see `slb_glossary.mcp.config`.

```python
import asyncio

from slb_glossary.mcp import Application, MCPConfig

app = Application(MCPConfig.default())
asyncio.run(app.run_async())
```

Requires the `mcp` extra: `pip install slb-glossary[mcp]`.
"""

from slb_glossary.mcp.api import Application
from slb_glossary.mcp.auth import ANONYMOUS, AuthBackend, NullAuth, Principal, StaticTokenAuth
from slb_glossary.mcp.config import (
    AuthConfig,
    HooksConfig,
    LocalAccessConfig,
    MCPConfig,
    MCPLoggingConfig,
    RateLimitConfig,
    RateLimitScope,
    ServerInfoConfig,
    SessionAccessConfig,
    SessionMode,
    SourcePolicyConfig,
    StreamingConfig,
    TimeoutConfig,
    ToolName,
    resolve_tools,
)
from slb_glossary.mcp.ratelimit import RateLimiter, SlidingWindowRateLimiter
from slb_glossary.mcp.runtime import Runtime, ToolRunContext

__all__ = [
    "Application",
    "MCPConfig",
    "ServerInfoConfig",
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
    "ToolName",
    "resolve_tools",
    "AuthBackend",
    "Principal",
    "ANONYMOUS",
    "StaticTokenAuth",
    "NullAuth",
    "RateLimiter",
    "SlidingWindowRateLimiter",
    "Runtime",
    "ToolRunContext",
]
