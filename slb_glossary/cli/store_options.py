"""Shared `--save`/`--format` options for commands that can persist their results.

This module only knows the shape of `slb_glossary.store` (a `save(records,
destination, format=...)` coroutine); it imports `slb_glossary.store` lazily,
inside `save_and_print`, so the CLI stays loosely coupled to that module and
keeps working even while the store API is still being revamped.
"""

import json
import pathlib
import typing

import click

from slb_glossary import store
from slb_glossary.models import SearchResult
from slb_glossary.store import records_to_dicts
from slb_glossary.store.records import RecordLike
from slb_glossary.utils import print_results

__all__ = ["store_options", "save_and_print"]


F = typing.TypeVar("F", bound=typing.Callable[..., typing.Any])


def store_options(func: F) -> F:
    """
    Attach `--save`/`-o` and `--format` options to a click command.

    Stack this directly above a command's `def`, alongside `@click.command()`.
    The decorated callback receives `save_paths: tuple[pathlib.Path, ...]`,
    `format: str | None` and `json_output: bool`; pass all three through to
    `save_and_print`.

    :param func: The click command callback to attach options to.
    :return: `func`, with the save options attached.
    """
    func = click.option(
        "--json",
        "json_output",
        is_flag=True,
        help="Print results as JSON to stdout instead of a table. Ignored with --quiet.",
    )(func)
    func = click.option(
        "--format",
        "-f",
        "format",
        default=None,
        help=(
            "File format to save results as, e.g. 'csv'. Overrides each "
            "--save destination's file extension. See `slb-glossary formats`."
        ),
    )(func)
    func = click.option(
        "--save",
        "-o",
        "save_paths",
        type=click.Path(dir_okay=False, path_type=pathlib.Path),
        multiple=True,
        help="Save results to this file. Repeatable, to save to several files/formats at once.",
    )(func)
    return func


async def save_and_print(
    results: typing.AsyncIterable[RecordLike] | typing.AsyncIterator[RecordLike],
    *,
    save_paths: typing.Sequence[pathlib.Path],
    format: str | None,
    quiet: bool,
    json_output: bool = False,
    print_limit: int | None = None,
    show_url: bool = True,
    show_topic: bool = True,
    show_grammar: bool = True,
    show_image: bool = False,
    show_related: bool = False,
) -> int:
    """
    Collect an async stream of results, then print and/or save it.

    Collects `results` into a list once so the same results can both be
    printed to the console and saved to one or more files without
    re-running the (network-bound) search that produced them.

    :param results: The async stream of records to consume, e.g. from
        `slb_glossary.search`, `slb_glossary.get_terms_on`, or any other
        `slb_glossary.store.RecordLike`-yielding source.
    :param save_paths: File paths to save the collected results to. Each
        path's format is inferred from its extension unless `format` is
        given. May be empty to skip saving.
    :param format: File format to force for every path in `save_paths`,
        overriding each path's extension. Ignored if `save_paths` is empty.
    :param quiet: If `True`, skip printing results to the console entirely
        (neither a table nor JSON); only `save_paths` are written.
    :param json_output: If `True` (and not `quiet`), print `collected` as a
        JSON array to stdout instead of a Rich table - suited to piping
        into `jq` or another program. `print_limit`/`show_*` are ignored
        in this mode, since JSON output is meant to be complete and
        machine-readable rather than trimmed for terminal display.
    :param print_limit: Maximum number of results to print as a table.
        Ignored when `json_output` is `True`. Every collected result is
        still saved regardless of this limit.
    :param show_url: For `SearchResult`s, whether to print the source URL column.
    :param show_topic: For `SearchResult`s, whether to print the topic column.
    :param show_grammar: For `SearchResult`s, whether to print the grammatical label column.
    :param show_image: For `SearchResult`s, whether to print the image URL column.
    :param show_related: For `SearchResult`s, whether to print the related-terms column.
    :return: The total number of results collected.
    :raises slb_glossary.store.UnsupportedFormatError: If a save path (or
        `format`) resolves to a file format with no registered writer.
    :raises slb_glossary.store.WriterError: If writing to a save path fails.
    """
    collected = [result async for result in results]

    if not quiet:
        if json_output:
            click.echo(json.dumps(records_to_dicts(collected), indent=2, ensure_ascii=False))
        else:
            print_results(
                collected,
                limit=print_limit,
                show_url=show_url,
                show_topic=show_topic,
                show_grammar=show_grammar,
                show_image=show_image,
                show_related=show_related,
            )

    if save_paths:
        for path in save_paths:
            await store.save(collected, path, format=format)
            click.echo(f"Saved {len(collected)} result(s) to {path}", err=True)

    return len(collected)
