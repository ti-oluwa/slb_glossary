"""Search engine API for the SLB glossary."""

import asyncio
import logging
import math
import time
import typing

from .grammar import resolve_grammatical_label
from .models import SearchResult, SearchSession
from .parsing import (
    get_result_links,
    get_results_header_text,
    get_term_detail_blocks,
    get_term_name,
    get_total_term_count,
)
from .topics import get_topic_match
from .urls import build_pager_query, build_search_url

logger = logging.getLogger(__name__)


__all__ = ["get_terms_on", "iter_results_from_url", "iter_term_urls", "search"]


async def _wait_for_results_to_settle(
    session: SearchSession,
    url: str,
    *,
    previous_links: typing.Sequence[str],
) -> None:
    """
    Load `url` and wait until the results list differs from `previous_links`.

    The glossary is a single-page application: navigating between search
    filters changes only the URL fragment, so a fresh `page.goto` can
    resolve before the site's JavaScript has actually re-rendered the
    results list. This polls the rendered result links until they change,
    or until `session.settle_timeout` elapses.

    :param session: The session to load `url` on.
    :param url: The search URL to load.
    :param previous_links: Result links rendered before this navigation, to
        detect once the page has actually updated. Pass an empty sequence
        on the first navigation of a session.
    """
    await session.page.goto(url, wait_until="domcontentloaded")
    if not previous_links:
        return

    deadline = time.monotonic() + session.settle_timeout
    while time.monotonic() < deadline:
        current_links = await get_result_links(session.page)
        if current_links != list(previous_links):
            return
        await asyncio.sleep(session.poll_interval)
    logger.debug(
        "Results list did not change within %.2fs of loading %s", session.settle_timeout, url
    )


async def iter_term_urls(
    session: SearchSession,
    *,
    query: str | None = None,
    under_topic: str | None = None,
    start_letter: str | None = None,
    limit: int | None = None,
) -> typing.AsyncIterator[str]:
    """
    Lazily yield term detail page URLs matching the given filters.

    Pages through the glossary site's results one tab at a time, only
    loading the next tab once the caller asks for another URL.

    :param session: An open glossary session.
    :param query: A free-text search query.
    :param under_topic: Restrict results to this topic, or several
        comma-separated topics, e.g. `"Well completions,Perforating"`. Need
        not be an exact match; the closest topic(s) in `session.topics` are
        used. See `slb_glossary.topics.get_topic_match`.
    :param start_letter: Restrict results to terms starting with this letter.
    :param limit: Maximum number of URLs to yield. Yields every matching URL
        if `None`.
    :yield: Term detail page URLs, in the order the glossary site returns
        them.
    :raises ValueError: If `limit` is given and is less than 1.
    """
    if limit is not None and limit < 1:
        raise ValueError("limit must be greater than 0")
    if not under_topic and not (query or start_letter):
        return

    topic_match = get_topic_match(session.topics, under_topic) if under_topic else None
    logger.debug(
        "Iterating term URLs: query=%r under_topic=%r start_letter=%r limit=%r",
        query,
        under_topic,
        start_letter,
        limit,
    )

    yielded = 0
    tab = 1
    max_tabs: int | None = None
    previous_links: list[str] = []

    while True:
        pager_query = build_pager_query(tab_number=tab, terms_per_tab=session.terms_per_tab)
        url = build_search_url(
            base_url=session.base_url,
            topic=topic_match,
            query=query,
            start_letter=start_letter,
            pager_query=pager_query,
        )
        await _wait_for_results_to_settle(session, url, previous_links=previous_links)

        header_text = await get_results_header_text(session.page)
        if not header_text:
            logger.debug("No results header on tab %d, stopping", tab)
            return

        total_terms = await get_total_term_count(session.page)
        if total_terms is None:
            logger.debug("Could not read a total term count on tab %d, stopping", tab)
            return
        if max_tabs is None:
            max_tabs = math.ceil(total_terms / session.terms_per_tab)
            logger.debug("Search matched %d terms across %d tabs", total_terms, max_tabs)

        links = await get_result_links(session.page)
        if not links:
            logger.debug("No result links on tab %d, stopping", tab)
            return

        for href in links:
            yield href
            yielded += 1
            if limit is not None and yielded >= limit:
                return

        previous_links = links
        if tab >= max_tabs:
            return
        tab += 1


async def iter_results_from_url(
    session: SearchSession,
    url: str,
    *,
    under_topic: str | None = None,
) -> typing.AsyncIterator[SearchResult]:
    """
    Load a term detail page and lazily yield each definition found on it.

    A term can carry several definitions, one per topic it appears under;
    this yields one `SearchResult` per definition.

    :param session: An open glossary session.
    :param url: A term detail page URL, as yielded by `iter_term_urls`.
    :param under_topic: If a definition's source topic matches this topic
        (or one of several comma-separated topics), that resolved topic
        name is used for its `SearchResult.topic` instead of the topic
        parsed off the page.
    :yield: One `SearchResult` per definition found on the page.
    """
    resolved_topic = get_topic_match(session.topics, under_topic) if under_topic else None

    await session.page.goto(url, wait_until="domcontentloaded")
    term_name = await get_term_name(session.page)
    detail_blocks = await get_term_detail_blocks(session.page)
    if not term_name or not detail_blocks:
        logger.debug("No definitions found at %s", url)
        return

    for block in detail_blocks:
        if len(block) < 2:
            continue

        summary_line = block[0]
        definition = block[2] if len(block) > 2 and block[1] == "" else block[1]

        summary_words = summary_line.split()
        grammatical_label_abbreviation = summary_words[1] if len(summary_words) > 1 else ""
        grammatical_label = resolve_grammatical_label(
            session.language, grammatical_label_abbreviation
        )

        if resolved_topic and resolved_topic.lower() in summary_line.lower():
            topic = resolved_topic
        else:
            topic = summary_line.split(".")[-1].strip().removeprefix("[").removesuffix("]")

        yield SearchResult(
            term=term_name,
            definition=definition,
            grammatical_label=grammatical_label,
            topic=topic,
            url=url,
        )


async def search(
    session: SearchSession,
    query: str,
    *,
    under_topic: str | None = None,
    start_letter: str | None = None,
    limit: int | None = 3,
) -> typing.AsyncIterator[SearchResult]:
    """
    Lazily search the glossary for `query` and yield matching definitions.

    A matched term can carry several definitions (one per topic), so more
    than `limit` results may be yielded; `limit` bounds the number of terms
    looked up, not the number of definitions returned.

    :param session: An open glossary session.
    :param query: The search query.
    :param under_topic: Restrict results to this topic, or several
        comma-separated topics. See `iter_term_urls` for matching rules.
    :param start_letter: Restrict results to terms starting with this letter.
    :param limit: Maximum number of terms to look up. Looks up every
        matching term if `None`. Defaults to `3`.
    :yield: `SearchResult`s for the matched terms, most relevant first.
    """
    logger.info("Searching glossary for %r (limit=%r)", query, limit)
    count = 0
    async for url in iter_term_urls(
        session,
        query=query,
        under_topic=under_topic,
        start_letter=start_letter,
        limit=limit,
    ):
        async for result in iter_results_from_url(session, url, under_topic=under_topic):
            count += 1
            yield result
    logger.info("Search for %r yielded %d result(s)", query, count)


async def get_terms_on(
    session: SearchSession,
    topic: str,
    *,
    limit: int | None = None,
) -> typing.AsyncIterator[SearchResult]:
    """
    Lazily yield the definition of every term filed under `topic`.

    Unlike `search`, this yields at most one `SearchResult` per term: the
    definition filed under `topic` itself, rather than every definition a
    term happens to have.

    :param session: An open glossary session.
    :param topic: The topic to look up terms for. Need not be an exact
        match; see `iter_term_urls` for matching rules.
    :param limit: Maximum number of terms to yield. Yields every term filed
        under `topic` if `None`.
    :yield: One `SearchResult` per term filed under `topic`.
    """
    logger.info("Fetching terms under topic %r (limit=%r)", topic, limit)
    count = 0
    async for url in iter_term_urls(session, under_topic=topic, limit=limit):
        async for result in iter_results_from_url(session, url, under_topic=topic):
            count += 1
            yield result
            break
    logger.info("Fetched %d term(s) under topic %r", count, topic)
