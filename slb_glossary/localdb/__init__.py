"""
Local search database: a SQLite (FTS5) cache of glossary terms, plus an
optional bring-your-own-embedding vector store, so repeat lookups don't
have to keep re-visiting the live site.

Open one with `open_db`/`local_db`, fill it from a live `SearchSession`
(`sync_topics`/`sync_query`/`sync_topic`/`sync_all`) or from your own
CSV/JSON/XLSX file (`slb_glossary.localdb.loaders.load_file`), then query
it with `search`/`get_terms_on`/`get_term`/`iter_term_urls`/`iter_topics` -
the same shapes `slb_glossary.engine`'s live functions return, so code
written against one works against the other. `flush`/`reset` clear it out
again when you're done with it.

**Disclaimer**: the data stored here is still SLB's - see the
`slb_glossary` package docstring for the full notice. Enabling this
module means keeping a local copy of glossary content on your own
machine; you are solely responsible for that copy's lifecycle (how long
you keep it, how often you refresh it, and deleting it when you're done)
in compliance with SLB's terms of use
<https://www.slb.com/en/terms-of-service>. Prefer `sync_query`/`sync_topic`
over `sync_all` where you can - fetching only what you actually look up
keeps this package's footprint on the live site as light as possible.
"""

from slb_glossary.errors import LocalDBError
from slb_glossary.localdb.api import (
    count,
    get_term,
    get_terms_on,
    iter_term_urls,
    iter_topics,
    search,
    upsert_results,
)
from slb_glossary.localdb.connection import close_db, local_db, open_db
from slb_glossary.localdb.loaders import load_file
from slb_glossary.localdb.maintenance import flush, reset
from slb_glossary.localdb.metadata import Metadata
from slb_glossary.localdb.models import LocalDB
from slb_glossary.localdb.sync import SyncSummary, sync_all, sync_query, sync_topic, sync_topics
from slb_glossary.localdb.vectors import delete_vectors, upsert_vector, vector_search

__all__ = [
    "LocalDB",
    "Metadata",
    "LocalDBError",
    "open_db",
    "close_db",
    "local_db",
    "upsert_results",
    "search",
    "get_terms_on",
    "get_term",
    "iter_term_urls",
    "iter_topics",
    "count",
    "load_file",
    "flush",
    "reset",
    "upsert_vector",
    "delete_vectors",
    "vector_search",
    "SyncSummary",
    "sync_topics",
    "sync_query",
    "sync_topic",
    "sync_all",
]
