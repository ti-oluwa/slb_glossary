"""Exceptions raised by the package."""


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
