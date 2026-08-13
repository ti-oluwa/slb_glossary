"""Exceptions raised by the `slb_glossary` package."""


class NetworkError(ConnectionError):
    """Raised when a page or resource could not be reached over the network."""


class BrowserError(Exception):
    """Raised when the browser automation layer fails outside of a network issue."""


class ParsingError(Exception):
    """Raised when a glossary page did not contain the markup a parser expected."""
