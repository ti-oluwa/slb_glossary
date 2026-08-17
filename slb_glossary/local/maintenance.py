"""Flushing and resetting the local database."""

import logging

from slb_glossary.local.types import Database, Metadata

logger = logging.getLogger(__name__)

__all__ = ["flush", "reset"]


async def flush(db: Database) -> None:
    """
    Delete every stored term and vector, keeping the schema and sync history.

    Use this to clear stale data while keeping `metadata.json`'s sync
    timestamps intact e.g. right before a fresh `slb_glossary.local.sync_all`.
    Use `reset` instead to also forget the local database's sync history.

    :param db: The local database to clear.
    """
    await db.connection.execute("DELETE FROM vectors")
    await db.connection.execute("DELETE FROM terms")
    await db.connection.commit()
    await db.connection.execute("VACUUM")
    logger.info("Flushed local glossary database at %s", db.db_path)


async def reset(db: Database) -> None:
    """
    Flush the local database and reset its `metadata.json` (sync history) to defaults.

    :param db: The local database to reset.
    """
    await flush(db)
    Metadata().save(db.metadata_path)
    logger.info("Reset local glossary database at %s", db.db_path)
