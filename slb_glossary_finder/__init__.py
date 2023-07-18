"""
Module for finding and saving glossary terms from Schlumberger Oilfield Glossary website
https://glossary.slb.com/

#### Internet Connection Required!!!

@Author: Daniel T. Afolayan (ti-oluwa)
"""

from .finder import GlossaryTermsFinder as TermsFinder
from .save import GlossaryTermsSaver as Saver
from .exceptions import *

__version__ = '0.1.0'
__all__ = ['TermsFinder', 'Saver', 'GlossaryTermsFinder', 'GlossaryTermsSaver', "__version__"]
