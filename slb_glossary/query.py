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
    async for result in slb.query.search(
        "water saturation", db=db, session=session, persist=True
    ):
        print(result.term, "-", result.definition)
```

At least one of `db` or `session` must be given to every function here.
Else, there's nothing to query. Which of the two is actually used (and
in what order) is controlled by `source`:

* `Source.LOCAL` - the local database only. Never touches the network.
  Requires `db`.
* `Source.LIVE` - the live glossary only. Never touches the local database
  (not even to read it). Requires `session`.
* `Source.AUTO` (the default when both `db` and `session` are given)
  - try `db` first; only fall back to `session` if the local database has
  nothing for the query. Pass `persist=True` to write whatever came back
  live into `db`, so a repeat lookup is served locally next time.

When only one of `db`/`session` is given, `Source.AUTO` simply
behaves like whichever of `Source.LOCAL`/`Source.LIVE` that one supports.

`search`/`get_terms_on` write live results to `db` incrementally, in
batches, rather than buffering the whole stream and writing it in one shot
at the end - see `slb_glossary.local.upsert_results_incrementally`'s
docstring for why, and `persist_batch_size`/`persist_on_error` for how to
tune it.
"""

import dataclasses
import enum
import logging
import random
import string
import time
import typing

from slb_glossary import live
from slb_glossary.errors import QueryError
from slb_glossary.live.browser import BrowserSession
from slb_glossary.local import api as local_api
from slb_glossary.local.models import Database
from slb_glossary.models import RelatedTerm, SearchResult

logger = logging.getLogger(__name__)

__all__ = [
    "Source",
    "TermLookup",
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
"""Default `persist_batch_size` for `search`/`get_terms_on`: how many
live results to buffer before writing an incremental upsert batch."""


class Source(enum.Enum):
    """Where a `slb_glossary.query` function is allowed to read/write results from."""

    LOCAL = "local"
    """The local database only. Never touches the network. Requires `db`."""

    LIVE = "live"
    """The live glossary only. Never touches the local database. Requires `session`."""

    AUTO = "auto"
    """Local first, live as a fallback when the local database has nothing.
    See the module docstring for the full behavior."""


T = typing.TypeVar("T")


@dataclasses.dataclass(slots=True, kw_only=True, frozen=True)
class TermLookup(typing.Generic[T]):
    """The outcome of a single-value lookup (`get_term`, `random_term`), with its provenance."""

    value: T
    """The looked-up value itself (e.g. a `SearchResult`, or `None` if nothing was found)."""

    source: Source
    """Which source actually served this lookup: `Source.LOCAL` or `Source.LIVE`"""

    persisted: bool
    """Whether this lookup's result was written to `db` as part of the call
    (only ever `True` for a live result fetched with `persist=True`)."""


def _require(db: Database | None, session: BrowserSession | None, source: Source) -> None:
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
        raise QueryError("`source=Source.LIVE` requires `session` (an open `BrowserSession`).")


def _resolve_source(db: Database | None, session: BrowserSession | None, source: Source) -> Source:
    """Narrow `Source.AUTO` to a starting concrete source given what's available."""
    _require(db, session, source)
    if source is not Source.AUTO:
        return source
    return Source.LOCAL if db is not None else Source.LIVE


async def _maybe_persist(
    db: Database | None, results: typing.Sequence[SearchResult], *, persist: bool, language: str
) -> bool:
    """Upsert `results` into `db` in one shot, for single-value lookups (`get_term` et al).

    `search`/`get_terms_on` use `_persist_incrementally` instead, since
    they stream potentially many results and shouldn't hold them all in
    memory (or lose them all on an error) before writing anything.
    """
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


def _persist_incrementally(
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

    A thin `search`/`get_terms_on`-facing wrapper around
    `slb_glossary.local.upsert_results_incrementally`, which does the
    actual batching/flush-on-error work (and is also what
    `slb_glossary.local.sync`'s `sync_*` functions use, so both
    live-persisting code paths share one implementation).

    :param db: The local database to write to. `results` is passed through
        unchanged (no persistence attempted) if this is `None`.
    :param results: The live result stream to wrap.
    :param persist: If `False`, disables writing entirely; `results` still
        passes through unchanged. Checked once up front so this is a cheap
        no-op wrapper when persistence wasn't requested.
    :param language: Glossary language edition these results were fetched
        in. Passed straight through to `local_api.upsert_results_incrementally`.
    :param batch_size: Number of results to buffer before writing an
        incremental batch. Smaller values save progress more often at the
        cost of more (smaller) database writes; larger values write less
        often but risk losing more unsaved results if something goes wrong
        before the next flush. Defaults to `DEFAULT_PERSIST_BATCH_SIZE`.
    :param persist_on_error: If `True` (the default), flush whatever's
        currently buffered when `results` raises, before letting the
        exception propagate - so an interrupted fetch still saves the
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
    session: BrowserSession | None = None,
    source: Source = Source.AUTO,
    topic: str | None = None,
    start_letter: str | None = None,
    limit: int | None = 3,
    concurrency: int = 1,
    persist: bool = False,
    persist_batch_size: int = DEFAULT_PERSIST_BATCH_SIZE,
    persist_on_error: bool = True,
    fuzzy: bool = False,
) -> typing.AsyncIterator[SearchResult]:
    """
    Search for `query`, reading from `db`/`session` according to `source`.

    With `source=Source.AUTO` (the default when both `db` and
    `session` are given), the local database is searched first; the live
    glossary is only queried if that search comes back empty. Note that
    `start_letter` filtering against the local database is best-effort:
    unlike the live site, the local search only has whatever's already
    been cached.

    :param query: Free-text query.
    :param db: An open local `Database`. Required for `Source.LOCAL`, and
        used as the primary source (and/or cache target) for `Source.AUTO`.
    :param session: An open live `BrowserSession`. Required for `Source.LIVE`,
        and used as the fallback (and/or live source) for `Source.AUTO`.
    :param source: Which source(s) to read from. See the module docstring.
    :param topic: Restrict results to this topic, or several comma-separated topics.
    :param start_letter: Restrict results to terms starting with this letter.
    :param limit: Maximum number of terms to look up. `None` for unlimited.
    :param concurrency: Concurrent term-page fetches, only relevant when a
        live fetch happens. See `slb_glossary.live.search`.
    :param persist: If `True`, and a live fetch happens, write its results
        into `db` (if given) so the next matching call can be served
        locally. Written incrementally as results arrive - see
        `slb_glossary.local.upsert_results_incrementally` - not all at
        once at the end.
    :param persist_batch_size: Number of live results to buffer before each
        incremental write to `db`. Only relevant when `persist=True` and a
        live fetch actually happens.
    :param persist_on_error: If `True` (the default), and `persist=True`,
        save whatever's buffered so far if the live fetch raises partway
        through, instead of losing it.
    :param fuzzy: If `True`, any local-database read (a `Source.LOCAL` read,
        or `Source.AUTO`'s local-first attempt) tolerates minor
        misspellings/partial names in `topic` - see
        `slb_glossary.local.fuzzy_match_topics`. Live reads already
        fuzzy-match topics unconditionally, so this has no effect on them.
    :yield: Matching `SearchResult`s.
    :raises slb_glossary.QueryError: If neither `db` nor `session` is given,
        or the requested `source` needs one that wasn't given.
    """
    started_at = time.monotonic()
    resolved = _resolve_source(db, session, source)
    count = 0
    if resolved is Source.LOCAL:
        assert db is not None
        async for result in local_api.search(db, query, topic=topic, limit=limit, fuzzy=fuzzy):
            count += 1
            yield result
        logger.debug(
            "query.search(%r, source=LOCAL) yielded %d result(s) in %.3fs",
            query,
            count,
            time.monotonic() - started_at,
        )
        return

    if resolved is Source.LIVE or source is not Source.AUTO:
        assert session is not None
        live_stream = live.search(
            session,
            query,
            topic=topic,
            start_letter=start_letter,
            limit=limit,
            concurrency=concurrency,
        )
        async for result in _persist_incrementally(
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
            "query.search(%r, source=LIVE) yielded %d result(s) in %.3fs",
            query,
            count,
            time.monotonic() - started_at,
        )
        return

    # source is Source.AUTO, resolved started as LOCAL: try it, then fall back.
    assert db is not None
    local_results = [
        result
        async for result in local_api.search(db, query, topic=topic, limit=limit, fuzzy=fuzzy)
    ]
    if start_letter:
        local_results = [
            result
            for result in local_results
            if (result.term or "").lower().startswith(start_letter.lower())
        ]
    if local_results:
        logger.debug(
            "Serving search(%r) from the local database (%d result(s) in %.3fs)",
            query,
            len(local_results),
            time.monotonic() - started_at,
        )
        for result in local_results:
            yield result
        return

    if session is None:
        logger.debug(
            "Local database had nothing for search(%r); no session to fall back to", query
        )
        return

    logger.debug(
        "Local database had nothing for search(%r); falling back to the live glossary", query
    )
    live_stream = live.search(
        session,
        query,
        topic=topic,
        start_letter=start_letter,
        limit=limit,
        concurrency=concurrency,
    )
    live_count = 0
    async for result in _persist_incrementally(
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
        "query.search(%r, source=AUTO->LIVE) yielded %d result(s) in %.3fs total",
        query,
        live_count,
        time.monotonic() - started_at,
    )


async def get_terms_on(
    topic: str,
    *,
    db: Database | None = None,
    session: BrowserSession | None = None,
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
    :param session: An open live `BrowserSession`.
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
        misspellings/partial names in `topic` - see
        `slb_glossary.local.fuzzy_match_topics`. Live reads already
        fuzzy-match topics unconditionally, so this has no effect on them.
    :yield: `SearchResult`s filed under `topic`.
    :raises slb_glossary.QueryError: If neither `db` nor `session` is given,
        or the requested `source` needs one that wasn't given.
    """
    started_at = time.monotonic()
    resolved = _resolve_source(db, session, source)
    if resolved is Source.LOCAL:
        assert db is not None
        count = 0
        async for result in local_api.get_terms_on(
            db, topic, start_letter=start_letter, limit=limit, fuzzy=fuzzy
        ):
            count += 1
            yield result
        logger.debug(
            "query.get_terms_on(%r, source=LOCAL) yielded %d result(s) in %.3fs",
            topic,
            count,
            time.monotonic() - started_at,
        )
        return

    if resolved is Source.LIVE or source is not Source.AUTO:
        assert session is not None
        live_stream = live.get_terms_on(
            session, topic, start_letter=start_letter, limit=limit, concurrency=concurrency
        )
        count = 0
        async for result in _persist_incrementally(
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
            "query.get_terms_on(%r, source=LIVE) yielded %d result(s) in %.3fs",
            topic,
            count,
            time.monotonic() - started_at,
        )
        return

    assert db is not None
    local_results = [
        result
        async for result in local_api.get_terms_on(
            db, topic, start_letter=start_letter, limit=limit, fuzzy=fuzzy
        )
    ]
    if local_results:
        logger.debug(
            "Serving get_terms_on(%r) from the local database (%d result(s) in %.3fs)",
            topic,
            len(local_results),
            time.monotonic() - started_at,
        )
        for result in local_results:
            yield result
        return

    if session is None:
        return

    logger.debug(
        "Local database had nothing for topic %r; falling back to the live glossary", topic
    )
    live_stream = live.get_terms_on(
        session, topic, start_letter=start_letter, limit=limit, concurrency=concurrency
    )
    live_count = 0
    async for result in _persist_incrementally(
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
        "query.get_terms_on(%r, source=AUTO->LIVE) yielded %d result(s) in %.3fs total",
        topic,
        live_count,
        time.monotonic() - started_at,
    )


async def get_terms_urls(
    *,
    db: Database | None = None,
    session: BrowserSession | None = None,
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
    :param session: An open live `BrowserSession`.
    :param source: Which source(s) to read from. See the module docstring.
    :param query: Restrict to a free-text query match.
    :param topic: Restrict to this topic, or several comma-separated topics.
    :param start_letter: Restrict to terms starting with this letter.
    :param limit: Maximum number of URLs to yield. `None` for unlimited.
    :param fuzzy: If `True`, any local-database read tolerates minor
        misspellings/partial names in `topic` - see
        `slb_glossary.local.fuzzy_match_topics`. Live reads already
        fuzzy-match topics unconditionally, so this has no effect on them.
    :yield: Matching term detail-page URLs.
    :raises slb_glossary.QueryError: If neither `db` nor `session` is given,
        or the requested `source` needs one that wasn't given.
    """
    resolved = _resolve_source(db, session, source)
    if resolved is Source.LOCAL:
        assert db is not None
        async for url in local_api.get_terms_urls(
            db, query=query, topic=topic, start_letter=start_letter, limit=limit, fuzzy=fuzzy
        ):
            yield url
        return

    if resolved is Source.LIVE or source is not Source.AUTO:
        assert session is not None
        async for url in live.get_terms_urls(
            session, query=query, topic=topic, start_letter=start_letter, limit=limit
        ):
            yield url
        return

    # source is Source.AUTO, resolved started as LOCAL: try it, then fall back.
    assert db is not None
    local_urls = [
        url
        async for url in local_api.get_terms_urls(
            db, query=query, topic=topic, start_letter=start_letter, limit=limit, fuzzy=fuzzy
        )
    ]
    if local_urls:
        logger.debug("Serving `get_terms_urls(...)` from the local database")
        for url in local_urls:
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
        session, query=query, topic=topic, start_letter=start_letter, limit=limit
    ):
        yield url


async def get_topics(
    *,
    db: Database | None = None,
    session: BrowserSession | None = None,
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
    :param session: An open live `BrowserSession`.
    :param source: Which source(s) to read from. `Source.AUTO`
        prefers the local database when it has at least one topic, falling
        back to `session.topics` otherwise. See the module docstring.
    :return: Topic name to term count.
    :raises slb_glossary.QueryError: If neither `db` nor `session` is given,
        or the requested `source` needs one that wasn't given.
    """
    resolved = _resolve_source(db, session, source)
    if resolved is Source.LOCAL:
        assert db is not None
        return await local_api.get_topics(db)

    if resolved is Source.LIVE or source is not Source.AUTO:
        assert session is not None
        return dict(session.topics)

    assert db is not None
    local_topics = await local_api.get_topics(db)
    if local_topics:
        return local_topics

    if session is None:
        return {}
    return dict(session.topics)


async def get_term(
    term_or_url: str,
    *,
    db: Database | None = None,
    session: BrowserSession | None = None,
    source: Source = Source.AUTO,
    persist: bool = False,
) -> TermLookup[SearchResult | None]:
    """
    Look up a single term by exact name or detail-page URL.

    :param term_or_url: An exact (case-insensitive) term name, or a
        glossary term detail-page URL.
    :param db: An open local `Database`.
    :param session: An open live `BrowserSession`.
    :param source: Which source(s) to read from. See the module docstring.
    :param persist: If `True`, and a live fetch happens, cache its result
        into `db`. This is a single-value lookup, so there's only ever one
        result to write - batching doesn't apply here the way it does for
        `search`/`get_terms_on`.
    :return: A `TermLookup` wrapping the found `SearchResult` (or `None` if
        not found by the resolved source(s)), which source actually served
        it, and whether it was cached as a result of this call.
    :raises slb_glossary.QueryError: If neither `db` nor `session` is given,
        or the requested `source` needs one that wasn't given.
    """
    resolved = _resolve_source(db, session, source)
    if resolved is Source.LOCAL:
        assert db is not None
        result = await local_api.get_term(db, term_or_url)
        return TermLookup(value=result, source=Source.LOCAL, persisted=False)

    if resolved is Source.LIVE or source is not Source.AUTO:
        assert session is not None
        result = await _fetch_live_term(session, term_or_url)
        persisted = await _maybe_persist(
            db,
            results=[result] if result else [],
            persist=persist,
            language=session.language.value,
        )
        return TermLookup(value=result, source=Source.LIVE, persisted=persisted)

    assert db is not None
    local_result = await local_api.get_term(db, term_or_url)
    if local_result is not None:
        return TermLookup(value=local_result, source=Source.LOCAL, persisted=False)

    if session is None:
        return TermLookup(value=None, source=Source.LOCAL, persisted=False)

    live_result = await _fetch_live_term(session, term_or_url)
    persisted = await _maybe_persist(
        db,
        results=[live_result] if live_result else [],
        persist=persist,
        language=session.language.value,
    )
    return TermLookup(value=live_result, source=Source.LIVE, persisted=persisted)


async def _fetch_live_term(session: BrowserSession, term_or_url: str) -> SearchResult | None:
    """Resolve `term_or_url` against the live glossary: a URL fetches directly, else it's searched."""
    if term_or_url.startswith(("http://", "https://")):
        async for result in live.get_results_from_url(session, term_or_url):
            return result
        return None

    async for result in live.search(session, term_or_url, limit=1):
        if result.term and result.term.strip().lower() == term_or_url.strip().lower():
            return result
    # No exact (case-insensitive) match among the top result's definitions;
    # fall back to whatever ranked first, if anything did.
    async for result in live.search(session, term_or_url, limit=1):
        return result
    return None


async def related_terms(
    term_or_url: str,
    *,
    db: Database | None = None,
    session: BrowserSession | None = None,
    source: Source = Source.AUTO,
    persist: bool = False,
) -> TermLookup[tuple[RelatedTerm, ...]]:
    """
    Look up the related terms linked from a single term's definition.

    A thin convenience wrapper around `get_term`: fetches the term, then
    returns just its `SearchResult.related` links.

    :param term_or_url: An exact (case-insensitive) term name, or a
        glossary term detail-page URL.
    :param db: An open local `Database`.
    :param session: An open live `BrowserSession`.
    :param source: Which source(s) to read from. See the module docstring.
    :param persist: If `True`, and a live fetch happens, cache the looked-up
        term's own result into `db`.
    :return: A `TermLookup` wrapping the related terms found (empty if
        `term_or_url` wasn't found, or was found but links to nothing).
    :raises slb_glossary.QueryError: If neither `db` nor `session` is given,
        or the requested `source` needs one that wasn't given.
    """
    lookup = await get_term(term_or_url, db=db, session=session, source=source, persist=persist)
    related = lookup.value.related if lookup.value is not None else None
    return TermLookup(value=related or (), source=lookup.source, persisted=lookup.persisted)


async def get_random_term(
    *,
    db: Database | None = None,
    session: BrowserSession | None = None,
    source: Source = Source.AUTO,
    topic: str | None = None,
    persist: bool = False,
    fuzzy: bool = False,
) -> TermLookup[SearchResult | None]:
    """
    Return one randomly chosen term, optionally restricted to a topic.

    For `Source.LIVE` (and `Source.AUTO` falling back to it), there's
    no "random" endpoint on the live site to call, so this samples one term
    detail-page URL from a random starting letter (or, if `topic` is given,
    from that topic) and fetches it.

    :param db: An open local `Database`.
    :param session: An open live `BrowserSession`.
    :param source: Which source(s) to read from. See the module docstring.
        `Source.AUTO` here means "pick locally if the local database
        has anything (matching `topic`, if given), otherwise pick live" -
        not "try local, then live" the way the streaming functions do,
        since a local miss on one random draw says nothing about whether
        the local database is empty.
    :param topic: Restrict the pick to this topic, or several comma-separated topics.
    :param persist: If `True`, and a live pick happens, cache it into `db`.
        A single-value lookup, so batching doesn't apply.
    :param fuzzy: If `True`, a local pick tolerates minor misspellings/
        partial names in `topic` - see `slb_glossary.local.fuzzy_match_topics`.
        Live picks already fuzzy-match topics unconditionally, so this has
        no effect on them.
    :return: A `TermLookup` wrapping the picked `SearchResult`, or `None` if
        nothing matched (empty local database/topic, or no live match found).
    :raises slb_glossary.QueryError: If neither `db` nor `session` is given,
        or the requested `source` needs one that wasn't given.
    """
    resolved = _resolve_source(db, session, source)
    if resolved is Source.LOCAL:
        assert db is not None
        result = await local_api.get_random_term(db, topic=topic, fuzzy=fuzzy)
        return TermLookup(value=result, source=Source.LOCAL, persisted=False)

    if resolved is Source.LIVE or source is not Source.AUTO:
        assert session is not None
        result = await _fetch_live_get_random_term(session, topic=topic)
        persisted = await _maybe_persist(
            db,
            results=[result] if result else [],
            persist=persist,
            language=session.language.value,
        )
        return TermLookup(value=result, source=Source.LIVE, persisted=persisted)

    # AUTO: prefer a local pick when the local database actually has
    # something to pick from; only go live when it doesn't.
    assert db is not None
    local_result = await local_api.get_random_term(db, topic=topic, fuzzy=fuzzy)
    if local_result is not None:
        return TermLookup(value=local_result, source=Source.LOCAL, persisted=False)

    if session is None:
        return TermLookup(value=None, source=Source.LOCAL, persisted=False)

    live_result = await _fetch_live_get_random_term(session, topic=topic, sample_size=25)
    persisted = await _maybe_persist(
        db, [live_result] if live_result else [], persist=persist, language=session.language.value
    )
    return TermLookup(value=live_result, source=Source.LIVE, persisted=persisted)


LETTERS = list(string.ascii_lowercase)


def random_letters(n: int | None = None) -> list[str]:
    """Return a shuffled list of letters a-z, optionally truncated to `n` letters."""
    shuffled = LETTERS[:]
    random.shuffle(shuffled)
    if n is not None:
        shuffled = shuffled[:n]
    return shuffled


async def _fetch_live_get_random_term(
    session: BrowserSession, *, topic: str | None, sample_size: int = 25
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
        for letter in random_letters():
            url_iter = live.get_terms_urls(session, start_letter=letter, limit=sample_size)
            urls = [url async for url in url_iter]
            if urls:
                break

    if not urls:
        return None

    chosen_url = random.choice(urls)
    async for result in live.get_results_from_url(session, chosen_url, topic=topic):
        return result
    return None


async def compare(
    terms: typing.Sequence[str],
    *,
    db: Database | None = None,
    session: BrowserSession | None = None,
    source: Source = Source.AUTO,
    persist: bool = False,
) -> dict[str, TermLookup[SearchResult | None]]:
    """
    Look up several terms at once, for side-by-side comparison.

    :param terms: Term names (or detail-page URLs) to look up. Order is preserved.
    :param db: An open local `Database`.
    :param session: An open live `BrowserSession`.
    :param source: Which source(s) to read from. See the module docstring.
    :param persist: If `True`, cache any live fetches into `db`. Each term
        is looked up (and, on a live fetch, persisted) individually via
        `get_term`, so an error partway through this call still leaves
        earlier terms' results saved.
    :return: `{term_or_url: TermLookup}`, in the order `terms` was given.
        A `TermLookup.value` of `None` means that term wasn't found by the
        resolved source(s).
    :raises slb_glossary.QueryError: If neither `db` nor `session` is given,
        or the requested `source` needs one that wasn't given, or `terms` is empty.
    """
    if not terms:
        raise QueryError("`compare()` needs at least one term to look up.")

    _require(db, session, source)
    started_at = time.monotonic()
    results: dict[str, TermLookup[SearchResult | None]] = {}
    for term in terms:
        results[term] = await get_term(
            term, db=db, session=session, source=source, persist=persist
        )
    elapsed = time.monotonic() - started_at
    logger.debug(
        "compare(%d term(s)) done in %.3fs (avg %.3fs/term)",
        len(terms),
        elapsed,
        elapsed / len(terms),
    )
    return results
