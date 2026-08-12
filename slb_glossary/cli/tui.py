"""Launch trogon's auto-generated TUI for the CLI, on demand.

Kept isolated from `slb_glossary.cli.main` so importing the CLI never
requires `trogon`/`textual` unless `--tui` is actually used - both are
optional extras (`pip install slb-glossary[tui]`).
"""

import inspect
import logging
import typing

import click

logger = logging.getLogger(__name__)


__all__ = ["TuiUnavailableError", "launch_tui"]


class TuiUnavailableError(RuntimeError):
    """Raised when `--tui` is used but `trogon` (or `textual`) isn't installed."""


def launch_tui(ctx: click.Context, *, command_path: typing.Sequence[str] = ()) -> None:
    """
    Open trogon's interactive TUI for the CLI rooted at `ctx`.

    :param ctx: The click context of the command `--tui` was passed to.
        Its top-level command group is what the TUI renders and drives -
        every command and option in the group becomes browsable/fillable.
    :param command_path: Names of the command (and parent groups, if any)
        to preselect in the TUI, e.g. `("search",)`. Best-effort: applied
        only if the installed trogon version exposes a way to preselect a
        command; otherwise the TUI opens with nothing preselected, so this
        never turns into a hard failure just because trogon changed shape.
    :raises TuiUnavailableError: If `trogon` (or one of its own
        dependencies, e.g. `textual`) is not installed.
    """
    try:
        from trogon.trogon import Trogon
    except ImportError as exc:
        raise TuiUnavailableError(
            "The --tui flag requires the 'trogon' and 'textual' packages. "
            "Install them with `pip install slb-glossary[tui]`."
        ) from exc

    root_ctx = ctx.find_root()
    root_command = root_ctx.command
    if not isinstance(root_command, click.Group):
        raise TuiUnavailableError("The TUI requires a click.Group as the CLI's root command.")

    kwargs: dict[str, typing.Any] = {
        "click_context": root_ctx,
        "app_name": root_ctx.info_name or "slb-glossary",
    }
    supported = inspect.signature(Trogon.__init__).parameters
    if command_path and "command_name" in supported:
        kwargs["command_name"] = list(command_path)
    elif command_path:
        logger.debug(
            "Installed trogon version has no command_name parameter; "
            "opening the TUI without preselecting %r",
            command_path,
        )

    app = Trogon(root_command, **kwargs)
    app.run()
