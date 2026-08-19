import asyncio
import dataclasses
import enum
import logging
import time
import typing
from asyncio import Handle

from patchright.async_api import Browser, BrowserContext, Page, Playwright

from slb_glossary.errors import NetworkError
from slb_glossary.retries import RetryPolicy
from slb_glossary.types import Language

logger = logging.getLogger(__name__)


__all__ = [
    "ResourceType",
    "BrowserType",
    "Session",
]


class BrowserType(enum.StrEnum):
    """Playwright browser families `open_session` can launch."""

    CHROMIUM = "chromium"
    FIREFOX = "firefox"
    WEBKIT = "webkit"


class ResourceType(enum.IntFlag):
    """Playwright request resource types used for resource blocking."""

    DOCUMENT = enum.auto()
    STYLESHEET = enum.auto()
    IMAGE = enum.auto()
    MEDIA = enum.auto()
    FONT = enum.auto()
    SCRIPT = enum.auto()
    TEXTTRACK = enum.auto()
    XHR = enum.auto()
    FETCH = enum.auto()
    EVENTSOURCE = enum.auto()
    WEBSOCKET = enum.auto()
    MANIFEST = enum.auto()
    OTHER = enum.auto()
    ALL = (
        DOCUMENT
        | STYLESHEET
        | IMAGE
        | MEDIA
        | FONT
        | SCRIPT
        | TEXTTRACK
        | XHR
        | FETCH
        | EVENTSOURCE
        | WEBSOCKET
        | MANIFEST
        | OTHER
    )



@dataclasses.dataclass(slots=True, kw_only=True)
class PageHandle:

    page: Page



@dataclasses.dataclass(slots=True, kw_only=True)
class Pages:

    context: BrowserContext
    max_size: int
    _pages: set[Page]

    async def get(self) -> PageHandle:
        ...

    


@dataclasses.dataclass(slots=True, kw_only=True)
class Session:
    """
    An open, ready-to-query browser session against the SLB glossary.

    Obtain one with `slb_glossary.browser.open_session`, `session`,
    or `Session.from_config`, then pass it to the search functions in
    `slb_glossary.live`.

    A session is single-page and not safe to use concurrently from multiple
    coroutines at once; open one session per concurrent task if you need parallelism.
    """

    playwright: Playwright
    """The running Playwright driver instance backing this session."""

    browser: Browser
    """The browser instance launched for this session."""

    context: BrowserContext
    """The browser context (cookies, cache, stealth patches) `page` runs in."""

    language: Language
    """The glossary language this session searches."""

    base_url: str
    """Base search URL for `language`."""

    topics: dict[str, int]
    """Mapping of topic name to number of glossary terms filed under it."""

    size: int
    """Total number of terms in the glossary, as reported by the site."""

    browser_type: str = "chromium"
    """Playwright browser family this session launched (`"chromium"`, `"firefox"` or `"webkit"`)."""

    terms_per_tab: int = 12
    """Number of results the glossary site returns per results page."""

    blocked_resources: frozenset[str] = dataclasses.field(default_factory=frozenset)
    """Request resource types (e.g. `"image"`) dropped for this session."""

    retry: RetryPolicy = dataclasses.field(default_factory=RetryPolicy)
    """
    Policy used to retry page loads that render before their JavaScript
    search widget has finished populating.
    """

    timeout: float = 60_000
    """Milliseconds to wait for page/element load or lookups, and navigation before timeout"""

    settle_timeout: float = 8000
    """
    Milliseconds to wait for the results list to update after a search
    filter changes, since the glossary updates its results via JavaScript
    rather than a full page navigation.
    """

    poll_interval: float = 300
    """Milliseconds to wait between polls while waiting on `settle_timeout`."""

    _initialized: bool = dataclasses.field(init=False, repr=False, default=False)

    @property
    def initialized(self) -> bool:
        return self._initialized

    async def initialize(self, page: Page | None = None) -> None:
        if self.initialized:
            return

        new_page: Page | None = None
        if page is None:
            page = new_page = await self.new_page()

        started_at = time.monotonic()
        try:
            from slb_glossary.live.topics import fetch_topics

            topics, size = await fetch_topics(
                page,
                base_url=self.base_url,
                settle_delay=self.settle_timeout,
                retry=self.retry,
            )
            self.topics = topics
            self.size = size
        except Exception as exc:
            raise NetworkError(f"Could not reach the glossary at {self.base_url}") from exc
        finally:
            if new_page is not None:
                await new_page.close()

        logger.debug(
            "Loaded topics/size for %s in %.3fs", self.base_url, time.monotonic() - started_at
        )

    async def new_page(self) -> Page:
        """
        Create a new page in the browser context.

        The page is associated with this session's browser context and is
        automatically closed when the session is closed.

        :returns: A new Playwright browser page.
        """
        return await self.context.new_page()

