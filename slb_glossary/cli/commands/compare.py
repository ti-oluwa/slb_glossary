"""`slb-glossary compare` - look up several glossary terms side by side."""

import typing

import click

from slb_glossary import query
from slb_glossary.cli.errors import cli_command
from slb_glossary.cli.output_options import output_options, output_results
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
from slb_glossary.cli.tui import launch_tui
from slb_glossary.models import SearchResult
from slb_glossary.query import Source

__all__ = ["compare"]


def _validate_terms(
    ctx: click.Context, param: click.Parameter, value: tuple[str, ...]
) -> tuple[str, ...]:
    """Validate that the user provided at least two terms to compare."""
    if len(value) < 2:
        raise click.BadParameter("Give at least two terms to compare.")
    return value


@click.command("compare")
@click.argument("terms", nargs=-1, callback=_validate_terms)
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
@output_options
@click.option(
    "--tui",
    "use_tui",
    is_flag=True,
    help="Open this command in the interactive TUI instead of running it directly.",
)
@click.pass_context
@cli_command
def compare(
    ctx: click.Context, terms: tuple[str, ...], use_tui: bool, **params: typing.Any
) -> None:
    """
    Look up TERMS (two or more) and print their definitions side by side for comparison.

    Same --local/--live/--intelligent source selection as `define`. Terms
    not found by the resolved source(s) are skipped, with a note printed
    to stderr.

    \b
    Examples:
      slb-glossary compare "water flooding" "gas flooding"
      slb-glossary compare porosity permeability --local
      slb-glossary compare "black oil" "heavy oil" --save comparison.csv
    """
    if use_tui:
        launch_tui(ctx, command_path=("compare",))
        return

    source = resolve_source(params)
    config = get_loaded_config(params)

    async def _run() -> int:
        found: list[SearchResult] = []
        missing: list[str] = []
        sources_seen: set[str] = set()

        async with open_configured_db(config, db_path_override=params["db_path"]) as db:
            for term in terms:
                lookup = await resolve_lookup(
                    ctx,
                    params,
                    db,
                    source=source,
                    local_call=lambda db, term=term: query.get_term(
                        term, db=db, source=Source.LOCAL
                    ),
                    live_call=lambda session, term=term: query.get_term(
                        term,
                        db=db,
                        session=session,
                        source=Source.LIVE,
                        persist=params["cache_results"],
                    ),
                )
                if lookup.value is not None:
                    found.append(lookup.value)
                    sources_seen.add(lookup.source.value)
                else:
                    missing.append(term)

        if not params["quiet"]:
            if sources_seen:
                click.secho(
                    f"(source: {', '.join(sorted(sources_seen))})", fg="bright_black", err=True
                )
            for term in missing:
                click.secho(f"Not found: {term!r}", fg="yellow", err=True)

        async def _records() -> typing.AsyncIterator[SearchResult]:
            for result in found:
                yield result

        return await output_results(
            _records(),
            save_paths=params["save_paths"],
            format=params["format"],
            quiet=params["quiet"],
            json_output=params["json_output"],
            show_related=params["show_related"],
        )

    count = run_async(_run())
    if not params["quiet"] and count == 0:
        click.echo("None of the given terms were found.", err=True)
