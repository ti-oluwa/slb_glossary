"""Core data structures."""

import dataclasses
import enum
import pathlib
import typing

from patchright.async_api import Browser, BrowserContext, Page, Playwright

from slb_glossary.retries import RetryPolicy

if typing.TYPE_CHECKING:
    from slb_glossary.config import Config

__all__ = [
    "Language",
    "RelatedTerm",
    "SearchResult",
    "BrowserSession",
]


class Language(enum.Enum):
    """A language edition of the SLB glossary."""

    ENGLISH = "en"
    SPANISH = "es"


class RelatedTerm(typing.NamedTuple):
    """A single term linked from within another term's definition."""

    term: str
    """Display text of the link - usually the related term's name."""

    url: str
    """Glossary URL the link points to."""


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

    image: str | None = None
    """URL of the term's illustrative image, or `None` if the page has none."""

    image_caption: str | None = None
    """Caption text accompanying `image`, or `None` if the page has none."""

    related: tuple[RelatedTerm, ...] | None = None
    """Terms linked from this definition's "See related terms" list, or
    `None` if the page has none."""

    @property
    def fields(self) -> list[str]:
        """Return a list of the field names in this result."""
        return list(self._fields)

    def asdict(self) -> dict[str, typing.Any]:
        """Return a dictionary representation of this result."""
        return self._asdict()


@dataclasses.dataclass(slots=True, kw_only=True)
class BrowserSession:
    """
    An open, ready-to-query browser session against the SLB glossary.

    Obtain one with `slb_glossary.browser.open_session`, `session`,
    or `BrowserSession.from_config`, then pass it to the search functions in
    `slb_glossary.engine`.

    A session is single-page and not safe to use concurrently from multiple
    coroutines at once; open one session per concurrent task if you need parallelism.
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

    retry: RetryPolicy = dataclasses.field(default_factory=RetryPolicy)
    """Policy used to retry page loads that render before their JavaScript
    search widget has finished populating."""

    settle_timeout: float = 8.0
    """Seconds to wait for the results list to update after a search
    filter changes, since the glossary updates its results via JavaScript
    rather than a full page navigation."""

    poll_interval: float = 0.3
    """Seconds to wait between polls while waiting on `settle_timeout`."""

    @classmethod
    async def from_config(
        cls, config: "Config | str | pathlib.Path", **overrides: typing.Any
    ) -> "BrowserSession":
        """
        Open a `BrowserSession` using a `Config`, or a path to a config file.

        ```python
        session = await BrowserSession.from_config("~/.config/slb-glossary/config.toml")
        ```

        :param config: A `slb_glossary.config.Config`, or a path to a JSON/
            TOML/YAML file `Config.from_file` can load.
        :param overrides: Keyword arguments forwarded to
            `slb_glossary.browser.open_session`, overriding whatever
            `config` specifies (e.g. `headless=False` for a one-off debug run).
        :return: An open `BrowserSession`. Close it with
            `slb_glossary.browser.close_session`, or prefer
            `slb_glossary.browser.session_from_config` for automatic
            cleanup via `async with`.
        """
        from slb_glossary.browser import open_session
        from slb_glossary.config import Config

        resolved_config = config if isinstance(config, Config) else Config.from_file(config)
        kwargs = resolved_config.to_session_kwargs()
        kwargs.update(overrides)
        return await open_session(**kwargs)
