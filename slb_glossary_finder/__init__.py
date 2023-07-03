"""
Module for finding and saving glossary terms from Schlumberger Oilfield Glossary website
https://glossary.slb.com/

@Author: Afolayan Daniel Toluwalase (ti-oluwa)
"""

from .finder import SLBGlossaryTermsFinder as TermsFinder
from .save import GlossaryTermsSaver as Saver
from .exceptions import *

__all__ = ['TermsFinder', 'Saver']
__version__ = '0.1.0'