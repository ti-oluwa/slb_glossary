"""Manage the browser engines patchright launches, via patchright's driver CLI."""

import dataclasses
import logging
import os
import pathlib
import shutil
import subprocess
import sys
import typing

logger = logging.getLogger(__name__)


__all__ = [
    "BrowserInstallError",
    "InstalledBrowser",
    "KNOWN_BROWSERS",
    "install_browsers",
    "list_installed_browsers",
    "remove_browsers",
]


class BrowserInstallError(RuntimeError):
    """Raised when a patchright driver invocation (install/uninstall) fails."""


KNOWN_BROWSERS: tuple[str, ...] = ("chromium", "firefox", "webkit")
"""Browser families patchright's driver knows how to install."""


@dataclasses.dataclass(slots=True, kw_only=True, frozen=True)
class InstalledBrowser:
    """One browser build found on disk in patchright's browser cache."""

    name: str
    """Directory name patchright installed the build under, e.g. `"chromium-1148"`."""

    family: str
    """Browser family the build belongs to, e.g. `"chromium"`."""

    path: pathlib.Path
    """Path to the build's directory."""

    size_bytes: int
    """Total on-disk size of the build's directory."""


def get_browsers_path() -> pathlib.Path:
    """
    Return the directory patchright installs (and looks up) browser builds in.

    Respects the `PLAYWRIGHT_BROWSERS_PATH` environment variable, since
    patchright's driver is a Playwright fork and honors the same variable.
    Falls back to the per-OS default Playwright/patchright cache directory.

    :return: The browsers cache directory. It may not exist yet if no
        browser has ever been installed.
    """
    override = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if override:
        return pathlib.Path(override).expanduser()

    if sys.platform == "win32":
        base = pathlib.Path(os.environ.get("LOCALAPPDATA", "~")).expanduser()
        return base / "ms-playwright"
    if sys.platform == "darwin":
        return pathlib.Path("~/Library/Caches/ms-playwright").expanduser()
    return pathlib.Path("~/.cache/ms-playwright").expanduser()


def get_directory_size(path: pathlib.Path) -> int:
    """Return the total size in bytes of every regular file under `path`."""
    total = 0
    for entry in path.rglob("*"):
        if entry.is_file():
            total += entry.stat().st_size
    return total


def run_driver(args: typing.Sequence[str]) -> None:
    """
    Run `python -m patchright <args>`, streaming its output live.

    :param args: Arguments to pass after `patchright` on the command line,
        e.g. `["install", "chromium", "--with-deps"]`.
    :raises BrowserInstallError: If patchright isn't importable, or the
        driver process exits with a non-zero status.
    """
    try:
        import patchright  # noqa: F401
    except ImportError as exc:
        raise BrowserInstallError(
            "patchright is not installed. Install it with `pip install patchright` "
            "or `pip install slb-glossary` (it's a core dependency of the library)."
        ) from exc

    command = [sys.executable, "-m", "patchright", *args]
    logger.debug("Running: %s", " ".join(command))
    try:
        result = subprocess.run(command, check=False)
    except OSError as exc:
        raise BrowserInstallError(f"Could not run the patchright driver: {exc}") from exc

    if result.returncode != 0:
        raise BrowserInstallError(f"`{' '.join(command)}` exited with status {result.returncode}.")


def install_browsers(
    browsers: typing.Sequence[str],
    *,
    with_deps: bool = False,
    force: bool = False,
    only_shell: bool = False,
) -> None:
    """
    Install one or more browser engines via patchright's driver.

    :param browsers: Browser family names to install, e.g. `["chromium"]`.
        An empty sequence installs patchright's default set of browsers.
    :param with_deps: Also install the OS-level packages the browsers need
        to run (Linux only). Requires root/sudo privileges on most systems.
    :param force: Reinstall even if the browser is already present.
    :param only_shell: For Chromium, install the headless-shell build
        instead of the full browser. Ignored for other browsers.
    :raises BrowserInstallError: If the install fails for any reason,
        including patchright not being installed.
    """
    args = ["install", *browsers]
    if with_deps:
        args.append("--with-deps")
    if force:
        args.append("--force")
    if only_shell:
        args.append("--only-shell")
    run_driver(args)


def remove_browsers(browsers: typing.Sequence[str]) -> list[str]:
    """
    Delete installed browser builds matching the given families from disk.

    patchright's driver has no per-browser uninstall subcommand, so this
    removes matching build directories directly from the browsers cache
    instead of shelling out to the driver.

    :param browsers: Browser family names to remove, e.g. `["firefox"]`.
        Matches by directory name prefix (`"firefox-1234"` matches
        `"firefox"`), so every installed build of a family is removed.
    :return: Names of the build directories that were actually removed.
        Empty if none of `browsers` were installed.
    :raises BrowserInstallError: If a matching directory could not be
        removed, e.g. due to a permissions error.
    """
    if not browsers:
        return []

    base = get_browsers_path()
    if not base.is_dir():
        return []

    wanted = {family.lower() for family in browsers}
    removed: list[str] = []
    for entry in sorted(base.iterdir()):
        if not entry.is_dir():
            continue
        family = entry.name.split("-", 1)[0].lower()
        # patchright also ships a "-headless-shell" suffix variant for chromium.
        family = family.removesuffix("_headless_shell")
        if family not in wanted and not any(entry.name.startswith(f"{w}") for w in wanted):
            continue
        try:
            shutil.rmtree(entry)
        except OSError as exc:
            raise BrowserInstallError(f"Could not remove {entry}: {exc}") from exc
        removed.append(entry.name)
        logger.info("Removed browser build %s", entry.name)

    return removed


def list_installed_browsers(
    browsers: typing.Sequence[str] | None = None,
) -> list[InstalledBrowser]:
    """
    List browser builds currently installed in patchright's browsers cache.

    :param browsers: If given, only list builds belonging to these
        families, e.g. `["chromium", "webkit"]`. Lists every installed
        build if `None` or empty.
    :return: Installed builds, sorted by family then build name. Empty if
        the browsers cache does not exist yet (nothing has been installed).
    """
    base = get_browsers_path()
    if not base.is_dir():
        return []

    wanted = {family.lower() for family in browsers} if browsers else None
    found: list[InstalledBrowser] = []
    for entry in sorted(base.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        family = entry.name.split("-", 1)[0].lower()
        if family not in KNOWN_BROWSERS:
            continue
        if wanted is not None and family not in wanted:
            continue
        found.append(
            InstalledBrowser(
                name=entry.name,
                family=family,
                path=entry,
                size_bytes=get_directory_size(entry),
            )
        )

    return sorted(found, key=lambda browser: (browser.family, browser.name))
