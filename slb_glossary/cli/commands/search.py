"""`slb-glossary search` - free-text search of the SLB glossary."""

import typing

import click

from slb_glossary import query as query_api
from slb_glossary.cli.errors import cli_command
from slb_glossary.cli.output_options import output_options, output_results
from slb_glossary.cli.runtime import run_async
from slb_glossary.cli.session_options import config_option, session_options
from slb_glossary.cli.source_options import (
    database_option,
    get_loaded_config,
    live_session,
    open_configured_db,
    persist_kwargs,
    resolve_source,
    resolve_stream,
    source_options,
)
from slb_glossary.cli.tui import launch_tui
from slb_glossary.local import scored_search as scored_search
from slb_glossary.local.types import Database
from slb_glossary.query import DEFAULT_RELEVANCE_THRESHOLD, Source
from slb_glossary.types import SearchResult

__all__ = ["search"]


def _validate_query(
    ctx: click.Context, param: click.Parameter, value: tuple[str, ...]
) -> tuple[str, ...]:
    """Validate that the user provided a non-empty search query."""
    if not value or not any(value):
        raise click.BadParameter(
            "Missing search query. Provide a query string to look up in the glossary."
        )
    return value


async def _stream_auto_search(
    ctx: click.Context,
    params: typing.Mapping[str, typing.Any],
    db: Database | None,
    *,
    query: str,
    limit: int | None,
    concurrency: int,
    relevance_threshold: float,
) -> typing.AsyncIterator[SearchResult]:
    """
    Stream `Source.AUTO` results for the `search` command, opening a live
    session only if the local database doesn't have a confident match.

    A `search`-specific alternative to `resolve_stream`'s generic
    `Source.AUTO` handling (shared with `terms`/`urls`, which have no
    notion of result relevance): this peeks at the local database's best
    score first with no browser involved, and only opens a live session if
    that score is below `relevance_threshold`. The actual local+live merge
    then happens inside `slb_glossary.query.search` itself, so that logic
    stays in one place rather than being duplicated here.

    :param ctx: The current click context.
    :param params: The command's parsed parameters.
    :param db: An already-open local `Database`, or `None` if local
        storage is disabled for this run.
    :param query: The free-text query to search for.
    :param limit: Maximum number of terms to look up. `None` for unlimited.
    :param concurrency: Concurrent term-page fetches, if a live fetch happens.
    :param relevance_threshold: See `slb_glossary.query.search`'s parameter of the same name.
    :yield: Matching `SearchResult`s, local results first if a live fetch also happens.
    """
    if db is None:
        async with live_session(ctx, params) as session:
            async for result in query_api.search(
                query,
                session=session,
                source=Source.LIVE,
                topic=params["topic"],
                start_letter=params["start_letter"],
                limit=limit,
                concurrency=concurrency,
                **persist_kwargs(params),
            ):
                yield result  # noqa: ASYNC119
        return

    scored = await scored_search(
        db,
        query,
        topic=params["topic"],
        start_letter=params["start_letter"],
        limit=limit,
        fuzzy=params["fuzzy"],
    )
    best_score = scored[0][1] if scored else 0.0
    if scored and best_score >= relevance_threshold:
        for result, _ in scored:
            yield result
        return

    async with live_session(ctx, params) as session:
        async for result in query_api.search(
            query,
            db=db,
            session=session,
            source=Source.AUTO,
            topic=params["topic"],
            start_letter=params["start_letter"],
            limit=limit,
            concurrency=concurrency,
            fuzzy=params["fuzzy"],
            relevance_threshold=relevance_threshold,
            **persist_kwargs(params),
        ):
            yield result  # noqa: ASYNC119


@click.command("search")
@click.argument("query", default="", callback=_validate_query)
@click.option(
    "--topic",
    "-t",
    default=None,
    help="Restrict results to this topic, or several comma-separated topics.",
)
@click.option(
    "--start-letter",
    "-a",
    default=None,
    help="Restrict results to terms starting with this letter.",
)
@click.option(
    "--limit",
    "-n",
    type=int,
    default=3,
    show_default=True,
    help="Maximum number of terms to look up. Use 0 for unlimited.",
)
@click.option(
    "--relevance-threshold",
    "relevance_threshold",
    type=click.FloatRange(min=0.0, max=1.0),
    default=DEFAULT_RELEVANCE_THRESHOLD,
    show_default=True,
    help=(
        "Only used with --auto (the default). The local database's best "
        "match must score at least this well (0.0-1.0) to be served alone; "
        "below it, the live glossary is also searched and its results are "
        "added after the local ones, rather than replacing them. Lower it "
        "to trust local results more readily (fewer live fetches); raise "
        "it to augment with live results more often."
    ),
)
@click.option(
    "--url/--no-url",
    "show_url",
    default=True,
    show_default=True,
    help="Show/hide the source URL column.",
)
@click.option(
    "--show-topic/--hide-topic",
    "show_topic",
    default=True,
    show_default=True,
    help="Show/hide the topic column.",
)
@click.option(
    "--show-grammar/--hide-grammar",
    "show_grammar",
    default=True,
    show_default=True,
    help="Show/hide the grammatical label column.",
)
@click.option(
    "--show-image/--hide-image",
    "show_image",
    default=False,
    show_default=True,
    help="Show/hide the illustrative image URL column.",
)
@click.option(
    "--show-related/--hide-related",
    "show_related",
    default=False,
    show_default=True,
    help="Show/hide the related-terms column.",
)
@click.option(
    "--concurrency",
    "concurrency",
    type=int,
    default=1,
    show_default=True,
    help="Number of concurrent term lookups to perform. Higher values may be faster, but use with discretion as we do not want to overload the glossary server.",
)
@click.option(
    "--fuzzy",
    is_flag=True,
    help="Tolerate minor misspellings/partial names in --topic when reading "
    "the local database, matched against topics actually stored locally, "
    "instead of requiring an exact (case-insensitive) match.",
)
@source_options
@database_option
@config_option
@session_options
@output_options
@click.option(
    "--tui",
    "use_tui",
    is_flag=True,
    help="Open this command in the interactive TUI instead of running it directly.",
)
@click.pass_context
@cli_command
def search(ctx: click.Context, query: str, use_tui: bool, **params: typing.Any) -> None:
    """
    Search the glossary for QUERY and print (or save) the matching definitions.

    A matched term can carry several definitions (one per topic it's filed
    under), so more results than --limit may be printed; --limit bounds the
    number of terms looked up, not the number of definitions returned.

    Reads from the local database, the live glossary, or both, depending on
    --local/--live/--auto (--auto is the default): with a local database
    available, its results are ranked and scored, and used alone if the
    best of them meets --relevance-threshold; otherwise the live site is
    also searched and its results are added on rather than replacing the
    local ones.

    With --cache (the default), live results are saved to the local
    database as they arrive, --cache-batch-size at a time, rather than all
    at once at the end - so a long-running fetch that gets interrupted
    still keeps whatever it already fetched (see --cache-on-error).

    \b
    Examples:
      slb-glossary search porosity
      slb-glossary search "drilling fluid" --topic Drilling --limit 10
      slb-glossary search viscosity --save results.csv --quiet
      slb-glossary search viscosity --show-related --show-image
      slb-glossary search porosity --local
      slb-glossary search porosity --local --fuzzy --topic Petrophysics
      slb-glossary search porosity --live --cache
      slb-glossary search porosity --live --limit 0 --cache-batch-size 5
      slb-glossary search porosity --relevance-threshold 0.8
      slb-glossary search porosity --config ~/my-config.toml
      slb-glossary search porosity --config none --headed
    """
    if use_tui:
        launch_tui(ctx, command_path=("search",))
        return

    limit = params["limit"] or None
    concurrency = params["concurrency"] or 1
    source = resolve_source(params)
    config = get_loaded_config(params)
    title = f"Search Results for {query!r}"
    if params["topic"]:
        title += f" (topic: {params['topic']})"

    async def _run() -> int:
        async with open_configured_db(config, db_path_override=params["db_path"]) as db:
            if source is Source.AUTO:
                results: typing.AsyncIterator[SearchResult] = _stream_auto_search(
                    ctx,
                    params,
                    db,
                    query=query,
                    limit=limit,
                    concurrency=concurrency,
                    relevance_threshold=params["relevance_threshold"],
                )
            else:
                results = resolve_stream(
                    ctx,
                    params,
                    db,
                    source=source,
                    local_call=lambda db: query_api.search(
                        query,
                        db=db,
                        source=Source.LOCAL,
                        topic=params["topic"],
                        start_letter=params["start_letter"],
                        limit=limit,
                        fuzzy=params["fuzzy"],
                    ),
                    live_call=lambda session: query_api.search(
                        query,
                        db=db,
                        session=session,
                        source=Source.LIVE,
                        topic=params["topic"],
                        start_letter=params["start_letter"],
                        limit=limit,
                        concurrency=concurrency,
                        **persist_kwargs(params),
                    ),
                )
            return await output_results(
                results,
                title=title,
                save_paths=params["save_paths"],
                format=params["format"],
                quiet=params["quiet"],
                json_output=params["json_output"],
                show_url=params["show_url"],
                show_topic=params["show_topic"],
                show_grammar=params["show_grammar"],
                show_image=params["show_image"],
                show_related=params["show_related"],
            )

    count = run_async(_run())
    if not params["quiet"] and count == 0:
        click.echo("No results found.", err=True)
