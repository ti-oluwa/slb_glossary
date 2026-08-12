"""API for launching and tearing down browser sessions used to search the glossary."""

import contextlib
import logging
import typing

from patchright.async_api import Route, async_playwright
from playwright_stealth import Stealth

from .backoff import DEFAULT_BACKOFF_POLICY, BackoffPolicy
from .exceptions import BrowserError, NetworkError
from .models import Language, SearchSession
from .topics import fetch_topics
from .urls import get_glossary_base_url

logger = logging.getLogger(__name__)


__all__ = ["close_session", "search_session", "open_session"]


SUPPORTED_BROWSER_TYPES = ("chromium", "firefox", "webkit")
"""Playwright browser families `open_session` can launch."""

DEFAULT_BLOCKED_RESOURCE_TYPES = frozenset({"image", "media", "font", "stylesheet"})
"""Resource types blocked when `block=True` (the default)."""

CHROMIUM_LAUNCH_ARGS = [
    "--disable-extensions",
    "--disable-background-networking",
    "--disable-sync",
    "--disable-translate",
    "--no-first-run",
]
"""Extra launch flags applied when `browser_type` is `"chromium"`."""


def _resolve_blocked_resource_types(
    block: bool | typing.Iterable[str],
) -> frozenset[str]:
    """Turn the `block` argument into a concrete set of resource types."""
    if block is True:
        return DEFAULT_BLOCKED_RESOURCE_TYPES
    if block is False:
        return frozenset()
    return frozenset(block)


def _build_resource_blocker(
    blocked_resource_types: frozenset[str],
) -> typing.Callable[[Route], typing.Awaitable[None]]:
    """Build a Playwright route handler that aborts blocked resource types."""

    async def _handle_route(route: Route) -> None:
        if route.request.resource_type in blocked_resource_types:
            await route.abort()
        else:
            await route.continue_()

    return _handle_route


async def _launch_browser(
    playwright: typing.Any,
    browser_type: str,
    *,
    headless: bool,
    executable_path: str | None,
    proxy: dict[str, str] | None,
) -> typing.Any:
    """
    Launch `browser_type` off `playwright`, however it happens to be named.

    Uses `getattr` rather than a fixed `playwright.chromium` reference so any
    browser family the installed Playwright/patchright driver exposes -
    including ones added in a later release - can be launched without a code
    change here.
    """
    launcher = getattr(playwright, browser_type, None)
    if launcher is None:
        raise BrowserError(
            f"The installed Playwright driver has no {browser_type!r} browser type. "
            f"Supported types: {', '.join(SUPPORTED_BROWSER_TYPES)}."
        )

    launch_kwargs: dict[str, typing.Any] = {"headless": headless, "proxy": proxy}
    if executable_path:
        launch_kwargs["executable_path"] = executable_path
    if browser_type == "chromium":
        launch_kwargs["args"] = CHROMIUM_LAUNCH_ARGS

    logger.debug("Launching %s (headless=%s)", browser_type, headless)
    return await launcher.launch(**launch_kwargs)


async def open_session(
    *,
    language: Language = Language.ENGLISH,
    browser_type: str = "chromium",
    headless: bool = True,
    block: bool | typing.Iterable[str] = True,
    timeout: float = 30_000,
    terms_per_tab: int = 12,
    backoff: BackoffPolicy = DEFAULT_BACKOFF_POLICY,
    settle_timeout: float = 8.0,
    poll_interval: float = 0.3,
    executable_path: str | None = None,
    proxy: dict[str, str] | None = None,
    viewport: dict[str, int] | None = None,
    use_stealth: bool = True,
) -> SearchSession:
    """
    Launch a stealth browser session and load the glossary's topics and size.

    :param language: Glossary language edition to search.
    :param browser_type: Playwright browser family to launch: `"chromium"`,
        `"firefox"` or `"webkit"`. Patchright's stealth patches are tuned for
        Chromium; other families run through the same stealth init script but
        haven't been evaluated against the glossary's bot detection.
    :param headless: Run the browser without a visible window. Set this to
        `False` for debugging.
    :param block: Which request resource types to drop for speed. `True`
        (the default) blocks `DEFAULT_BLOCKED_RESOURCE_TYPES` (images, media,
        fonts). `False` blocks nothing. Or pass your own iterable of
        Playwright resource type names, e.g. `{"image", "stylesheet"}`. The
        glossary is a JavaScript application so scripts are always loaded
        regardless of this setting.
    :param timeout: Milliseconds to wait for page loads and element lookups
        before raising a timeout error.
    :param terms_per_tab: Number of results the glossary site returns per
        results page. Only change this if the site's pagination changes.
    :param backoff: Policy for retrying the initial topic-list load if the
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
    :param use_stealth: Whether to apply Playwright stealth patches to the
        browser context. Defaults to `True`.
    :return: An open `SearchSession` ready to pass to `slb_glossary.search`
        functions. Close it with `close_session` when done, or use
        `search_session` instead of calling this function directly.
    :raises NetworkError: If the glossary site could not be reached.
    :raises BrowserError: If the browser failed to launch for any other
        reason, including an unsupported `browser_type`.
    """
    if browser_type not in SUPPORTED_BROWSER_TYPES:
        raise BrowserError(
            f"Unsupported `browser_type` {browser_type!r}. "
            f"Supported types: {', '.join(SUPPORTED_BROWSER_TYPES)}."
        )

    logger.info("Opening a '%s' glossary search session over %s", language.value, browser_type)
    playwright = await async_playwright().start()
    try:
        browser = await _launch_browser(
            playwright,
            browser_type,
            headless=headless,
            executable_path=executable_path,
            proxy=proxy,
        )
        context = await browser.new_context(viewport=viewport)
        if use_stealth:
            await Stealth().apply_stealth_async(context)

        page = await context.new_page()
        page.set_default_timeout(timeout)
        page.set_default_navigation_timeout(timeout)

        blocked_resource_types = _resolve_blocked_resource_types(block)
        if blocked_resource_types:
            await context.route("**/*", _build_resource_blocker(blocked_resource_types))
            logger.debug("Blocking resource types: %s", ", ".join(sorted(blocked_resource_types)))

        base_url = get_glossary_base_url(language)
        try:
            topics, size = await fetch_topics(
                page,
                base_url=base_url,
                settle_delay=settle_timeout,
                backoff=backoff,
            )
        except Exception as exc:
            raise NetworkError(f"Could not reach the glossary at {base_url}") from exc

        session = SearchSession(
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
            blocked_resource_types=blocked_resource_types,
            backoff=backoff,
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


async def close_session(session: SearchSession) -> None:
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
async def search_session(
    *,
    language: Language = Language.ENGLISH,
    browser_type: str = "chromium",
    headless: bool = True,
    block: bool | typing.Iterable[str] = True,
    timeout: float = 30_000,
    terms_per_tab: int = 12,
    backoff: BackoffPolicy = DEFAULT_BACKOFF_POLICY,
    settle_timeout: float = 8.0,
    poll_interval: float = 0.3,
    executable_path: str | None = None,
    proxy: dict[str, str] | None = None,
    viewport: dict[str, int] | None = None,
    use_stealth: bool = True,
) -> typing.AsyncIterator[SearchSession]:
    """
    Open a `SearchSession` for the duration of an `async with` block.

    ```python
    async with search_session() as session:
        async for result in search(session, "porosity"):
            print(result)
    ```

    :param language: Glossary language edition to search.
    :param browser_type: Playwright browser family to launch: `"chromium"`,
        `"firefox"` or `"webkit"`.
    :param headless: Run the browser without a visible window. Set this to
        `False` for debugging.
    :param block: Which request resource types to drop for speed. `True`
        blocks the default resource types, `False` blocks nothing, or pass
        an iterable of resource type strings.
    :param timeout: Milliseconds to wait for page loads and element lookups.
    :param terms_per_tab: Number of results returned per glossary results page.
    :param backoff: Policy used when retrying the initial topic-list load.
    :param settle_timeout: Seconds to wait for the results list to settle.
    :param poll_interval: Poll interval used while waiting for results updates.
    :param executable_path: Path to a specific browser build to launch.
    :param proxy: Playwright proxy settings, e.g.
        `{"server": "http://myproxy:3128"}`.
    :param viewport: A Playwright viewport dict such as
        `{"width": 1920, "height": 1080}`. Defaults to `None` so the
        session is created without an explicit viewport.
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
        backoff=backoff,
        settle_timeout=settle_timeout,
        poll_interval=poll_interval,
        executable_path=executable_path,
        proxy=proxy,
        viewport=viewport,
        use_stealth=use_stealth,
    )
    try:
        yield session
    finally:
        await close_session(session)
