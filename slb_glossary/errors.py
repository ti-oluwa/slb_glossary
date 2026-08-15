"""Exceptions raised by the package."""

import pathlib


class GlossaryError(Exception):
    """Base exception for all errors in the glossary"""


class NetworkError(ConnectionError, GlossaryError):
    """Raised when a page or resource could not be reached over the network."""


class BrowserError(GlossaryError):
    """Raised when the browser automation layer fails outside of a network issue."""


class ParsingError(GlossaryError):
    """Raised when a glossary page did not contain the markup a parser expected."""


class ConfigError(GlossaryError):
    """Raised when a `slb_glossary.config.Config` file or key is invalid."""


class DatabaseError(GlossaryError):
    """Raised when `slb_glossary.local` fails to open, query, or write the local database."""


class QueryError(GlossaryError):
    """Raised when `slb_glossary.query` can't satisfy a lookup with the source(s) it was given."""


class LoggingError(GlossaryError):
    """Raised when a `slb_glossary.logging` sink (e.g. `--log-to`/`--log-sink`) could not be set up."""


class UnsupportedFormatError(ValueError, GlossaryError):
    """Raised when `save` is asked to write a format with no registered writer."""


class WriterError(OSError, GlossaryError):
    """
    Raised when a registered writer fails while writing `records`.

    Wraps whatever the writer itself raised (typically an `OSError` from
    the filesystem, but any exception is caught) with the destination path
    and resolved format attached, so callers get useful context without
    needing to inspect the writer's internals. The original exception is
    always available via `__cause__`.
    """

    def __init__(self, message: str, *, destination: pathlib.Path, format: str) -> None:
        super().__init__(message)
        self.destination = destination
        self.format = format
