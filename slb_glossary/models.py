"""Core data structures shared across the `slb_glossary` package."""

import dataclasses
import enum
import typing

from patchright.async_api import Browser, BrowserContext, Page, Playwright


__all__ = [
    "Language",
    "SearchResult",
    "GlossarySearch",
]


class Language(enum.Enum):
    """A language edition of the SLB glossary."""

    ENGLISH = "en"
    SPANISH = "es"


class SearchResult(typing.NamedTuple):
    """A single term definition extracted from the glossary."""

    term: str
    """The glossary term this result defines."""

    definition: typing.Optional[str]
    """Full text of the definition, or `None` if it could not be parsed."""

    grammatical_label: typing.Optional[str]
    """Part of speech of the term (e.g. "Noun"), or `None` if unavailable."""

    topic: typing.Optional[str]
    """Topic/discipline this definition is filed under in the glossary."""

    url: typing.Optional[str]
    """URL of the glossary page the definition was extracted from."""


@dataclasses.dataclass
class GlossarySearch:
    """
    An open, ready-to-query session against the SLB glossary.

    Obtain one with `slb_glossary.browser.open_glossary_search` or the
    `slb_glossary.browser.glossary_session` context manager, then pass it to
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

    topics: typing.Dict[str, int]
    """Mapping of topic name to number of glossary terms filed under it."""

    size: int
    """Total number of terms in the glossary, as reported by the site."""

    terms_per_tab: int = 12
    """Number of results the glossary site returns per results page."""
