"""A small ASCII-art banner for the `slb-glossary` CLI's `--help`/`--version` output."""

__all__ = ["BANNER"]

BANNER = r"""
 ____  _     ____
/ ___|| |   | __ )
\___ \| |   |  _ \
 ___) | |___| |_) |
|____/|_____|____/    glossary
""".strip("\n")
"""
Rendered once at the top of `slb-glossary --help`/`--version`, via
`slb_glossary.cli.main.BannerGroup`/`slb_glossary.cli.main._version_option`.
Plain ASCII (no box-drawing/unicode) so it renders identically in any terminal.
"""
