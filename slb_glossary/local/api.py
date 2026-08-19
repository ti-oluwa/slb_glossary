"""Functional query API for the local search database."""

import datetime
import json
import logging
import time
import typing
from difflib import get_close_matches

import aiosqlite

from slb_glossary.local.types import Database
from slb_glossary.types import RelatedTerm, SearchResult
from slb_glossary.utils import as_async_iterator

logger = logging.getLogger(__name__)

__all__ = [
    "upsert_results",
    "upsert_results_incrementally",
    "search",
    "scored_search",
    "get_terms_on",
    "get_term",
    "get_random_term",
    "get_terms_urls",
    "get_topics",
    "fuzzy_match_topics",
    "count",
]

DEFAULT_UPSERT_BATCH_SIZE = 20
"""Default `batch_size` for `upsert_results_incrementally`."""

FTS_COLUMN_WEIGHTS: tuple[float, float, float] = (10.0, 1.0, 3.0)
"""
bm25() column weights for `terms_fts`'s `(term, definition, topic)` columns,
in that order. FTS5's default is `1.0` for every column, which lets a
result whose *definition* happens to repeat the query outrank one whose
*term name* actually matches it. 

Weighting `term` well above the others still doesn't fully fix 
this as bm25 also rewards a column for how *often* the query appears in it, 
so a term whose definition just says the query word a lot can still out-score 
the term actually named that. `scored_search` sidesteps this with an 
exact/prefix name-match tier computed directly in SQL, ahead of bm25 entirely, 
see its docstring.
"""


def _dump_related(related: tuple[RelatedTerm, ...] | None) -> str | None:
    """Serialize a `SearchResult.related` tuple to a compact JSON string."""
    if not related:
        return None
    return json.dumps([[link.term, link.url] for link in related])


def _load_related(raw: str | None) -> tuple[RelatedTerm, ...] | None:
    """Deserialize a `related_json` column back into a `SearchResult.related` tuple."""
    if not raw:
        return None
    return tuple(RelatedTerm(term=term, url=url) for term, url in json.loads(raw))


def _row_to_result(row: aiosqlite.Row) -> SearchResult:
    """Build a `SearchResult` from a `terms` row (or a row that at least joins in its columns)."""
    return SearchResult(
        term=row["term"],
        definition=row["definition"],
        grammatical_label=row["grammatical_label"],
        topic=row["topic"],
        url=row["url"],
        image=row["image"],
        image_caption=row["image_caption"],
        related=_load_related(row["related_json"]),
    )


UPSERT_STATEMENT = """
    INSERT INTO terms (
        url, term, definition, grammatical_label, topic, language,
        image, image_caption, related_json, source, fetched_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(url) DO UPDATE SET
        term=excluded.term,
        definition=excluded.definition,
        grammatical_label=excluded.grammatical_label,
        topic=excluded.topic,
        language=excluded.language,
        image=excluded.image,
        image_caption=excluded.image_caption,
        related_json=excluded.related_json,
        source=excluded.source,
        fetched_at=excluded.fetched_at
"""


async def upsert_results(
    db: Database,
    results: typing.Iterable[SearchResult] | typing.AsyncIterable[SearchResult],
    *,
    language: str = "en",
    source: str = "glossary",
) -> int:
    """
    Insert or replace `results` into the local database, keyed by URL.

    A result with no `url` is skipped, since `url` is the local database's
    primary key and there's nothing stable to upsert it against.

    This writes everything in `results` in one go, only once `results` is
    fully consumed. For a live-fetched, potentially long-running stream,
    prefer `upsert_results_incrementally` instead, which writes in batches
    as results arrive rather than holding them all in memory and risking
    losing everything if the fetch is interrupted before this is called.

    :param db: The local database to write to.
    :param results: Results to store - a plain or async iterable of
        `SearchResult`, e.g. from `slb_glossary.live.search`,
        `slb_glossary.live.get_terms_on`, or `slb_glossary.local.loaders`.
    :param language: Glossary language edition these results were fetched
        in, stored alongside each row.
    :param source: Provenance tag stored alongside each row: `"glossary"`
        for results fetched live from the site (the default), or a
        caller-chosen value such as `"user"` for imported data.
    :return: Number of rows written (results with no `url` don't count).
    """
    started_at = time.monotonic()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    rows: list[tuple[typing.Any, ...]] = []
    skipped = 0

    def get_row(result: SearchResult) -> tuple[typing.Any, ...] | None:
        if not result.url:
            return None
        return (
            result.url,
            result.term,
            result.definition,
            result.grammatical_label,
            result.topic,
            language,
            result.image,
            result.image_caption,
            _dump_related(result.related),
            source,
            now,
        )

    if isinstance(results, typing.AsyncIterable):
        async for result in results:
            row = get_row(result)
            if row is not None:
                rows.append(row)
            else:
                skipped += 1
    else:
        for result in results:
            row = get_row(result)
            if row is not None:
                rows.append(row)
            else:
                skipped += 1

    if skipped:
        logger.debug("Skipped %d result(s) with no url during upsert", skipped)

    if not rows:
        logger.debug(
            "upsert_results: nothing to write (0 rows in %.3fs)", time.monotonic() - started_at
        )
        return 0

    await db.connection.executemany(UPSERT_STATEMENT, rows)
    await db.connection.commit()
    elapsed = time.monotonic() - started_at
    logger.info(
        "Upserted %d row(s) into the local database in %.3fs (avg %.3fs/row, source=%r)",
        len(rows),
        elapsed,
        elapsed / len(rows),
        source,
    )
    return len(rows)


async def upsert_results_incrementally(
    db: Database,
    results: typing.Iterable[SearchResult] | typing.AsyncIterable[SearchResult],
    *,
    language: str = "en",
    source: str = "glossary",
    batch_size: int = DEFAULT_UPSERT_BATCH_SIZE,
    persist_on_error: bool = True,
    stats: dict[str, int] | None = None,
) -> typing.AsyncIterator[SearchResult]:
    """
    Wrap `results`, upserting into `db` in batches as they arrive, instead of all at once.

    `upsert_results` only writes once its entire input has been consumed,
    which means the whole stream sits in memory until then, and a stream
    that dies partway through (a browser crash, a network blip, the
    process getting killed) loses everything already fetched, since
    nothing was ever written. This writes to `db` every `batch_size`
    results instead, and again with whatever's left over once `results`
    ends, including when it ends via an exception, if `persist_on_error`
    is `True`. Hence, progress is saved as it happens rather than all at once
    at the very end.

    :param db: The local database to write to.
    :param results: The result stream to wrap. A plain or async iterable.
    :param language: Glossary language edition these results were fetched
        in. Passed straight through to `upsert_results`.
    :param source: Provenance tag stored alongside each row. Passed
        straight through to `upsert_results`.
    :param batch_size: Number of results to buffer before writing an
        incremental batch. Smaller values save progress more often at the
        cost of more (smaller) database writes; larger values write less
        often but risk losing more unsaved results if something goes wrong
        before the next flush.
    :param persist_on_error: If `True` (the default), flush whatever's
        currently buffered when `results` raises, before letting the
        exception propagate, so an interrupted fetch still saves the
        progress it made. If `False`, an exception discards the current,
        not-yet-flushed buffer (results already flushed in earlier batches
        are unaffected either way).
    :param stats: If given, populated in place with `"written"` (total
        rows written) and `"batches"` (number of upsert calls made) once
        this generator is exhausted (normally or via error) - since an
        async generator can't hand back a return value the way a plain
        function can. Callers that only want the final count and don't
        need each result passed through (e.g. `slb_glossary.local.sync`)
        can drain this with `async for _ in ...: pass` and then read `stats`.
    :yield: Every item from `results`, unchanged.
    :raises ValueError: If `batch_size` is less than 1.
    """
    if batch_size < 1:
        raise ValueError("`batch_size` must be at least 1")

    buffer: list[SearchResult] = []
    total_written = 0
    batches_written = 0
    error: BaseException | None = None

    async def _flush() -> None:
        nonlocal buffer, total_written, batches_written
        if not buffer:
            return

        pending, buffer = buffer, []
        written = await upsert_results(db, pending, language=language, source=source)
        total_written += written
        batches_written += 1
        logger.debug(
            "Persisted batch #%d: %d row(s) (%d total so far)",
            batches_written,
            written,
            total_written,
        )

    try:
        async for result in as_async_iterator(results):
            buffer.append(result)
            yield result
            if len(buffer) >= batch_size:
                await _flush()
    except BaseException as exc:
        error = exc
        raise
    finally:
        if buffer and (error is None or persist_on_error):
            try:
                await _flush()
            except Exception:
                logger.warning("Failed to persist the final batch of results", exc_info=True)
        elif buffer:
            logger.debug(
                "Discarding %d unpersisted result(s) after an error (persist_on_error=False)",
                len(buffer),
            )

        if total_written:
            level = logging.WARNING if error is not None else logging.INFO
            logger.log(
                level,
                "Persisted %d row(s) to the local database across %d batch(es)%s",
                total_written,
                batches_written,
                " (interrupted)" if error is not None else "",
            )
        if stats is not None:
            stats["written"] = total_written
            stats["batches"] = batches_written


def _to_fts_query(query: str) -> str:
    """
    Turn free text into a safe FTS5 MATCH query: quoted, prefix-matched tokens ANDed together.

    Quoting each token sidesteps FTS5's own query syntax (so punctuation
    in `query` can't be misread as an FTS operator), and the trailing `*`
    makes each token a prefix match, so `"poros"` finds `"porosity"`.

    :param query: Free-text search input.
    :return: An FTS5 `MATCH` query string equivalent to "every token,
        as a prefix, in any order".
    """
    tokens = query.strip().split()
    if not tokens:
        return '""'
    return " AND ".join(f'"{token}"*' for token in tokens)


def _normalize(text: str) -> str:
    """Lowercase `text` and collapse its whitespace, for the exact/prefix-match SQL params."""
    return " ".join(text.strip().lower().split())


def fuzzy_match_topics(
    topics: typing.Mapping[str, typing.Any] | typing.Iterable[str],
    topic: str,
    *,
    cutoff: float = 0.6,
) -> str:
    """
    Resolve a user-supplied topic name to its closest match(es) among locally stored topics.

    Same difflib-based approach as `slb_glossary.utils.get_topic_match`
    uses for the live glossary's topic list, applied to whatever's actually
    been synced/imported into the local database instead.

    :param topics: Known local topic names, e.g. `get_topics(db)`'s
        return value (or any iterable of topic name strings).
    :param topic: One topic name, or several comma-separated, e.g.
        `"Geophysic,Drillng"`. Matching is case-insensitive and tolerant of
        minor misspellings.
    :param cutoff: Minimum similarity ratio (0-1, per `difflib.get_close_matches`)
        for a candidate to count as a match. Lower values match more loosely.
    :return: The resolved topic name(s), comma-separated, in their
        originally stored casing. A part of `topic` with no close match is
        dropped silently. Returns `""` if `topic` is empty, `topics` is
        empty, or nothing in `topic` matched.
    """
    if not topic:
        return ""

    lowered_to_original = {name.lower(): name for name in topics}
    if not lowered_to_original:
        return ""
    available = list(lowered_to_original)

    resolved: list[str] = []
    for raw_part in topic.split(","):
        candidate = raw_part.strip().lower()
        if not candidate:
            continue
        if candidate in lowered_to_original:
            resolved.append(lowered_to_original[candidate])
            continue
        matches = get_close_matches(candidate, available, n=1, cutoff=cutoff)
        if matches:
            resolved.append(lowered_to_original[matches[0]])

    result = ",".join(dict.fromkeys(resolved))
    if result != topic:
        logger.debug("Fuzzy-matched topic %r -> %r", topic, result)
    return result


async def resolve_topic(db: Database, topic: str | None, fuzzy: bool) -> str | None:
    """
    Resolve a caller-supplied topic filter, optionally fuzzily, against the local database.

    :param db: The local database to read stored topic names from, only
        queried when `fuzzy` is `True`.
    :param topic: Raw topic filter as given by the caller (comma-separated
        for several topics), or `None`/empty for no filter.
    :param fuzzy: If `True`, resolve `topic` against `get_topics(db)` via
        `fuzzy_match_topics` instead of using it as-is.
    :return: The topic filter to apply, or `None`/`""` if there's nothing
        to filter by, including when `fuzzy` is `True` and no locally
        stored topic came close enough to match.
    """
    if not topic:
        return None
    if not fuzzy:
        return topic

    stored_topics = await get_topics(db)
    return fuzzy_match_topics(stored_topics, topic) or None


async def scored_search(
    db: Database,
    query: str,
    *,
    topic: str | None = None,
    start_letter: str | None = None,
    limit: int | None = 20,
    fuzzy: bool = False,
) -> list[tuple[SearchResult, float]]:
    """
    Full-text search the local database for `query`, ranked, scored, best match first.

    Ranking happens entirely in SQL, in two tiers:

    1. An exact (case/whitespace-insensitive) match against `term` scores
       `1.0`; `term` starting with `query` scores `0.9`. Computed directly
       against `terms.term`, so this tier is never affected by how often
       `query` happens to appear elsewhere.
    2. Everything else is ordered by `bm25()`, weighted toward the `term`
       column, see `FTS_COLUMN_WEIGHTS`, and scored by normalizing that
       result set's own bm25 spread into `(0.0, 0.85]`, worst match to
       best. bm25 isn't comparable *across* different queries, only within
       one, which is exactly what this needs it for.

    Tier 1 is always ordered ahead of tier 2, so a term named after the
    query is never outranked by an unrelated term whose definition just
    happens to mention it a lot (e.g. searching "mud" surfacing "Drilling
    fluid" ahead of "Mud" itself, because "mud" is repeated throughout
    that definition) which is the failure mode a purely bm25/word-count-driven
    ranking is prone to.

    `search` is a thin wrapper around this. Pass `scored=True` to it
    instead if you want results and scores together without a second call.
    Reach for this function directly when you only need the scores. For example,
    `slb_glossary.query.search`'s `Source.AUTO` uses it to decide whether
    the local database's results are good enough to serve alone, or worth
    augmenting with a live search.

    :param db: The local database to search.
    :param query: Free-text query, matched against term, definition, and topic.
    :param topic: Restrict results to this topic, or several
        comma-separated topics (case-insensitive exact match by default).
    :param start_letter: Restrict results to terms starting with this letter.
    :param limit: Maximum number of results to return. `None` for unlimited.
    :param fuzzy: If `True`, tolerate minor misspellings/partial names in
        `topic` by resolving it against locally stored topic names first.
        Has no effect if `topic` is falsy.
    :return: `(result, score)` pairs, best match first. `score` is in `[0.0, 1.0]`.
    """
    logger.debug(
        "Local `search` (scored): query=%r topic=%r start_letter=%r limit=%r fuzzy=%r",
        query,
        topic,
        start_letter,
        limit,
        fuzzy,
    )
    started_at = time.monotonic()
    query_norm = _normalize(query)
    weights = ", ".join(str(weight) for weight in FTS_COLUMN_WEIGHTS)
    sql = f"""
        SELECT terms.*,
            (LOWER(terms.term) = ?) AS is_exact,
            (? != '' AND LOWER(terms.term) LIKE ? || '%') AS is_prefix,
            bm25(terms_fts, {weights}) AS bm25_score
        FROM terms
        JOIN terms_fts ON terms.rowid = terms_fts.rowid
        WHERE terms_fts MATCH ?
    """
    params: list[typing.Any] = [query_norm, query_norm, query_norm, _to_fts_query(query)]

    resolved_topic = await resolve_topic(db, topic, fuzzy)
    if resolved_topic:
        topics = [name.strip() for name in resolved_topic.split(",") if name.strip()]
        if topics:
            placeholders = ", ".join("?" for _ in topics)
            sql += f" AND terms.topic COLLATE NOCASE IN ({placeholders})"
            params.extend(topics)

    if start_letter:
        sql += " AND terms.term COLLATE NOCASE LIKE ?"
        params.append(f"{start_letter}%")

    sql += " ORDER BY is_exact DESC, is_prefix DESC, bm25_score ASC"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)

    async with db.connection.execute(sql, params) as cursor:
        rows = await cursor.fetchall()

    # Rows already come back best-first (exact, then prefix, then bm25); no
    # further sorting needed, we only need to turn that order into `[0.0, 1.0]` scores.
    others_bm25 = [
        row["bm25_score"] for row in rows if not row["is_exact"] and not row["is_prefix"]
    ]
    worst = max(others_bm25, default=0.0)  # bm25 is negative-is-better; less negative is worse.
    best = min(others_bm25, default=0.0)
    spread = (worst - best) or 1.0

    scored: list[tuple[SearchResult, float]] = []
    for row in rows:
        if row["is_exact"]:
            score = 1.0
        elif row["is_prefix"]:
            score = 0.9
        else:
            score = round(0.85 * (worst - row["bm25_score"]) / spread, 4)
        scored.append((_row_to_result(row), score))

    elapsed = time.monotonic() - started_at
    logger.debug(
        "Local `search` (scored) for %r yielded %d candidate(s) in %.3fs (best score %.3f)",
        query,
        len(scored),
        elapsed,
        scored[0][1] if scored else 0.0,
    )
    return scored


async def _search(
    db: Database,
    query: str,
    *,
    topic: str | None,
    start_letter: str | None,
    limit: int | None,
    fuzzy: bool,
    scored: bool,
) -> typing.AsyncIterator[typing.Any]:
    results = await scored_search(
        db, query, topic=topic, start_letter=start_letter, limit=limit, fuzzy=fuzzy
    )
    for result, score in results:
        yield (result, score) if scored else result


@typing.overload
def search(
    db: Database,
    query: str,
    *,
    topic: str | None = None,
    start_letter: str | None = None,
    limit: int | None = 20,
    fuzzy: bool = False,
    scored: typing.Literal[False] = False,
) -> typing.AsyncIterator[SearchResult]: ...


@typing.overload
def search(
    db: Database,
    query: str,
    *,
    topic: str | None = None,
    start_letter: str | None = None,
    limit: int | None = 20,
    fuzzy: bool = False,
    scored: typing.Literal[True],
) -> typing.AsyncIterator[tuple[SearchResult, float]]: ...


def search(
    db: Database,
    query: str,
    *,
    topic: str | None = None,
    start_letter: str | None = None,
    limit: int | None = 20,
    fuzzy: bool = False,
    scored: bool = False,
) -> typing.AsyncIterator[SearchResult] | typing.AsyncIterator[tuple[SearchResult, float]]:
    """
    Full-text search the local database for `query`, best match first.

    Built on `scored_search`. Pass `scored=True` to get each result's
    `[0.0, 1.0]` relevance score alongside it, as `(result, score)` pairs,
    instead of calling `scored_search` separately.

    Unlike `slb_glossary.live.search`, this never touches the live
    glossary site; results are only as fresh as the last sync or import.

    :param db: The local database to search.
    :param query: Free-text query, matched against term, definition, and topic.
    :param topic: Restrict results to this topic, or several
        comma-separated topics (case-insensitive exact match by default).
    :param start_letter: Restrict results to terms starting with this letter.
    :param limit: Maximum number of results. `None` for unlimited.
    :param fuzzy: If `True`, tolerate minor misspellings/partial names in
        `topic` by resolving it against locally stored topic names first.
        Has no effect if `topic` is falsy.
    :param scored: If `True`, yield `(result, score)` pairs instead of
        bare results. See `scored_search`.
    :yield: Matching `SearchResult`s, or `(SearchResult, float)` pairs if
        `scored=True`, best match first either way.
    """
    return _search(
        db,
        query,
        topic=topic,
        start_letter=start_letter,
        limit=limit,
        fuzzy=fuzzy,
        scored=scored,
    )


async def get_terms_on(
    db: Database,
    topic: str,
    *,
    start_letter: str | None = None,
    limit: int | None = None,
    fuzzy: bool = False,
) -> typing.AsyncIterator[SearchResult]:
    """
    Yield every locally stored term filed under `topic`.

    By default, `topic` must match a topic name already stored in the
    local database exactly (case-insensitively). Pass `fuzzy=True` to
    tolerate minor misspellings/partial names instead, resolved against
    whatever topics are actually present locally (there's no access to the
    live site's full topic list here, unlike `slb_glossary.live.get_terms_on`).

    :param db: The local database to read from.
    :param topic: Topic name, or several comma-separated topic names.
    :param start_letter: Restrict results to terms starting with this letter.
    :param limit: Maximum number of results. `None` for unlimited.
    :param fuzzy: If `True`, resolve `topic` against locally stored topic
        names first, instead of requiring an exact (case-insensitive) match.
    :yield: `SearchResult`s filed under `topic`, ordered by term name.
    """
    logger.debug(
        "Local `get_terms_on`: topic=%r start_letter=%r limit=%r fuzzy=%r",
        topic,
        start_letter,
        limit,
        fuzzy,
    )
    started_at = time.monotonic()
    resolved_topic = await resolve_topic(db, topic, fuzzy)
    if not resolved_topic:
        logger.debug("No local topic resolved for %r, yielding nothing", topic)
        return

    topics = [name.strip() for name in resolved_topic.split(",") if name.strip()]
    if not topics:
        return

    placeholders = ", ".join("?" for _ in topics)
    sql = f"SELECT * FROM terms WHERE topic COLLATE NOCASE IN ({placeholders})"
    params: list[typing.Any] = list(topics)
    if start_letter:
        sql += " AND term COLLATE NOCASE LIKE ?"
        params.append(f"{start_letter}%")

    sql += " ORDER BY term"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)

    async with db.connection.execute(sql, params) as cursor:
        rows = await cursor.fetchall()

    count_yielded = 0
    for row in rows:
        count_yielded += 1
        yield _row_to_result(row)

    elapsed = time.monotonic() - started_at
    logger.debug(
        "Local `get_terms_on(%r)` yielded %d term(s) in %.3fs", topic, count_yielded, elapsed
    )


async def get_term(db: Database, term_or_url: str) -> SearchResult | None:
    """
    Look up a single locally stored term by exact URL or exact term name.

    :param db: The local database to read from.
    :param term_or_url: A glossary term detail-page URL, or an exact
        (case-insensitive) term name.
    :return: The stored `SearchResult`, or `None` if not found locally.
    """
    logger.debug("Local get_term: %r", term_or_url)
    async with db.connection.execute(
        "SELECT * FROM terms WHERE url = ? OR term = ? COLLATE NOCASE LIMIT 1",
        (term_or_url, term_or_url),
    ) as cursor:
        row = await cursor.fetchone()

    if row is None:
        logger.debug("No local term found for %r", term_or_url)
        return None
    return _row_to_result(row)


async def get_random_term(
    db: Database, *, topic: str | None = None, fuzzy: bool = False
) -> SearchResult | None:
    """
    Return one randomly chosen locally stored term, optionally restricted to a topic.

    :param db: The local database to read from.
    :param topic: Restrict the pick to this topic, or several
        comma-separated topics. `None` picks from every locally stored term.
    :param fuzzy: If `True`, tolerate minor misspellings/partial names in
        `topic` by resolving it against locally stored topic names first.
        Has no effect if `topic` is falsy.
    :return: A random `SearchResult`, or `None` if the local database (or
        the given topic within it) has no terms stored yet.
    """
    logger.debug("Local `get_random_term`: topic=%r fuzzy=%r", topic, fuzzy)
    sql = "SELECT * FROM terms"
    params: list[typing.Any] = []

    resolved_topic = await resolve_topic(db, topic, fuzzy)
    if resolved_topic:
        topics = [name.strip() for name in resolved_topic.split(",") if name.strip()]
        if topics:
            placeholders = ", ".join("?" for _ in topics)
            sql += f" WHERE topic COLLATE NOCASE IN ({placeholders})"
            params.extend(topics)
    sql += " ORDER BY RANDOM() LIMIT 1"

    async with db.connection.execute(sql, params) as cursor:
        row = await cursor.fetchone()

    if row is None:
        logger.debug("No local term available for random pick (topic=%r)", topic)
        return None
    return _row_to_result(row)


async def get_terms_urls(
    db: Database,
    *,
    query: str | None = None,
    topic: str | None = None,
    start_letter: str | None = None,
    limit: int | None = None,
    fuzzy: bool = False,
) -> typing.AsyncIterator[str]:
    """
    Yield locally stored term URLs matching the given filters.

    :param db: The local database to read from.
    :param query: If given, restrict to (and rank by) an FTS5 match on
        this free-text query. See `search`.
    :param topic: Restrict to this topic, or several comma-separated topics.
    :param start_letter: Restrict to terms starting with this letter.
    :param limit: Maximum number of URLs. `None` for unlimited.
    :param fuzzy: If `True`, tolerate minor misspellings/partial names in
        `topic` by resolving it against locally stored topic names first.
        Has no effect if `topic` is falsy.
    :yield: Matching term URLs.
    """
    logger.debug(
        "Local `get_terms_urls`: query=%r topic=%r start_letter=%r limit=%r",
        query,
        topic,
        start_letter,
        limit,
    )
    started_at = time.monotonic()
    yielded = 0

    if query:
        async for result in search(
            db, query, topic=topic, start_letter=start_letter, limit=limit, fuzzy=fuzzy
        ):
            if url := result.url:
                yielded += 1
                yield url

        logger.debug(
            "Local `get_terms_urls(query=%r)` yielded %d url(s) in %.3fs",
            query,
            yielded,
            time.monotonic() - started_at,
        )
        return

    resolved_topic = await resolve_topic(db, topic, fuzzy)
    sql = "SELECT url FROM terms WHERE 1=1"
    params: list[typing.Any] = []
    if resolved_topic:
        topics = [name.strip() for name in resolved_topic.split(",") if name.strip()]
        if topics:
            placeholders = ", ".join("?" for _ in topics)
            sql += f" AND topic COLLATE NOCASE IN ({placeholders})"
            params.extend(topics)

    if start_letter:
        sql += " AND term COLLATE NOCASE LIKE ?"
        params.append(f"{start_letter}%")

    sql += " ORDER BY term"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)

    async with db.connection.execute(sql, params) as cursor:
        rows = await cursor.fetchall()
    for row in rows:
        if url := row["url"]:
            yielded += 1
            yield url

    logger.debug(
        "Local `get_terms_urls` yielded %d url(s) in %.3fs", yielded, time.monotonic() - started_at
    )


async def get_topics(db: Database) -> dict[str, int]:
    """
    Return `{topic: term_count}` for every topic represented in the local database.

    :param db: The local database to read from.
    :return: Topic name to term count, for topics that have at least one
        locally stored term.
    """
    sql = """
        SELECT topic, COUNT(*) AS term_count FROM terms
        WHERE topic IS NOT NULL AND topic != ''
        GROUP BY topic COLLATE NOCASE
        ORDER BY topic COLLATE NOCASE
    """
    counts: dict[str, int] = {}
    async with db.connection.execute(sql) as cursor:
        async for row in cursor:
            counts[row["topic"]] = row["term_count"]

    logger.debug("Local database has %d topic(s) stored", len(counts))
    return counts


async def count(db: Database) -> int:
    """
    Return the total number of terms stored locally.

    :param db: The local database to read from.
    :return: The row count of the `terms` table.
    """
    async with db.connection.execute("SELECT COUNT(*) AS n FROM terms") as cursor:
        row = await cursor.fetchone()

    total = row["n"] if row is not None else 0
    logger.debug("Local database has %d term(s) stored", total)
    return total
