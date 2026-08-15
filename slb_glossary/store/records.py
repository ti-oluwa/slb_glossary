"""The record shape `slb_glossary.store` saves, and how to collect it."""

import typing
from collections.abc import AsyncIterable, Sequence

__all__ = ["RecordLike", "materialize_records"]


@typing.runtime_checkable
class RecordLike(typing.Protocol):
    """
    Structural type for anything `slb_glossary.store` can save.
    """

    @property
    def fields(self) -> Sequence[str]:
        """Return a list of the field names in this record."""
        ...

    def asdict(self) -> dict[str, typing.Any]:
        """Return a dict mapping each field name to its value in this record."""
        ...


async def materialize_records(
    records: typing.Iterable[RecordLike] | typing.AsyncIterable[RecordLike],
) -> list[RecordLike]:
    """
    Collect `records` into a list, consuming it if it is a lazy iterable.

    :param records: A sync iterable, or an async iterable such as the
        generators `slb_glossary.search` yields results from.
    :return: `records` as a plain list.
    """
    if isinstance(records, AsyncIterable):
        return [record async for record in records]
    return list(records)
