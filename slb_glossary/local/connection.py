"""Opening, closing, and context-managing the local search database."""

import contextlib
import logging
import pathlib
import typing

import aiosqlite

from slb_glossary.local.models import Database, Metadata
from slb_glossary.local.schema import initialize
from slb_glossary.paths import default_db_path, default_metadata_path

logger = logging.getLogger(__name__)

__all__ = ["open_db", "close_db", "local_db"]


def _resolve_metadata_path(
    db_path: pathlib.Path, metadata_path: str | pathlib.Path | None, db_path_was_given: bool
) -> pathlib.Path:
    """Work out where a database's `metadata.json` lives, given its own path."""
    if metadata_path is not None:
        return pathlib.Path(metadata_path)
    if not db_path_was_given:
        return default_metadata_path()
    return db_path.with_name(db_path.stem + ".metadata.json")


async def open_db(
    path: str | pathlib.Path | None = None,
    *,
    metadata_path: str | pathlib.Path | None = None,
) -> Database:
    """
    Open (creating if needed) the local search database at `path`.

    :param path: Path to the SQLite database file. Defaults to
        `slb_glossary.paths.default_db_path()` (the OS-appropriate user
        data directory - see `slb_glossary.paths`).
    :param metadata_path: Path to the metadata JSON file. Defaults to
        `slb_glossary.paths.default_metadata_path()` when `path` is also
        left at its default, or `<path stem>.metadata.json` next to a
        custom `path`.
    :return: An open `Database`. Close it with `close_db`, or use
        `local_db` instead of calling this function directly.
    :raises DatabaseError: If the installed SQLite build lacks FTS5.
    """
    resolved_db_path = pathlib.Path(path) if path is not None else default_db_path()
    resolved_db_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_metadata_path = _resolve_metadata_path(
        db_path=resolved_db_path,
        metadata_path=metadata_path,
        db_path_was_given=path is not None,
    )

    connection = await aiosqlite.connect(resolved_db_path)
    connection.row_factory = aiosqlite.Row
    await initialize(connection)

    if not resolved_metadata_path.exists():
        Metadata().save(resolved_metadata_path)

    logger.info("Opened local glossary database at %s", resolved_db_path)
    return Database(
        connection=connection,
        db_path=resolved_db_path,
        metadata_path=resolved_metadata_path,
    )


async def close_db(db: Database) -> None:
    """
    Close `db`'s connection.

    Safe to call more than once; later calls are no-ops.

    :param db: The local database to close.
    """
    with contextlib.suppress(Exception):
        await db.connection.close()
    logger.info("Closed local glossary database at %s", db.db_path)


@contextlib.asynccontextmanager
async def local_db(
    path: str | pathlib.Path | None = None,
    *,
    metadata_path: str | pathlib.Path | None = None,
) -> typing.AsyncIterator[Database]:
    """
    Open a `Database` for the duration of an `async with` block.

    ```python
    async with local_db(...) as db:
        async for result in search(db, "porosity"):
            print(result)
    ```

    Arguments are the same as `open_db`. The database is always closed on
    exit, including when the block raises.
    """
    db = await open_db(path, metadata_path=metadata_path)
    try:
        yield db
    finally:
        await close_db(db)
