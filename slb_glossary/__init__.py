"""
Search the Schlumberger Oilfield Glossary programmatically using Selenium.
https://glossary.slb.com/

This package is meant for educational/instructional use only and may not be 
suitable for production.

#### Internet Connection Required!!!

@Author: Daniel T. Afolayan (ti-oluwa)
"""

from .glossary import Glossary, Browser, Language, SearchResult
from .saver import Saver


__version__ = '0.0.1b'
__all__ = [
    'Glossary', 
    'Saver', 
    "Browser", 
    "Language", 
    "SearchResult"
]

