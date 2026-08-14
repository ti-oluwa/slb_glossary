"""`slb-glossary local` - inspect, search, and maintain the local search database directly."""

import typing

import click

from slb_glossary import local as local_pkg
from slb_glossary.cli.commands.sync import sync as sync_command
from slb_glossary.cli.commands.update import update as update_command
from slb_glossary.cli.errors import cli_command
from slb_glossary.cli.runtime import run_async
from slb_glossary.cli.session_options import config_option
from slb_glossary.cli.source_options import get_loaded_config, local_db_option, resolve_db_path
from slb_glossary.cli.store_options import output_results, store_options
from slb_glossary.local.models import Metadata

__all__ = ["local"]


@click.group("local")
def local() -> None:
    """
    Inspect, search, and maintain the local search database directly.

    Every command here talks only to the local database - never the live
    site - regardless of any --local/--live/--intelligent flag elsewhere.
    `local sync`/`local update` are the exception (and the only ones here
    that go live): they're the same commands as top-level `sync`/`update`,
    grouped here too for discoverability.
    """


@local.command("path")
@local_db_option
@config_option
@cli_command
def show_path(**params: typing.Any) -> None:
    """
    Print the resolved local database and metadata file paths.

    \b
    Examples:
      slb-glossary local path
    """

    async def _run() -> tuple[typing.Any, typing.Any]:
        config = get_loaded_config(params)
        db_path = resolve_db_path(config, params["db_path"])
        async with local_pkg.local_db(db_path) as db:
            return db.db_path, db.metadata_path

    db_path, metadata_path = run_async(_run())
    click.echo(f"Database: {db_path}")
    click.echo(f"Metadata: {metadata_path}")


@local.command("stats")
@local_db_option
@config_option
@click.option(
    "--json",
    "json_output",
    is_flag=True,
    help="Print stats as JSON instead of a human-readable summary.",
)
@cli_command
def stats(**params: typing.Any) -> None:
    """
    Print term counts, topic breakdown, and last-sync info for the local database.

    \b
    Examples:
      slb-glossary local stats
      slb-glossary local stats --json
    """

    async def _run() -> tuple[int, dict[str, int], Metadata]:
        config = get_loaded_config(params)
        db_path = resolve_db_path(config, params["db_path"])
        async with local_pkg.local_db(db_path) as db:
            total = await local_pkg.count(db)
            topics = await local_pkg.iter_topics(db)
            metadata = Metadata.load(db.metadata_path)
            return total, topics, metadata

    total, topics, metadata = run_async(_run())

    if params["json_output"]:
        import json

        click.echo(
            json.dumps(
                {
                    "term_count": total,
                    "topics": topics,
                    "last_synced_at": metadata.last_synced_at,
                    "last_sync_language": metadata.last_sync_language,
                    "schema_version": metadata.schema_version,
                },
                indent=2,
            )
        )
        return

    click.echo(f"Terms stored locally: {total}")
    click.echo(f"Last synced: {metadata.last_synced_at or 'never'}")
    if metadata.last_sync_language:
        click.echo(f"Last sync language: {metadata.last_sync_language}")
    if topics:
        click.echo(f"Topics ({len(topics)}):")
        for name, count in sorted(topics.items(), key=lambda item: item[1], reverse=True):
            click.echo(f"  {name:<40} {count}")
    else:
        click.echo("No topics stored locally yet.")


@local.command("search")
@click.argument("query", default="")
@click.option(
    "--topic",
    "-t",
    default=None,
    help="Restrict results to this topic, or several comma-separated topics.",
)
@click.option(
    "--fuzzy",
    is_flag=True,
    help="Tolerate minor misspellings/partial names in --topic, matched "
    "against topics actually stored locally, instead of requiring an exact "
    "(case-insensitive) match.",
)
@click.option(
    "--limit",
    "-n",
    type=int,
    default=20,
    show_default=True,
    help="Maximum number of results. Use 0 for unlimited.",
)
@click.option(
    "--quiet",
    "-q",
    is_flag=True,
    help="Don't print results to the console (useful with --save).",
)
@local_db_option
@config_option
@store_options
@cli_command
def local_search(query: str, **params: typing.Any) -> None:
    """
    Full-text search the local database only. Never touches the live glossary.

    \b
    Examples:
      slb-glossary local search porosity
      slb-glossary local search "drilling fluid" --topic Drilling
      slb-glossary local search viscosity --topic Petrophysic --fuzzy
    """
    if not query.strip():
        raise click.BadParameter("Missing search query.")

    limit = params["limit"] or None

    async def _run() -> int:
        config = get_loaded_config(params)
        db_path = resolve_db_path(config, params["db_path"])
        async with local_pkg.local_db(db_path) as db:
            results = local_pkg.search(
                db, query, topic=params["topic"], limit=limit, fuzzy=params["fuzzy"]
            )
            return await output_results(
                results,
                save_paths=params["save_paths"],
                format=params["format"],
                quiet=params["quiet"],
                json_output=params["json_output"],
            )

    count = run_async(_run())
    if not params["quiet"] and count == 0:
        click.echo("No local results found.", err=True)


@local.command("get")
@click.argument("term_or_url", default="")
@local_db_option
@config_option
@store_options
@click.option(
    "--quiet",
    "-q",
    is_flag=True,
    help="Don't print the result to the console (useful with --save).",
)
@cli_command
def local_get(term_or_url: str, **params: typing.Any) -> None:
    """
    Look up a single term by exact name or URL in the local database only.

    \b
    Examples:
      slb-glossary local get porosity
    """
    if not term_or_url.strip():
        raise click.BadParameter("Missing term or URL.")

    async def _run() -> int:
        config = get_loaded_config(params)
        db_path = resolve_db_path(config, params["db_path"])
        async with local_pkg.local_db(db_path) as db:
            result = await local_pkg.get_term(db, term_or_url)
            if result is None:
                return 0

            async def _one() -> typing.AsyncIterator[typing.Any]:
                yield result

            return await output_results(
                _one(),
                save_paths=params["save_paths"],
                format=params["format"],
                quiet=params["quiet"],
                json_output=params["json_output"],
            )

    count = run_async(_run())
    if not params["quiet"] and count == 0:
        click.echo(f"{term_or_url!r} was not found locally.", err=True)


@local.command("flush")
@local_db_option
@config_option
@click.option("--yes", "-y", "assume_yes", is_flag=True, help="Don't ask for confirmation.")
@cli_command
def flush(**params: typing.Any) -> None:
    """
    Delete every locally stored term, keeping sync history/metadata intact.

    \b
    Examples:
      slb-glossary local flush --yes
    """
    if not params["assume_yes"]:
        click.confirm("Delete every term stored in the local database?", abort=True)

    async def _run() -> None:
        config = get_loaded_config(params)
        db_path = resolve_db_path(config, params["db_path"])
        async with local_pkg.local_db(db_path) as db:
            await local_pkg.flush(db)

    run_async(_run())
    click.echo("Local database flushed.")


@local.command("reset")
@local_db_option
@config_option
@click.option("--yes", "-y", "assume_yes", is_flag=True, help="Don't ask for confirmation.")
@cli_command
def reset(**params: typing.Any) -> None:
    """
    Flush the local database and forget its sync history too.

    \b
    Examples:
      slb-glossary local reset --yes
    """
    if not params["assume_yes"]:
        click.confirm(
            "Delete every term AND reset sync history in the local database?", abort=True
        )

    async def _run() -> None:
        config = get_loaded_config(params)
        db_path = resolve_db_path(config, params["db_path"])
        async with local_pkg.local_db(db_path) as db:
            await local_pkg.reset(db)

    run_async(_run())
    click.echo("Local database reset.")


# `sync`/`update` are the same commands registered at the CLI root, added
# here too under `local` for discoverability - both go live, unlike
# everything else in this group.
local.add_command(sync_command, name="sync")
local.add_command(update_command, name="update")
