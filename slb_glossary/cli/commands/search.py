"""`slb-glossary search` - free-text search of the SLB glossary."""

import typing

import click

from slb_glossary.browser import search_session
from slb_glossary.cli.errors import cli_command
from slb_glossary.cli.runtime import run_async
from slb_glossary.cli.session_options import session_kwargs_from_params, session_options
from slb_glossary.cli.store_options import save_and_print, store_options
from slb_glossary.cli.tui import launch_tui
from slb_glossary.engine import search as run_search

__all__ = ["search"]


@click.command("search")
@click.argument("query")
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
    "--topic-column/--no-topic-column",
    "show_topic",
    default=True,
    show_default=True,
    help="Show/hide the topic column.",
)
@click.option(
    "--grammar-column/--no-grammar-column",
    "show_grammar",
    default=True,
    show_default=True,
    help="Show/hide the grammatical label column.",
)
@click.option(
    "--image-column/--no-image-column",
    "show_image",
    default=False,
    show_default=True,
    help="Show/hide the illustrative image URL column.",
)
@click.option(
    "--related-column/--no-related-column",
    "show_related",
    default=False,
    show_default=True,
    help="Show/hide the related-terms column.",
)
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
      slb-glossary search viscosity --related-column --image-column
    """
    if use_tui:
        launch_tui(ctx, command_path=("search",))
        return

    limit = params["limit"] or None

    async def _run() -> int:
        async with search_session(**session_kwargs_from_params(params)) as session:
            results = run_search(
                session,
                query,
                topic=params["topic"],
                start_letter=params["start_letter"],
                limit=limit,
            )
            return await save_and_print(
                results,
                save_paths=params["save_paths"],
                format=params["format"],
                quiet=params["quiet"],
                show_url=params["show_url"],
                show_topic=params["show_topic"],
                show_grammar=params["show_grammar"],
                show_image=params["show_image"],
                show_related=params["show_related"],
            )

    count = run_async(_run())
    if not params["quiet"] and count == 0:
        click.echo("No results found.", err=True)
