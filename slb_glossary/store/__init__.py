"""
Save search results to a file.

This package has no dependency on the rest of `slb_glossary`: `save` accepts
any sequence (or async iterable) of namedtuple-like records - anything with
`_asdict()` and `_fields`, which `slb_glossary.models.SearchResult` already
provides - so it can save results from this package, results you built
yourself, or records from an entirely different project.
"""

import pathlib
import typing

from .records import RecordLike, materialize_records
from .writers import WRITERS, Writer

__all__ = [
    "RecordLike",
    "UnsupportedFormatError",
    "Writer",
    "writer",
    "register_writer",
    "save",
    "supported_formats",
]


class UnsupportedFormatError(ValueError):
    """Raised when `save` is asked to write a format with no registered writer."""


async def save(
    records: typing.Iterable[RecordLike] | typing.AsyncIterable[RecordLike],
    destination: str | pathlib.Path,
    *,
    format: str | None = None,
) -> None:
    """
    Save `records` to `destination`, choosing a writer by file format.

    `records` may be a plain list, any other sync iterable, or an async
    iterable - including the async generators returned by
    `slb_glossary.search.search` and `slb_glossary.search.get_terms_on`, which
    this collects before writing.

    :param records: The records to save. Each record must support
        `_asdict()` and `_fields`, as `typing.NamedTuple` instances do.
    :param destination: Path to write to. Its extension selects the writer
        to use, unless `format` is given.
    :param format: File format to write, e.g. `"csv"`. Overrides the
        extension on `destination`. See `supported_formats` for the
        built-in choices.
    :raises UnsupportedFormatError: If no writer is registered for the
        resolved format.
    """
    destination = pathlib.Path(destination)
    resolved_format = (format or destination.suffix.lstrip(".") or "txt").lower()

    writer = WRITERS.get(resolved_format)
    if writer is None:
        raise UnsupportedFormatError(
            f"No writer registered for '{resolved_format}' files. "
            f"Supported formats: {', '.join(supported_formats())}. "
            "Register a custom writer with `register_writer`."
        )

    record_list = await materialize_records(records)
    await writer(record_list, destination)


def register_writer(format: str, writer: Writer) -> None:
    """
    Register `writer` as the handler for `format`, adding or replacing it.

    :param format: File extension the writer handles, without a leading
        dot, e.g. `"yaml"`.
    :param writer: An async callable taking `(records, destination)` and
        writing `records` to `destination`. See `slb_glossary.store.writers`
        for examples.
    """
    WRITERS[format.lower().lstrip(".")] = writer


def writer(format: str) -> typing.Callable[[Writer], Writer]:
    """
    Decorator to register a writer function for a given file format.

    :param format: File extension the writer handles, without a leading
        dot, e.g. `"yaml"`.
    :return: A decorator that registers the decorated function as a writer.
    """

    def decorator(func: Writer) -> Writer:
        register_writer(format, func)
        return func

    return decorator


def supported_formats() -> list[str]:
    """Return the file formats `save` currently has a writer for."""
    return sorted(WRITERS.keys())
