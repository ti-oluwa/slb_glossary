"""`slb-glossary terms` - list every term filed under a glossary topic."""

import typing

import click

from slb_glossary import query as glossary_query
from slb_glossary.cli.errors import cli_command
from slb_glossary.cli.output_options import output_options, output_results
from slb_glossary.cli.runtime import run_async
from slb_glossary.cli.session_options import config_option, session_options
from slb_glossary.cli.source_options import (
    get_loaded_config,
    local_db_option,
    open_configured_db,
    resolve_source,
    resolve_stream,
    source_options,
)
from slb_glossary.cli.tui import launch_tui
from slb_glossary.query import Source

__all__ = ["terms"]


def _validate_topic(
    ctx: click.Context, param: click.Parameter, value: tuple[str, ...]
) -> tuple[str, ...]:
    """Validate that the user provided a non-empty search topic."""
    if not value or not any(value):
        raise click.BadParameter("Missing topic. Provide a topic name to look up in the glossary.")
    return value


@click.command("terms")
@click.argument("topic", default="", callback=_validate_topic)
@click.option(
    "--limit",
    "-n",
    type=int,
    default=0,
    show_default=False,
    help="Maximum number of terms to fetch. Defaults to every term under the topic.",
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
    help="Tolerate minor misspellings/partial names in TOPIC when reading "
    "the local database, matched against topics actually stored locally, "
    "instead of requiring an exact (case-insensitive) match.",
)
@source_options
@local_db_option
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
def terms(ctx: click.Context, topic: str, use_tui: bool, **params: typing.Any) -> None:
    """
    Fetch the definition of every term filed under TOPIC.

    TOPIC need not be an exact match; the closest topic(s) known to the
    glossary are used. Unlike `search`, this yields at most one result per
    term: the definition filed under TOPIC itself.

    Reads from the local database, the live glossary, or both, depending on
    --local/--live/--intelligent (--intelligent is the default): with a
    local database available, cached results are used first and the live
    site is only visited if the local database has nothing for TOPIC.

    \b
    Examples:
      slb-glossary terms Geophysics
      slb-glossary terms "Well completions,Perforating" --limit 20
      slb-glossary terms Drilling --save drilling_terms.json
      slb-glossary terms Drilling --local --fuzzy
      slb-glossary terms Drilling --config ~/my-config.toml
    """
    if use_tui:
        launch_tui(ctx, command_path=("terms",))
        return

    limit = params["limit"] or None
    concurrency = params["concurrency"] or 1
    source = resolve_source(params)
    config = get_loaded_config(params)

    async def _run() -> int:
        async with open_configured_db(config, db_path_override=params["db_path"]) as db:
            results = resolve_stream(
                ctx,
                params,
                db,
                source=source,
                local_call=lambda db: glossary_query.get_terms_on(
                    topic,
                    db=db,
                    source=Source.LOCAL,
                    limit=limit,
                    fuzzy=params["fuzzy"],
                ),
                live_call=lambda session: glossary_query.get_terms_on(
                    topic,
                    db=db,
                    session=session,
                    source=Source.LIVE,
                    limit=limit,
                    concurrency=concurrency,
                    persist=params["cache_results"],
                ),
            )
            return await output_results(
                results,
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
        click.echo("No terms found for that topic.", err=True)
