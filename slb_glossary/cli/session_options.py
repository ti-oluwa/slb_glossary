"""Shared, fully-configurable click options for opening a glossary `SearchSession`."""

import typing

import click

from slb_glossary.browser import BrowserType, ResourceType
from slb_glossary.models import Language
from slb_glossary.retries import BackoffType, RetryPolicy

__all__ = ["session_options", "build_retry_policy", "session_kwargs_from_params"]


F = typing.TypeVar("F", bound=typing.Callable[..., typing.Any])


def _parse_viewport(
    ctx: click.Context, param: click.Parameter, value: str | None
) -> dict[str, int] | None:
    """Parse a `--viewport WIDTHxHEIGHT` option value into a Playwright viewport dict."""
    if value is None:
        return None
    try:
        width_text, height_text = value.lower().split("x", 1)
        return {"width": int(width_text), "height": int(height_text)}
    except ValueError as exc:
        raise click.BadParameter(
            f"{value!r} is not a valid WIDTHxHEIGHT viewport, e.g. '1920x1080'."
        ) from exc


def _parse_proxy(
    ctx: click.Context, param: click.Parameter, value: str | None
) -> dict[str, str] | None:
    """Parse a `--proxy SERVER[,username=U][,password=P]` option value into a Playwright proxy dict."""
    if value is None:
        return None
    parts = [part.strip() for part in value.split(",") if part.strip()]
    if not parts:
        raise click.BadParameter("--proxy must include at least a server URL.")

    proxy: dict[str, str] = {"server": parts[0]}
    for part in parts[1:]:
        key, _, val = part.partition("=")
        key = key.strip().lower()
        if key not in {"username", "password", "bypass"}:
            raise click.BadParameter(
                f"Unknown proxy option {key!r}. Expected 'username', 'password' or 'bypass'."
            )
        proxy[key] = val.strip()
    return proxy


def session_options(func: F) -> F:
    """
    Attach every glossary-session-configuring option to a click command.

    Stack this directly above a command's `def`, alongside `@click.command()`.
    The decorated callback receives each option as a keyword argument named
    after its destination (e.g. `browser_type`, `settle_timeout`); pass the
    full `**kwargs` (or the relevant subset) to `session_kwargs_from_params`
    to turn them into arguments for `slb_glossary.browser.open_session` /
    `search_session`.

    :param func: The click command callback to attach options to.
    :return: `func`, with session-configuration options attached.
    """
    options: list[typing.Callable[[F], F]] = [
        click.option(
            "--language",
            "-L",
            type=click.Choice([lang.value for lang in Language], case_sensitive=False),
            default=Language.ENGLISH.value,
            show_default=True,
            help="Glossary language edition to search.",
        ),
        click.option(
            "--browser-type",
            "-b",
            type=click.Choice([bt.value for bt in BrowserType], case_sensitive=False),
            default=BrowserType.CHROMIUM.value,
            show_default=True,
            help="Playwright browser family to launch.",
        ),
        click.option(
            "--headless/--headed",
            default=True,
            show_default=True,
            help="Run the browser without (or with) a visible window.",
        ),
        click.option(
            "--block/--no-block",
            "block",
            default=True,
            show_default=True,
            help="Block images/media/fonts/stylesheets for faster page loads.",
        ),
        click.option(
            "--block-resource",
            "block_resources",
            type=click.Choice(
                [name.lower() for name in ResourceType.__members__ if name != "ALL"],
                case_sensitive=False,
            ),
            multiple=True,
            help=(
                "Request resource type to block, e.g. 'image'. Repeatable. "
                "Overrides --block/--no-block when given."
            ),
        ),
        click.option(
            "--timeout",
            type=float,
            default=30_000.0,
            show_default=True,
            help="Milliseconds to wait for page loads and element lookups.",
        ),
        click.option(
            "--terms-per-tab",
            type=int,
            default=12,
            show_default=True,
            help="Number of results the glossary site returns per results page.",
        ),
        click.option(
            "--settle-timeout",
            type=float,
            default=8.0,
            show_default=True,
            help="Seconds to wait for the results list to update after a search filter changes.",
        ),
        click.option(
            "--poll-interval",
            type=float,
            default=0.3,
            show_default=True,
            help="Seconds to wait between polls while waiting on --settle-timeout.",
        ),
        click.option(
            "--executable-path",
            type=click.Path(dir_okay=False),
            default=None,
            help="Path to a specific browser build to launch.",
        ),
        click.option(
            "--proxy",
            callback=_parse_proxy,
            default=None,
            metavar="SERVER[,username=U][,password=P]",
            help="Proxy server for the browser to use, e.g. 'http://myproxy:3128'.",
        ),
        click.option(
            "--viewport",
            callback=_parse_viewport,
            default=None,
            metavar="WIDTHxHEIGHT",
            help="Browser viewport size, e.g. '1920x1080'. Defaults to full-screen.",
        ),
        click.option(
            "--stealth/--no-stealth",
            "use_stealth",
            default=True,
            show_default=True,
            help="Apply Playwright stealth patches to the browser context.",
        ),
        click.option(
            "--retry-attempts",
            type=int,
            default=3,
            show_default=True,
            help="Maximum attempts when retrying a flaky initial page load.",
        ),
        click.option(
            "--retry-base-delay",
            type=float,
            default=0.8,
            show_default=True,
            help="Base delay in seconds for the retry backoff calculation.",
        ),
        click.option(
            "--retry-backoff",
            type=click.Choice([bt.value for bt in BackoffType], case_sensitive=False),
            default=BackoffType.EXPONENTIAL.value,
            show_default=True,
            help="Strategy used to grow the delay between retry attempts.",
        ),
        click.option(
            "--retry-factor",
            type=float,
            default=2.0,
            show_default=True,
            help="Growth base for exponential backoff, or log base for logarithmic backoff.",
        ),
        click.option(
            "--retry-max-delay",
            type=float,
            default=10.0,
            show_default=True,
            help="Upper bound in seconds on any single retry delay.",
        ),
        click.option(
            "--retry-jitter/--no-retry-jitter",
            default=True,
            show_default=True,
            help="Randomize each retry delay by up to +/-50%% to avoid retry storms.",
        ),
    ]
    for option in reversed(options):
        func = option(func)
    return func


def build_retry_policy(params: typing.Mapping[str, typing.Any]) -> RetryPolicy:
    """
    Build a `RetryPolicy` from the `retry_*` options `session_options` attaches.

    :param params: The click command's parsed parameters (e.g. `ctx.params`
        or a command callback's `**kwargs`). Only the `retry_*` keys are read.
    :return: A `RetryPolicy` matching the parsed `--retry-*` options.
    """
    return RetryPolicy(
        attempts=params["retry_attempts"],
        base_delay=params["retry_base_delay"],
        backoff_type=BackoffType(params["retry_backoff"]),
        factor=params["retry_factor"],
        max_delay=params["retry_max_delay"],
        jitter=params["retry_jitter"],
    )


def session_kwargs_from_params(params: typing.Mapping[str, typing.Any]) -> dict[str, typing.Any]:
    """
    Turn parsed `session_options` parameters into `open_session`/`search_session` kwargs.

    :param params: The click command's parsed parameters (e.g. `ctx.params`
        or a command callback's `**kwargs`). Extra keys (e.g. a command's
        own `query` or `--save` options) are ignored.
    :return: A keyword-argument dict ready to splat into
        `slb_glossary.browser.open_session` or `search_session`.
    """
    block: bool | frozenset[str] = params["block"]
    block_resources = params.get("block_resources") or ()
    if block_resources:
        block = frozenset(name.lower() for name in block_resources)

    return {
        "language": Language(params["language"]),
        "browser_type": BrowserType(params["browser_type"]),
        "headless": params["headless"],
        "block": block,
        "timeout": params["timeout"],
        "terms_per_tab": params["terms_per_tab"],
        "retry": build_retry_policy(params),
        "settle_timeout": params["settle_timeout"],
        "poll_interval": params["poll_interval"],
        "executable_path": params["executable_path"],
        "proxy": params["proxy"],
        "viewport": params["viewport"],
        "use_stealth": params["use_stealth"],
    }
