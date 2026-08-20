"""
Shared relevance-scoring building blocks for search results, local or live.

`slb_glossary.local.scored_search` computes its scores in SQL (bm25 plus
an exact/prefix name-match tier). A live search has no database to run
that kind of query against, so `slb_glossary.query` scores live results
here instead, using the same tiers and the same `CONTENT_MATCH_SCORE_CAP` 
so a local score and a live score mean roughly the same thing to a caller comparing the two.
"""

from slb_glossary.types import SearchResult

__all__ = [
    "EXACT_MATCH_SCORE",
    "PREFIX_MATCH_SCORE",
    "CONTENT_MATCH_SCORE_CAP",
    "score_name_match",
    "score_content_overlap",
    "score_result",
]

EXACT_MATCH_SCORE = 1.0
"""Score for a query that exactly matches a result's term name (case/whitespace-insensitive)."""

PREFIX_MATCH_SCORE = 0.9
"""Score for a result's term name starting with the query."""

CONTENT_MATCH_SCORE_CAP = 0.45
"""
Upper bound on a result's score when it only matched by content
(definition/topic text), never the term name. Kept below
`slb_glossary.query.DEFAULT_RELEVANCE_THRESHOLD` (0.55), so a content-only
match is never, by default, mistaken for a confident name match. Without
this cap, a query that happens to line up well with one term's definition
(but isn't actually about that term) could otherwise look confident
enough to end a search right there, on the strength of word overlap alone.
"""


def _normalize(text: str) -> str:
    """Lowercase `text` and collapse its whitespace, for name-match comparisons."""
    return " ".join(text.strip().lower().split())


def score_name_match(query: str, term: str) -> float | None:
    """
    Score `term` against `query` on the exact/prefix name tiers only.

    :param query: The free-text query.
    :param term: A result's term name.
    :return: `EXACT_MATCH_SCORE`, `PREFIX_MATCH_SCORE`, or `None` if `term`
        is neither an exact nor a prefix match. `None` tells the caller to
        fall back to `score_content_overlap`, or an equivalent bm25 pass.
    """
    query_norm = _normalize(query)
    term_norm = _normalize(term)
    if not query_norm or not term_norm:
        return None
    if term_norm == query_norm:
        return EXACT_MATCH_SCORE
    if term_norm.startswith(query_norm):
        return PREFIX_MATCH_SCORE
    return None


def score_content_overlap(query: str, *texts: str) -> float:
    """
    Score `query` against `texts` by token overlap, capped at `CONTENT_MATCH_SCORE_CAP`.

    Used where there's no larger corpus to rank against (a single live
    result, scored on its own), so a proper bm25-style pass isn't
    possible. What's measured is coverage: how many of `query`'s own
    tokens turn up somewhere in `texts`, not how long `texts` are or how
    often each token repeats. A short exact phrase match and a long one
    both score about as well, so a longer definition doesn't win purely
    for containing more words.

    :param query: The free-text query.
    :param texts: The result's other fields to check for overlap (its
        definition, topic, and so on). Assumed not to be the term name
        itself. Use `score_name_match` for that.
    :return: A score in `[0.0, CONTENT_MATCH_SCORE_CAP]`.
    """
    query_tokens = _normalize(query).split()
    if not query_tokens:
        return 0.0

    haystack = " ".join(_normalize(text) for text in texts if text)
    if not haystack:
        return 0.0

    matched = sum(1 for token in query_tokens if token in haystack)
    coverage = matched / len(query_tokens)
    return round(CONTENT_MATCH_SCORE_CAP * coverage, 4)


def score_result(query: str, result: SearchResult) -> float:
    """
    Score `result` against `query`, combining the name and content tiers.

    The Python equivalent of one row of `slb_glossary.local.scored_search`'s
    SQL query, for a result that didn't come from that query (a live one).
    Checks the name tier first (`score_name_match`); only falls back to
    the weaker, capped content tier (`score_content_overlap`) if
    `result.term` itself isn't an exact/prefix match.

    :param query: The free-text query `result` was found for.
    :param result: The result to score.
    :return: A score in `[0.0, 1.0]`.
    """
    name_score = score_name_match(query, result.term or "")
    if name_score is not None:
        return name_score
    return score_content_overlap(query, result.definition or "", result.topic or "")
