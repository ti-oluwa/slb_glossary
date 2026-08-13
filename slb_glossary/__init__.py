"""
Search the SLB Energy Glossary (https://glossary.slb.com/).

All rights to the data and content on the SLB Energy Glossary website are owned by SLB. 
This package is not affiliated with or endorsed by SLB.
Visit <https://www.slb.com/en/terms-of-service> for the terms of use.

**Not for commercial use. This package is intended for educational and research purposes only.**

@Author: Daniel T. Afolayan (ti-oluwa)
"""

import logging

from . import store
from .browser import BrowserType, ResourceType, close_session, open_session, search_session
from .engine import get_terms_on, iter_results_from_url, iter_term_urls, search
from .exceptions import BrowserError, NetworkError, ParsingError
from .models import Language, SearchResult, SearchSession
from .retries import BackoffType, RetryPolicy
from .topics import get_topic_match, refresh_topics
from .utils import print_results, print_results_async

logging.basicConfig(
    format="%(asctime)s - [%(name)s] - %(levelname)s - %(message)s", level=logging.INFO
)

__version__ = "0.1.0"
__all__ = [
    "store",
    "open_session",
    "close_session",
    "search_session",
    "SearchSession",
    "Language",
    "SearchResult",
    "search",
    "get_terms_on",
    "iter_term_urls",
    "iter_results_from_url",
    "print_results",
    "print_results_async",
    "get_topic_match",
    "refresh_topics",
    "RetryPolicy",
    "BackoffType",
    "NetworkError",
    "BrowserError",
    "ParsingError",
    "BrowserType",
    "ResourceType",
]
