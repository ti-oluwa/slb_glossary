"""Utilities shared across the package."""

import sys
import typing

from rich import box
from rich.console import Console
from rich.live import Live
from rich.table import Table

from .models import SearchResult

__all__ = ["parse_int", "print_results", "print_results_async"]


def parse_int(text: str) -> int:
    """
    Parse an integer out of glossary page text such as `"1,204"` or `" 42 "`.

    :param text: The text to parse.
    :return: The parsed integer.
    :raises ValueError: If `text` does not contain a valid integer once
        commas and surrounding whitespace are stripped.
    """
    return int(text.replace(",", "").replace(" ", ""))


def _make_results_table(
    *,
    show_url: bool = True,
    show_topic: bool = True,
    show_grammar: bool = True,
) -> Table:
    table = Table(
        title="Search Results",
        title_style="bold bright_blue",
        box=box.ROUNDED,
        expand=True,
        show_lines=True,
    )
    table.add_column("Term", style="bold magenta", no_wrap=True)
    if show_grammar:
        table.add_column("Grammar", style="cyan", no_wrap=True)
    if show_topic:
        table.add_column("Topic", style="green", no_wrap=True)
    table.add_column("Definition", style="white")
    if show_url:
        table.add_column("Source", style="blue", overflow="fold")
    return table


def _format_result_row(
    result: SearchResult,
    *,
    show_url: bool = True,
    show_topic: bool = True,
    show_grammar: bool = True,
) -> list[str]:
    definition = result.definition.strip() if result.definition else "(no definition parsed)"
    row: list[str] = [result.term]
    if show_grammar:
        row.append(result.grammatical_label or "-")
    if show_topic:
        row.append(result.topic or "-")
    row.append(definition)
    if show_url:
        row.append(result.url or "-")
    return row


def print_results(
    results: typing.Iterable[SearchResult],
    *,
    out: typing.TextIO | None = None,
    limit: int | None = None,
    show_url: bool = True,
    show_topic: bool = True,
    show_grammar: bool = True,
) -> int:
    """Pretty-print a sequence of results to `out`.

    This works with any iterable, including lazily produced generators.
    """
    if out is None:
        out = sys.stdout

    table = _make_results_table(
        show_url=show_url,
        show_topic=show_topic,
        show_grammar=show_grammar,
    )
    console = Console(file=out)

    count = 0
    if console.is_terminal:
        with Live(table, console=console, refresh_per_second=8, transient=False) as live:
            for result in results:
                if limit is not None and count >= limit:
                    break
                table.add_row(
                    *_format_result_row(
                        result,
                        show_url=show_url,
                        show_topic=show_topic,
                        show_grammar=show_grammar,
                    )
                )
                live.update(table)
                count += 1
        return count

    for result in results:
        if limit is not None and count >= limit:
            break
        table.add_row(
            *_format_result_row(
                result,
                show_url=show_url,
                show_topic=show_topic,
                show_grammar=show_grammar,
            )
        )
        count += 1

    console.print(table)
    return count


async def print_results_async(
    results: typing.AsyncIterable[SearchResult],
    *,
    out: typing.TextIO | None = None,
    limit: int | None = None,
    show_url: bool = True,
    show_topic: bool = True,
    show_grammar: bool = True,
) -> int:
    """Pretty-print an async stream of results as they are yielded."""
    if out is None:
        out = sys.stdout

    table = _make_results_table(
        show_url=show_url,
        show_topic=show_topic,
        show_grammar=show_grammar,
    )
    console = Console(file=out)

    count = 0
    if console.is_terminal:
        with Live(table, console=console, refresh_per_second=8, transient=False) as live:
            async for result in results:
                if limit is not None and count >= limit:
                    break
                table.add_row(
                    *_format_result_row(
                        result,
                        show_url=show_url,
                        show_topic=show_topic,
                        show_grammar=show_grammar,
                    )
                )
                live.update(table)
                count += 1
        return count

    async for result in results:
        if limit is not None and count >= limit:
            break
        table.add_row(
            *_format_result_row(
                result,
                show_url=show_url,
                show_topic=show_topic,
                show_grammar=show_grammar,
            )
        )
        count += 1

    console.print(table)
    return count
