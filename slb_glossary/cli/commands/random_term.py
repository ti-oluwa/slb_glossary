"""`slb-glossary random` - print one (or several) randomly chosen glossary term(s)."""

import typing

import click

from slb_glossary import query
from slb_glossary.cli.errors import cli_command
from slb_glossary.cli.runtime import run_async
from slb_glossary.cli.session_options import config_option, session_options
from slb_glossary.cli.source_options import (
    get_loaded_config,
    local_db_option,
    open_configured_db,
    resolve_lookup,
    resolve_source,
    source_options,
)
from slb_glossary.cli.store_options import output_results, store_options
from slb_glossary.cli.tui import launch_tui
from slb_glossary.models import SearchResult
from slb_glossary.query import Source

__all__ = ["random_term"]


@click.command("random")
@click.option(
    "--topic",
    "-t",
    default=None,
    help="Restrict the pick to this topic, or several comma-separated topics.",
)
@click.option(
    "--count",
    "-n",
    type=int,
    default=1,
    show_default=True,
    help="Number of random terms to pick (each picked independently; duplicates are possible).",
)
@source_options
@local_db_option
@click.option(
    "--show-related/--hide-related",
    "show_related",
    default=False,
    show_default=True,
    help="Show/hide the related-terms column.",
)
@config_option
@session_options
@store_options
@click.option(
    "--tui",
    "use_tui",
    is_flag=True,
    help="Open this command in the interactive TUI instead of running it directly.",
)
@click.pass_context
@cli_command
def random_term(ctx: click.Context, use_tui: bool, **params: typing.Any) -> None:
    """
    Print one or more randomly chosen glossary terms.

    Handy for "term of the day"-style exploration. Same
    --local/--live/--intelligent source selection as `define`; with
    --live (or --intelligent falling back to it), a random detail page is
    sampled since the live site has no dedicated "random" endpoint.

    \b
    Examples:
      slb-glossary random
      slb-glossary random --topic Drilling
      slb-glossary random --count 5 --local
    """
    if use_tui:
        launch_tui(ctx, command_path=("random",))
        return

    source = resolve_source(params)
    config = get_loaded_config(params)
    topic = params["topic"]
    count = max(params["count"] or 1, 1)

    async def _run() -> int:
        picks: list[SearchResult] = []
        sources_seen: set[str] = set()

        async with open_configured_db(config, db_path_override=params["db_path"]) as db:
            for _ in range(count):
                lookup = await resolve_lookup(
                    ctx,
                    params,
                    db,
                    source=source,
                    local_call=lambda db: query.random_term(
                        db=db, topic=topic, source=Source.LOCAL
                    ),
                    live_call=lambda session: query.random_term(
                        db=db,
                        session=session,
                        topic=topic,
                        source=Source.LIVE,
                        persist=params["cache_results"],
                    ),
                )
                if lookup.value is not None:
                    picks.append(lookup.value)
                    sources_seen.add(lookup.source.value)

        if not params["quiet"] and sources_seen:
            click.secho(
                f"(source: {', '.join(sorted(sources_seen))})", fg="bright_black", err=True
            )

        async def _records() -> typing.AsyncIterator[SearchResult]:
            for pick in picks:
                yield pick

        return await output_results(
            _records(),
            save_paths=params["save_paths"],
            format=params["format"],
            quiet=params["quiet"],
            json_output=params["json_output"],
            show_related=params["show_related"],
        )

    count_printed = run_async(_run())
    if not params["quiet"] and count_printed == 0:
        click.echo("No terms available to pick from.", err=True)
