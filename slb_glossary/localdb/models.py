"""Data structures for the local search database."""

import dataclasses
import pathlib

import aiosqlite

__all__ = ["LocalDB"]


@dataclasses.dataclass(slots=True, kw_only=True)
class LocalDB:
    """
    An open connection to slb_glossary's local search database.

    Obtain one with `slb_glossary.localdb.open_db`/`local_db`, then pass it
    to the functions in `slb_glossary.localdb.api`,
    `slb_glossary.localdb.vectors`, `slb_glossary.localdb.sync`,
    `slb_glossary.localdb.loaders`, and `slb_glossary.localdb.maintenance`.
    """

    connection: aiosqlite.Connection
    """The open `aiosqlite` connection to the SQLite database file."""

    db_path: pathlib.Path
    """Path to the SQLite database file on disk."""

    metadata_path: pathlib.Path
    """Path to this database's `metadata.json` sync/provenance file."""
