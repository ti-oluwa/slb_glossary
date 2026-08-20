"""
Source-aware query API containing a set of functions that can read the local
database, the live glossary, or both, without the caller having to
hand-roll the "check local, fall back live, maybe cache what came back"
dance every time.

```python
import slb_glossary as slb

async with slb.local.database() as db, slb.live.session() as session:
    # Local first; only opens a live page if the local DB has nothing.
    # Whatever came back live is written to `db` so the next call is local-only.
    async for lookup in slb.query.search(
        "water saturation", db=db, session=session, persist=True
    ):
        print(lookup.source.value, lookup.score, lookup.value.term)
```

At least one of `db` or `session` must be given to every function here.
Else, there's nothing to query. Which of the two is actually used (and
in what order) is controlled by `source`:

* `Source.LOCAL` - the local database only. Never touches the network.
  Requires `db`.
* `Source.LIVE` - the live glossary only. Never touches the local database
  (not even to read it). Requires `session`.
* `Source.AUTO` (the default when both `db` and `session` are given).
  Try `db` first; only fall back to `session` if the local database has
  nothing for the query. Pass `persist=True` to write whatever came back
  live into `db`, so a repeat lookup is served locally next time.

When only one of `db`/`session` is given, `Source.AUTO` simply
behaves like whichever of `Source.LOCAL`/`Source.LIVE` that one supports.

`search` narrows `Source.AUTO` further than the other functions here: a
local hit doesn't automatically end the search. Each local result is
scored against the query (see `slb_glossary.local.scored_search`), and if
even the best of them isn't a confident match, the live glossary is
queried too and its results are added on. The local results aren't
thrown away, just no longer treated as the whole answer.
`relevance_threshold` controls how confident is confident enough. See
`search`'s own docstring.

`search`/`get_terms_on` write live results to `db` incrementally, in
batches, rather than buffering the whole stream and writing it in one shot
at the end. See `slb_glossary.local.upsert_results_incrementally`'s
docstring for why, and `persist_batch_size`/`persist_on_error` for how to
tune it.

Every function here returns or yields `LookupResult`s, not bare values,
so a caller always knows which source actually answered a query (and,
where relevant, how confident the match was) without threading that
information through separately. Unwrap with `.value`.
"""

import asyncio
import dataclasses
import enum
import logging
import random
import string
import time
import typing

from slb_glossary import live
from slb_glossary.errors import QueryError
from slb_glossary.live.browser import Session
from slb_glossary.local import api as local_api
from slb_glossary.local.types import Database
from slb_glossary.natural_language import strip_wrapper
from slb_glossary.relevance import EXACT_MATCH_SCORE, score_result
from slb_glossary.types import RelatedTerm, SearchResult

logger = logging.getLogger(__name__)

__all__ = [
    "Source",
    "LookupResult",
    "SimilarResult",
    "search",
    "get_terms_on",
    "get_terms_urls",
    "get_topics",
    "get_term",
    "related_terms",
    "get_random_term",
    "compare",
]

DEFAULT_PERSIST_BATCH_SIZE = local_api.DEFAULT_UPSERT_BATCH_SIZE
"""
Default `persist_batch_size` for `search`/`get_terms_on`: how many
live results to buffer before writing an incremental upsert batch.
"""

DEFAULT_RELEVANCE_THRESHOLD = 0.55
"""
Default `relevance_threshold` for `search`'s `Source.AUTO` behavior:
below this score (see `slb_glossary.local.scored_search`), the local
database's best match isn't trusted alone and a live search is added on.
"""

SIMILAR_TERMS_POOL_SIZE = 5
"""
Maximum number of live results to pull from the glossary
site to look for an exact match in and, when `with_similar` is `True`,
to draw `SimilarResult.similar` alternatives from.
"""

MAX_SIMILAR_TERMS = 3
"""Max number of alternative/similar terms to return in `SimilarResult.similar`."""

DEFAULT_COMPARE_CONCURRENCY = 1
"""Default `concurrency` for `compare`: term lookups happen sequentially unless raised."""


class Source(enum.Enum):
    """Where a `slb_glossary.query` function is allowed to read/write results from."""

    LOCAL = "local"
    """The local database only. Never touches the network. Requires `db`."""

    LIVE = "live"
    """The live glossary only. Never touches the local database. Requires `session`."""

    AUTO = "auto"
    """
    Local first, live as a fallback when the local database has nothing.
    See the module docstring for the full behavior.
    """


T = typing.TypeVar("T")


@dataclasses.dataclass(slots=True, kw_only=True, frozen=True)
class LookupResult(typing.Generic[T]):
    """The outcome of one value returned or yielded by a `slb_glossary.query` function, with its provenance."""

    value: T
    """The looked-up value itself (e.g. a `SearchResult`, or `None` if nothing was found)."""

    source: Source
    """Which source actually served this lookup: `Source.LOCAL` or `Source.LIVE`."""

    persisted: bool
    """
    Whether this result was written to `db` as part of the call that
    produced it (only ever `True` for a live result fetched with
    `persist=True`). For a streamed lookup (`search`, `get_terms_on`),
    this reflects whether persistence was requested for the call as a
    whole, not whether this specific item's own database write has been
    confirmed yet. 
    
    Live results are written incrementally in batches so an individual 
    item's write may still be pending in its batch when it's yielded.
    """

    score: float | None = None
    """
    A relevance score in `[0.0, 1.0]` for this value against the query it
    was found for, where that's meaningful. 
    
    `None` where scoring doesn't apply (a topic listing, a related-terms lookup, 
    and so on).
    """


@dataclasses.dataclass(slots=True, kw_only=True, frozen=True)
class SimilarResult:
    """
    The outcome of a `with_similar=True` term lookup: an exact match, plus alternatives.

    Returned by `get_term` (wrapped in a `LookupResult` itself) in place
    of a bare `SearchResult | None` when the caller opted into also
    seeing similarly-named results.
    """

    exact: LookupResult[SearchResult] | None
    """
    A `LookupResult` wrapping the exact (case-insensitive) term-name
    match, or `None` if there wasn't one. Its own `.score` is
    `EXACT_MATCH_SCORE`, since it's exact by definition.
    """

    similar: tuple[LookupResult[SearchResult], ...] = ()
    """
    Other results the live search turned up for the same query, each
    scored against it (see `slb_glossary.relevance.score_result`), best
    match first, `exact` itself excluded.

    Always empty for a local-only lookup, since only a live search has
    anything to compare against.
    """

    def __bool__(self) -> bool:
        return self.exact is not None or bool(self.similar)


def validate_source(db: Database | None, session: Session | None, source: Source) -> None:
    """Validate that `db`/`session` actually support the requested `source`."""
    if db is None and session is None:
        raise QueryError(
            "`slb_glossary.query` needs at least one of `db` or `session` to query anything."
        )
    if source is Source.LOCAL and db is None:
        raise QueryError(
            "`source=Source.LOCAL` requires `db` (a `database()`/`open_db()` Database)."
        )
    if source is Source.LIVE and session is None:
        raise QueryError("`source=Source.LIVE` requires `session` (an open `Session`).")


def resolve_source(db: Database | None, session: Session | None, source: Source) -> Source:
    """Attempt to narrow `Source.AUTO` to a starting concrete source given what's available."""
    validate_source(db, session, source)
    if source is not Source.AUTO or (db is not None and session is not None):
        return source
    return Source.LOCAL if db is not None else Source.LIVE


async def _maybe_persist(
    db: Database | None, results: typing.Sequence[SearchResult], *, persist: bool, language: str
) -> bool:
    """Upsert `results` into `db` in one shot."""
    if not persist or db is None or not results:
        return False
    started_at = time.monotonic()
    written = await local_api.upsert_results(db, results, language=language)
    if written:
        logger.info(
            "Cached %d result(s) fetched live into the local database in %.3fs",
            written,
            time.monotonic() - started_at,
        )
    return written > 0


def persist_incrementally(
    db: Database | None,
    results: typing.AsyncIterator[SearchResult],
    *,
    persist: bool,
    language: str,
    batch_size: int = DEFAULT_PERSIST_BATCH_SIZE,
    persist_on_error: bool = True,
) -> typing.AsyncIterator[SearchResult]:
    """
    Wrap a live result stream, upserting into `db` in batches as results arrive.

    A thin wrapper around `slb_glossary.local.upsert_results_incrementally`,
    which does batching/flush-on-error work.

    :param db: The local database to write to. `results` is passed through
        unchanged (no persistence attempted) if this is `None`.
    :param results: The live result stream to wrap.
    :param persist: If `False`, disables writing entirely; `results` still
        passes through unchanged. Checked once up front so this is a cheap
        no-op wrapper when persistence wasn't requested.
    :param language: Glossary language edition these results were fetched
        in. Passed straight through to `slb_glossary.local.upsert_results_incrementally`.
    :param batch_size: Number of results to buffer before writing an
        incremental batch. Smaller values save progress more often at the
        cost of more (smaller) database writes; larger values write less
        often but risk losing more unsaved results if something goes wrong
        before the next flush. Defaults to `DEFAULT_PERSIST_BATCH_SIZE`.
    :param persist_on_error: If `True` (the default), flush whatever's
        currently buffered when `results` raises, before letting the
        exception propagate, so an interrupted fetch still saves the
        progress it made. If `False`, an exception discards the current,
        not-yet-flushed buffer (results already flushed in earlier batches
        are unaffected either way).
    :yield: Every item from `results`, unchanged.
    :raises ValueError: If `batch_size` is less than 1.
    """
    if not persist or db is None:
        return results

    return local_api.upsert_results_incrementally(
        db,
        results,
        language=language,
        batch_size=batch_size,
        persist_on_error=persist_on_error,
    )


async def search(
    query: str,
    *,
    db: Database | None = None,
    session: Session | None = None,
    source: Source = Source.AUTO,
    topic: str | None = None,
    start_letter: str | None = None,
    limit: int | None = 3,
    concurrency: int = 1,
    persist: bool = False,
    persist_batch_size: int = DEFAULT_PERSIST_BATCH_SIZE,
    persist_on_error: bool = True,
    fuzzy: bool = False,
    relevance_threshold: float = DEFAULT_RELEVANCE_THRESHOLD,
) -> typing.AsyncIterator[LookupResult[SearchResult]]:
    """
    Search for `query`, reading from `db`/`session` according to `source`.

    `query` is first passed through `slb_glossary.natural_language.strip_wrapper`,
    so a plain-English question like "what is water saturation" is searched
    as "water saturation" against both `db` and `session`.

    With `source=Source.AUTO` (the default when both `db` and `session`
    are given), the local database is searched first and scored.
    If its best result meets `relevance_threshold`, those local results
    are served alone. Otherwise the live glossary is queried too, and
    its results are added on after the local ones. Local results aren't
    thrown away just because they weren't confident, they're just not
    trusted as the whole answer.

    :param query: Free-text query.
    :param db: An open local `Database`. Required for `Source.LOCAL`, and
        used as the primary source (and/or cache target) for `Source.AUTO`.
    :param session: An open live `Session`. Required for `Source.LIVE`,
        and used as the fallback (and/or live source) for `Source.AUTO`.
    :param source: Which source(s) to read from. See the module docstring.
    :param topic: Restrict results to this topic, or several comma-separated topics.
    :param start_letter: Restrict results to terms starting with this letter.
    :param limit: Maximum number of terms to look up. `None` for unlimited.
    :param concurrency: Concurrent term-page fetches, only relevant when a
        live fetch happens. See `slb_glossary.live.search`.
    :param persist: If `True`, and a live fetch happens, write its results
        into `db` (if given) so the next matching call can be served
        locally. Written incrementally as results arrive (see
        `slb_glossary.local.upsert_results_incrementally`), and not all at
        once at the end.
    :param persist_batch_size: Number of live results to buffer before each
        incremental write to `db`. Only relevant when `persist=True` and a
        live fetch actually happens.
    :param persist_on_error: If `True` (the default), and `persist=True`,
        save whatever's buffered so far if the live fetch raises partway
        through, instead of losing it.
    :param fuzzy: If `True`, any local-database read (a `Source.LOCAL` read,
        or `Source.AUTO`'s local-first attempt) tolerates minor
        misspellings/partial names in `topic`. Live reads already
        fuzzy-match topics unconditionally, so this has no effect on them.
    :param relevance_threshold: Only used by `Source.AUTO`. The local
        database's best-scoring result must meet this (`0.0`-`1.0`, see
        `slb_glossary.local.scored_search`) for its results to be served
        without also querying the live glossary. Lower it to trust local
        results more readily (fewer live fetches); raise it to augment
        with live results more often.
    :yield: `LookupResult[SearchResult]`s, best match first.
    :raises slb_glossary.QueryError: If neither `db` nor `session` is given,
        or the requested `source` needs one that wasn't given.
    """
    normalized_query = strip_wrapper(query)
    started_at = time.monotonic()
    resolved = resolve_source(db, session, source)
    count = 0
    if resolved is Source.LOCAL:
        assert db is not None
        async for result, score in local_api.search(
            db,
            normalized_query,
            topic=topic,
            start_letter=start_letter,
            limit=limit,
            fuzzy=fuzzy,
            scored=True,
        ):
            count += 1
            yield LookupResult(value=result, source=Source.LOCAL, persisted=False, score=score)

        logger.debug(
            "`query.search(%r, source=LOCAL)` yielded %d result(s) in %.3fs",
            normalized_query,
            count,
            time.monotonic() - started_at,
        )
        return

    if resolved is Source.LIVE or source is not Source.AUTO:
        assert session is not None
        live_stream = live.search(
            session,
            normalized_query,
            topic=topic,
            start_letter=start_letter,
            limit=limit,
            concurrency=concurrency,
        )
        async for result in persist_incrementally(
            db,
            live_stream,
            persist=persist,
            language=session.language.value,
            batch_size=persist_batch_size,
            persist_on_error=persist_on_error,
        ):
            count += 1
            score = score_result(normalized_query, result)
            yield LookupResult(value=result, source=Source.LIVE, persisted=persist, score=score)

        logger.debug(
            "`query.search(%r, source=LIVE)` yielded %d result(s) in %.3fs",
            normalized_query,
            count,
            time.monotonic() - started_at,
        )
        return

    # source is `Source.AUTO`, resolved started as `LOCAL`: score it, then decide.
    assert db is not None
    scored = await local_api.scored_search(
        db, normalized_query, topic=topic, start_letter=start_letter, limit=limit, fuzzy=fuzzy
    )
    results = [result for result, _ in scored]
    best_score = scored[0][1] if scored else 0.0

    if results and best_score >= relevance_threshold:
        logger.debug(
            "Serving `search(%r)` from the local database alone "
            "(%d result(s), best score %.3f >= threshold %.3f, in %.3fs)",
            normalized_query,
            len(results),
            best_score,
            relevance_threshold,
            time.monotonic() - started_at,
        )
        for result, score in scored:
            yield LookupResult(value=result, source=Source.LOCAL, persisted=False, score=score)
        return

    if session is None:
        logger.debug(
            "`search(%r)`: local database's best score %.3f is below threshold %.3f "
            "(or empty), but no session to augment with; serving local results as-is",
            normalized_query,
            best_score,
            relevance_threshold,
        )
        for result, score in scored:
            yield LookupResult(value=result, source=Source.LOCAL, persisted=False, score=score)
        return

    logger.debug(
        "`search(%r)`: local database's best score %.3f is below threshold %.3f "
        "(or empty); augmenting with the live glossary",
        normalized_query,
        best_score,
        relevance_threshold,
    )
    for result, score in scored:
        count += 1
        yield LookupResult(value=result, source=Source.LOCAL, persisted=False, score=score)

    remaining = None if limit is None else max(limit - len(results), 0)
    if remaining == 0:
        logger.debug(
            "`query.search(%r, source=AUTO)` yielded %d result(s) in %.3fs total "
            "(local quota already filled; not augmenting further)",
            normalized_query,
            count,
            time.monotonic() - started_at,
        )
        return

    seen_urls = {result.url for result in results if result.url}
    seen_terms = {(result.term or "").strip().lower() for result in results}
    live_stream = live.search(
        session,
        normalized_query,
        topic=topic,
        start_letter=start_letter,
        limit=remaining if remaining is not None else limit,
        concurrency=concurrency,
    )
    async for result in persist_incrementally(
        db,
        live_stream,
        persist=persist,
        language=session.language.value,
        batch_size=persist_batch_size,
        persist_on_error=persist_on_error,
    ):
        url = result.url
        term_key = (result.term or "").strip().lower()
        if (url and url in seen_urls) or term_key in seen_terms:
            # Already covered by a local result; don't yield it twice.
            continue

        seen_urls.add(url or "")
        seen_terms.add(term_key)
        count += 1
        score = score_result(normalized_query, result)
        yield LookupResult(value=result, source=Source.LIVE, persisted=persist, score=score)

    logger.debug(
        "`query.search(%r, source=AUTO->LOCAL+LIVE)` yielded %d result(s) in %.3fs total",
        normalized_query,
        count,
        time.monotonic() - started_at,
    )


async def get_terms_on(
    topic: str,
    *,
    db: Database | None = None,
    session: Session | None = None,
    source: Source = Source.AUTO,
    start_letter: str | None = None,
    limit: int | None = None,
    concurrency: int = 1,
    persist: bool = False,
    persist_batch_size: int = DEFAULT_PERSIST_BATCH_SIZE,
    persist_on_error: bool = True,
    fuzzy: bool = False,
) -> typing.AsyncIterator[SearchResult]:
    """
    Yield every term filed under `topic`, reading from `db`/`session` according to `source`.

    Same local-first, live-fallback behavior as `search` for `Source.AUTO`.

    :param topic: Topic name, or several comma-separated topic names.
    :param db: An open local `Database`.
    :param session: An open live `Session`.
    :param source: Which source(s) to read from. See the module docstring.
    :param start_letter: Restrict results to terms starting with this letter.
    :param limit: Maximum number of terms to yield. `None` for unlimited.
    :param concurrency: Concurrent term-page fetches, only relevant when a
        live fetch happens.
    :param persist: If `True`, and a live fetch happens, cache its results
        into `db`, incrementally as they arrive - see
        `slb_glossary.local.upsert_results_incrementally`.
    :param persist_batch_size: Number of live results to buffer before each
        incremental write to `db`. Only relevant when `persist=True` and a
        live fetch actually happens.
    :param persist_on_error: If `True` (the default), and `persist=True`,
        save whatever's buffered so far if the live fetch raises partway
        through, instead of losing it.
    :param fuzzy: If `True`, any local-database read tolerates minor
        misspellings/partial names in `topic`. Live reads already
        fuzzy-match topics unconditionally, so this has no effect on them.
    :yield: `SearchResult`s filed under `topic`.
    :raises slb_glossary.QueryError: If neither `db` nor `session` is given,
        or the requested `source` needs one that wasn't given.
    """
    started_at = time.monotonic()
    resolved = resolve_source(db, session, source)
    if resolved is Source.LOCAL:
        assert db is not None
        count = 0
        async for result in local_api.get_terms_on(
            db,
            topic,
            start_letter=start_letter,
            limit=limit,
            fuzzy=fuzzy,
        ):
            count += 1
            yield result

        logger.debug(
            "`query.get_terms_on(%r, source=LOCAL)` yielded %d result(s) in %.3fs",
            topic,
            count,
            time.monotonic() - started_at,
        )
        return

    if resolved is Source.LIVE or source is not Source.AUTO:
        assert session is not None
        live_stream = live.get_terms_on(
            session,
            topic,
            start_letter=start_letter,
            limit=limit,
            concurrency=concurrency,
        )
        count = 0
        async for result in persist_incrementally(
            db,
            live_stream,
            persist=persist,
            language=session.language.value,
            batch_size=persist_batch_size,
            persist_on_error=persist_on_error,
        ):
            count += 1
            yield result

        logger.debug(
            "`query.get_terms_on(%r, source=LIVE)` yielded %d result(s) in %.3fs",
            topic,
            count,
            time.monotonic() - started_at,
        )
        return

    assert db is not None
    results = [
        result
        async for result in local_api.get_terms_on(
            db,
            topic,
            start_letter=start_letter,
            limit=limit,
            fuzzy=fuzzy,
        )
    ]
    if results:
        logger.debug(
            "Serving `get_terms_on(%r)` from the local database (%d result(s) in %.3fs)",
            topic,
            len(results),
            time.monotonic() - started_at,
        )
        for result in results:
            yield result
        return

    if session is None:
        return

    logger.debug(
        "Local database had nothing for topic %r; falling back to the live glossary", topic
    )
    live_stream = live.get_terms_on(
        session,
        topic,
        start_letter=start_letter,
        limit=limit,
        concurrency=concurrency,
    )
    live_count = 0
    async for result in persist_incrementally(
        db,
        live_stream,
        persist=persist,
        language=session.language.value,
        batch_size=persist_batch_size,
        persist_on_error=persist_on_error,
    ):
        live_count += 1
        yield result
    logger.debug(
        "`query.get_terms_on(%r, source=AUTO->LIVE)` yielded %d result(s) in %.3fs total",
        topic,
        live_count,
        time.monotonic() - started_at,
    )


async def get_terms_urls(
    *,
    db: Database | None = None,
    session: Session | None = None,
    source: Source = Source.AUTO,
    query: str | None = None,
    topic: str | None = None,
    start_letter: str | None = None,
    limit: int | None = None,
    fuzzy: bool = False,
) -> typing.AsyncIterator[str]:
    """
    Yield term detail-page URLs matching the given filters, reading from
    `db`/`session` according to `source`.

    Lighter-weight than `search`/`get_terms_on`: only the URLs themselves
    are returned, no definitions are fetched or parsed - so there's
    nothing here to persist. Same local-first, live-fallback behavior as
    `search` for `Source.AUTO`.

    :param db: An open local `Database`.
    :param session: An open live `Session`.
    :param source: Which source(s) to read from. See the module docstring.
    :param query: Restrict to a free-text query match.
    :param topic: Restrict to this topic, or several comma-separated topics.
    :param start_letter: Restrict to terms starting with this letter.
    :param limit: Maximum number of URLs to yield. `None` for unlimited.
    :param fuzzy: If `True`, any local-database read tolerates minor
        misspellings/partial names in `topic`. Live reads already
        fuzzy-match topics unconditionally, so this has no effect on them.
    :yield: Matching term detail-page URLs.
    :raises slb_glossary.QueryError: If neither `db` nor `session` is given,
        or the requested `source` needs one that wasn't given.
    """
    resolved = resolve_source(db, session, source)
    if resolved is Source.LOCAL:
        assert db is not None
        async for url in local_api.get_terms_urls(
            db,
            query=query,
            topic=topic,
            start_letter=start_letter,
            limit=limit,
            fuzzy=fuzzy,
        ):
            yield url
        return

    if resolved is Source.LIVE or source is not Source.AUTO:
        assert session is not None
        async for url in live.get_terms_urls(
            session,
            query=query,
            topic=topic,
            start_letter=start_letter,
            limit=limit,
        ):
            yield url
        return

    # source is Source.AUTO, resolved started as LOCAL: try it, then fall back.
    assert db is not None
    urls = [
        url
        async for url in local_api.get_terms_urls(
            db,
            query=query,
            topic=topic,
            start_letter=start_letter,
            limit=limit,
            fuzzy=fuzzy,
        )
    ]
    if urls:
        logger.debug("Serving `get_terms_urls(...)` from the local database")
        for url in urls:
            yield url
        return

    if session is None:
        logger.debug(
            "Local database had nothing for `get_terms_urls(...)`; no session to fall back to"
        )
        return

    logger.debug(
        "Local database had nothing for `get_terms_urls(...)`; falling back to the live glossary"
    )
    async for url in live.get_terms_urls(
        session,
        query=query,
        topic=topic,
        start_letter=start_letter,
        limit=limit,
    ):
        yield url


async def get_topics(
    *,
    db: Database | None = None,
    session: Session | None = None,
    source: Source = Source.AUTO,
) -> dict[str, int]:
    """
    Return `{topic: term_count}`, reading from `db`/`session` according to `source`.

    Unlike `search`/`get_terms_on`, a live read here never touches the
    network by itself: `session.topics` is already loaded when the session
    was opened, so this just returns it directly.

    :param db: An open local `Database`. Its topic counts only reflect
        terms that have actually been cached locally, which may be a
        subset of the live glossary's full topic list.
    :param session: An open live `Session`.
    :param source: Which source(s) to read from. `Source.AUTO`
        prefers the local database when it has at least one topic, falling
        back to `session.topics` otherwise. See the module docstring.
    :return: Topic name to term count.
    :raises slb_glossary.QueryError: If neither `db` nor `session` is given,
        or the requested `source` needs one that wasn't given.
    """
    resolved = resolve_source(db, session, source)
    if resolved is Source.LOCAL:
        assert db is not None
        return await local_api.get_topics(db)

    if resolved is Source.LIVE or source is not Source.AUTO:
        assert session is not None
        return dict(session.topics)

    assert db is not None
    topics = await local_api.get_topics(db)
    if topics:
        return topics

    if session is None:
        return {}
    return dict(session.topics)


@typing.overload
async def get_term(
    term_or_url: str,
    *,
    db: Database | None = None,
    session: Session | None = None,
    source: Source = Source.AUTO,
    persist: bool = False,
    with_similar: typing.Literal[False] = False,
    similar_pool_size: int = SIMILAR_TERMS_POOL_SIZE,
    max_similar_terms: int = MAX_SIMILAR_TERMS,
) -> LookupResult[SearchResult | None]: ...


@typing.overload
async def get_term(
    term_or_url: str,
    *,
    db: Database | None = None,
    session: Session | None = None,
    source: Source = Source.AUTO,
    persist: bool = False,
    with_similar: typing.Literal[True],
    similar_pool_size: int = SIMILAR_TERMS_POOL_SIZE,
    max_similar_terms: int = MAX_SIMILAR_TERMS,
) -> LookupResult[SimilarResult]: ...


async def get_term(
    term_or_url: str,
    *,
    db: Database | None = None,
    session: Session | None = None,
    source: Source = Source.AUTO,
    persist: bool = False,
    with_similar: bool = False,
    similar_pool_size: int = SIMILAR_TERMS_POOL_SIZE,
    max_similar_terms: int = MAX_SIMILAR_TERMS,
) -> LookupResult:
    """
    Look up a single term by exact name or detail-page URL.

    :param term_or_url: An exact (case-insensitive) term name, or a
        glossary term detail-page URL.
    :param db: An open local `Database`.
    :param session: An open live `Session`.
    :param source: Which source(s) to read from. See the module docstring.
    :param persist: If `True`, and a live fetch happens, cache its result(s)
        into `db`. This is a single-value lookup, so there's normally only
        one result to write. Batching doesn't apply here the way it does
        for `search`/`get_terms_on`. With `with_similar=True`, every
        alternative gathered alongside the exact match is cached too.
    :param with_similar: If `True`, resolve to a `LookupResult[SimilarResult]`
        instead: `SimilarResult.exact` holds what a plain call would have
        returned, and `SimilarResult.similar` holds up to `max_similar_terms`
        other results found for `term_or_url` along the way, best match
        first and is only ever populated by a live lookup, since that's the
        only source with anything to compare against. Handy for a "did you
        mean" prompt when the exact match turns out to be `None`.
    :param similar_pool_size: Live results to pull while looking for the
        exact match, and, with `with_similar=True`, to draw alternatives
        from. Defaults to `SIMILAR_TERMS_POOL_SIZE`.
    :param max_similar_terms: Max alternatives returned in
        `SimilarResult.similar`. Defaults to `MAX_SIMILAR_TERMS`. Ignored
        unless `with_similar=True`.
    :return: A `LookupResult` wrapping the found `SearchResult` (or `None` if
        not found by the resolved source(s)), scored `EXACT_MATCH_SCORE` if
        found. Or, with `with_similar=True`, a `SimilarResult`, where each
        of `.exact`/`.similar` carries its own score.
    :raises slb_glossary.QueryError: If neither `db` nor `session` is given,
        or the requested `source` needs one that wasn't given.
    """
    resolved = resolve_source(db, session, source)
    if resolved is Source.LOCAL:
        assert db is not None
        result = await local_api.get_term(db, term_or_url)
        return _local_term_lookup(result, with_similar=with_similar)

    if resolved is Source.LIVE or source is not Source.AUTO:
        assert session is not None
        fetched = await _fetch_term(
            session,
            term_or_url,
            with_similar=with_similar,
            similar_pool_size=similar_pool_size,
            max_similar_terms=max_similar_terms,
        )
        return await _finalize_live_term_lookup(
            db, session, fetched, with_similar=with_similar, persist=persist
        )

    assert db is not None
    result = await local_api.get_term(db, term_or_url)
    if result is not None:
        return _local_term_lookup(result, with_similar=with_similar)

    if session is None:
        empty = SimilarResult(exact=None) if with_similar else None
        return LookupResult(value=empty, source=Source.LOCAL, persisted=False)

    fetched = await _fetch_term(
        session,
        term_or_url,
        with_similar=with_similar,
        similar_pool_size=similar_pool_size,
        max_similar_terms=max_similar_terms,
    )
    return await _finalize_live_term_lookup(
        db, session, fetched, with_similar=with_similar, persist=persist
    )


def _local_term_lookup(result: SearchResult | None, *, with_similar: bool) -> LookupResult:
    """
    Build `get_term`'s return value for a local hit (or miss).

    A local lookup is always an exact-name match by construction (there's
    no "similar" concept locally), so a hit always scores `EXACT_MATCH_SCORE`.
    """
    if with_similar:
        exact = (
            LookupResult(
                value=result, source=Source.LOCAL, persisted=False, score=EXACT_MATCH_SCORE
            )
            if result is not None
            else None
        )
        return LookupResult(value=SimilarResult(exact=exact), source=Source.LOCAL, persisted=False)

    score = EXACT_MATCH_SCORE if result is not None else None
    return LookupResult(value=result, source=Source.LOCAL, persisted=False, score=score)


async def _finalize_live_term_lookup(
    db: Database | None,
    session: Session,
    fetched: LookupResult[SearchResult] | None | SimilarResult,
    *,
    with_similar: bool,
    persist: bool,
) -> LookupResult:
    """
    Persist `_fetch_term`'s result if requested, then build `get_term`'s return value from it.

    Shared by `get_term`'s `Source.LIVE` branch and its `Source.AUTO`
    live-fallback branch, since both do the same persist-then-wrap work
    once they have a `fetched` value from `_fetch_term`.
    """
    persisted = await _maybe_persist(
        db,
        results=_flatten_results(fetched, with_similar=with_similar),
        persist=persist,
        language=session.language.value,
    )
    if with_similar:
        assert isinstance(fetched, SimilarResult)
        return LookupResult(value=fetched, source=Source.LIVE, persisted=persisted)

    assert not isinstance(fetched, SimilarResult)
    if fetched is None:
        return LookupResult(value=None, source=Source.LIVE, persisted=persisted)
    return LookupResult(
        value=fetched.value, source=Source.LIVE, persisted=persisted, score=fetched.score
    )


def _flatten_results(
    fetched: LookupResult[SearchResult] | None | SimilarResult, *, with_similar: bool
) -> list[SearchResult]:
    """Flatten a `_fetch_term` result into the `SearchResult`(s) `_maybe_persist` should cache."""
    if not with_similar:
        assert not isinstance(fetched, SimilarResult)
        return [fetched.value] if fetched is not None else []

    assert isinstance(fetched, SimilarResult)
    exact = [fetched.exact.value] if fetched.exact is not None else []
    return exact + [lookup.value for lookup in fetched.similar]


@typing.overload
async def _fetch_term(
    session: Session,
    term_or_url: str,
    *,
    with_similar: typing.Literal[False] = False,
    similar_pool_size: int = SIMILAR_TERMS_POOL_SIZE,
    max_similar_terms: int = MAX_SIMILAR_TERMS,
) -> LookupResult[SearchResult] | None: ...


@typing.overload
async def _fetch_term(
    session: Session,
    term_or_url: str,
    *,
    with_similar: typing.Literal[True],
    similar_pool_size: int = SIMILAR_TERMS_POOL_SIZE,
    max_similar_terms: int = MAX_SIMILAR_TERMS,
) -> SimilarResult: ...


async def _fetch_term(
    session: Session,
    term_or_url: str,
    *,
    with_similar: bool = False,
    similar_pool_size: int = SIMILAR_TERMS_POOL_SIZE,
    max_similar_terms: int = MAX_SIMILAR_TERMS,
) -> LookupResult[SearchResult] | None | SimilarResult:
    """
    Resolve `term_or_url` against the live glossary: a URL fetches directly, else it's searched.

    :param session: An open live `Session`.
    :param term_or_url: An exact (case-insensitive) term name, or a
        glossary term detail-page URL.
    :param with_similar: If `True`, return a `SimilarResult` gathering up to
        `max_similar_terms` other results turned up while searching for
        the exact match, instead of just the exact match itself. A direct
        URL fetch has nothing to search, so `SimilarResult.similar` is
        always empty in that case.
    :param similar_pool_size: Live results to pull while looking for the
        exact match, and, with `with_similar=True`, to draw
        `SimilarResult.similar` alternatives from. Defaults to `SIMILAR_TERMS_POOL_SIZE`.
    :param max_similar_terms: Max alternatives returned in
        `SimilarResult.similar`. Defaults to `MAX_SIMILAR_TERMS`. Ignored
        unless `with_similar=True`.
    :return: A `LookupResult` wrapping the exact `SearchResult` match (or
        `None`), or with `with_similar=True`, a `SimilarResult` wrapping
        the exact match (if any) and its alternatives, each already
        wrapped in its own `LookupResult`.
    """
    if term_or_url.startswith(("http://", "https://")):
        results: list[SearchResult] = [
            result async for result in live.get_results_from_url(session, term_or_url)
        ]
        if not results:
            return SimilarResult(exact=None) if with_similar else None

        # A direct URL fetch is definitionally an exact match: the caller
        # already knows exactly which page they want, so every definition
        # found on it scores `EXACT_MATCH_SCORE`.
        wrapped = [
            LookupResult(
                value=result, source=Source.LIVE, persisted=False, score=EXACT_MATCH_SCORE
            )
            for result in results
        ]
        if not with_similar:
            return wrapped[0]
        return SimilarResult(exact=wrapped[0], similar=tuple(wrapped[1:]))

    term = term_or_url.strip().lower()

    if not with_similar:
        # The correct definition should at least be in the first `similar_pool_size`
        # results, searching at least 2 at a time.
        async for result in live.search(session, term, limit=similar_pool_size, concurrency=2):
            if result.term and result.term.strip().lower() == term:
                return LookupResult(
                    value=result, source=Source.LIVE, persisted=False, score=EXACT_MATCH_SCORE
                )

        # No exact (case-insensitive) match among the top results;
        # fall back to whatever ranked first, if anything did.
        async for result in live.search(session, term, limit=1):
            score = score_result(term, result)
            return LookupResult(value=result, source=Source.LIVE, persisted=False, score=score)
        return None

    # When `with_similar=True`, we drain the whole pool so alternatives are
    # available regardless of where (or whether) the exact match turned up.
    pool = [
        result
        async for result in live.search(session, term, limit=similar_pool_size, concurrency=2)
    ]
    exact_result = next(
        (result for result in pool if result.term and result.term.strip().lower() == term), None
    )
    exact = (
        LookupResult(
            value=exact_result, source=Source.LIVE, persisted=False, score=EXACT_MATCH_SCORE
        )
        if exact_result is not None
        else None
    )
    similar_results = tuple(result for result in pool if result is not exact_result)[
        :max_similar_terms
    ]
    similar = tuple(
        LookupResult(
            value=result, source=Source.LIVE, persisted=False, score=score_result(term, result)
        )
        for result in similar_results
    )
    return SimilarResult(exact=exact, similar=similar)


async def related_terms(
    term_or_url: str,
    *,
    db: Database | None = None,
    session: Session | None = None,
    source: Source = Source.AUTO,
    persist: bool = False,
) -> LookupResult[tuple[RelatedTerm, ...]]:
    """
    Look up the related terms linked from a single term's definition.

    A thin convenience wrapper around `get_term`: fetches the term, then
    returns just its `SearchResult.related` links.

    :param term_or_url: An exact (case-insensitive) term name, or a
        glossary term detail-page URL.
    :param db: An open local `Database`.
    :param session: An open live `Session`.
    :param source: Which source(s) to read from. See the module docstring.
    :param persist: If `True`, and a live fetch happens, cache the looked-up
        term's own result into `db`.
    :return: A `LookupResult` wrapping the related terms found (empty if
        `term_or_url` wasn't found, or was found but links to nothing).
    :raises slb_glossary.QueryError: If neither `db` nor `session` is given,
        or the requested `source` needs one that wasn't given.
    """
    lookup = await get_term(term_or_url, db=db, session=session, source=source, persist=persist)
    related = lookup.value.related if lookup.value is not None else None
    return LookupResult(value=related or (), source=lookup.source, persisted=lookup.persisted)


async def get_random_term(
    *,
    db: Database | None = None,
    session: Session | None = None,
    source: Source = Source.AUTO,
    topic: str | None = None,
    persist: bool = False,
    fuzzy: bool = False,
) -> LookupResult[SearchResult | None]:
    """
    Return one randomly chosen term, optionally restricted to a topic.

    For `Source.LIVE` (and `Source.AUTO` falling back to it), there's
    no "random" endpoint on the live site to call, so this samples one term
    detail-page URL from a random starting letter (or, if `topic` is given,
    from that topic) and fetches it.

    :param db: An open local `Database`.
    :param session: An open live `Session`.
    :param source: Which source(s) to read from. See the module docstring.
        `Source.AUTO` here means "pick locally if the local database
        has anything (matching `topic`, if given), otherwise pick form the live site,
        not "try local, then live" the way the streaming functions do,
        since a local miss on one random draw says nothing about whether
        the local database is empty.
    :param topic: Restrict the pick to this topic, or several comma-separated topics.
    :param persist: If `True`, and a live pick happens, cache it into `db`.
        A single-value lookup, so batching doesn't apply.
    :param fuzzy: If `True`, a local pick tolerates minor misspellings/
        partial names in `topic`.
        Live picks already fuzzy-match topics unconditionally, so this has
        no effect on them.
    :return: A `LookupResult` wrapping the picked `SearchResult`, or `None` if
        nothing matched (empty local database/topic, or no live match found).
    :raises slb_glossary.QueryError: If neither `db` nor `session` is given,
        or the requested `source` needs one that wasn't given.
    """
    resolved = resolve_source(db, session, source)
    if resolved is Source.LOCAL:
        assert db is not None
        result = await local_api.get_random_term(db, topic=topic, fuzzy=fuzzy)
        return LookupResult(value=result, source=Source.LOCAL, persisted=False)

    if resolved is Source.LIVE or source is not Source.AUTO:
        assert session is not None
        result = await _fetch_random_term(session, topic=topic)
        persisted = await _maybe_persist(
            db,
            results=[result] if result else [],
            persist=persist,
            language=session.language.value,
        )
        return LookupResult(value=result, source=Source.LIVE, persisted=persisted)

    # AUTO: prefer a local pick when the local database actually has
    # something to pick from; only go live when it doesn't.
    assert db is not None
    result = await local_api.get_random_term(db, topic=topic, fuzzy=fuzzy)
    if result is not None:
        return LookupResult(value=result, source=Source.LOCAL, persisted=False)

    if session is None:
        return LookupResult(value=None, source=Source.LOCAL, persisted=False)

    result = await _fetch_random_term(session, topic=topic, sample_size=25)
    persisted = await _maybe_persist(
        db, results=[result] if result else [], persist=persist, language=session.language.value
    )
    return LookupResult(value=result, source=Source.LIVE, persisted=persisted)


LETTERS = list(string.ascii_lowercase)


def _random_letters(n: int | None = None) -> list[str]:
    """Return a shuffled list of letters a-z, optionally truncated to `n` letters."""
    shuffled = LETTERS[:]
    random.shuffle(shuffled)
    if n is not None:
        shuffled = shuffled[:n]
    return shuffled


async def _fetch_random_term(
    session: Session, *, topic: str | None, sample_size: int = 25
) -> SearchResult | None:
    """Sample up to `sample_size` live term URLs (by topic, or a random letter) and fetch one."""
    urls: list[str] = []
    if topic:
        url_iter = live.get_terms_urls(session, topic=topic, limit=sample_size)
        urls = [url async for url in url_iter]
    else:
        # No topic given: shuffle through starting letters until one yields
        # results, since a purely random letter (e.g. an uncommon one) may
        # have no terms at all.
        for letter in _random_letters():
            url_iter = live.get_terms_urls(session, start_letter=letter, limit=sample_size)
            urls = [url async for url in url_iter]
            if urls:
                break

    if not urls:
        return None

    chosen_url = random.choice(urls)
    return await anext(live.get_results_from_url(session, chosen_url, topic=topic), None)


@typing.overload
async def compare(
    terms: typing.Sequence[str],
    *,
    db: Database | None = None,
    session: Session | None = None,
    source: Source = Source.AUTO,
    persist: bool = False,
    concurrency: int = DEFAULT_COMPARE_CONCURRENCY,
    with_similar: typing.Literal[False] = False,
) -> dict[str, LookupResult[SearchResult | None]]: ...


@typing.overload
async def compare(
    terms: typing.Sequence[str],
    *,
    db: Database | None = None,
    session: Session | None = None,
    source: Source = Source.AUTO,
    persist: bool = False,
    concurrency: int = DEFAULT_COMPARE_CONCURRENCY,
    with_similar: typing.Literal[True],
) -> dict[str, LookupResult[SimilarResult]]: ...


async def compare(
    terms: typing.Sequence[str],
    *,
    db: Database | None = None,
    session: Session | None = None,
    source: Source = Source.AUTO,
    persist: bool = False,
    concurrency: int = DEFAULT_COMPARE_CONCURRENCY,
    with_similar: bool = False,
) -> dict[str, LookupResult]:
    """
    Look up several terms at once, for side-by-side comparison.

    Terms are looked up concurrently via `asyncio.gather`, up to
    `concurrency` at a time, bounded by a semaphore. Each lookup that
    actually reaches the live glossary checks out its own page from
    `session.pages` for the duration of its own fetch (the same pooled
    pattern `slb_glossary.live.get_results_from_urls` uses for its own
    `concurrency`), so concurrent lookups never race over a single shared
    page. `session.max_pages` should comfortably cover `concurrency`. A
    local-only lookup never touches a page at all.

    :param terms: Term names (or detail-page URLs) to look up. Order is
        preserved in the returned dict, regardless of which order lookups
        actually finish in.
    :param db: An open local `Database`.
    :param session: An open live `Session`.
    :param source: Which source(s) to read from. See the module docstring.
    :param persist: If `True`, cache any live fetches into `db`. Each term
        is looked up (and, on a live fetch, persisted) individually via
        `get_term`, so an error partway through this call still leaves
        earlier terms' results saved.
    :param concurrency: Number of terms to look up in parallel. `1` (the
        default) looks them up one at a time.
    :param with_similar: If `True`, each entry is a `LookupResult[SimilarResult]`
        instead of `LookupResult[SearchResult | None]`, the same as `get_term`'s.
    :return: `{term_or_url: LookupResult}`, in the order `terms` was given.
        A `LookupResult.value` of `None` (or, with `with_similar=True`, a
        falsy `SimilarResult`) means that term wasn't found by the
        resolved source(s).
    :raises slb_glossary.QueryError: If neither `db` nor `session` is given,
        or the requested `source` needs one that wasn't given, or `terms` is empty.
    :raises ValueError: If `concurrency` is less than 1.
    """
    if not terms:
        raise QueryError("`compare()` needs at least one term to look up.")
    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")

    validate_source(db, session, source)
    started_at = time.monotonic()

    semaphore = asyncio.Semaphore(concurrency)

    async def _lookup(term: str) -> tuple[str, LookupResult]:
        async with semaphore:
            lookup = await get_term(
                term,
                db=db,
                session=session,
                source=source,
                persist=persist,
                with_similar=with_similar,
            )
        return term, lookup

    # `asyncio.gather` preserves the order of the awaitables passed to it
    # in its results, regardless of which finishes first, so `results`
    # already comes back in `terms`' own order.
    pairs = await asyncio.gather(*(_lookup(term) for term in terms))
    results = dict(pairs)

    elapsed = time.monotonic() - started_at
    logger.debug(
        "`compare(%d term(s), concurrency=%d)` done in %.3fs (avg %.3fs/term)",
        len(terms),
        concurrency,
        elapsed,
        elapsed / len(terms),
    )
    return results
