"""
Local vector store: *bring-your-own-embedding* similarity search over stored terms.

`slb_glossary.local` deliberately doesn't bundle an embedding model as
that would drag in a heavy ML dependency for something most callers won't
use. Instead, this module just stores whatever embedding vector the
caller already computed for a term (with any model they like) and ranks
stored vectors by cosine similarity against a query vector, also supplied
by the caller.
"""

import array
import math
import typing

from slb_glossary.local.api import _row_to_result
from slb_glossary.local.models import Database
from slb_glossary.models import SearchResult

__all__ = ["upsert_vector", "delete_vectors", "vector_search"]


def _pack(embedding: typing.Sequence[float]) -> bytes:
    """Pack a vector of floats into a compact binary blob (32-bit floats)."""
    return array.array("f", embedding).tobytes()


def _unpack(blob: bytes) -> array.array:
    """Unpack a binary blob back into an `array.array` of 32-bit floats."""
    values: array.array = array.array("f")
    values.frombytes(blob)
    return values


def _cosine_similarity(a: typing.Sequence[float], b: typing.Sequence[float]) -> float:
    """Compute cosine similarity between two equal-length vectors, 0.0 if either is a zero vector."""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


async def upsert_vector(
    db: Database, url: str, embedding: typing.Sequence[float], *, model: str = "custom"
) -> None:
    """
    Store (or replace) the embedding vector for a locally stored term.

    :param db: The local database to write to.
    :param url: URL of a term already stored in `db` (see
        `slb_glossary.local.api.upsert_results`). Its vectors are
        removed automatically if that term is later deleted.
    :param embedding: The embedding vector, as computed by whatever model
        the caller chooses.
    :param model: A label identifying which model produced `embedding`,
        e.g. `"text-embedding-3-small"`. `vector_search` only compares
        vectors stored under the same label, so mixed-model vectors for
        one term don't get compared against each other.
    """
    await db.connection.execute(
        """
        INSERT INTO vectors (url, model, dim, embedding)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(url, model) DO UPDATE SET
            dim=excluded.dim, embedding=excluded.embedding
        """,
        (url, model, len(embedding), _pack(embedding)),
    )
    await db.connection.commit()


async def delete_vectors(db: Database, *, model: str | None = None) -> None:
    """
    Delete stored vectors, optionally scoped to one `model`.

    :param db: The local database to write to.
    :param model: If given, only delete vectors stored under this model
        label. Otherwise delete every stored vector.
    """
    if model is None:
        await db.connection.execute("DELETE FROM vectors")
    else:
        await db.connection.execute("DELETE FROM vectors WHERE model = ?", (model,))
    await db.connection.commit()


async def vector_search(
    db: Database,
    query_embedding: typing.Sequence[float],
    *,
    model: str = "custom",
    limit: int = 10,
    min_similarity: float = 0.0,
) -> list[tuple[SearchResult, float]]:
    """
    Rank locally stored terms by cosine similarity to `query_embedding`.

    This is a brute-force scan over every vector stored under `model` which is
    fine for a glossary-sized dataset (thousands of terms), but is not good for
    million-row corpora.

    Compute `query_embedding` with whatever model produced the stored vectors
    (see `upsert_vector`); mismatched dimensions raise, since cosine similarity
    is undefined between them.

    :param db: The local database to search.
    :param query_embedding: The query's embedding vector.
    :param model: Only compare against vectors stored under this model label.
    :param limit: Maximum number of results.
    :param min_similarity: Drop results below this cosine similarity (-1.0 to 1.0).
    :return: `(result, similarity)` pairs, most similar first.
    """
    sql = """
        SELECT terms.*, vectors.embedding FROM vectors
        JOIN terms ON terms.url = vectors.url
        WHERE vectors.model = ?
    """
    scored: list[tuple[SearchResult, float]] = []
    async with db.connection.execute(sql, (model,)) as cursor:
        async for row in cursor:
            stored_embedding = _unpack(row["embedding"])
            similarity = _cosine_similarity(query_embedding, stored_embedding)
            if similarity >= min_similarity:
                scored.append((_row_to_result(row), similarity))

    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:limit]
