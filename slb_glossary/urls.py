"""Pure helpers for building glossary search URLs."""

import typing
from urllib.parse import quote

from .models import Language


__all__ = [
    "get_glossary_base_url",
    "build_pager_query",
    "build_search_url",
]


def get_glossary_base_url(language: Language = Language.ENGLISH) -> str:
    """
    Return the base search URL for the given glossary language.

    :param language: The glossary language to build the URL for.
    :return: The base search URL, e.g. `"https://glossary.slb.com/en/search"`.
    """
    return f"https://glossary.slb.com/{language.value}/search"


def build_pager_query(*, tab_number: int = 1, terms_per_tab: int = 12) -> str:
    """
    Build the pagination query fragment for the given results tab.

    :param tab_number: The 1-indexed results tab to build the fragment for.
    :param terms_per_tab: Number of results the glossary site returns per tab.
    :return: A `"first=<offset>&"` fragment, or an empty string for tab 1.
    """
    if tab_number < 2:
        return ""
    return f"first={terms_per_tab * (tab_number - 1)}&"


def build_search_url(
    *,
    base_url: str,
    topic: typing.Optional[str] = None,
    query: typing.Optional[str] = None,
    start_letter: typing.Optional[str] = None,
    pager_query: typing.Optional[str] = None,
) -> str:
    """
    Build a full glossary search URL from its constituent filters.

    :param base_url: Base search URL, as returned by `get_glossary_base_url`.
    :param topic: An exact, already-resolved topic (or comma-separated
        topics) to filter results by. Use `slb_glossary.topics.get_topic_match`
        to resolve a user-supplied topic name before passing it here.
    :param query: A free-text search query.
    :param start_letter: Limit results to terms starting with this letter.
    :param pager_query: A pagination fragment from `build_pager_query`.
    :return: The full URL to load in the browser for these filters. Returns
        `base_url` unchanged if no filter was given.
    """
    if not topic and not (query or start_letter):
        return base_url

    query_part = f"q={quote(query)}&" if query else ""
    start_letter_part = (
        f"&f:TermStartLetterFacet=[{quote(start_letter[0].upper())}]"
        if start_letter
        else ""
    )
    topic_part = f"&f:DisciplineFacet=[{quote(topic)}]" if topic else ""
    return f"{base_url}#{query_part}{pager_query or ''}sort=relevancy{topic_part}{start_letter_part}"
