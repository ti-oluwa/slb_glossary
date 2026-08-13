"""`slb-glossary terms` - list every term filed under a glossary topic."""

import typing

import click

from slb_glossary.browser import search_session
from slb_glossary.cli.errors import cli_command
from slb_glossary.cli.runtime import run_async
from slb_glossary.cli.session_options import config_option, resolve_session_kwargs, session_options
from slb_glossary.cli.store_options import save_and_print, store_options
from slb_glossary.cli.tui import launch_tui
from slb_glossary.engine import get_terms_on

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
def terms(ctx: click.Context, topic: str, use_tui: bool, **params: typing.Any) -> None:
    """
    Fetch the definition of every term filed under TOPIC.

    TOPIC need not be an exact match; the closest topic(s) known to the
    glossary are used. Unlike `search`, this yields at most one result per
    term: the definition filed under TOPIC itself.

    \b
    Examples:
      slb-glossary terms Geophysics
      slb-glossary terms "Well completions,Perforating" --limit 20
      slb-glossary terms Drilling --save drilling_terms.json
      slb-glossary terms Drilling --config ~/my-config.toml
    """
    if use_tui:
        launch_tui(ctx, command_path=("terms",))
        return

    limit = params["limit"] or None
    concurrency = params["concurrency"] or 1

    async def _run() -> int:
        async with search_session(**resolve_session_kwargs(ctx, params)) as session:
            results = get_terms_on(session, topic, limit=limit, concurrency=concurrency)
            return await save_and_print(
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
