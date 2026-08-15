"""
Shared `--local`/`--live`/`--intelligent` options for commands built on `slb_glossary.query`.

Also handles resolving *where* the local database lives for those
commands (`--db-path`, or the `Database` section of the loaded `Config`),
and opening it/a live session lazily, so a command that turns out to be
satisfiable locally never pays for launching a browser.
"""

import contextlib
import pathlib
import typing

import click

from slb_glossary.browser import search_session
from slb_glossary.cli.session_options import (
    load_named_config,
    resolve_session_kwargs,
)
from slb_glossary.config import Config
from slb_glossary.local.connection import local_db
from slb_glossary.local.models import Database
from slb_glossary.models import SearchSession
from slb_glossary.paths import get_data_dir
from slb_glossary.query import Source, TermLookup

__all__ = [
    "source_options",
    "resolve_source",
    "local_db_option",
    "resolve_db_path",
    "local_storage_enabled",
    "open_configured_db",
    "live_session",
    "resolve_lookup",
    "resolve_stream",
    "get_loaded_config",
]


F = typing.TypeVar("F", bound=typing.Callable[..., typing.Any])


def source_options(func: F) -> F:
    """
    Attach `--source`, its `--local`/`--live`/`--intelligent` shorthands, and `--cache` to a command.

    Pair with `resolve_source` to turn the parsed flags into one `Source`.

    :param func: The click command callback to attach options to.
    :return: `func`, with the source-selection options attached.
    """
    func = click.option(
        "--cache/--no-cache",
        "cache_results",
        default=True,
        show_default=True,
        help=(
            "When a live fetch happens, save its results to the local "
            "database so the same lookup is served locally next time."
        ),
    )(func)
    func = click.option(
        "--intelligent",
        "source_intelligent",
        is_flag=True,
        help="Shorthand for --source intelligent (the default): local first, live as a fallback.",
    )(func)
    func = click.option(
        "--live",
        "source_live",
        is_flag=True,
        help="Shorthand for --source live: always fetch from the live glossary.",
    )(func)
    func = click.option(
        "--local",
        "source_local",
        is_flag=True,
        help="Shorthand for --source local: only read the local database, never the network.",
    )(func)
    func = click.option(
        "--source",
        "source",
        type=click.Choice([s.value for s in Source], case_sensitive=False),
        default=None,
        help="Where to read from. Same choices as --local/--live/--intelligent, spelled out.",
    )(func)
    return func


def resolve_source(params: typing.Mapping[str, typing.Any]) -> Source:
    """
    Resolve `--source`/`--local`/`--live`/`--intelligent` to one `Source`.

    :param params: The command's parsed parameters, as attached by `source_options`.
    :return: The resolved `Source`. `Source.INTELLIGENT` if nothing was given.
    :raises click.UsageError: If more than one of the flags/`--source` was given.
    """
    chosen: list[Source] = []
    if params.get("source_local"):
        chosen.append(Source.LOCAL)
    if params.get("source_live"):
        chosen.append(Source.LIVE)
    if params.get("source_intelligent"):
        chosen.append(Source.INTELLIGENT)
    if params.get("source"):
        chosen.append(Source(str(params["source"]).lower()))

    unique = list(dict.fromkeys(chosen))
    if len(unique) > 1:
        raise click.UsageError("Give at most one of --source/--local/--live/--intelligent.")
    return unique[0] if unique else Source.INTELLIGENT


def local_db_option(func: F) -> F:
    """
    Attach `--db-path` to a command that may open the local search database.

    :param func: The click command callback to attach the option to.
    :return: `func`, with `--db-path` attached.
    """
    return click.option(
        "--db-path",
        "db_path",
        type=click.Path(dir_okay=False, path_type=pathlib.Path),
        default=None,
        help=(
            "Path to the local search database file. Defaults to the path "
            "configured in `slb-glossary config` (or the OS default - see "
            "`slb-glossary local path`)."
        ),
    )(func)


def resolve_db_path(config: Config, override: pathlib.Path | None) -> pathlib.Path:
    """
    Resolve the local database file path for this run.

    :param config: The loaded `Config` (see `slb_glossary.cli.session_options.load_named_config`).
    :param override: An explicit `--db-path` value, if given. Takes precedence over `config`.
    :return: The resolved database file path.
    """
    if override is not None:
        return pathlib.Path(override)
    return get_data_dir(config.local.data_dir) / config.local.db_filename


def local_storage_enabled(config: Config, *, db_path_override: pathlib.Path | None) -> bool:
    """
    Return whether commands should try the local database by default for this run.

    An explicit `--db-path` always counts as "yes" (the user named a
    database, so use it), regardless of `config.local.enabled`.

    :param config: The loaded `Config`.
    :param db_path_override: An explicit `--db-path` value, if given.
    :return: `True` if local-database fallback should be attempted.
    """
    return db_path_override is not None or config.local.enabled


@contextlib.asynccontextmanager
async def open_configured_db(
    config: Config, *, db_path_override: pathlib.Path | None
) -> typing.AsyncIterator[Database | None]:
    """
    Open the configured local database for the duration of an `async with` block.

    Yields `None` (opens nothing) if local storage isn't enabled for this
    run - see `local_storage_enabled`.

    :param config: The loaded `Config`.
    :param db_path_override: An explicit `--db-path` value, if given.
    :yield: An open `Database`, or `None` if local storage is disabled.
    """
    if not local_storage_enabled(config, db_path_override=db_path_override):
        yield None
        return
    async with local_db(resolve_db_path(config, db_path_override)) as db:
        yield db


@contextlib.asynccontextmanager
async def live_session(
    ctx: click.Context, params: typing.Mapping[str, typing.Any]
) -> typing.AsyncIterator[SearchSession]:
    """
    Open a live `SearchSession` for the duration of an `async with` block.

    A thin wrapper around `slb_glossary.browser.search_session` using this
    run's resolved `--config`/session flags - kept here so query commands
    have one obvious way to open the browser only once they've actually
    decided they need it (e.g. after a local-only pass came back empty).

    :param ctx: The current click context.
    :param params: The command's parsed parameters, including everything
        `slb_glossary.cli.session_options.session_options`/`config_option` attach.
    :yield: An open `SearchSession`.
    """
    async with search_session(**resolve_session_kwargs(ctx, params)) as session:
        yield session


def get_loaded_config(params: typing.Mapping[str, typing.Any]) -> Config:
    """Load the `Config` named by this run's `--config` option (see `config_option`)."""
    return load_named_config(params.get("config_path", "default"))


T = typing.TypeVar("T")


async def resolve_lookup(
    ctx: click.Context,
    params: typing.Mapping[str, typing.Any],
    db: Database | None,
    *,
    source: Source,
    local_call: typing.Callable[[Database], typing.Awaitable[TermLookup[T]]],
    live_call: typing.Callable[[SearchSession], typing.Awaitable[TermLookup[T]]],
) -> TermLookup[T]:
    """
    Run a single-value `slb_glossary.query` lookup, opening a live session only if actually needed.

    For `Source.INTELLIGENT`, `local_call` is tried first (no browser
    launched); a live session is opened via `live_call` only if that came
    back empty (`TermLookup.value` falsy).

    :param ctx: The current click context.
    :param params: The command's parsed parameters (for `live_session`).
    :param db: An already-open local `Database`, or `None` if local storage
        is disabled for this run.
    :param source: The resolved `Source` to honor (see `resolve_source`).
    :param local_call: Awaitable-returning callable given `db`, e.g.
        `lambda db: query.get_term(term, db=db, source=Source.LOCAL)`.
    :param live_call: Awaitable-returning callable given an opened
        `SearchSession`, e.g. `lambda s: query.get_term(term, db=db,
        session=s, source=Source.LIVE, persist=cache_results)`.
    :return: The resolved `TermLookup`.
    :raises click.UsageError: If `source` is `Source.LOCAL` but `db` is `None`.
    """
    if source is Source.LOCAL:
        if db is None:
            raise click.UsageError(
                "--local needs a local database, but local storage is disabled "
                "for this run (see `slb-glossary config get local.enabled`) "
                "and no --db-path was given."
            )
        return await local_call(db)

    if source is Source.LIVE:
        async with live_session(ctx, params) as session:
            return await live_call(session)

    # Source.INTELLIGENT: a local hit never opens a browser.
    if db is not None:
        local_result = await local_call(db)
        if local_result.value:
            return local_result

    async with live_session(ctx, params) as session:
        return await live_call(session)


async def resolve_stream(
    ctx: click.Context,
    params: typing.Mapping[str, typing.Any],
    db: Database | None,
    *,
    source: Source,
    local_call: typing.Callable[[Database], typing.AsyncIterator[T]],
    live_call: typing.Callable[[SearchSession], typing.AsyncIterator[T]],
) -> typing.AsyncIterator[T]:
    """
    Stream a `slb_glossary.query`-style lookup, opening a live session only if actually needed.

    The streaming counterpart to `resolve_lookup`, for commands built on a
    `slb_glossary.query` function that yields several results (`search`,
    `get_terms_on`, `get_terms_urls`) rather than a single `TermLookup`.

    For `Source.INTELLIGENT`, `local_call` is fully drained first (no
    browser launched); a live session is opened via `live_call` only if
    that came back with nothing at all.

    :param ctx: The current click context.
    :param params: The command's parsed parameters (for `live_session`).
    :param db: An already-open local `Database`, or `None` if local storage
        is disabled for this run.
    :param source: The resolved `Source` to honor (see `resolve_source`).
    :param local_call: Async-generator-returning callable given `db`, e.g.
        `lambda db: query.search(term, db=db, source=Source.LOCAL)`.
    :param live_call: Async-generator-returning callable given an opened
        `SearchSession`, e.g. `lambda s: query.search(term, db=db,
        session=s, source=Source.LIVE, persist=cache_results)`.
    :yield: Whatever `local_call`/`live_call` yield.
    :raises click.UsageError: If `source` is `Source.LOCAL` but `db` is `None`.
    """
    if source is Source.LOCAL:
        if db is None:
            raise click.UsageError(
                "--local needs a local database, but local storage is disabled "
                "for this run (see `slb-glossary config get local.enabled`) "
                "and no --db-path was given."
            )
        async for item in local_call(db):
            yield item
        return

    if source is Source.LIVE:
        async with live_session(ctx, params) as session:
            async for item in live_call(session):
                yield item
        return

    # Source.INTELLIGENT: a local hit never opens a browser.
    if db is not None:
        local_items = [item async for item in local_call(db)]
        if local_items:
            for item in local_items:
                yield item
            return

    async with live_session(ctx, params) as session:
        async for item in live_call(session):
            yield item
