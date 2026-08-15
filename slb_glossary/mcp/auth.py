"""
Pluggable, token-based authentication/authorization for `slb_glossary.mcp`.

This is deliberately independent of FastMCP's own OAuth-flavored
`AuthProvider` machinery (which secures the *transport*): `AuthBackend` here
resolves a single bearer token, taken from the request, into a `Principal`
that the server's middleware and rate limiter key off of, per tool call. If
you don't need per-caller identity, ignore this module entirely - the
server runs unauthenticated by default (`AuthConfig.backend=None`).

```python
from slb_glossary.mcp.auth import Principal, StaticTokenAuth

auth = StaticTokenAuth({
    "sk-alice-...": Principal(id="alice", scopes=frozenset({"read", "write"})),
    "sk-bot-...": "readonly-bot",  # bare string is shorthand for Principal(id=...)
})
```
"""

import types
import typing
from collections.abc import Mapping

__all__ = ["Principal", "AuthBackend", "StaticTokenAuth", "NullAuth", "ANONYMOUS"]


class Principal(typing.NamedTuple):
    """An authenticated (or anonymous) caller identity."""

    id: str
    """Stable identifier for this caller - used as the rate-limit key
    (see `slb_glossary.mcp.config.RateLimitScope`) and passed to hooks."""

    scopes: frozenset[str] = frozenset()
    """Free-form authorization scopes this caller holds. Not interpreted by
    `slb_glossary.mcp` itself; read them from
    `slb_glossary.mcp.runtime.ToolRunContext.principal` in a hook or a
    custom `AuthBackend` if you need scope-gated behavior."""

    metadata: Mapping[str, typing.Any] = types.MappingProxyType({})
    """Arbitrary extra data an `AuthBackend` wants to carry alongside the
    principal (e.g. a display name, a plan tier)."""


ANONYMOUS = Principal(id="anonymous")
"""The `Principal` used for calls with no token, when `AuthConfig.required` is `False`."""


@typing.runtime_checkable
class AuthBackend(typing.Protocol):
    """
    Protocol for resolving a bearer token into a `Principal`.

    Implement this (no base class required, just `authenticate`) to back
    tokens with a database, an external identity provider, environment
    variables, whatever. Pass an instance to `slb_glossary.mcp.config.AuthConfig.backend`.
    """

    async def authenticate(self, token: str | None) -> Principal | None:
        """
        Resolve `token` into a `Principal`.

        :param token: The bearer token extracted from the incoming
            request's `Authorization` header (with the `\"Bearer \"` prefix
            already stripped), or `None` if the request carried no token at all.
        :return: The resolved `Principal`, or `None` if `token` doesn't
            resolve to anyone. A `None` return is treated as
            "unauthenticated": rejected if `AuthConfig.required` is `True`,
            otherwise falls back to `ANONYMOUS`.
        """
        ...


class StaticTokenAuth:
    """An `AuthBackend` backed by a fixed, in-process mapping of token to `Principal`."""

    __slots__ = ("_tokens",)

    def __init__(self, tokens: Mapping[str, "Principal | str"]) -> None:
        """
        :param tokens: Mapping of raw bearer token to either a `Principal`
            directly, or a bare `str` used as shorthand for
            `Principal(id=that_string)`.
        """
        resolved: dict[str, Principal] = {}
        for token, value in tokens.items():
            resolved[token] = value if isinstance(value, Principal) else Principal(id=value)
        self._tokens = resolved

    async def authenticate(self, token: str | None) -> Principal | None:
        if token is None:
            return None
        return self._tokens.get(token)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({len(self._tokens)} token(s))"


class NullAuth:
    """An `AuthBackend` that authenticates nobody. Equivalent to leaving `backend=None`."""

    __slots__ = ()

    async def authenticate(self, token: str | None) -> Principal | None:
        return None
