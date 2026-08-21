"""Root `slb-glossary` click group: logging setup, command wiring, and `--tui`."""

import logging
import typing

import click

from slb_glossary.cli.banner import BANNER
from slb_glossary.cli.commands import (
    compare,
    config,
    define,
    install,
    local,
    mcp,
    random_term,
    related,
    search,
    sync,
    terms,
    topics,
    update,
    urls,
)
from slb_glossary.cli.tui import TuiUnavailableError, launch_tui

__all__ = ["cli", "main"]


def _configure_logging(level_name: str) -> None:
    """Set the root `slb_glossary` logger to `level_name`, leaving the format from `__init__.py` intact."""
    logging.getLogger("slb_glossary").setLevel(getattr(logging, level_name.upper()))


class BannerGroup(click.Group):
    """A `click.Group` that prints `slb_glossary.cli.banner.BANNER` above the usual `--help` text."""

    def format_help(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        formatter.write(BANNER + "\n\n")
        super().format_help(ctx, formatter)


def _print_version(ctx: click.Context, param: click.Parameter, value: bool) -> None:
    """Eager `--version` callback: print `BANNER` plus the package version, then exit."""
    if not value or ctx.resilient_parsing:
        return

    from slb_glossary import __version__

    click.echo(BANNER)
    click.echo()
    click.echo(f"slb-glossary, version {__version__}")
    ctx.exit()


@click.group("slb-glossary", cls=BannerGroup, invoke_without_command=True, no_args_is_help=True)
@click.option(
    "--log-level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], case_sensitive=False),
    default="WARNING",
    show_default=True,
    help="Verbosity of the package's own logging output.",
)
@click.option(
    "--tui",
    "use_tui",
    is_flag=True,
    help="Open the interactive TUI to browse and run any command.",
)
@click.option(
    "--version",
    is_flag=True,
    expose_value=False,
    is_eager=True,
    callback=_print_version,
    help="Show the version and exit.",
)
@click.pass_context
def cli(ctx: click.Context, log_level: str, use_tui: bool) -> None:
    """
    Search the SLB Energy Glossary from the command line.

    Run any subcommand with --help for its full set of options, or pass
    --tui (here, or after a subcommand) to fill them in interactively
    instead of memorizing flags.
    """
    _configure_logging(log_level)
    if use_tui and ctx.invoked_subcommand is None:
        try:
            launch_tui(ctx)
        except TuiUnavailableError as exc:
            raise click.ClickException(str(exc)) from exc
        ctx.exit(0)


COMMANDS = {
    "install": install,
    "search": search,
    "terms": terms,
    "topics": topics,
    "urls": urls,
    "define": define,
    "related": related,
    "compare": compare,
    "random": random_term,
    "sync": sync,
    "update": update,
    "local": local,
    "config": config,
    "mcp": mcp,
}

for name, command in COMMANDS.items():
    cli.add_command(typing.cast(click.Command, command), name=name)  # type: ignore[attr-defined]


def main() -> None:
    """Entry point installed as both the `slb-glossary` and `slb` console scripts."""
    cli()  # type: ignore


if __name__ == "__main__":
    main()
