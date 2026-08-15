"""API for fetching and matching glossary topics (disciplines)."""

import asyncio
import logging

from patchright.async_api import Page

from slb_glossary.live.browser import BrowserSession
from slb_glossary.live.parsers import (
    FACET_EXPAND_SELECTOR,
    FACET_HEADER_SELECTOR,
    get_element_text,
    get_facet_topics,
    get_glossary_size,
)
from slb_glossary.retries import DEFAULT_RETRY_POLICY, RetryPolicy
from slb_glossary.retries import retry as retry_func

logger = logging.getLogger(__name__)


__all__ = ["fetch_topics", "refresh_topics"]


async def fetch_topics(
    page: Page,
    *,
    base_url: str,
    settle_delay: float = 0.8,
    retry: RetryPolicy = DEFAULT_RETRY_POLICY,
) -> tuple[dict[str, int], int]:
    """
    Load `base_url` and read the glossary's topic list and total term count.

    :param page: The page to load the glossary search screen on.
    :param base_url: Base search URL for the target glossary language, as
        returned by `slb_glossary.urls.get_glossary_base_url`.
    :param settle_delay: Seconds to wait after the facet panel first renders
        and after expanding it, giving the site's search widget time to
        finish populating both.
    :param retry: Policy for retrying the page load if the facet panel
        renders empty.
    :return: A `(topics, size)` pair: a mapping of topic name to term count,
        and the total number of terms in the glossary.
    """
    logger.info("Loading glossary topics from %s", base_url)

    async def _load_facet_header() -> str:
        await page.goto(base_url, wait_until="domcontentloaded")
        return await get_element_text(page, FACET_HEADER_SELECTOR)

    header_text = await retry_func(_load_facet_header, policy=retry, until=bool)
    if not header_text:
        logger.warning("Topics did not load after %d attempts", retry.attempts)
        return {}, 0

    await asyncio.sleep(settle_delay)

    expand_button = page.locator(FACET_EXPAND_SELECTOR).first
    if await expand_button.count():
        try:
            await expand_button.scroll_into_view_if_needed(timeout=5_000)
            await expand_button.click(timeout=5_000)
            await asyncio.sleep(settle_delay)
        except Exception:
            logger.debug("Could not expand the full topic list", exc_info=True)

    topics = await get_facet_topics(page)
    size = await get_glossary_size(page)
    logger.info("Loaded %d topics; glossary has %d terms", len(topics), size)
    return topics, size


async def refresh_topics(session: BrowserSession) -> BrowserSession:
    """
    Reload `session.topics` and `session.size` from the glossary site.

    :param session: The session to refresh.
    :return: `session`, with `topics` and `size` updated in place.
    """
    topics, size = await fetch_topics(
        session.page,
        base_url=session.base_url,
        retry=session.retry,
        settle_delay=session.settle_timeout,
    )
    session.topics = topics
    session.size = size
    return session
