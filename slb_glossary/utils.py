"""Utilities shared across the package."""

import sys
import typing

from rich import box
from rich.console import Console
from rich.live import Live
from rich.table import Table

from slb_glossary.models import SearchResult

__all__ = ["parse_int", "print_results", "async_print_results"]


def parse_int(text: str) -> int:
    """
    Parse an integer out of glossary page text such as `"1,204"` or `" 42 "`.

    :param text: The text to parse.
    :return: The parsed integer.
    :raises ValueError: If `text` does not contain a valid integer once
        commas and surrounding whitespace are stripped.
    """
    return int(text.replace(",", "").replace(" ", ""))


_ACRONYMS = frozenset({"url", "id"})
"""Field-name words rendered upper-case rather than title-cased by `humanize_field`."""


def humanize_field(field: str) -> str:
    """Turn a `snake_case` field name into a `Title Case` column header."""
    words = field.split("_")
    return " ".join(word.upper() if word in _ACRONYMS else word.title() for word in words)


def _format_cell(value: typing.Any, *, max_related_shown: int = 6) -> str:
    """
    Render an arbitrary record field value as printable table cell text.

    Handles the shapes records actually carry: `None`, a
    single `RelatedTerm`-like `NamedTuple`, and lists/tuples of those (e.g.
    `SearchResult.related`) - trimming long lists rather than flooding the
    cell, since this is for a terminal table, not a file export.

    :param value: A field value from `record.asdict()`.
    :param max_related_shown: Maximum number of items to list from a
        list/tuple value before summarizing the rest as `"+N more"`.
    :return: Cell text. Never `None`; empty/missing values render as `"-"`.
    """
    if value is None:
        return "-"
    if isinstance(value, (list, tuple)):
        if not value:
            return "-"
        names = [_format_cell(item) for item in value]
        if len(names) > max_related_shown:
            shown = ", ".join(names[:max_related_shown])
            return f"{shown}, +{len(names) - max_related_shown} more"
        return ", ".join(names)
    if hasattr(value, "asdict"):
        record_dict = value.asdict()
        fallback = next(iter(record_dict.values()), "-")
        return str(record_dict.get("term") or record_dict.get("name") or fallback)
    text = str(value).strip()
    return text or "-"


def _make_result_table(
    *,
    show_url: bool = True,
    show_topic: bool = True,
    show_grammar: bool = True,
    show_image: bool = False,
    show_related: bool = False,
) -> Table:
    """Build the specialized table used to display `SearchResult`s."""
    table = Table(
        title="Search Results",
        title_style="bold bright_blue",
        box=box.HEAVY,
        expand=True,
        show_lines=True,
    )
    table.add_column("Term", style="bold magenta", no_wrap=True)
    if show_grammar:
        table.add_column("Grammar", style="cyan", no_wrap=True)
    if show_topic:
        table.add_column("Topic", style="green", no_wrap=True)
    table.add_column("Definition", style="white")
    if show_related:
        table.add_column("Related", style="yellow")
    if show_image:
        table.add_column("Image", style="blue", overflow="fold")
    if show_url:
        table.add_column("Source", style="blue", overflow="fold")
    return table


def _format_result_row(
    result: SearchResult,
    *,
    show_url: bool = True,
    show_topic: bool = True,
    show_grammar: bool = True,
    show_image: bool = False,
    show_related: bool = False,
) -> list[str]:
    """Build one table row for a `SearchResult`, matching `_make_result_table`'s columns."""
    definition = result.definition.strip() if result.definition else "(no definition parsed)"
    row: list[str] = [result.term]
    if show_grammar:
        row.append(result.grammatical_label or "-")
    if show_topic:
        row.append(result.topic or "-")
    row.append(definition)
    if show_related:
        row.append(_format_cell(result.related))
    if show_image:
        if not result.image_caption:
            row.append(result.image or "-")
        else:
            row.append(f"{result.image_caption} - {result.image}")
    if show_url:
        row.append(result.url or "-")
    return row


def _make_generic_table(fields: typing.Sequence[str]) -> Table:
    """Build a plain table with one humanized column per field, for non-`SearchResult` records."""
    table = Table(
        title="Results",
        title_style="bold bright_blue",
        box=box.HEAVY,
        expand=True,
        show_lines=True,
    )
    for field in fields:
        table.add_column(humanize_field(field), style="white", overflow="fold")
    return table


def _format_generic_row(record: typing.Any, fields: typing.Sequence[str]) -> list[str]:
    """Build one table row for an arbitrary `RecordLike`, matching `_make_generic_table`'s columns."""
    record_dict = record.asdict()
    return [_format_cell(record_dict.get(field)) for field in fields]


def _make_table_and_formatter(
    sample: typing.Any,
    *,
    show_url: bool,
    show_topic: bool,
    show_grammar: bool,
    show_image: bool,
    show_related: bool,
) -> tuple[Table, typing.Callable[[typing.Any], list[str]]]:
    """
    Choose a table layout and row formatter suited to `sample`'s record type.

    `slb_glossary`'s CLI prints several record shapes through this same
    function (search results, but also plain URL/topic listings), so this
    dispatches on the *first* item seen rather than assuming every caller
    is printing `SearchResult`s.

    :param sample: The first record to be printed, used only to pick a layout.
    :return: A `(table, formatter)` pair; call `formatter(record)` for
        every record (including `sample`) to get its row cells.
    """
    if isinstance(sample, SearchResult):
        table = _make_result_table(
            show_url=show_url,
            show_topic=show_topic,
            show_grammar=show_grammar,
            show_image=show_image,
            show_related=show_related,
        )

        def _result_formatter(record: SearchResult) -> list[str]:
            return _format_result_row(
                record,
                show_url=show_url,
                show_topic=show_topic,
                show_grammar=show_grammar,
                show_image=show_image,
                show_related=show_related,
            )

        return table, _result_formatter

    fields = list(getattr(sample, "fields", None) or sample.asdict().keys())
    table = _make_generic_table(fields)

    def _generic_formatter(record: typing.Any) -> list[str]:
        return _format_generic_row(record, fields)

    return table, _generic_formatter


def print_results(
    results: typing.Iterable[typing.Any],
    *,
    out: typing.TextIO | None = None,
    limit: int | None = None,
    show_url: bool = True,
    show_topic: bool = True,
    show_grammar: bool = True,
    show_image: bool = False,
    show_related: bool = False,
) -> int:
    """
    Pretty-print a sequence of records to `out` as a table.

    Works with any `slb_glossary.store.RecordLike` (`SearchResult`s get a
    specialized layout with `show_*` column toggles; any other record type
    gets a generic table with one column per field), and with any iterable,
    including lazily produced generators.

    :param results: The records to print. May be empty.
    :param out: Stream to print to. Defaults to `sys.stdout`.
    :param limit: Maximum number of records to print. Prints every record
        if `None`.
    :param show_url: For `SearchResult`s, whether to show the source URL column.
    :param show_topic: For `SearchResult`s, whether to show the topic column.
    :param show_grammar: For `SearchResult`s, whether to show the grammatical label column.
    :param show_image: For `SearchResult`s, whether to show the image URL column.
    :param show_related: For `SearchResult`s, whether to show the related-terms column.
    :return: The number of records printed.
    """
    if out is None:
        out = sys.stdout
    console = Console(file=out)

    iterator = iter(results)
    try:
        first = next(iterator)
    except StopIteration:
        console.print(_make_generic_table([]))
        return 0

    table, format_row = _make_table_and_formatter(
        first,
        show_url=show_url,
        show_topic=show_topic,
        show_grammar=show_grammar,
        show_image=show_image,
        show_related=show_related,
    )

    def _remaining() -> typing.Iterator[typing.Any]:
        yield first
        yield from iterator

    count = 0
    if console.is_terminal:
        with Live(table, console=console, refresh_per_second=8, transient=False) as live:
            for record in _remaining():
                if limit is not None and count >= limit:
                    break
                table.add_row(*format_row(record))
                live.update(table)
                count += 1
        return count

    for record in _remaining():
        if limit is not None and count >= limit:
            break
        table.add_row(*format_row(record))
        count += 1

    console.print(table)
    return count


async def async_print_results(
    results: typing.AsyncIterable[typing.Any],
    *,
    out: typing.TextIO | None = None,
    limit: int | None = None,
    show_url: bool = True,
    show_topic: bool = True,
    show_grammar: bool = True,
    show_image: bool = False,
    show_related: bool = False,
) -> int:
    """Pretty-print an async stream of records as they are yielded. See `print_results`."""
    if out is None:
        out = sys.stdout
    console = Console(file=out)

    iterator = results.__aiter__()
    try:
        first = await iterator.__anext__()
    except StopAsyncIteration:
        console.print(_make_generic_table([]))
        return 0

    table, format_row = _make_table_and_formatter(
        first,
        show_url=show_url,
        show_topic=show_topic,
        show_grammar=show_grammar,
        show_image=show_image,
        show_related=show_related,
    )

    async def _records() -> typing.AsyncIterator[typing.Any]:
        yield first
        async for record in iterator:
            yield record

    count = 0
    if console.is_terminal:
        with Live(table, console=console, refresh_per_second=8, transient=False) as live:
            async for record in _records():
                if limit is not None and count >= limit:
                    break
                table.add_row(*format_row(record))
                live.update(table)
                count += 1
        return count

    async for record in _records():
        if limit is not None and count >= limit:
            break
        table.add_row(*format_row(record))
        count += 1

    console.print(table)
    return count
