"""
Low-level DOM extraction for glossary pages.

Every CSS selector the scraper depends on lives in this module, so a change
to the glossary site's markup only ever needs to be fixed here.
"""

import logging

from patchright.async_api import Page

from slb_glossary.utils import parse_int

logger = logging.getLogger(__name__)


__all__ = [
    "FACET_EXPAND_SELECTOR",
    "FACET_HEADER_SELECTOR",
    "RESULTS_HEADER_SELECTOR",
    "RESULT_LINK_SELECTOR",
    "TERM_DETAIL_SELECTOR",
    "TERM_NAME_SELECTOR",
    "TOPIC_VALUE_SELECTOR",
    "TOTAL_COUNT_SELECTOR",
    "get_element_text",
    "get_facet_topics",
    "get_glossary_size",
    "get_result_links",
    "get_results_header_text",
    "get_term_detail_blocks",
    "get_term_name",
    "get_total_term_count",
]


FACET_HEADER_SELECTOR = ".CoveoFacet .coveo-facet-header"
"""Header of the discipline/topic facet panel; empty until facets have loaded."""

FACET_EXPAND_SELECTOR = ".CoveoFacet .coveo-facet-footer .coveo-facet-more"
""""Show more" button that reveals every topic in the facet panel."""

TOPIC_VALUE_SELECTOR = "#discipline-facet .coveo-facet-value"
"""One entry (topic name + term count) in the discipline facet panel."""

RESULTS_HEADER_SELECTOR = ".coveo-results-header"
"""Header shown above the search results list once a search has resolved."""

TOTAL_COUNT_SELECTOR = ".CoveoQuerySummary .coveo-highlight-total-count"
"""Element holding the total number of terms matched by the current search."""

RESULT_LINK_SELECTOR = ".CoveoResult .CoveoResultLink"
"""Anchor linking to a term's detail page, one per search result."""

TERM_NAME_SELECTOR = ".row .small-12 h1 strong"
"""Heading holding the term name on a term detail page."""

TERM_DETAIL_SELECTOR = ".content-two-col__text"
"""One definition block on a term detail page; a term may have several."""


async def get_element_text(page: Page, selector: str, *, timeout: float = 5_000) -> str:
    """
    Return the trimmed text content of the first element matching `selector`.

    :param page: The page to search.
    :param selector: A CSS selector.
    :param timeout: Milliseconds to wait for the element to appear.
    :return: The element's text content, or `""` if it never appears or has
        no text.
    """
    locator = page.locator(selector).first
    try:
        text = await locator.text_content(timeout=timeout)
    except Exception as exc:
        logger.debug("Selector %r had no text within %sms", selector, timeout, exc_info=exc)
        return ""
    return (text or "").strip()


async def get_facet_topics(page: Page) -> dict[str, int]:
    """
    Read every topic and its term count out of the discipline facet panel.

    Call `get_element_text(page, FACET_EXPAND_SELECTOR)` and click it first
    if you need every topic; otherwise only the topics visible by default
    are returned.

    :param page: A page currently showing the glossary search screen.
    :return: Mapping of topic name to number of terms filed under it.
    """
    raw_entries = await page.eval_on_selector_all(
        TOPIC_VALUE_SELECTOR,
        """
        (elements) => elements.map((element) => {
            const label = element.querySelector(
                ".coveo-facet-value-label .coveo-facet-value-caption"
            );
            const count = element.querySelector(
                ".coveo-facet-value-label .coveo-facet-value-count"
            );
            if (!label || !count) {
                return null;
            }
            return [label.textContent.trim(), count.textContent.trim()];
        }).filter((entry) => entry !== null)
        """,
    )
    topics: dict[str, int] = {}
    for name, count_text in raw_entries:
        try:
            topics[name] = parse_int(count_text)
        except ValueError:
            logger.debug("Could not parse term count %r for topic %r", count_text, name)
            continue
    logger.debug("Read %d topics from the facet panel", len(topics))
    return topics


async def get_glossary_size(page: Page) -> int:
    """
    Read the total number of terms in the glossary off the search screen.

    :param page: A page currently showing the glossary search screen.
    :return: The total term count, or `0` if it could not be read.
    """
    text = await get_element_text(page, TOTAL_COUNT_SELECTOR)
    if not text:
        return 0
    try:
        return parse_int(text)
    except ValueError:
        return 0


async def get_results_header_text(page: Page) -> str:
    """Return the text of the search results header, or `""` if not loaded."""
    return await get_element_text(page, RESULTS_HEADER_SELECTOR)


async def get_total_term_count(page: Page) -> int | None:
    """
    Read the number of terms matched by the current search.

    :param page: A page currently showing glossary search results.
    :return: The matched term count, or `None` if it could not be read.
    """
    text = await get_element_text(page, TOTAL_COUNT_SELECTOR)
    if not text:
        return None
    try:
        return parse_int(text)
    except ValueError:
        return None


async def get_result_links(page: Page) -> list[str]:
    """
    Return the term detail page URLs listed on the current results page.

    :param page: A page currently showing glossary search results.
    :return: Ordered list of term detail URLs, one per result on the page.
    """
    hrefs = await page.eval_on_selector_all(
        RESULT_LINK_SELECTOR,
        "(elements) => elements.map((element) => element.getAttribute('href'))",
    )
    links = [href for href in hrefs if href]
    logger.debug("Read %d result links from the current page", len(links))
    return links


async def get_term_name(page: Page) -> str | None:
    """
    Return the term name heading on a term detail page.

    :param page: A page currently showing a term detail page.
    :return: The term name, or `None` if the page has no term heading.
    """
    text = await get_element_text(page, TERM_NAME_SELECTOR)
    return text or None


async def get_term_detail_blocks(page: Page) -> list[list[str]]:
    """
    Return the raw paragraph text of every definition block on a term page.

    A term detail page holds one `TERM_DETAIL_SELECTOR` block per definition
    (a term can have several, one per topic). Each block's paragraphs are
    returned in document order; the first paragraph carries the grammatical
    label and source topic, and the definition text follows in the next
    non-empty paragraph.

    :param page: A page currently showing a term detail page.
    :return: One list of paragraph texts per definition block.
    """
    blocks = await page.eval_on_selector_all(
        TERM_DETAIL_SELECTOR,
        """
        (elements) => elements.map((element) =>
            Array.from(element.querySelectorAll("p")).map(
                (paragraph) => paragraph.textContent.trim()
            )
        )
        """,
    )
    return blocks
