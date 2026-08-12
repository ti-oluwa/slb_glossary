"""`slb-glossary topics` - list and refresh the glossary's topic (discipline) list."""

import typing

import click

from slb_glossary.browser import search_session
from slb_glossary.cli.errors import cli_command
from slb_glossary.cli.runtime import run_async
from slb_glossary.cli.session_options import session_kwargs_from_params, session_options
from slb_glossary.cli.store_options import save_and_print, store_options
from slb_glossary.cli.tui import launch_tui
from slb_glossary.topics import refresh_topics

__all__ = ["topics"]


class TopicRecord(typing.NamedTuple):
    """A single glossary topic (discipline) and its term count, saveable via `slb_glossary.store`."""

    topic: str
    """The topic's display name."""

    term_count: int
    """Number of glossary terms filed under this topic."""

    @property
    def fields(self) -> list[str]:
        """Return a list of the field names in this record."""
        return list(self._fields)

    def asdict(self) -> dict[str, typing.Any]:
        """Return a dictionary representation of this record."""
        return self._asdict()


@click.group("topics")
def topics() -> None:
    """List or refresh the glossary's topic (discipline) list."""


async def _topic_records(topic_counts: typing.Mapping[str, int]) -> typing.AsyncIterator[TopicRecord]:
    """Yield a `TopicRecord` for each entry in `topic_counts`, sorted by name."""
    for name, count in sorted(topic_counts.items()):
        yield TopicRecord(topic=name, term_count=count)


@topics.command("list")
@click.option(
    "--quiet",
    "-q",
    is_flag=True,
    help="Don't print topics to the console (useful with --save).",
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
def list_topics(ctx: click.Context, use_tui: bool, **params: typing.Any) -> None:
    """
    List every topic (discipline) the glossary is organized under, with term counts.

    \b
    Examples:
      slb-glossary topics list
      slb-glossary topics list --save topics.csv --quiet
    """
    if use_tui:
        launch_tui(ctx, command_path=("topics", "list"))
        return

    async def _run() -> int:
        async with search_session(**session_kwargs_from_params(params)) as session:
            return await save_and_print(
                _topic_records(session.topics),
                save_paths=params["save_paths"],
                format=params["format"],
                quiet=params["quiet"],
                show_url=False,
                show_topic=False,
                show_grammar=False,
            )

    count = run_async(_run())
    if not params["quiet"] and count == 0:
        click.echo("No topics found.", err=True)


@topics.command("refresh")
@click.option(
    "--quiet",
    "-q",
    is_flag=True,
    help="Don't print topics to the console (useful with --save).",
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
def refresh(ctx: click.Context, use_tui: bool, **params: typing.Any) -> None:
    """
    Reload the glossary's topic list and term counts directly from the site.

    Unlike `topics list`, this reloads the search page instead of trusting
    the topic list captured when the session opened - use it if the
    glossary's topics may have changed since.

    \b
    Examples:
      slb-glossary topics refresh
    """
    if use_tui:
        launch_tui(ctx, command_path=("topics", "refresh"))
        return

    async def _run() -> int:
        async with search_session(**session_kwargs_from_params(params)) as session:
            session = await refresh_topics(session)
            return await save_and_print(
                _topic_records(session.topics),
                save_paths=params["save_paths"],
                format=params["format"],
                quiet=params["quiet"],
                show_url=False,
                show_topic=False,
                show_grammar=False,
            )

    count = run_async(_run())
    if not params["quiet"] and count == 0:
        click.echo("No topics found.", err=True)
