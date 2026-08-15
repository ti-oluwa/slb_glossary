"""
Sync the local database from a live `BrowserSession`.

Call one of these functions as often (or as rarely) as fits your own use of the glossary; see the
responsible-use note on `sync_all` in particular.
"""

import dataclasses
import datetime
import logging
import time

from slb_glossary.live.api import get_results_from_urls, get_terms_urls
from slb_glossary.live.api import get_terms_on as fetch_terms_on
from slb_glossary.live.api import search as live_search
from slb_glossary.live.browser import BrowserSession
from slb_glossary.local.api import count as count_terms
from slb_glossary.local.api import get_topics, upsert_results
from slb_glossary.local.models import Database, Metadata

logger = logging.getLogger(__name__)

__all__ = [
    "SyncSummary",
    "sync_topics",
    "sync_query",
    "sync_topic",
    "sync_letter",
    "sync_all",
]


@dataclasses.dataclass(slots=True, frozen=True, kw_only=True)
class SyncSummary:
    """Outcome of a `slb_glossary.local.sync` call."""

    terms_written: int
    """Number of term rows inserted or updated by this sync."""

    total_terms: int
    """Total number of terms stored locally after this sync."""

    topics: dict[str, int]
    """`{topic: term_count}` across every term stored locally after this sync."""

    synced_at: str
    """ISO-8601 UTC timestamp this sync completed at."""


async def _record_sync(db: Database, *, terms_written: int, language: str) -> SyncSummary:
    """Recompute the local database's totals and persist them to `metadata.json`."""
    total = await count_terms(db)
    topics = await get_topics(db)

    metadata = Metadata.load(db.metadata_path)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    metadata.last_synced_at = now
    metadata.last_sync_language = language
    metadata.term_count = total
    metadata.topics = topics
    metadata.save(db.metadata_path)

    logger.debug(
        "Recorded sync metadata: %d term(s) written, %d total, %d topic(s)",
        terms_written,
        total,
        len(topics),
    )
    return SyncSummary(
        terms_written=terms_written, total_terms=total, topics=topics, synced_at=now
    )


async def sync_topics(db: Database, session: BrowserSession) -> SyncSummary:
    """
    Refresh the local database's recorded topic list from `session`, without fetching terms.

    Cheap relative to the other sync functions: it only records
    `session.topics`, the counts already captured when the session opened
    (or last refreshed via `slb_glossary.topics.refresh_topics`) and does no
    additional requests to the glossary site.

    :param db: The local database to update.
    :param session: An open `BrowserSession` to read topic counts from.
    :return: A summary of the sync (`terms_written` is always `0`).
    """
    logger.debug("Syncing topic list only (%d topic(s) known to session)", len(session.topics))
    return await _record_sync(db, terms_written=0, language=session.language.value)


async def sync_query(
    db: Database,
    session: BrowserSession,
    query: str,
    *,
    topic: str | None = None,
    start_letter: str | None = None,
    limit: int | None = None,
    concurrency: int = 1,
) -> SyncSummary:
    """
    Fetch `query`'s results from the live glossary and store them locally.

    A lightweight way to keep the local database warm for terms you
    actually look up, without pulling the whole glossary.

    :param db: The local database to write to.
    :param session: An open `BrowserSession` to fetch from.
    :param query: Free-text query, as for `slb_glossary.live.search`.
    :param topic: Restrict the fetch to this topic, or several
        comma-separated topics.
    :param start_letter: Restrict the fetch to terms starting with this letter.
    :param limit: Maximum number of terms to fetch. `None` for unlimited.
    :param concurrency: Concurrent term-page fetches. Keep this low; see
        `slb_glossary.live.get_results_from_urls`'s own note on server load.
    :return: A summary of the sync.
    """
    started_at = time.monotonic()
    logger.info("Syncing query %r to the local database", query)
    results = live_search(
        session,
        query,
        topic=topic,
        start_letter=start_letter,
        limit=limit,
        concurrency=concurrency,
    )
    written = await upsert_results(db, results, language=session.language.value)
    summary = await _record_sync(db, terms_written=written, language=session.language.value)
    logger.info(
        "Synced query %r: %d term(s) written in %.3fs", query, written, time.monotonic() - started_at
    )
    return summary


async def sync_topic(
    db: Database,
    session: BrowserSession,
    topic: str,
    *,
    limit: int | None = None,
    concurrency: int = 1,
) -> SyncSummary:
    """
    Fetch every term filed under `topic` from the live glossary and store them locally.

    :param db: The local database to write to.
    :param session: An open `BrowserSession` to fetch from.
    :param topic: Topic name, or several comma-separated topic names.
    :param limit: Maximum number of terms to fetch. `None` for unlimited.
    :param concurrency: Concurrent term-page fetches.
    :return: A summary of the sync.
    """
    started_at = time.monotonic()
    logger.info("Syncing topic %r to the local database", topic)
    results = fetch_terms_on(session, topic, limit=limit, concurrency=concurrency)
    written = await upsert_results(db, results, language=session.language.value)
    summary = await _record_sync(db, terms_written=written, language=session.language.value)
    logger.info(
        "Synced topic %r: %d term(s) written in %.3fs", topic, written, time.monotonic() - started_at
    )
    return summary


async def sync_letter(
    db: Database,
    session: BrowserSession,
    start_letter: str,
    *,
    topic: str | None = None,
    limit: int | None = None,
    concurrency: int = 1,
) -> SyncSummary:
    """
    Fetch every term starting with `start_letter` from the live glossary and store them locally.

    Useful for incremental updates keyed by the alphabet instead of by
    topic, e.g. syncing `slb-glossary update --start-letter a` through `z`
    over several separate, spaced-out runs.

    :param db: The local database to write to.
    :param session: An open `BrowserSession` to fetch from.
    :param start_letter: The starting letter to restrict the fetch to.
    :param topic: Also restrict the fetch to this topic, or several
        comma-separated topics.
    :param limit: Maximum number of terms to fetch. `None` for unlimited.
    :param concurrency: Concurrent term-page fetches.
    :return: A summary of the sync.
    """
    started_at = time.monotonic()
    logger.info("Syncing letter %r (topic=%r) to the local database", start_letter, topic)
    urls = get_terms_urls(session, topic=topic, start_letter=start_letter, limit=limit)
    results = get_results_from_urls(
        session, urls, topic=topic, concurrency=concurrency, first_only=True
    )
    written = await upsert_results(db, results, language=session.language.value)
    summary = await _record_sync(db, terms_written=written, language=session.language.value)
    logger.info(
        "Synced letter %r: %d term(s) written in %.3fs",
        start_letter,
        written,
        time.monotonic() - started_at,
    )
    return summary


async def sync_all(db: Database, session: BrowserSession, *, concurrency: int = 1) -> SyncSummary:
    """
    Fetch the entire glossary from the live site and store it locally.

    This walks every topic `session` knows about and fetches every term
    filed under it. This is the heaviest sync this module offers, and the one
    most likely to draw attention from the glossary site's own rate
    limiting.

    Use it sparingly, and mind the local-data disclaimer in
    `slb_glossary.local`'s package docstring; `sync_query`/`sync_topic`
    are lighter alternatives for keeping specific terms fresh instead of
    mirroring the whole site.

    :param db: The local database to write to.
    :param session: An open `BrowserSession` to fetch from.
    :param concurrency: Concurrent term-page fetches, per topic.
    :return: A summary of the sync.
    """
    started_at = time.monotonic()
    topic_names = sorted(session.topics)
    logger.info("Syncing entire glossary (%d topics) to local database", len(topic_names))
    total_written = 0
    for index, topic_name in enumerate(topic_names, start=1):
        topic_started_at = time.monotonic()
        results = fetch_terms_on(session, topic_name, concurrency=concurrency)
        written = await upsert_results(db, results, language=session.language.value)
        total_written += written
        elapsed = time.monotonic() - started_at
        logger.debug(
            "Synced topic %d/%d (%r): %d term(s) in %.3fs (%d total so far, %.3fs elapsed, avg %.3fs/topic)",
            index,
            len(topic_names),
            topic_name,
            written,
            time.monotonic() - topic_started_at,
            total_written,
            elapsed,
            elapsed / index,
        )

    summary = await _record_sync(db, terms_written=total_written, language=session.language.value)
    elapsed = time.monotonic() - started_at
    logger.info(
        "Synced entire glossary: %d term(s) written across %d topic(s) in %.3fs (avg %.3fs/topic)",
        total_written,
        len(topic_names),
        elapsed,
        elapsed / len(topic_names) if topic_names else 0.0,
    )
    return summary
