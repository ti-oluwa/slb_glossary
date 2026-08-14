"""`slb-glossary search` - free-text search of the SLB glossary."""

import typing

import click

from slb_glossary.browser import search_session
from slb_glossary.cli.errors import cli_command
from slb_glossary.cli.runtime import run_async
from slb_glossary.cli.session_options import config_option, resolve_session_kwargs, session_options
from slb_glossary.cli.store_options import output_results, store_options
from slb_glossary.cli.tui import launch_tui
from slb_glossary.engine import search as run_search

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
    "--quiet",
    "-q",
    is_flag=True,
    help="Don't print results to the console (useful with --save).",
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
def search(ctx: click.Context, query: str, use_tui: bool, **params: typing.Any) -> None:
    """
    Search the glossary for QUERY and print (or save) the matching definitions.

    A matched term can carry several definitions (one per topic it's filed
    under), so more results than --limit may be printed; --limit bounds the
    number of terms looked up, not the number of definitions returned.

    \b
    Examples:
      slb-glossary search porosity
      slb-glossary search "drilling fluid" --topic Drilling --limit 10
      slb-glossary search viscosity --save results.csv --quiet
      slb-glossary search viscosity --show-related --show-image
      slb-glossary search porosity --config ~/my-config.toml
      slb-glossary search porosity --config none --headed
    """
    if use_tui:
        launch_tui(ctx, command_path=("search",))
        return

    limit = params["limit"] or None
    concurrency = params["concurrency"] or 1

    async def _run() -> int:
        async with search_session(**resolve_session_kwargs(ctx, params)) as session:
            results = run_search(
                session,
                query,
                topic=params["topic"],
                start_letter=params["start_letter"],
                limit=limit,
                concurrency=concurrency,
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
        click.echo("No results found.", err=True)
