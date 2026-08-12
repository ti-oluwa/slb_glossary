"""Individual command implementations wired into `slb_glossary.cli.main`."""

from slb_glossary.cli.commands.install import install
from slb_glossary.cli.commands.search import search
from slb_glossary.cli.commands.terms import terms
from slb_glossary.cli.commands.topics import topics
from slb_glossary.cli.commands.urls import urls

__all__ = ["install", "search", "terms", "topics", "urls"]
