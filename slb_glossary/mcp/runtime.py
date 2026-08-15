"""
Resource lifecycle management for `slb_glossary.mcp`'s MCP server.

`Runtime` owns the (at most one, shared) local `Database` connection and
live `BrowserSession` a server built from an `MCPConfig` uses, opening and
closing them according to `LocalAccessConfig`/`SessionAccessConfig`, and
hands each tool call a `db`/`session` pair through `Runtime.acquire`. This
is the one place `slb_glossary.mcp` talks to `slb_glossary.local`/
`slb_glossary.live` directly - every tool function in `slb_glossary.mcp.tools`
goes through it rather than opening resources itself.
"""

import asyncio
import contextlib
import dataclasses
import logging
import pathlib
import time
import typing

from slb_glossary.errors import QueryError
from slb_glossary.live.browser import BrowserSession, close_session, open_session
from slb_glossary.local.connection import close_db, open_db
from slb_glossary.local.models import Database
from slb_glossary.mcp.auth import Principal
from slb_glossary.mcp.config import MCPConfig, SessionMode
from slb_glossary.query import Source

logger = logging.getLogger(__name__)

__all__ = ["Runtime", "ToolRunContext"]


@dataclasses.dataclass(slots=True, kw_only=True)
class ToolRunContext:
    """
    Everything a tool call's hooks (see `slb_glossary.mcp.config.HooksConfig`) get to see.

    Built fresh per call by `slb_glossary.mcp.tools`/`slb_glossary.mcp.middleware`
    and passed to `before_tool`/`after_tool`/`on_error` hooks. Read-only in
    practice - hooks are meant to observe/veto (by raising), not mutate call state.
    """

    tool_name: str
    """The MCP tool name being called, e.g. `\"glossary_search\"`."""

    principal: Principal
    """The resolved caller identity - `slb_glossary.mcp.auth.ANONYMOUS` if
    no auth backend is configured or the call carried no token."""

    arguments: typing.Mapping[str, typing.Any]
    """The tool call's raw arguments, as a plain mapping."""

    source: Source | None
    """The `Source` this call resolved to, if applicable to this tool."""

    started_at: float = dataclasses.field(default_factory=time.monotonic)
    """`time.monotonic()` reading taken when the call began."""


class Runtime:
    """
    Owns the shared `Database`/`BrowserSession` resources for one running MCP server.

    One `Runtime` per `slb_glossary.mcp.api.Application`. Not safe to share
    across `Application` instances since it tracks its own resource
    lifecycle state.
    """

    def __init__(self, config: MCPConfig) -> None:
        self.config = config
        self._db: Database | None = None
        self._db_lock = asyncio.Lock()
        self._session: BrowserSession | None = None
        self._session_lock = asyncio.Lock()
        self._session_semaphore = asyncio.Semaphore(config.session.max_concurrent)
        self._session_last_used: float = 0.0
        self._reaper_task: asyncio.Task[None] | None = None
        self._started = False
        self._closed = False

    async def start(self) -> None:
        """
        Perform startup-time work: open a local DB connection (if enabled), eagerly
        open the live session if `SessionMode.EAGER` is configured, and start the
        idle-session reaper if `idle_timeout` is set.

        Safe to call more than once; later calls are no-ops.
        """
        if self._started:
            return
        self._started = True

        if self.config.local.enabled:
            await self._open_db()

        if self.config.session.enabled and self.config.session.mode is SessionMode.EAGER:
            await self._open_session()

        if (
            self.config.session.enabled
            and self.config.session.mode is not SessionMode.PER_CALL
            and self.config.session.idle_timeout is not None
        ):
            self._reaper_task = asyncio.ensure_future(self._reap_idle_session())

        logger.info("slb_glossary.mcp Runtime started")

    async def aclose(self) -> None:
        """Tear down every resource this runtime opened. Safe to call more than once."""
        if self._closed:
            return
        self._closed = True

        if self._reaper_task is not None:
            self._reaper_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reaper_task
            self._reaper_task = None

        async with self._session_lock:
            if self._session is not None:
                await close_session(self._session)
                self._session = None

        async with self._db_lock:
            if self._db is not None:
                await close_db(self._db)
                self._db = None

        logger.info("slb_glossary.mcp Runtime closed")

    async def _open_db(self) -> Database:
        async with self._db_lock:
            if self._db is None:
                self._db = await open_db(_db_path(self.config.local.database))
            return self._db

    async def _open_session(self) -> BrowserSession:
        async with self._session_lock:
            if self._session is None:
                kwargs = self.config.session.browser.to_session_kwargs()
                self._session = await open_session(**kwargs)
            self._session_last_used = time.monotonic()
            return self._session

    async def _reap_idle_session(self) -> None:
        """Background task: close the shared session after it's sat idle past `idle_timeout`."""
        idle_timeout = self.config.session.idle_timeout
        assert idle_timeout is not None
        try:
            while True:
                await asyncio.sleep(max(idle_timeout / 4, 5.0))
                async with self._session_lock:
                    if self._session is None:
                        continue
                    idle_for = time.monotonic() - self._session_last_used
                    if idle_for >= idle_timeout:
                        logger.info(
                            "Closing idle live session after %.1fs (idle_timeout=%.1fs)",
                            idle_for,
                            idle_timeout,
                        )
                        await close_session(self._session)
                        self._session = None
        except asyncio.CancelledError:
            raise

    async def open_local_db(self) -> Database:
        """
        Return the shared local `Database`, opening it on first use.

        Unlike `acquire`, this doesn't route through `Source` resolution -
        it's for callers (like the `glossary_sync` tool) that always need a
        writable local database regardless of which `Source` a call
        otherwise resolves to.

        :raises QueryError: If this runtime's `MCPConfig.local.enabled` is `False`.
        """
        if not self.config.local.enabled:
            raise QueryError("This server has local database access disabled.")
        return await self._open_db()

    @contextlib.asynccontextmanager
    async def acquire(
        self, source: Source
    ) -> typing.AsyncIterator[tuple[Database | None, BrowserSession | None]]:
        """
        Yield the `(db, session)` pair a tool call needs to satisfy `source`.

        Honors `SessionMode`: for `PER_CALL`, a fresh session is opened for
        the duration of the `async with` block and closed on exit (bounded
        by `SessionAccessConfig.max_concurrent` via a semaphore); for
        `EAGER`/`LAZY`, the shared session is reused (and lazily opened on
        first use, for `LAZY`).

        :param source: The resolved `Source` this call needs resources for.
        :yield: A `(db, session)` tuple, either of which may be `None` if
            `source` doesn't require it.
        :raises QueryError: If `source` needs a resource this `Runtime`
            wasn't configured to provide (`local.enabled=False` for
            `Source.LOCAL`, `session.enabled=False` for `Source.LIVE`).
        """
        needs_db = source in (Source.LOCAL, Source.AUTO)
        needs_session = source in (Source.LIVE, Source.AUTO)

        if source is Source.LOCAL and not self.config.local.enabled:
            raise QueryError("This server has local database access disabled.")
        if source is Source.LIVE and not self.config.session.enabled:
            raise QueryError("This server has live glossary access disabled.")

        db = await self._open_db() if (needs_db and self.config.local.enabled) else None

        if not needs_session or not self.config.session.enabled:
            yield db, None
            return

        if self.config.session.mode is SessionMode.PER_CALL:
            async with self._session_semaphore:
                kwargs = self.config.session.browser.to_session_kwargs()
                session = await open_session(**kwargs)
                try:
                    yield db, session
                finally:
                    await close_session(session)
            return

        session = await self._open_session()
        yield db, session


def _db_path(database_config: typing.Any) -> str | None:
    """Extract the configured local database path, or `None` for the OS default."""
    if not database_config.data_dir:
        return None
    return str(pathlib.Path(database_config.data_dir) / database_config.db_filename)
