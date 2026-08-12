"""Uniform, error-resilient execution wrapper for CLI command callbacks."""

import functools
import logging
import typing

import click

from slb_glossary.exceptions import BrowserError, NetworkError, ParsingError

logger = logging.getLogger(__name__)


__all__ = ["cli_command"]


P = typing.ParamSpec("P")
R = typing.TypeVar("R")


EXIT_CODES: dict[type[BaseException], int] = {
    NetworkError: 2,
    BrowserError: 3,
    ParsingError: 4,
}
"""
Maps a known library exception type to the process exit code it should
produce, so scripts calling this CLI can distinguish failure causes.
"""


def _describe(exc: BaseException) -> str:
    """Return a one-line, user-facing description of `exc`."""
    message = str(exc).strip()
    return message or exc.__class__.__name__


def cli_command(func: typing.Callable[P, R]) -> typing.Callable[P, R]:
    """
    Wrap a click command callback so failures are reported, not traced.

    Catches exceptions the callback raises, prints a concise `Error: ...`
    message via click instead of a raw traceback, and exits with a code
    from `EXIT_CODES` when the exception is one of this package's known
    error types (falling back to exit code `1` otherwise). Debug logging
    (`--log-level DEBUG`) still shows the full traceback, since the
    exception is logged before the friendly message is printed.

    `click.ClickException`, `click.Abort`, and `KeyboardInterrupt` pass
    through unchanged, since click and the user already handle those.

    :param func: A click command callback to wrap. Apply this as the
        innermost decorator, directly above `def`, so click still sees the
        original function's signature for argument/option parsing.
    :return: A wrapped callback with the same signature as `func`.
    """

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return func(*args, **kwargs)
        except (click.ClickException, click.Abort, KeyboardInterrupt):
            raise
        except Exception as exc:
            logger.debug("Command failed", exc_info=True)
            exit_code = 1
            for exc_type, code in EXIT_CODES.items():
                if isinstance(exc, exc_type):
                    exit_code = code
                    break
            click.secho(f"Error: {_describe(exc)}", fg="red", err=True)
            raise SystemExit(exit_code) from None

    return wrapper
