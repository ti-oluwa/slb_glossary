"""Shared output options for CLI commands that display or persist results."""

import contextlib
import json
import logging
import pathlib
import time
import typing

import click

from slb_glossary import store
from slb_glossary.store import records_to_dicts
from slb_glossary.store.records import RecordLike
from slb_glossary.utils import async_print_results

logger = logging.getLogger(__name__)

__all__ = ["output_options", "output_results"]


F = typing.TypeVar("F", bound=typing.Callable[..., typing.Any])


def output_options(func: F) -> F:
    """
    Attach shared output options to a Click command.

    Adds options for controlling console output and optionally persisting
    command results, including `--quiet`, `--json`, `--save`, and `--format`.

    Stack this directly above a command's `def`, alongside
    `@click.command()`. The decorated callback receives `quiet`,
    `json_output`, `save_paths`, and `format`; pass these values through to
    `output_results`.

    :param func: The Click command callback to attach the output options to.
    :return: `func`, with the output options attached.
    """
    func = click.option(
        "--quiet",
        "-q",
        is_flag=True,
        help="Don't print results to the console (useful with --save).",
    )(func)
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


async def output_results(
    results: typing.AsyncIterable[RecordLike] | typing.AsyncIterator[RecordLike],
    *,
    title: str | None = None,
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
    Collect, display, and optionally persist an async stream of results.

    Results are collected once so the same records can be displayed on the
    console and written to one or more files without re-running the
    network-bound operation that produced them.

    :param results: The async stream of records to consume.
    :param title: Title shown above the printed table, e.g.
        `f"Terms under {topic}"`. Passed straight through to
        `slb_glossary.utils.async_print_results`; ignored when
        `json_output` is `True` (JSON output has no table to title).
        Defaults to a generic type-based title - see `print_results`.
    :param save_paths: File paths to save the collected results to. Each
        path's format is inferred from its extension unless `format` is given.
    :param format: File format to use for every path in `save_paths`,
        overriding each path's extension.
    :param quiet: If `True`, don't print results to the console. Results are
        still written to `save_paths`.
    :param json_output: If `True` and `quiet` is `False`, print results as
        JSON instead of a table.
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
    started_at = time.monotonic()
    async with contextlib.aclosing(results) as results:  # type: ignore[arg-type]
        count = await _collect_and_output(
            results,  # type: ignore[arg-type]
            title=title,
            save_paths=save_paths,
            format=format,
            quiet=quiet,
            json_output=json_output,
            print_limit=print_limit,
            show_url=show_url,
            show_topic=show_topic,
            show_grammar=show_grammar,
            show_image=show_image,
            show_related=show_related,
        )
    elapsed = time.monotonic() - started_at
    logger.debug(
        "Output %d result(s) in %.3fs (avg %.3fs/result)",
        count,
        elapsed,
        elapsed / count if count else 0.0,
    )
    return count


async def _collect_and_output(
    results: typing.AsyncIterator[RecordLike],
    *,
    title: str | None,
    save_paths: typing.Sequence[pathlib.Path],
    format: str | None,
    quiet: bool,
    json_output: bool,
    print_limit: int | None,
    show_url: bool,
    show_topic: bool,
    show_grammar: bool,
    show_image: bool,
    show_related: bool,
) -> int:
    """The body of `output_results`, run inside its `contextlib.aclosing(results)` block."""
    collected: list[RecordLike] = []
    count = 0
    was_collected = False
    records = None

    if not quiet:

        async def _async_gen() -> typing.AsyncIterator[RecordLike]:
            nonlocal collected, count, was_collected
            was_collected = True
            async for record in results:
                collected.append(record)
                count += 1
                yield record

        records = _async_gen()
        if json_output:
            output = []
            output_count = 0
            async for record in records:
                output.append(record)
                output_count += 1
                if print_limit and output_count >= print_limit:
                    break

            exclude = []
            if not show_url:
                exclude.append("url")
            if not show_topic:
                exclude.append("topic")
            if not show_grammar:
                exclude.append("grammatical_label")
            if not show_image:
                exclude.append("image")
                exclude.append("image_caption")
            if not show_related:
                exclude.append("related")

            click.echo(
                json.dumps(
                    records_to_dicts(output, exclude=exclude),
                    indent=2,
                    ensure_ascii=False,
                )
            )
        else:
            printed_count = await async_print_results(
                records,
                title=title,
                limit=print_limit,
                show_url=show_url,
                show_topic=show_topic,
                show_grammar=show_grammar,
                show_image=show_image,
                show_related=show_related,
            )
            assert printed_count == count

    if save_paths:
        # If we printed an output then `collected` and `count` must have been updated.
        # But if `print_limit` was defined then there a high likelihood that that not all results
        # were collected and `count == print_limit` not `len(results)`. In that case,
        # we must collect the targets again fully.
        if was_collected and not print_limit:
            targets = collected
        else:
            if records is not None:
                # We collect the remaining record + already collected ones
                targets = collected + [record async for record in records]
            else:
                targets = [record async for record in results]
            count = len(targets)  # Make to update count

        for path in save_paths:
            await store.save(targets, path, format=format)
            click.echo(f"Saved {count} result(s) to {path}", err=True)
    return count
