"""
API for persisting search results to a store.

`save` is the only function most callers need; `register_writer` (or the
`@writer` decorator) extends it to new file formats without subclassing
anything. See `slb_glossary.store.writers` for the built-in writers and the
shape a custom one should have.
"""

import pathlib
import typing

from .records import RecordLike, materialize_records
from .writers import WRITERS, Writer, records_to_dicts

__all__ = [
    "RecordLike",
    "UnsupportedFormatError",
    "WriterError",
    "Writer",
    "writer",
    "register_writer",
    "records_to_dicts",
    "save",
    "supported_formats",
]


class UnsupportedFormatError(ValueError):
    """Raised when `save` is asked to write a format with no registered writer."""


class WriterError(OSError):
    """
    Raised when a registered writer fails while writing `records`.

    Wraps whatever the writer itself raised (typically an `OSError` from
    the filesystem, but any exception is caught) with the destination path
    and resolved format attached, so callers get useful context without
    needing to inspect the writer's internals. The original exception is
    always available via `__cause__`.
    """

    def __init__(self, message: str, *, destination: pathlib.Path, format: str) -> None:
        super().__init__(message)
        self.destination = destination
        self.format = format


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
    this collects before writing. `destination`'s parent directory is
    created automatically if it doesn't exist yet.

    :param records: The records to save. Each record must support
        `_asdict()` and `_fields`, as `typing.NamedTuple` instances do.
    :param destination: Path to write to. Its extension selects the writer
        to use, unless `format` is given. Missing parent directories are
        created automatically.
    :param format: File format to write, e.g. `"csv"`. Overrides the
        extension on `destination`. See `supported_formats` for the
        built-in choices.
    :raises UnsupportedFormatError: If no writer is registered for the
        resolved format.
    :raises WriterError: If the resolved writer raises while writing -
        commonly a permissions error or a full disk. The original
        exception is chained as `__cause__`.
    """
    destination = pathlib.Path(destination)
    resolved_format = (format or destination.suffix.lstrip(".") or "txt").lower()

    selected_writer = WRITERS.get(resolved_format)
    if selected_writer is None:
        raise UnsupportedFormatError(
            f"No writer registered for '{resolved_format}' files. "
            f"Supported formats: {', '.join(supported_formats())}. "
            "Register a custom writer with `register_writer`."
        )

    record_list = await materialize_records(records)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        await selected_writer(record_list, destination)
    except Exception as exc:
        raise WriterError(
            f"Failed to write {len(record_list)} record(s) to {destination!s} "
            f"as '{resolved_format}': {exc}",
            destination=destination,
            format=resolved_format,
        ) from exc


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
