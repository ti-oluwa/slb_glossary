"""Root `slb-glossary` click group: logging setup, command wiring, and `--tui`."""

import logging
import typing

import click

from slb_glossary.cli.commands import (
    compare,
    config,
    define,
    install,
    local,
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


@click.group("slb-glossary", invoke_without_command=True, no_args_is_help=True)
@click.option(
    "--log-level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], case_sensitive=False),
    default="WARNING",
    show_default=True,
    help="Verbosity of slb_glossary's own logging output.",
)
@click.option(
    "--tui",
    "use_tui",
    is_flag=True,
    help="Open the interactive TUI to browse and run any command.",
)
@click.version_option(package_name="slb-glossary", prog_name="slb-glossary")
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
}

for name, command in COMMANDS.items():
    cli.add_command(typing.cast(click.Command, command), name=name)  # type: ignore[attr-defined]


def main() -> None:
    """Entry point installed as both the `slb-glossary` and `slb` console scripts."""
    cli()  # type: ignore


if __name__ == "__main__":
    main()
