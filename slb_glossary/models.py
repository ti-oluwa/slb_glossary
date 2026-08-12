"""Core data structures."""

import dataclasses
import enum
import typing

from patchright.async_api import Browser, BrowserContext, Page, Playwright

from .backoff import BackoffPolicy

__all__ = [
    "Language",
    "SearchResult",
    "SearchSession",
]


class Language(enum.Enum):
    """A language edition of the SLB glossary."""

    ENGLISH = "en"
    SPANISH = "es"


class SearchResult(typing.NamedTuple):
    """A single term definition extracted from the glossary."""

    term: str
    """The glossary term this result defines."""

    definition: str | None
    """Full text of the definition, or `None` if it could not be parsed."""

    grammatical_label: str | None
    """Part of speech of the term (e.g. "Noun"), or `None` if unavailable."""

    topic: str | None
    """Topic/discipline this definition is filed under in the glossary."""

    url: str | None
    """URL of the glossary page the definition was extracted from."""

    @property
    def fields(self) -> list[str]:
        """Return a list of the field names in this result."""
        return list(self._fields)

    def asdict(self) -> dict[str, typing.Any]:
        """Return a dictionary representation of this result."""
        return self._asdict()


@dataclasses.dataclass(slots=True)
class SearchSession:
    """
    An open, ready-to-query session against the SLB glossary.

    Obtain one with `slb_glossary.browser.open_session` or the
    `slb_glossary.browser.search_session` context manager, then pass it to
    the search functions in `slb_glossary.search`. A session is single-page
    and not safe to use concurrently from multiple coroutines at once; open
    one session per concurrent task if you need parallelism.
    """

    playwright: Playwright
    """The running Playwright driver instance backing this session."""

    browser: Browser
    """The browser instance launched for this session."""

    context: BrowserContext
    """The browser context (cookies, cache, stealth patches) `page` runs in."""

    page: Page
    """The browser page searches and lookups are performed on."""

    language: Language
    """The glossary language this session searches."""

    base_url: str
    """Base search URL for `language`."""

    topics: dict[str, int]
    """Mapping of topic name to number of glossary terms filed under it."""

    size: int
    """Total number of terms in the glossary, as reported by the site."""

    browser_type: str = "chromium"
    """Playwright browser family this session launched (`"chromium"`,
    `"firefox"` or `"webkit"`)."""

    terms_per_tab: int = 12
    """Number of results the glossary site returns per results page."""

    blocked_resource_types: frozenset[str] = dataclasses.field(default_factory=frozenset)
    """Request resource types (e.g. `"image"`) dropped for this session."""

    backoff: BackoffPolicy = dataclasses.field(default_factory=BackoffPolicy)
    """Policy used to retry page loads that render before their JavaScript
    search widget has finished populating."""

    settle_timeout: float = 8.0
    """Seconds to wait for the results list to update after a search
    filter changes, since the glossary updates its results via JavaScript
    rather than a full page navigation."""

    poll_interval: float = 0.3
    """Seconds to wait between polls while waiting on `settle_timeout`."""
