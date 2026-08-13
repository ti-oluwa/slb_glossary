"""Search engine API for the SLB glossary."""

import asyncio
import logging
import math
import time
import typing

from slb_glossary.grammar import resolve_grammatical_label
from slb_glossary.models import RelatedTerm, SearchResult, SearchSession
from slb_glossary.parsers import (
    get_result_links,
    get_results_header_text,
    get_term_detail_blocks,
    get_term_image,
    get_term_name,
    get_total_term_count,
)
from slb_glossary.topics import get_topic_match
from slb_glossary.urls import build_pager_query, build_search_url

logger = logging.getLogger(__name__)


__all__ = ["get_terms_on", "iter_results_from_url", "iter_term_urls", "search"]


def _find_related_links(
    paragraphs: typing.Sequence[typing.Any],
) -> tuple[RelatedTerm, ...]:
    """
    Return the related-term links from a definition block's paragraphs.

    Looks for the paragraph that introduces a "See related terms:" (or
    plain "See:") list and returns the terms it links to; most definition
    blocks have at most one such paragraph.

    :param paragraphs: A definition block's `TermParagraph`s, as returned
        by `slb_glossary.parsers.get_term_detail_blocks`.
    :return: The related terms found, in the order they're linked. Empty
        if no paragraph in the block links to any related terms.
    """
    for paragraph in paragraphs:
        text_lower = paragraph.text.lower()
        if paragraph.links and ("related term" in text_lower or "see:" in text_lower):
            return paragraph.links
    # Fall back to any paragraph with links at all, in case the site's
    # wording of the "related terms" lead-in ever changes.
    for paragraph in paragraphs:
        if paragraph.links:
            return paragraph.links
    return ()


async def _wait_for_settle(
    session: SearchSession,
    url: str,
    *,
    previous_links: typing.Sequence[str],
    previous_header: str,
) -> tuple[list[str], str]:
    """
    Load `url` and wait until the results panel differs from the given baseline.

    The glossary is a single-page application: navigating between search
    filters changes only the URL fragment, so a fresh `page.goto` can
    resolve before the site's JavaScript has actually re-rendered the
    results panel. This polls the rendered result links and results header
    until at least one of them differs from the caller's baseline, or
    until `session.settle_timeout` elapses - whichever comes first.

    :param session: The session to load `url` on.
    :param url: The search URL to load.
    :param previous_links: Result links rendered on the page *before* this
        navigation. Always pass the page's actual current state here, even
        for the first search of a session - the glossary auto-runs an
        unfiltered query as soon as the search screen loads, so there is
        always something real to diff against. An empty sequence here
        means "nothing rendered yet", which skips the wait entirely and
        risks reading a stale, pre-filter panel.
    :param previous_header: Results header text rendered before this
        navigation - a second, independent signal that the panel actually
        updated, so a coincidental match on `previous_links` alone (e.g.
        the same top result happens to rank first for two different
        queries) doesn't return before the panel has really changed.
    :return: The `(links, header_text)` pair read once the panel changed,
        or the last values read if `session.settle_timeout` elapsed first
        without any observed change.
    """
    await session.page.goto(url, wait_until="domcontentloaded")

    deadline = time.monotonic() + session.settle_timeout
    previous_links = list(previous_links)
    while True:
        current_links = await get_result_links(session.page)
        current_header = await get_results_header_text(session.page)
        if current_links != previous_links or current_header != previous_header:
            return current_links, current_header
        if time.monotonic() >= deadline:
            logger.debug(
                "Results panel did not change within %.2fs of loading %s",
                session.settle_timeout,
                url,
            )
            return current_links, current_header
        await asyncio.sleep(session.poll_interval)


async def iter_term_urls(
    session: SearchSession,
    *,
    query: str | None = None,
    topic: str | None = None,
    start_letter: str | None = None,
    limit: int | None = None,
) -> typing.AsyncIterator[str]:
    """
    Yield term detail page URLs matching the given filters.

    Pages through the glossary site's results one tab at a time, only
    loading the next tab once the caller asks for another URL.

    :param session: An open glossary session.
    :param query: A free-text search query.
    :param topic: Restrict results to this topic, or several
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
    if not topic and not (query or start_letter):
        return

    topic_match = get_topic_match(session.topics, topic=topic) if topic else None
    logger.debug(
        "Iterating term URLs: query=%r topic=%r start_letter=%r limit=%r",
        query,
        topic,
        start_letter,
        limit,
    )

    yielded = 0
    tab = 1
    max_tabs: int | None = None
    # The glossary auto-runs an unfiltered query as soon as the search
    # screen loads (that's what populates the facet panel), so the page
    # always has *some* results-panel state to diff a filtered search
    # against, so we read it now rather than starting from an empty baseline.
    # An empty baseline previously meant "nothing to wait for", so the
    # very first search of every session read that pre-filter panel
    # before the site's JS had applied the query. Which will look exactly
    # like every search returning the same (default) results.
    previous_links = await get_result_links(session.page)
    previous_header = await get_results_header_text(session.page)

    while True:
        pager_query = build_pager_query(tab_number=tab, terms_per_tab=session.terms_per_tab)
        url = build_search_url(
            base_url=session.base_url,
            topic=topic_match,
            query=query,
            start_letter=start_letter,
            pager_query=pager_query,
        )
        links, header_text = await _wait_for_settle(
            session,
            url=url,
            previous_links=previous_links,
            previous_header=previous_header,
        )

        if not links:
            logger.debug("No result links on tab %d, stopping", tab)
            return
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

        for href in links:
            yield href
            yielded += 1
            if limit is not None and yielded >= limit:
                return

        previous_links = links
        previous_header = header_text
        if tab >= max_tabs:
            return
        tab += 1


async def iter_results_from_url(
    session: SearchSession,
    url: str,
    *,
    topic: str | None = None,
) -> typing.AsyncIterator[SearchResult]:
    """
    Load a term detail page and lazily yield each definition found on it.

    A term can carry several definitions, one per topic it appears under;
    this yields one `SearchResult` per definition.

    :param session: An open glossary session.
    :param url: A term detail page URL, as yielded by `iter_term_urls`.
    :param topic: If a definition's source topic matches this topic
        (or one of several comma-separated topics), that resolved topic
        name is used for its `SearchResult.topic` instead of the topic
        parsed off the page.
    :yield: One `SearchResult` per definition found on the page. Each
        result's `image` and `related` fields are `None`/empty when the
        page has no illustrative image or no related-term links.
    """
    resolved_topic = get_topic_match(session.topics, topic) if topic else None

    await session.page.goto(url, wait_until="domcontentloaded")
    term_name = await get_term_name(session.page)
    detail_blocks = await get_term_detail_blocks(session.page)
    if not term_name or not detail_blocks:
        logger.debug("No definitions found at %s", url)
        return

    # A term page carries at most one illustrative image, shared across
    # every definition block on it (not one image per topic/definition).
    term_image = await get_term_image(session.page)
    image_url, image_caption = (
        (term_image.url, term_image.caption) if term_image is not None else (None, None)
    )

    for block in detail_blocks:
        if len(block) < 2:
            continue

        summary_line = block[0].text
        definition = block[2].text if len(block) > 2 and block[1].text == "" else block[1].text
        related = _find_related_links(block) or None

        summary_words = summary_line.split()
        label_abbreviation = summary_words[1] if len(summary_words) > 1 else ""
        grammatical_label = resolve_grammatical_label(session.language, label_abbreviation)

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
            image=image_url,
            image_caption=image_caption,
            related=related,
        )


async def search(
    session: SearchSession,
    query: str,
    *,
    topic: str | None = None,
    start_letter: str | None = None,
    limit: int | None = 3,
) -> typing.AsyncIterator[SearchResult]:
    """
    Search the glossary for `query` and yield matching definitions.

    A matched term can carry several definitions (one per topic), so more
    than `limit` results may be yielded; `limit` bounds the number of terms
    looked up, not the number of definitions returned.

    :param session: An open glossary session.
    :param query: The search query.
    :param topic: Restrict results to this topic, or several
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
        topic=topic,
        start_letter=start_letter,
        limit=limit,
    ):
        async for result in iter_results_from_url(session, url, topic=topic):
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
    Yield the definition of every term filed under `topic`.

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
    async for url in iter_term_urls(session, topic=topic, limit=limit):
        async for result in iter_results_from_url(session, url, topic=topic):
            count += 1
            yield result
            break
    logger.info("Fetched %d term(s) under topic %r", count, topic)
