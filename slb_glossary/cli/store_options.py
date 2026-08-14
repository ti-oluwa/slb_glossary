"""Shared `--save`/`--format` options for commands that can persist their results."""

import json
import pathlib
import typing

import click

from slb_glossary import store
from slb_glossary.store import records_to_dicts
from slb_glossary.store.records import RecordLike
from slb_glossary.utils import async_print_results

__all__ = ["store_options", "output_results"]


F = typing.TypeVar("F", bound=typing.Callable[..., typing.Any])


def store_options(func: F) -> F:
    """
    Attach `--save`/`-o` and `--format` options to a click command.

    Stack this directly above a command's `def`, alongside `@click.command()`.
    The decorated callback receives `save_paths: tuple[pathlib.Path, ...]`,
    `format: str | None` and `json_output: bool`; pass all three through to
    `output_results`.

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


async def output_results(
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
        JSON array to stdout instead of a Rich table. Suited to piping
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
    collected: list[RecordLike] = []
    count = 0
    was_collected = False

    if not quiet:

        async def async_gen() -> typing.AsyncIterator[RecordLike]:
            nonlocal collected, count, was_collected
            was_collected = True
            async for record in results:
                collected.append(record)
                count += 1
                yield record

        records = async_gen()
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
            targets = [record async for record in results]
            count = len(targets)  # Make to update count

        for path in save_paths:
            await store.save(targets, path, format=format)
            click.echo(f"Saved {count} result(s) to {path}", err=True)
    return count
