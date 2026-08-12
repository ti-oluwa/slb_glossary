"""Shared `--save`/`--format` options for commands that can persist their results.

This module only knows the shape of `slb_glossary.store` (a `save(records,
destination, format=...)` coroutine); it imports `slb_glossary.store` lazily,
inside `save_results`, so the CLI stays loosely coupled to that module and
keeps working even while the store API is still being revamped.
"""

import pathlib
import typing

import click

from slb_glossary.models import SearchResult

__all__ = ["store_options", "save_and_print"]


F = typing.TypeVar("F", bound=typing.Callable[..., typing.Any])


def store_options(func: F) -> F:
    """
    Attach `--save`/`-o` and `--format` options to a click command.

    Stack this directly above a command's `def`, alongside `@click.command()`.
    The decorated callback receives `save_paths: tuple[pathlib.Path, ...]`
    and `format: str | None`; pass both through to `save_and_print`.

    :param func: The click command callback to attach options to.
    :return: `func`, with the save options attached.
    """
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
    results: typing.AsyncIterable[SearchResult],
    *,
    save_paths: typing.Sequence[pathlib.Path],
    format: str | None,
    quiet: bool,
    print_limit: int | None = None,
    show_url: bool = True,
    show_topic: bool = True,
    show_grammar: bool = True,
) -> int:
    """
    Collect an async stream of results, then print and/or save it.

    Collects `results` into a list once so the same results can both be
    printed to the console and saved to one or more files without
    re-running the (network-bound) search that produced them.

    :param results: The async stream of results to consume, e.g. from
        `slb_glossary.search` or `slb_glossary.get_terms_on`.
    :param save_paths: File paths to save the collected results to. Each
        path's format is inferred from its extension unless `format` is
        given. May be empty to skip saving.
    :param format: File format to force for every path in `save_paths`,
        overriding each path's extension. Ignored if `save_paths` is empty.
    :param quiet: If `True`, skip printing results to the console; only
        `save_paths` are written.
    :param print_limit: Maximum number of results to print. Every collected
        result is still saved regardless of this limit.
    :param show_url: Whether to print the result's source URL column.
    :param show_topic: Whether to print the result's topic column.
    :param show_grammar: Whether to print the result's grammatical label column.
    :return: The total number of results collected.
    :raises slb_glossary.store.UnsupportedFormatError: If a save path (or
        `format`) resolves to a file format with no registered writer.
    """
    collected = [result async for result in results]

    if not quiet:
        from slb_glossary.utils import print_results

        print_results(
            collected,
            limit=print_limit,
            show_url=show_url,
            show_topic=show_topic,
            show_grammar=show_grammar,
        )

    if save_paths:
        from slb_glossary import store

        for path in save_paths:
            await store.save(collected, path, format=format)
            click.echo(f"Saved {len(collected)} result(s) to {path}", err=True)

    return len(collected)
