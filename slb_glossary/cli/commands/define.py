"""`slb-glossary define` - look up a single glossary term's definition."""

import typing

import click

from slb_glossary import query
from slb_glossary.cli.errors import cli_command
from slb_glossary.cli.output_options import output_options, output_results
from slb_glossary.cli.runtime import run_async
from slb_glossary.cli.session_options import config_option, session_options
from slb_glossary.cli.source_options import (
    database_option,
    get_loaded_config,
    open_configured_db,
    resolve_lookup,
    resolve_source,
    source_options,
)
from slb_glossary.cli.tui import launch_tui
from slb_glossary.query import Source

__all__ = ["define"]


def _validate_term(ctx: click.Context, param: click.Parameter, value: str) -> str:
    """Validate that the user provided a non-empty term."""
    if not value or not value.strip():
        raise click.BadParameter("Missing term. Provide a term name or detail-page URL.")
    return value


@click.command("define")
@click.argument("term", default="", callback=_validate_term)
@source_options
@database_option
@click.option(
    "--show-related/--hide-related",
    "show_related",
    default=True,
    show_default=True,
    help="Show/hide the related-terms column.",
)
@click.option(
    "--show-image/--hide-image",
    "show_image",
    default=False,
    show_default=True,
    help="Show/hide the illustrative image URL column.",
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
def define(ctx: click.Context, term: str, use_tui: bool, **params: typing.Any) -> None:
    """
    Look up TERM (an exact term name, or a term detail-page URL) and print its definition.

    Reads from the local database, the live glossary, or both, depending on
    --local/--live/--auto (--auto is the default): with a
    local database available, the local copy is used first and the live
    site is only visited if TERM isn't cached yet.

    \b
    Examples:
      slb-glossary define "black oil"
      slb-glossary define porosity --local
      slb-glossary define "water saturation" --live --cache
      slb-glossary define "black oil" --save black_oil.json
    """
    if use_tui:
        launch_tui(ctx, command_path=("define",))
        return

    source = resolve_source(params)
    config = get_loaded_config(params)

    async def _run() -> int:
        async with open_configured_db(config, db_path_override=params["db_path"]) as db:
            lookup = await resolve_lookup(
                ctx,
                params,
                db,
                source=source,
                local_call=lambda db: query.get_term(term, db=db, source=Source.LOCAL),
                live_call=lambda session: query.get_term(
                    term,
                    db=db,
                    session=session,
                    source=Source.LIVE,
                    persist=params["cache_results"],
                ),
            )

        if lookup.value is None:
            return 0

        if not params["quiet"]:
            click.secho(f"(source: {lookup.source.value})", fg="bright_black", err=True)

        async def _one() -> typing.AsyncIterator[typing.Any]:
            yield lookup.value

        return await output_results(
            _one(),
            title=f"Definition: {term}",
            save_paths=params["save_paths"],
            format=params["format"],
            quiet=params["quiet"],
            json_output=params["json_output"],
            show_related=params["show_related"],
            show_image=params["show_image"],
        )

    count = run_async(_run())
    if not params["quiet"] and count == 0:
        click.echo(f"{term!r} was not found.", err=True)
