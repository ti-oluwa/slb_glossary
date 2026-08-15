"""
Search the SLB Energy Glossary (https://glossary.slb.com/).

All rights to the data and content on the SLB Energy Glossary website are owned by SLB.
This package is not affiliated with or endorsed by SLB.
Visit <https://www.slb.com/en/terms-of-service> for the terms of use.

**Not for commercial use. This package is intended for educational and research purposes only.**

This package can optionally cache glossary data locally (see `slb_glossary.local`)
so repeat lookups don't have to re-visit the site. That local copy is still SLB's
data: anyone who enables local storage is solely responsible for keeping its
retention, refresh, and deletion in compliance with SLB's terms of use linked above.

@Author: Daniel T. Afolayan (ti-oluwa)
"""

import logging as py_logging

from . import live, local, query, store
from . import logging as log
from .browser import (
    BrowserType,
    ResourceType,
    browser_session,
    close_session,
    open_session,
    open_session_from_config,
    session,
    session_from_config,
)
from .config import Config
from .errors import (
    BrowserError,
    ConfigError,
    DatabaseError,
    GlossaryError,
    LoggingError,
    NetworkError,
    ParsingError,
    QueryError,
)
from .models import BrowserSession, Language, SearchResult
from .retries import BackoffType, RetryPolicy
from .topics import get_topic_match, refresh_topics
from .utils import async_print_results, print_results

py_logging.basicConfig(
    format="%(asctime)s - [%(name)s] - %(levelname)s - %(message)s", level=py_logging.INFO
)

__version__ = "0.1.0"
__all__ = [
    "live",
    "local",
    "log",
    "query",
    "store",
    "open_session",
    "open_session_from_config",
    "browser_session",
    "close_session",
    "session",
    "session_from_config",
    "BrowserSession",
    "Config",
    "Language",
    "SearchResult",
    "print_results",
    "async_print_results",
    "get_topic_match",
    "refresh_topics",
    "RetryPolicy",
    "BackoffType",
    "NetworkError",
    "BrowserError",
    "GlossaryError",
    "ParsingError",
    "ConfigError",
    "DatabaseError",
    "QueryError",
    "LoggingError",
    "BrowserType",
    "ResourceType",
]
