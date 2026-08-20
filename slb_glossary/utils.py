"""Utilities shared across the package."""

import dataclasses
import logging
import sys
import time
import typing
from difflib import get_close_matches

from rich import box
from rich.console import Console
from rich.live import Live
from rich.table import Table

from slb_glossary.types import RecordLike, SearchResult

__all__ = [
    "parse_int",
    "print_records",
    "print_async_records",
    "log_timed_yields",
    "Updatable",
]

logger = logging.getLogger(__name__)

T = typing.TypeVar("T")
UpdatableT = typing.TypeVar("UpdatableT", bound="Updatable")


class Updatable:
    """
    Mixin adding `.update(**changes)` to a `@dataclasses.dataclass`, as a
    shorter, more efficient alternative to `dataclasses.replace` for the
    common case of changing a few top-level fields.

    ```python
    @dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
    class Options(Updatable):
        timeout: float = 30.0
        retries: int = 3

    opts = Options()
    opts2 = opts.update(timeout=60.0)  # instead of dataclasses.replace(opts, timeout=60.0)
    ```

    For a **frozen** dataclass, `update` returns a new instance with
    `changes` applied so `self` is untouched, exactly like
    `dataclasses.replace`, just shorter to write and to chain
    (`config.update(a=1).update(b=2)`).

    For a **non-frozen** one, `update` mutates `self` in place, field by field,
    and returns `self` so a caller that doesn't know (or care) whether a particular config is
    frozen can still call `.update(...)` and either use the return value or not, uniformly.

    `changes` are applied via `dataclasses.replace`/`setattr`.

    Declare this *before* other bases so it doesn't shadow a dataclass
    field actually named `update`, e.g. `class Foo(Updatable): ...` not
    `class Foo(SomethingElse, Updatable): ...` if `SomethingElse` has an
    `update` field/method of its own.
    """

    __slots__ = ()

    def update(self: UpdatableT, **changes: typing.Any) -> UpdatableT:
        """
        Apply `changes` to this dataclass instance.

        :param changes: Field name to new value. Every name must be an
            actual field of this dataclass.
        :return: A new instance with `changes` applied, if this dataclass
            is frozen; `self`, mutated in place, otherwise.
        :raises TypeError: If this class isn't a `dataclasses.dataclass`,
            or `changes` includes a name that isn't one of its fields.
        """
        if not dataclasses.is_dataclass(self):
            raise TypeError(f"`{type(self).__name__}.update()` requires a dataclasses.dataclass.")
        if not changes:
            return self

        valid = {f.name for f in dataclasses.fields(self)}
        unknown = changes.keys() - valid
        if unknown:
            raise TypeError(
                f"`{type(self).__name__}.update()` got unexpected field(s): "
                f"{', '.join(sorted(unknown))}. Expected one of: {', '.join(sorted(valid))}."
            )

        if dataclasses.is_dataclass(self) and type(self).__dataclass_params__.frozen:  # type: ignore[attr-defined]
            return dataclasses.replace(self, **changes)

        for name, value in changes.items():
            setattr(self, name, value)
        return self


def parse_int(text: str) -> int:
    """
    Parse an integer out of glossary page text such as `"1,204"` or `" 42 "`.

    :param text: The text to parse.
    :return: The parsed integer.
    :raises ValueError: If `text` does not contain a valid integer once
        commas and surrounding whitespace are stripped.
    """
    return int(text.replace(",", "").replace(" ", ""))


def get_topic_match(topics: typing.Mapping[str, int], topic: str) -> str:
    """
    Resolve a user-supplied topic name to its closest match in `topics`.

    :param topics: Known glossary topics, as returned by `fetch_topics` or
        held on `Session.topics`.
    :param topic: One topic name, or several separated by commas, e.g.
        `"Geophysics,Geology"`. Matching is case-insensitive and tolerant of
        minor misspellings.
    :return: The resolved topic(s), comma-separated and title-cased, ready
        to pass to `slb_glossary.urls.build_search_url`. Returns `""` if
        `topic` is empty or any of its parts has no close match in `topics`.
    """
    if not topic:
        return topic

    available = [name.lower() for name in topics]
    resolved: list[str] = []
    for raw_part in topic.split(","):
        candidate = raw_part.strip().lower()
        if candidate in available:
            resolved.append(candidate)
            continue

        matches = get_close_matches(candidate, available, n=1, cutoff=0.5)
        if not matches:
            logger.warning("No topic match found for %r", candidate)
            return ""
        resolved.append(matches[0])

    return ",".join(resolved).title()


_ACRONYMS = frozenset({"url", "id"})
"""Field-name words rendered upper-case rather than title-cased by `humanize_field`."""


def humanize_field(field: str) -> str:
    """Turn a `snake_case` field name into a `Title Case` column header."""
    words = field.split("_")
    return " ".join(word.upper() if word in _ACRONYMS else word.title() for word in words)


async def log_timed_yields(
    iterable: typing.AsyncIterable[T],
    *,
    logger: logging.Logger,
    label: str,
    level: int = logging.DEBUG,
) -> typing.AsyncIterator[T]:
    """
    Wrap an async iterator, logging per-yield and running-average timing metrics.

    Every item logs one `level` line with the time since the previous
    yield (or since iteration started, for the first item), the running
    average time per yield so far, and the total elapsed time so far,
    e.g. for spotting a slow tail end of an otherwise-fast fetch. Nothing
    is logged if the wrapped iterator never yields anything.

    This only instruments timing; it doesn't buffer or otherwise change
    what's yielded. `async for item in log_timed_yields(inner, ...)` is
    equivalent to `async for item in inner` except for the added logging.

    :param iterable: The async iterator to wrap.
    :param logger: Logger to emit timing records to.
    :param label: Short description of what's being iterated, included in
        every log line, e.g. `"search(%r)" % query`.
    :param level: Logging level for the per-yield lines.
    :yield: Each item from `iterable`, unchanged.
    """
    start = time.monotonic()
    previous = start
    count = 0
    async for item in iterable:
        now = time.monotonic()
        count += 1
        elapsed = now - start
        logger.log(
            level,
            "`%s`: yield #%d took %.3fs (avg %.3fs/yield so far, %.3fs elapsed total)",
            label,
            count,
            now - previous,
            elapsed / count,
            elapsed,
        )
        previous = now
        yield item


def as_async_iterator(
    results: typing.Iterable[T] | typing.AsyncIterable[T],
) -> typing.AsyncIterator[T]:
    """Normalize a sync or async iterable of items `T` into an async iterator."""

    async def _wrap_sync(
        sync_results: typing.Iterable[T],
    ) -> typing.AsyncIterator[T]:
        for result in sync_results:
            yield result

    if isinstance(results, typing.AsyncIterable):
        return results.__aiter__()
    return _wrap_sync(results)


def _format_cell(value: typing.Any, *, max_related_shown: int = 6) -> str:
    """
    Render an arbitrary record field value as printable table cell text.

    Handles the shapes records actually carry: `None`, a
    single `RelatedTerm`-like `NamedTuple`, and lists/tuples of those (e.g.
    `SearchResult.related`). Trims long lists rather than flooding the
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

    if isinstance(value, RecordLike) or hasattr(value, "asdict"):
        record_dict = value.asdict()
        fallback = next(iter(record_dict.values()), "-")
        return str(record_dict.get("term") or record_dict.get("name") or fallback)

    text = str(value).strip()
    return text or "-"


DEFAULT_RESULT_TABLE_TITLE = "Search Results"
"""Default table title used by `print_records`/`print_async_records` for `SearchResult`s."""

DEFAULT_GENERIC_TABLE_TITLE = "Results"
"""Default table title used by `print_records`/`print_async_records` for non-`SearchResult` records."""


def _make_result_table(
    *,
    title: str | None = None,
    show_url: bool = True,
    show_topic: bool = True,
    show_grammar: bool = True,
    show_image: bool = False,
    show_related: bool = False,
    show_origin: bool = False,
    show_score: bool = False,
) -> Table:
    """Build the specialized table used to display `SearchResult`s."""
    table = Table(
        title=title or DEFAULT_RESULT_TABLE_TITLE,
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
    if show_origin:
        table.add_column("Origin", style="bright_black", no_wrap=True)
    if show_score:
        table.add_column("Score", style="bright_black", no_wrap=True)
    return table


def _format_result_row(
    result: SearchResult,
    *,
    show_url: bool = True,
    show_topic: bool = True,
    show_grammar: bool = True,
    show_image: bool = False,
    show_related: bool = False,
    show_origin: bool = False,
    show_score: bool = False,
    origin: str | None = None,
    score: float | None = None,
) -> list[str]:
    """
    Build one table row for a `SearchResult`, matching `_make_result_table`'s columns.

    :param show_origin: Whether to append an "Origin" cell. Must match
        whatever `_make_result_table` was built with.
    :param show_score: Whether to append a "Score" cell. Must match
        whatever `_make_result_table` was built with.
    :param origin: Text for the "Origin" cell, e.g. `"local"`/`"live"`.
        Rendered as `"-"` if `None`. Ignored unless `show_origin=True`.
    :param score: Value for the "Score" cell, e.g. a `LookupResult.score`.
        Rendered as `"-"` if `None` (expected for a result with no
        comparable score, e.g. most live ones). Ignored unless `show_score=True`.
    """
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
    if show_origin:
        row.append(origin or "-")
    if show_score:
        row.append(f"{score:.2f}" if score is not None else "-")
    return row


def _make_generic_table(
    fields: typing.Sequence[str],
    *,
    title: str | None = None,
    show_origin: bool = False,
    show_score: bool = False,
) -> Table:
    """Build a plain table with one humanized column per field, for non-`SearchResult` records."""
    table = Table(
        title=title or DEFAULT_GENERIC_TABLE_TITLE,
        title_style="bold bright_blue",
        box=box.HEAVY,
        expand=True,
        show_lines=True,
    )
    for field in fields:
        table.add_column(humanize_field(field), style="white", overflow="fold")
    if show_origin:
        table.add_column("Origin", style="bright_black", no_wrap=True)
    if show_score:
        table.add_column("Score", style="bright_black", no_wrap=True)
    return table


def _format_generic_row(
    record: typing.Any,
    fields: typing.Sequence[str],
    *,
    show_origin: bool = False,
    show_score: bool = False,
    origin: str | None = None,
    score: float | None = None,
) -> list[str]:
    """Build one table row for an arbitrary `RecordLike`, matching `_make_generic_table`'s columns."""
    record_dict = record.asdict()
    row = [_format_cell(record_dict.get(field)) for field in fields]
    if show_origin:
        row.append(origin or "-")
    if show_score:
        row.append(f"{score:.2f}" if score is not None else "-")
    return row


@typing.runtime_checkable
class _Lookup(typing.Protocol):
    """
    Structural shape `annotate=True` table/JSON output needs from each
    item: satisfied by `slb_glossary.query.LookupResult`, without
    importing that class directly (`slb_glossary.query` itself depends
    on this module, so importing it back here would be circular).
    """

    value: typing.Any
    source: typing.Any
    """A `slb_glossary.query.Source` member; only `.value` (its string name) is used."""
    score: float | None


RecordT = typing.TypeVar("RecordT", bound=RecordLike)


def _make_table_and_formatter(
    sample: RecordT,
    *,
    title: str | None,
    show_url: bool,
    show_topic: bool,
    show_grammar: bool,
    show_image: bool,
    show_related: bool,
    annotate: bool = False,
) -> tuple[Table, typing.Callable[[RecordT], list[str]]]:
    """
    Choose a table layout and row formatter suited to `sample`'s record type.

    `slb_glossary`'s CLI prints several record shapes through this same
    function (search results, but also plain URL/topic listings), so this
    dispatches on the *first* item seen rather than assuming every caller
    is printing `SearchResult`s.

    :param sample: The first record to be printed, used only to pick a
        layout. With `annotate=True`, this is a `_Lookup`-shaped item
        (e.g. a `slb_glossary.query.LookupResult`), not the bare record itself.
    :param title: Table/section title to use instead of the type-based
        default (`"Search Results"` for `SearchResult`s, `"Results"`
        otherwise). `None` keeps that default.
    :param annotate: If `True`, add "Origin"/"Score" columns, and expect
        every record passed to the returned formatter to be `_Lookup`-shaped
        (`.value`/`.source`/`.score`) rather than a bare record.
    :return: A `(table, formatter)` pair; call `formatter(record)` for
        every record (including `sample`) to get its row cells.
    """
    record_sample = sample.value if annotate else sample  # type: ignore[union-attr]

    if isinstance(record_sample, SearchResult):
        table = _make_result_table(
            title=title,
            show_url=show_url,
            show_topic=show_topic,
            show_grammar=show_grammar,
            show_image=show_image,
            show_related=show_related,
            show_origin=annotate,
            show_score=annotate,
        )

        def _result_formatter(record: RecordT) -> list[str]:
            result, origin, score = _unwrap(record, annotate=annotate)
            return _format_result_row(
                result,
                show_url=show_url,
                show_topic=show_topic,
                show_grammar=show_grammar,
                show_image=show_image,
                show_related=show_related,
                show_origin=annotate,
                show_score=annotate,
                origin=origin,
                score=score,
            )

        return table, _result_formatter

    fields = list(getattr(record_sample, "fields", None) or record_sample.asdict().keys())
    table = _make_generic_table(fields, title=title, show_origin=annotate, show_score=annotate)

    def _generic_formatter(record: RecordT) -> list[str]:
        rec, origin, score = _unwrap(record, annotate=annotate)
        return _format_generic_row(
            rec, fields, show_origin=annotate, show_score=annotate, origin=origin, score=score
        )

    return table, _generic_formatter


def _unwrap(record: typing.Any, *, annotate: bool) -> tuple[typing.Any, str | None, float | None]:
    """Split a possibly `_Lookup`-wrapped `record` into `(record, origin, score)`."""
    if not annotate:
        return record, None, None
    lookup = typing.cast(_Lookup, record)
    return lookup.value, lookup.source.value, lookup.score


def print_records(
    results: typing.Iterable[RecordLike],
    *,
    title: str | None = None,
    out: typing.TextIO | None = None,
    limit: int | None = None,
    show_url: bool = True,
    show_topic: bool = True,
    show_grammar: bool = True,
    show_image: bool = False,
    show_related: bool = False,
    annotate: bool = False,
) -> int:
    """
    Pretty-print a sequence of records to `out` as a table.

    Works with any `slb_glossary.types.RecordLike` (`SearchResult`s get a
    specialized layout with `show_*` column toggles; any other record type
    gets a generic table with one column per field), and with any iterable,
    including lazily produced generators.

    :param results: The records to print. May be empty. With
        `annotate=True`, each item is expected to be `_Lookup`-shaped
        (e.g. a `slb_glossary.query.LookupResult`) rather than a bare record.
    :param title: Title shown above the table, e.g. `"Terms under Drilling"`.
        Defaults to `"Search Results"` for `SearchResult`s, or `"Results"`
        for any other record type.
    :param out: Stream to print to. Defaults to `sys.stdout`.
    :param limit: Maximum number of records to print. Prints every record
        if `None`.
    :param show_url: For `SearchResult`s, whether to show the source URL column.
    :param show_topic: For `SearchResult`s, whether to show the topic column.
    :param show_grammar: For `SearchResult`s, whether to show the grammatical label column.
    :param show_image: For `SearchResult`s, whether to show the image URL column.
    :param show_related: For `SearchResult`s, whether to show the related-terms column.
    :param annotate: If `True`, add "Origin"/"Score" columns, reading them
        off each `_Lookup`-shaped item, instead of printing bare records.
    :return: The number of records printed.
    """
    if out is None:
        out = sys.stdout
    console = Console(file=out)

    iterator = iter(results)
    try:
        first = next(iterator)
    except StopIteration:
        console.print(_make_generic_table([], title=title))
        return 0

    table, format_row = _make_table_and_formatter(
        first,
        title=title,
        show_url=show_url,
        show_topic=show_topic,
        show_grammar=show_grammar,
        show_image=show_image,
        show_related=show_related,
        annotate=annotate,
    )

    def _records() -> typing.Iterator[RecordLike]:
        yield first
        yield from iterator

    count = 0
    if console.is_terminal:
        with Live(table, console=console, refresh_per_second=8, transient=False) as live:
            for record in _records():
                if limit is not None and count >= limit:
                    break
                table.add_row(*format_row(record))
                live.update(table)
                count += 1
        return count

    for record in _records():
        if limit is not None and count >= limit:
            break
        table.add_row(*format_row(record))
        count += 1

    console.print(table)
    return count


async def print_async_records(
    results: typing.AsyncIterable[RecordLike],
    *,
    title: str | None = None,
    out: typing.TextIO | None = None,
    limit: int | None = None,
    show_url: bool = True,
    show_topic: bool = True,
    show_grammar: bool = True,
    show_image: bool = False,
    show_related: bool = False,
    annotate: bool = False,
) -> int:
    """Pretty-print an async stream of records as they are yielded. See `print_records`."""
    if out is None:
        out = sys.stdout
    console = Console(file=out)

    iterator = results.__aiter__()
    try:
        first = await iterator.__anext__()
    except StopAsyncIteration:
        console.print(_make_generic_table([], title=title))
        return 0

    table, format_row = _make_table_and_formatter(
        first,
        title=title,
        show_url=show_url,
        show_topic=show_topic,
        show_grammar=show_grammar,
        show_image=show_image,
        show_related=show_related,
        annotate=annotate,
    )

    async def _records() -> typing.AsyncIterator[RecordLike]:
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
