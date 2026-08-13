"""Exceptions raised by the `slb_glossary` package."""


class NetworkError(ConnectionError):
    """Raised when a page or resource could not be reached over the network."""


class BrowserError(Exception):
    """Raised when the browser automation layer fails outside of a network issue."""


class ParsingError(Exception):
    """Raised when a glossary page did not contain the markup a parser expected."""


class ConfigError(Exception):
    """Raised when a `slb_glossary.config.Config` file or key is invalid."""


class LocalDBError(Exception):
    """Raised when `slb_glossary.localdb` fails to open, query, or write the local database."""
