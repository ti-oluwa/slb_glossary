"""Functional query API for the local search database."""

import datetime
import json
import typing

import aiosqlite

from slb_glossary.local.models import Database
from slb_glossary.models import RelatedTerm, SearchResult

__all__ = [
    "upsert_results",
    "search",
    "get_terms_on",
    "get_term",
    "random_term",
    "iter_term_urls",
    "iter_topics",
    "count",
]


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

    :param db: The local database to write to.
    :param results: Results to store - a plain or async iterable of
        `SearchResult`, e.g. from `slb_glossary.engine.search`,
        `slb_glossary.engine.get_terms_on`, or `slb_glossary.local.loaders`.
    :param language: Glossary language edition these results were fetched
        in, stored alongside each row.
    :param source: Provenance tag stored alongside each row: `"glossary"`
        for results fetched live from the site (the default), or a
        caller-chosen value such as `"user"` for imported data.
    :return: Number of rows written (results with no `url` don't count).
    """
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    rows: list[tuple[typing.Any, ...]] = []

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
        for result in results:
            row = get_row(result)
            if row is not None:
                rows.append(row)

    if not rows:
        return 0

    await db.connection.executemany(UPSERT_STATEMENT, rows)
    await db.connection.commit()
    return len(rows)


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


async def search(
    db: Database,
    query: str,
    *,
    topic: str | None = None,
    limit: int | None = 20,
) -> typing.AsyncIterator[SearchResult]:
    """
    Full-text search the local database for `query`, best match first.

    Uses SQLite FTS5 with bm25 ranking over each stored term's name,
    definition, and topic. Unlike `slb_glossary.engine.search`, this never
    touches the live glossary site. Results are only as fresh as the
    last `slb_glossary.local.sync` or import.

    :param db: The local database to search.
    :param query: Free-text query, matched against term, definition, and topic.
    :param topic: Restrict results to this topic (case-insensitive exact match).
    :param limit: Maximum number of results. `None` for unlimited.
    :yield: Matching `SearchResult`s, best match first.
    """
    sql = """
        SELECT terms.* FROM terms
        JOIN terms_fts ON terms.rowid = terms_fts.rowid
        WHERE terms_fts MATCH ?
    """
    params: list[typing.Any] = [_to_fts_query(query)]
    if topic:
        sql += " AND terms.topic = ? COLLATE NOCASE"
        params.append(topic)
    sql += " ORDER BY bm25(terms_fts)"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)

    async with db.connection.execute(sql, params) as cursor:
        async for row in cursor:
            yield _row_to_result(row)


async def get_terms_on(
    db: Database, topic: str, *, limit: int | None = None
) -> typing.AsyncIterator[SearchResult]:
    """
    Yield every locally stored term filed under `topic`.

    Unlike `slb_glossary.engine.get_terms_on`, `topic` must match a topic
    name already stored in the local database exactly (case-insensitively)
    - there's no fuzzy topic matching here, since that requires the live
    session's full topic list.

    :param db: The local database to read from.
    :param topic: Topic name, or several comma-separated topic names.
    :param limit: Maximum number of results. `None` for unlimited.
    :yield: `SearchResult`s filed under `topic`, ordered by term name.
    """
    topics = [name.strip() for name in topic.split(",") if name.strip()]
    if not topics:
        return

    placeholders = ", ".join("?" for _ in topics)
    sql = f"SELECT * FROM terms WHERE topic COLLATE NOCASE IN ({placeholders}) ORDER BY term"
    params: list[typing.Any] = list(topics)
    if limit:
        sql += " LIMIT ?"
        params.append(limit)

    async with db.connection.execute(sql, params) as cursor:
        async for row in cursor:
            yield _row_to_result(row)


async def get_term(db: Database, term_or_url: str) -> SearchResult | None:
    """
    Look up a single locally stored term by exact URL or exact term name.

    :param db: The local database to read from.
    :param term_or_url: A glossary term detail-page URL, or an exact
        (case-insensitive) term name.
    :return: The stored `SearchResult`, or `None` if not found locally.
    """
    async with db.connection.execute(
        "SELECT * FROM terms WHERE url = ? OR term = ? COLLATE NOCASE LIMIT 1",
        (term_or_url, term_or_url),
    ) as cursor:
        row = await cursor.fetchone()
    return _row_to_result(row) if row is not None else None


async def random_term(db: Database, *, topic: str | None = None) -> SearchResult | None:
    """
    Return one randomly chosen locally stored term, optionally restricted to a topic.

    :param db: The local database to read from.
    :param topic: Restrict the pick to this topic, or several
        comma-separated topics. `None` picks from every locally stored term.
    :return: A random `SearchResult`, or `None` if the local database (or
        the given topic within it) has no terms stored yet.
    """
    sql = "SELECT * FROM terms"
    params: list[typing.Any] = []
    if topic:
        topics = [name.strip() for name in topic.split(",") if name.strip()]
        if topics:
            placeholders = ", ".join("?" for _ in topics)
            sql += f" WHERE topic COLLATE NOCASE IN ({placeholders})"
            params.extend(topics)
    sql += " ORDER BY RANDOM() LIMIT 1"

    async with db.connection.execute(sql, params) as cursor:
        row = await cursor.fetchone()
    return _row_to_result(row) if row is not None else None


async def iter_term_urls(
    db: Database,
    *,
    query: str | None = None,
    topic: str | None = None,
    start_letter: str | None = None,
    limit: int | None = None,
) -> typing.AsyncIterator[str]:
    """
    Yield locally stored term URLs matching the given filters.

    :param db: The local database to read from.
    :param query: If given, restrict to (and rank by) an FTS5 match on
        this free-text query - see `search`.
    :param topic: Restrict to this topic, or several comma-separated topics.
    :param start_letter: Restrict to terms starting with this letter.
    :param limit: Maximum number of URLs. `None` for unlimited.
    :yield: Matching term URLs.
    """
    if query:
        async for result in search(db, query, topic=topic, limit=limit):
            if start_letter and not (result.term or "").lower().startswith(start_letter.lower()):
                continue
            if url := result.url:
                yield url
        return

    sql = "SELECT url FROM terms WHERE 1=1"
    params: list[typing.Any] = []
    if topic:
        topics = [name.strip() for name in topic.split(",") if name.strip()]
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
        async for row in cursor:
            if url := row["url"]:
                yield url


async def iter_topics(db: Database) -> dict[str, int]:
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
    return counts


async def count(db: Database) -> int:
    """
    Return the total number of terms stored locally.

    :param db: The local database to read from.
    :return: The row count of the `terms` table.
    """
    async with db.connection.execute("SELECT COUNT(*) AS n FROM terms") as cursor:
        row = await cursor.fetchone()
    return row["n"] if row is not None else 0
