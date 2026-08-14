"""`slb-glossary urls` - list term detail-page URLs, and fetch results from one directly."""

import typing

import click

from slb_glossary.browser import search_session
from slb_glossary.cli.errors import cli_command
from slb_glossary.cli.runtime import run_async
from slb_glossary.cli.session_options import config_option, resolve_session_kwargs, session_options
from slb_glossary.cli.store_options import output_results, store_options
from slb_glossary.cli.tui import launch_tui
from slb_glossary.live import iter_results_from_url, iter_term_urls

__all__ = ["urls"]


class UrlRecord(typing.NamedTuple):
    """A single glossary term detail-page URL, saveable via `slb_glossary.store`."""

    url: str
    """The term detail-page URL."""

    @property
    def fields(self) -> list[str]:
        """Return a list of the field names in this record."""
        return list(self._fields)

    def asdict(self) -> dict[str, typing.Any]:
        """Return a dictionary representation of this record."""
        return self._asdict()


@click.group("urls")
def urls() -> None:
    """List glossary term URLs, or fetch results directly from one."""


@urls.command("list")
@click.option(
    "--query",
    "-Q",
    default=None,
    help="A free-text search query to filter URLs by.",
)
@click.option(
    "--topic",
    "-t",
    default=None,
    help="Restrict URLs to this topic, or several comma-separated topics.",
)
@click.option(
    "--start-letter",
    "-a",
    default=None,
    help="Restrict URLs to terms starting with this letter.",
)
@click.option(
    "--limit",
    "-n",
    type=int,
    default=0,
    help="Maximum number of URLs to fetch. Defaults to every matching URL.",
)
@click.option(
    "--quiet",
    "-q",
    is_flag=True,
    help="Don't print URLs to the console (useful with --save).",
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
def list_urls(ctx: click.Context, use_tui: bool, **params: typing.Any) -> None:
    """
    List glossary term detail-page URLs matching --query/--topic/--start-letter.

    At least one of --query, --topic or --start-letter must be given.

    \b
    Examples:
      slb-glossary urls list --topic Geophysics
      slb-glossary urls list --query porosity --limit 5
      slb-glossary urls list --start-letter a --save urls.txt
    """
    if use_tui:
        launch_tui(ctx, command_path=("urls", "list"))
        return

    if not any([params["query"], params["topic"], params["start_letter"]]):
        raise click.UsageError("Give at least one of --query, --topic or --start-letter.")

    limit = params["limit"] or None

    async def _run() -> int:
        async with search_session(**resolve_session_kwargs(ctx, params)) as session:
            url_iter = iter_term_urls(
                session,
                query=params["query"],
                topic=params["topic"],
                start_letter=params["start_letter"],
                limit=limit,
            )
            records = (UrlRecord(url=url) async for url in url_iter)
            return await output_results(
                records,
                save_paths=params["save_paths"],
                format=params["format"],
                quiet=params["quiet"],
                json_output=params["json_output"],
                show_url=False,
                show_topic=False,
                show_grammar=False,
            )

    count = run_async(_run())
    if not params["quiet"] and count == 0:
        click.echo("No URLs found.", err=True)


def _validate_url(
    ctx: click.Context, param: click.Parameter, value: tuple[str, ...]
) -> tuple[str, ...]:
    """Validate that the user provided a non-empty URL argument."""
    if not value or not any(value):
        raise click.BadParameter("Missing URL argument.")
    return value


@urls.command("fetch")
@click.argument("url", default="", callback=_validate_url)
@click.option(
    "--topic",
    "-t",
    default=None,
    help="Resolve this topic (or comma-separated topics) against the page's definitions.",
)
@click.option(
    "--quiet",
    "-q",
    is_flag=True,
    help="Don't print results to the console (useful with --save).",
)
@click.option(
    "--url-column/--no-url-column",
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
def fetch_url(ctx: click.Context, url: str, use_tui: bool, **params: typing.Any) -> None:
    """
    Fetch every definition found on a single glossary term detail page URL.

    \b
    Examples:
      slb-glossary urls fetch "https://glossary.slb.com/en/terms/p/porosity"
      slb-glossary urls fetch "$URL" --save porosity.json
    """
    if use_tui:
        launch_tui(ctx, command_path=("urls", "fetch"))
        return

    async def _run() -> int:
        async with search_session(**resolve_session_kwargs(ctx, params)) as session:
            results = iter_results_from_url(session, url, topic=params["topic"])
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
        click.echo("No definitions found at that URL.", err=True)
