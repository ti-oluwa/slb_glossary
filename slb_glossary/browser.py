"""API for launching and tearing down live browser sessions used to search the glossary."""

import contextlib
import enum
import logging
import pathlib
import typing
from urllib.parse import urlsplit

from patchright.async_api import Browser, Playwright, Route, async_playwright
from playwright_stealth import Stealth

from slb_glossary.config import Config
from slb_glossary.errors import BrowserError, NetworkError
from slb_glossary.models import BrowserSession, Language
from slb_glossary.retries import DEFAULT_RETRY_POLICY, RetryPolicy
from slb_glossary.topics import fetch_topics
from slb_glossary.urls import get_glossary_base_url

logger = logging.getLogger(__name__)


__all__ = [
    "close_session",
    "session",
    "session_from_config",
    "open_session",
    "open_session_from_config",
    "ResourceType",
    "BrowserType",
    "browser_session",
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


RESOURCE_TYPE_NAME_MAP: dict[ResourceType, str] = {
    ResourceType.DOCUMENT: "document",
    ResourceType.STYLESHEET: "stylesheet",
    ResourceType.IMAGE: "image",
    ResourceType.MEDIA: "media",
    ResourceType.FONT: "font",
    ResourceType.SCRIPT: "script",
    ResourceType.TEXTTRACK: "texttrack",
    ResourceType.XHR: "xhr",
    ResourceType.FETCH: "fetch",
    ResourceType.EVENTSOURCE: "eventsource",
    ResourceType.WEBSOCKET: "websocket",
    ResourceType.MANIFEST: "manifest",
    ResourceType.OTHER: "other",
}


DEFAULT_BLOCKED_RESOURCE_TYPES = (
    ResourceType.IMAGE | ResourceType.MEDIA | ResourceType.FONT | ResourceType.STYLESHEET
)
"""Resource types blocked when `block=True` (the default)."""

CHROMIUM_LAUNCH_ARGS = [
    "--disable-extensions",
    "--disable-background-networking",
    "--disable-sync",
    "--disable-translate",
    "--no-first-run",
    # Avoid unnecessary UI/background work
    "--disable-default-apps",
    "--disable-component-update",
    "--disable-features=MediaRouter",
    # Reduce disk/cache overhead for ephemeral browser sessions
    "--disable-backgrounding-occluded-windows",
    "--no-sandbox",
    "--disable-dev-shm-usage",
    # Prevent Chromium from deprioritizing background tabs.
    # Especially for concurency > 1 which spins up multiple
    # tabs/pages in one session.
    "--disable-renderer-backgrounding",
]
"""Extra launch flags applied when `browser_type` is `BrowserType.CHROMIUM`."""


BLOCKED_HOSTS = frozenset(
    {
        "google-analytics.com",
        "googletagmanager.com",
        "doubleclick.net",
        "facebook.com",
        "facebook.net",
        "connect.facebook.net",
        "hotjar.com",
        "segment.io",
        "segment.com",
        "clarity.ms",
        "cookiepro.com",
        "onetrust.com",
        "linkedin.com",
        "googlesyndication.com",
        "googleadservices.com",
        "sharethis.com",
        "csi.slb.com",
        "segments.company-target.com",
        "kaltura.com",
        "peer5.com",
        "bing.com",
        "addthis.com",
        "perk0mean.com",
        "brightcove.net",
        "botframework.com",
        "google.com",
        "powerplatform.com",
        "crwdcntrl.net",
        "arcgis.com",
    }
)


def should_block_host(hostname: str, blocked_hosts: frozenset[str]) -> bool:
    hostname = hostname.lower()
    return hostname in blocked_hosts or any(
        hostname.endswith("." + host) for host in blocked_hosts
    )


def get_resource_names(resource_types: ResourceType) -> list[str]:
    return [
        name
        for kind, name in RESOURCE_TYPE_NAME_MAP.items()
        if kind != ResourceType.ALL and kind & resource_types
    ]


def _resolve_blocked_resources(
    block: bool | typing.Iterable[str] | ResourceType,
) -> frozenset[str]:
    """Turn the `block` argument into a concrete set of resource types."""
    if block is True:
        return frozenset(get_resource_names(DEFAULT_BLOCKED_RESOURCE_TYPES))
    if block is False:
        return frozenset()
    if isinstance(block, ResourceType):
        return frozenset(get_resource_names(block))
    return frozenset(
        RESOURCE_TYPE_NAME_MAP.get(ResourceType[name.upper()], name.lower())
        if isinstance(name, str)
        else str(name).lower()
        for name in block
    )


def _build_blocker(
    blocked_resources: frozenset[str], blocked_hosts: frozenset[str] | None = None
) -> typing.Callable[[Route], typing.Awaitable[None]]:
    """Build a Playwright route handler that aborts blocked resource types or hosts."""

    async def _handle_route(route: Route) -> None:
        request = route.request
        if request.resource_type in blocked_resources:
            await route.abort()
        elif (
            blocked_hosts
            and (hostname := urlsplit(request.url).hostname)
            and should_block_host(hostname, blocked_hosts)
        ):
            await route.abort()
        else:
            await route.continue_()

    return _handle_route


async def _launch_browser(
    playwright: Playwright,
    browser_type: BrowserType | str,
    *,
    headless: bool,
    executable_path: str | None,
    proxy: dict[str, str] | None,
    launch_kwargs: dict[str, typing.Any] | None = None,
) -> Browser:
    """
    Launch `browser_type` off `playwright`, however it happens to be named.

    :param playwright: The Playwright instance to launch the browser from.
    :param browser_type: The browser family to launch.
    :param headless: Whether to launch the browser headless.
    :param executable_path: Path to a specific browser build to launch.
    :param proxy: Playwright proxy settings, e.g. `{"server": "http://myproxy:3128"}`.
    :param launch_kwargs: Additional keyword arguments to pass
        to Playwright's `browser.launch()` call. Values passed here are merged
        with the library defaults, and Chromium gets a default `args` list if
        none is provided.
    :return: The launched browser.
    """
    browser_type = BrowserType(browser_type) if isinstance(browser_type, str) else browser_type
    launcher = getattr(playwright, browser_type.value, None)
    if launcher is None:
        raise BrowserError(
            f"The installed Playwright driver has no {browser_type.value!r} browser type. "
            f"Supported types: {', '.join(BrowserType.__members__)}."
        )

    launch_kwargs = dict(launch_kwargs or {})
    launch_kwargs["headless"] = headless
    if proxy is not None:
        launch_kwargs["proxy"] = proxy
    if executable_path is not None:
        launch_kwargs["executable_path"] = executable_path
    if browser_type == BrowserType.CHROMIUM:
        launch_kwargs.setdefault(
            "args",
            # Disable GPU if we are running headless
            CHROMIUM_LAUNCH_ARGS if not headless else [*CHROMIUM_LAUNCH_ARGS, "--disable-gpu"],
        )

    logger.debug("Launching %s (headless=%s) %s", browser_type, headless, launch_kwargs)
    return await launcher.launch(**launch_kwargs)


async def open_session(
    *,
    language: Language = Language.ENGLISH,
    browser_type: BrowserType | str = BrowserType.CHROMIUM,
    headless: bool = True,
    block: bool | typing.Iterable[str] | ResourceType = True,
    timeout: float = 60_000,
    terms_per_tab: int = 12,
    retry: RetryPolicy = DEFAULT_RETRY_POLICY,
    settle_timeout: float = 8.0,
    poll_interval: float = 0.3,
    executable_path: str | None = None,
    proxy: dict[str, str] | None = None,
    viewport: dict[str, int] | None = None,
    launch_kwargs: dict[str, typing.Any] | None = None,
    context_kwargs: dict[str, typing.Any] | None = None,
    use_stealth: bool = True,
) -> BrowserSession:
    """
    Launch a (stealth) browser session and load the glossary's topics and size.

    :param language: Glossary language edition to search.
    :param browser_type: Playwright browser family to launch: `"chromium"`,
        `"firefox"` or `"webkit"`. Patchright's stealth patches are tuned for
        Chromium; other families run through the same stealth init script but
        haven't been evaluated against the glossary's bot detection.
    :param headless: Run the browser without a visible window. Set this to
        `False` for debugging.
    :param block: Which request resource types to drop for speed. `True`
        (the default) blocks `DEFAULT_BLOCKED_RESOURCE_TYPES` (images, media,
        fonts). `False` blocks nothing. Or pass a `ResourceType` to block. The
        glossary is a JavaScript application so scripts are always loaded
        regardless of this setting.
    :param timeout: Milliseconds to wait for page loads and element lookups
        before raising a timeout error.
    :param terms_per_tab: Number of results the glossary site returns per
        results page. Only change this if the site's pagination changes.
    :param retry: Policy for retrying the initial topic-list load if the
        glossary's search widget briefly renders empty. Also stored on the
        returned session for search functions to reuse.
    :param settle_timeout: Seconds search functions should wait for the
        results list to update after changing a search filter.
    :param poll_interval: Seconds search functions should wait between polls
        while waiting on `settle_timeout`.
    :param executable_path: Path to a specific browser build to launch.
        Defaults to the build patchright installs for `browser_type`.
    :param proxy: Playwright proxy settings, e.g.
        `{"server": "http://myproxy:3128"}`.
    :param viewport: A Playwright viewport dict such as
        `{"width": 1920, "height": 1080}`. Defaults to `None` so the
        session is created without an explicit viewport and the browser uses
        the available full-screen size.
    :param launch_kwargs: Additional keyword arguments to pass to
        Playwright's `browser.launch()` call. Values passed here are merged
        with the library defaults, and Chromium gets a default `args` list if
        none is provided.
    :param context_kwargs: Additional keyword arguments to pass to `browser.new_context()`.
        Values passed here are merged with the library defaults.
    :param use_stealth: Whether to apply Playwright stealth patches to the
        browser context. Defaults to `True`.
    :return: An open `BrowserSession` ready to pass to `slb_glossary.search`
        functions. Close it with `close_session` when done, or use
        `session` instead of calling this function directly.
    :raises NetworkError: If the glossary site could not be reached.
    :raises BrowserError: If the browser failed to launch for any other
        reason, including an unsupported `browser_type`.
    """
    if browser_type not in BrowserType:
        raise BrowserError(
            f"Unsupported `browser_type` {browser_type!r}. "
            f"Supported types: {', '.join(BrowserType.__members__)}."
        )

    logger.info("Opening a %r glossary search session over %s", language.value, browser_type)
    playwright = await async_playwright().start()
    try:
        browser = await _launch_browser(
            playwright,
            browser_type,
            headless=headless,
            executable_path=executable_path,
            proxy=proxy,
            launch_kwargs=launch_kwargs,
        )
        context_kwargs = dict(context_kwargs or {})
        if viewport is not None:
            context_kwargs["viewport"] = viewport
        context = await browser.new_context(**context_kwargs)

        if use_stealth:
            await Stealth().apply_stealth_async(context)  # type: ignore[arg-type]

        page = await context.new_page()
        page.set_default_timeout(timeout)
        page.set_default_navigation_timeout(timeout)

        blocked_resources = _resolve_blocked_resources(block)
        if blocked_resources:
            await context.route(
                "**/*", _build_blocker(blocked_resources, blocked_hosts=BLOCKED_HOSTS)
            )
            logger.debug("Blocking resource types: %s", ", ".join(sorted(blocked_resources)))

        base_url = get_glossary_base_url(language)
        try:
            topics, size = await fetch_topics(
                page,
                base_url=base_url,
                settle_delay=settle_timeout,
                retry=retry,
            )
        except Exception as exc:
            raise NetworkError(f"Could not reach the glossary at {base_url}") from exc

        session = BrowserSession(
            playwright=playwright,
            browser=browser,
            context=context,
            page=page,
            language=language,
            base_url=base_url,
            topics=topics,
            size=size,
            browser_type=browser_type,
            terms_per_tab=terms_per_tab,
            blocked_resource_types=blocked_resources,
            retry=retry,
            settle_timeout=settle_timeout,
            poll_interval=poll_interval,
        )
        logger.info("Glossary search session ready: %d topics, %d terms", len(topics), size)
        return session
    except NetworkError:
        logger.exception("Could not reach the glossary at startup")
        await playwright.stop()
        raise
    except Exception as exc:
        logger.exception("Failed to launch the glossary browser session")
        await playwright.stop()
        raise BrowserError("Failed to launch the glossary browser session") from exc


async def open_session_from_config(
    config: Config | str | pathlib.Path, **overrides: typing.Any
) -> BrowserSession:
    """
    Open a `BrowserSession` using a `Config`, or a path to a config file.

    Equivalent to `BrowserSession.from_config`; provided here as well so
    `slb_glossary.browser` stays a complete, self-contained entry point for
    opening sessions without needing an import from `slb_glossary.models`.

    :param config: A `slb_glossary.config.Config`, or a path to a JSON/
        TOML/YAML file `Config.from_file` can load.
    :param overrides: Keyword arguments forwarded to `open_session`,
        overriding whatever `config` specifies.
    :return: An open `BrowserSession`. Close it with `close_session`, or
        prefer `session_from_config` for automatic cleanup.
    """
    resolved_config = config if isinstance(config, Config) else Config.from_file(config)
    kwargs = resolved_config.to_session_kwargs()
    kwargs.update(overrides)
    return await open_session(**kwargs)


async def close_session(session: BrowserSession) -> None:
    """
    Close every resource opened for `session`.

    Safe to call more than once; later calls are no-ops.

    :param session: The session to close.
    """
    logger.info("Closing glossary search session")
    with contextlib.suppress(Exception):
        await session.context.close()
    with contextlib.suppress(Exception):
        await session.browser.close()
    with contextlib.suppress(Exception):
        await session.playwright.stop()


@contextlib.asynccontextmanager
async def session(
    *,
    language: Language = Language.ENGLISH,
    browser_type: BrowserType | str = BrowserType.CHROMIUM,
    headless: bool = True,
    block: bool | typing.Iterable[str] | ResourceType = True,
    timeout: float = 60_000,
    terms_per_tab: int = 12,
    retry: RetryPolicy = DEFAULT_RETRY_POLICY,
    settle_timeout: float = 8.0,
    poll_interval: float = 0.3,
    executable_path: str | None = None,
    proxy: dict[str, str] | None = None,
    viewport: dict[str, int] | None = None,
    launch_kwargs: dict[str, typing.Any] | None = None,
    context_kwargs: dict[str, typing.Any] | None = None,
    use_stealth: bool = True,
) -> typing.AsyncIterator[BrowserSession]:
    """
    Open a `BrowserSession` for the duration of an `async with` block.

    ```python
    async with session(...) as session:
        async for result in search(session, "porosity"):
            print(result)
    ```

    :param language: Glossary language edition to search.
    :param browser_type: Playwright browser family to launch: `"chromium"`,
        `"firefox"` or `"webkit"`.
    :param headless: Run the browser without a visible window. Set this to
        `False` for debugging.
    :param block: Which request resource types to drop for speed. `True`
        blocks the default resource types, `False` blocks nothing,
        or pass a `ResourceType` to block.
    :param timeout: Milliseconds to wait for page loads and element lookups.
    :param terms_per_tab: Number of results returned per glossary results page.
    :param retry: Policy used when retrying the initial topic-list load.
    :param settle_timeout: Seconds to wait for the results list to settle.
    :param poll_interval: Poll interval used while waiting for results updates.
    :param executable_path: Path to a specific browser build to launch.
    :param proxy: Playwright proxy settings, e.g.
        `{"server": "http://myproxy:3128"}`.
    :param viewport: A Playwright viewport dict such as
        `{"width": 1920, "height": 1080}`. Defaults to `None` so the
        session is created without an explicit viewport.
    :param launch_kwargs: Additional keyword arguments to pass to
        Playwright's `browser.launch()` call. Values passed here are merged
        with the library defaults, and Chromium gets a default `args` list if
        none is provided.
    :param context_kwargs: Additional keyword arguments to pass to `browser.new_context()`.
        Values passed here are merged with the library defaults.
    :param use_stealth: Whether to apply Playwright stealth patches to the
        browser context. Defaults to `True`.

    Arguments are the same as `open_session`. The session is always
    closed on exit, including when the block raises.
    """
    session = await open_session(
        language=language,
        browser_type=browser_type,
        headless=headless,
        block=block,
        timeout=timeout,
        terms_per_tab=terms_per_tab,
        retry=retry,
        settle_timeout=settle_timeout,
        poll_interval=poll_interval,
        executable_path=executable_path,
        proxy=proxy,
        viewport=viewport,
        launch_kwargs=launch_kwargs,
        context_kwargs=context_kwargs,
        use_stealth=use_stealth,
    )
    try:
        yield session
    finally:
        await close_session(session)


browser_session = session  # Alias for `session` to match the naming in `slb_glossary.models.BrowserSession.from_config`.


@contextlib.asynccontextmanager
async def session_from_config(
    config: Config | str | pathlib.Path, **overrides: typing.Any
) -> typing.AsyncIterator[BrowserSession]:
    """
    Open a `BrowserSession` from a `Config` (or config file path) for an `async with` block.

    ```python
    async with session_from_config("config.toml") as session:
        async for result in search(session, "porosity"):
            print(result)
    ```

    :param config: A `slb_glossary.config.Config`, or a path to a JSON/
        TOML/YAML file `Config.from_file` can load.
    :param overrides: Keyword arguments forwarded to `open_session`,
        overriding whatever `config` specifies.

    The session is always closed on exit, including when the block raises.
    """
    session = await open_session_from_config(config, **overrides)
    try:
        yield session
    finally:
        await close_session(session)
