"""
Source-aware query API: one set of functions that can read the local
database, the live glossary, or both, without the caller having to
hand-roll the "check local, fall back live, maybe cache what came back"
dance every time.

This is an intermediary layer `slb_glossary.local` and `slb_glossary.engine`
do not provide on their own: `slb_glossary.local.api` only ever reads the
local database, and `slb_glossary.engine` only ever talks to the live site.
Everything here picks between (or combines) the two based on a `Source`.

```python
import slb_glossary as slb
from slb_glossary import query

async with slb.local_db() as db, slb.search_session() as session:
    # Local first; only opens a live page if the local DB has nothing.
    # Whatever came back live is written to `db` so the next call is local-only.
    async for result in query.search(
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
* `Source.INTELLIGENT` (the default when both `db` and `session` are given)
  - try `db` first; only fall back to `session` if the local database has
  nothing for the query. Pass `persist=True` to write whatever came back
  live into `db`, so a repeat lookup is served locally next time.

When only one of `db`/`session` is given, `Source.INTELLIGENT` simply
behaves like whichever of `Source.LOCAL`/`Source.LIVE` that one supports.
"""

import dataclasses
import enum
import logging
import random
import string
import typing

from slb_glossary import live
from slb_glossary.errors import QueryError
from slb_glossary.local import api as local_api
from slb_glossary.local.models import Database
from slb_glossary.models import RelatedTerm, SearchResult, SearchSession

logger = logging.getLogger(__name__)

__all__ = [
    "Source",
    "TermLookup",
    "search",
    "get_terms_on",
    "get_term",
    "related_terms",
    "random_term",
    "compare",
]


class Source(enum.Enum):
    """Where a `slb_glossary.query` function is allowed to read/write results from."""

    LOCAL = "local"
    """The local database only. Never touches the network. Requires `db`."""

    LIVE = "live"
    """The live glossary only. Never touches the local database. Requires `session`."""

    INTELLIGENT = "intelligent"
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


def _require(db: Database | None, session: SearchSession | None, source: Source) -> None:
    """Validate that `db`/`session` actually support the requested `source`."""
    if db is None and session is None:
        raise QueryError(
            "slb_glossary.query needs at least one of `db` or `session` to query anything."
        )
    if source is Source.LOCAL and db is None:
        raise QueryError("source=Source.LOCAL requires `db` (a local_db()/open_db() Database).")
    if source is Source.LIVE and session is None:
        raise QueryError("source=Source.LIVE requires `session` (an open SearchSession).")


def _resolve_source(db: Database | None, session: SearchSession | None, source: Source) -> Source:
    """Narrow `Source.INTELLIGENT` to a starting concrete source given what's available."""
    _require(db, session, source)
    if source is not Source.INTELLIGENT:
        return source
    return Source.LOCAL if db is not None else Source.LIVE


async def _maybe_persist(
    db: Database | None, results: typing.Sequence[SearchResult], *, persist: bool, language: str
) -> bool:
    """Upsert `results` into `db` if `persist` was requested and there's anything to write."""
    if not persist or db is None or not results:
        return False
    written = await local_api.upsert_results(db, results, language=language)
    if written:
        logger.info("Cached %d result(s) fetched live into the local database", written)
    return written > 0


async def search(
    query: str,
    *,
    db: Database | None = None,
    session: SearchSession | None = None,
    source: Source = Source.INTELLIGENT,
    topic: str | None = None,
    start_letter: str | None = None,
    limit: int | None = 3,
    concurrency: int = 1,
    persist: bool = False,
) -> typing.AsyncIterator[SearchResult]:
    """
    Search for `query`, reading from `db`/`session` according to `source`.

    With `source=Source.INTELLIGENT` (the default when both `db` and
    `session` are given), the local database is searched first; the live
    glossary is only queried if that search comes back empty. Note that
    `start_letter` filtering against the local database is best-effort:
    unlike the live site, the local search only has whatever's already
    been cached.

    :param query: Free-text query.
    :param db: An open local `Database`. Required for `Source.LOCAL`, and
        used as the primary source (and/or cache target) for `Source.INTELLIGENT`.
    :param session: An open live `SearchSession`. Required for `Source.LIVE`,
        and used as the fallback (and/or live source) for `Source.INTELLIGENT`.
    :param source: Which source(s) to read from. See the module docstring.
    :param topic: Restrict results to this topic, or several comma-separated topics.
    :param start_letter: Restrict results to terms starting with this letter.
    :param limit: Maximum number of terms to look up. `None` for unlimited.
    :param concurrency: Concurrent term-page fetches, only relevant when a
        live fetch happens. See `slb_glossary.engine.search`.
    :param persist: If `True`, and a live fetch happens, write its results
        into `db` (if given) so the next matching call can be served locally.
    :yield: Matching `SearchResult`s.
    :raises slb_glossary.QueryError: If neither `db` nor `session` is given,
        or the requested `source` needs one that wasn't given.
    """
    resolved = _resolve_source(db, session, source)

    if resolved is Source.LOCAL:
        assert db is not None
        async for result in local_api.search(db, query, topic=topic, limit=limit):
            yield result
        return

    if resolved is Source.LIVE or source is not Source.INTELLIGENT:
        assert session is not None
        results: list[SearchResult] = []
        async for result in live.search(
            session,
            query,
            topic=topic,
            start_letter=start_letter,
            limit=limit,
            concurrency=concurrency,
        ):
            results.append(result)
            yield result
        await _maybe_persist(db, results, persist=persist, language=session.language.value)
        return

    # source is Source.INTELLIGENT, resolved started as LOCAL: try it, then fall back.
    assert db is not None
    local_results = [
        result async for result in local_api.search(db, query, topic=topic, limit=limit)
    ]
    if start_letter:
        local_results = [
            result
            for result in local_results
            if (result.term or "").lower().startswith(start_letter.lower())
        ]
    if local_results:
        logger.debug("Serving search(%r) from the local database", query)
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
    live_results: list[SearchResult] = []
    async for result in live.search(
        session,
        query,
        topic=topic,
        start_letter=start_letter,
        limit=limit,
        concurrency=concurrency,
    ):
        live_results.append(result)
        yield result
    await _maybe_persist(db, live_results, persist=persist, language=session.language.value)


async def get_terms_on(
    topic: str,
    *,
    db: Database | None = None,
    session: SearchSession | None = None,
    source: Source = Source.INTELLIGENT,
    limit: int | None = None,
    concurrency: int = 1,
    persist: bool = False,
) -> typing.AsyncIterator[SearchResult]:
    """
    Yield every term filed under `topic`, reading from `db`/`session` according to `source`.

    Same local-first, live-fallback behavior as `search` for `Source.INTELLIGENT`.

    :param topic: Topic name, or several comma-separated topic names.
    :param db: An open local `Database`.
    :param session: An open live `SearchSession`.
    :param source: Which source(s) to read from. See the module docstring.
    :param limit: Maximum number of terms to yield. `None` for unlimited.
    :param concurrency: Concurrent term-page fetches, only relevant when a
        live fetch happens.
    :param persist: If `True`, and a live fetch happens, cache its results into `db`.
    :yield: `SearchResult`s filed under `topic`.
    :raises slb_glossary.QueryError: If neither `db` nor `session` is given,
        or the requested `source` needs one that wasn't given.
    """
    resolved = _resolve_source(db, session, source)

    if resolved is Source.LOCAL:
        assert db is not None
        async for result in local_api.get_terms_on(db, topic, limit=limit):
            yield result
        return

    if resolved is Source.LIVE or source is not Source.INTELLIGENT:
        assert session is not None
        results: list[SearchResult] = []
        async for result in live.get_terms_on(
            session, topic, limit=limit, concurrency=concurrency
        ):
            results.append(result)
            yield result
        await _maybe_persist(db, results, persist=persist, language=session.language.value)
        return

    assert db is not None
    local_results = [result async for result in local_api.get_terms_on(db, topic, limit=limit)]
    if local_results:
        logger.debug("Serving get_terms_on(%r) from the local database", topic)
        for result in local_results:
            yield result
        return

    if session is None:
        return

    logger.debug(
        "Local database had nothing for topic %r; falling back to the live glossary", topic
    )
    live_results: list[SearchResult] = []
    async for result in live.get_terms_on(session, topic, limit=limit, concurrency=concurrency):
        live_results.append(result)
        yield result
    await _maybe_persist(db, live_results, persist=persist, language=session.language.value)


async def get_term(
    term_or_url: str,
    *,
    db: Database | None = None,
    session: SearchSession | None = None,
    source: Source = Source.INTELLIGENT,
    persist: bool = False,
) -> TermLookup[SearchResult | None]:
    """
    Look up a single term by exact name or detail-page URL.

    :param term_or_url: An exact (case-insensitive) term name, or a
        glossary term detail-page URL.
    :param db: An open local `Database`.
    :param session: An open live `SearchSession`.
    :param source: Which source(s) to read from. See the module docstring.
    :param persist: If `True`, and a live fetch happens, cache its result into `db`.
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

    if resolved is Source.LIVE or source is not Source.INTELLIGENT:
        assert session is not None
        result = await _fetch_live_term(session, term_or_url)
        persisted = await _maybe_persist(
            db, [result] if result else [], persist=persist, language=session.language.value
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


async def _fetch_live_term(session: SearchSession, term_or_url: str) -> SearchResult | None:
    """Resolve `term_or_url` against the live glossary: a URL fetches directly, else it's searched."""
    if term_or_url.startswith(("http://", "https://")):
        async for result in live.iter_results_from_url(session, term_or_url):
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
    session: SearchSession | None = None,
    source: Source = Source.INTELLIGENT,
    persist: bool = False,
) -> TermLookup[tuple[RelatedTerm, ...]]:
    """
    Look up the related terms linked from a single term's definition.

    A thin convenience wrapper around `get_term`: fetches the term, then
    returns just its `SearchResult.related` links.

    :param term_or_url: An exact (case-insensitive) term name, or a
        glossary term detail-page URL.
    :param db: An open local `Database`.
    :param session: An open live `SearchSession`.
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


async def random_term(
    *,
    db: Database | None = None,
    session: SearchSession | None = None,
    source: Source = Source.INTELLIGENT,
    topic: str | None = None,
    persist: bool = False,
) -> TermLookup[SearchResult | None]:
    """
    Return one randomly chosen term, optionally restricted to a topic.

    For `Source.LIVE` (and `Source.INTELLIGENT` falling back to it), there's
    no "random" endpoint on the live site to call, so this samples one term
    detail-page URL from a random starting letter (or, if `topic` is given,
    from that topic) and fetches it.

    :param db: An open local `Database`.
    :param session: An open live `SearchSession`.
    :param source: Which source(s) to read from. See the module docstring.
        `Source.INTELLIGENT` here means "pick locally if the local database
        has anything (matching `topic`, if given), otherwise pick live" -
        not "try local, then live" the way the streaming functions do,
        since a local miss on one random draw says nothing about whether
        the local database is empty.
    :param topic: Restrict the pick to this topic, or several comma-separated topics.
    :param persist: If `True`, and a live pick happens, cache it into `db`.
    :return: A `TermLookup` wrapping the picked `SearchResult`, or `None` if
        nothing matched (empty local database/topic, or no live match found).
    :raises slb_glossary.QueryError: If neither `db` nor `session` is given,
        or the requested `source` needs one that wasn't given.
    """
    resolved = _resolve_source(db, session, source)

    if resolved is Source.LOCAL:
        assert db is not None
        result = await local_api.random_term(db, topic=topic)
        return TermLookup(value=result, source=Source.LOCAL, persisted=False)

    if resolved is Source.LIVE or source is not Source.INTELLIGENT:
        assert session is not None
        result = await _fetch_live_random_term(session, topic=topic)
        persisted = await _maybe_persist(
            db, [result] if result else [], persist=persist, language=session.language.value
        )
        return TermLookup(value=result, source=Source.LIVE, persisted=persisted)

    # INTELLIGENT: prefer a local pick when the local database actually has
    # something to pick from; only go live when it doesn't.
    assert db is not None
    local_result = await local_api.random_term(db, topic=topic)
    if local_result is not None:
        return TermLookup(value=local_result, source=Source.LOCAL, persisted=False)

    if session is None:
        return TermLookup(value=None, source=Source.LOCAL, persisted=False)

    live_result = await _fetch_live_random_term(session, topic=topic)
    persisted = await _maybe_persist(
        db, [live_result] if live_result else [], persist=persist, language=session.language.value
    )
    return TermLookup(value=live_result, source=Source.LIVE, persisted=persisted)


async def _fetch_live_random_term(
    session: SearchSession, *, topic: str | None, sample_size: int = 25
) -> SearchResult | None:
    """Sample up to `sample_size` live term URLs (by topic, or a random letter) and fetch one."""
    urls: list[str] = []
    if topic:
        url_iter = live.iter_term_urls(session, topic=topic, limit=sample_size)
        urls = [url async for url in url_iter]
    else:
        # No topic given: shuffle through starting letters until one yields
        # results, since a purely random letter (e.g. an uncommon one) may
        # have no terms at all.
        letters = list(string.ascii_lowercase)
        random.shuffle(letters)
        for letter in letters:
            url_iter = live.iter_term_urls(session, start_letter=letter, limit=sample_size)
            urls = [url async for url in url_iter]
            if urls:
                break

    if not urls:
        return None

    chosen_url = random.choice(urls)
    async for result in live.iter_results_from_url(session, chosen_url, topic=topic):
        return result
    return None


async def compare(
    terms: typing.Sequence[str],
    *,
    db: Database | None = None,
    session: SearchSession | None = None,
    source: Source = Source.INTELLIGENT,
    persist: bool = False,
) -> dict[str, TermLookup[SearchResult | None]]:
    """
    Look up several terms at once, for side-by-side comparison.

    :param terms: Term names (or detail-page URLs) to look up. Order is preserved.
    :param db: An open local `Database`.
    :param session: An open live `SearchSession`.
    :param source: Which source(s) to read from. See the module docstring.
    :param persist: If `True`, cache any live fetches into `db`.
    :return: `{term_or_url: TermLookup}`, in the order `terms` was given.
        A `TermLookup.value` of `None` means that term wasn't found by the
        resolved source(s).
    :raises slb_glossary.QueryError: If neither `db` nor `session` is given,
        or the requested `source` needs one that wasn't given, or `terms` is empty.
    """
    if not terms:
        raise QueryError("`compare()` needs at least one term to look up.")

    _require(db, session, source)
    results: dict[str, TermLookup[SearchResult | None]] = {}
    for term in terms:
        results[term] = await get_term(
            term, db=db, session=session, source=source, persist=persist
        )
    return results
