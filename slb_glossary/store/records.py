"""The record shape `slb_glossary.store` saves, and how to collect it."""

import typing

__all__ = ["RecordLike", "materialize_records"]


@typing.runtime_checkable
class RecordLike(typing.Protocol):
    """
    Structural type for anything `slb_glossary.store` can save.

    Any `typing.NamedTuple` instance satisfies this, including
    `slb_glossary.models.SearchResult`. `store` depends only on this
    protocol, never on `SearchResult` itself.
    """

    fields: tuple[str, ...]

    def asdict(self) -> dict[str, typing.Any]: ...


async def materialize_records(
    records: typing.Iterable[RecordLike] | typing.AsyncIterable[RecordLike],
) -> list[RecordLike]:
    """
    Collect `records` into a list, consuming it if it is a lazy iterable.

    :param records: A sync iterable, or an async iterable such as the
        generators `slb_glossary.search` yields results from.
    :return: `records` as a plain list.
    """
    if hasattr(records, "__aiter__"):
        return [record async for record in records]  # type: ignore[union-attr]
    return list(records)  # type: ignore[union-attr]
