"""Command-line interface for `slb_glossary`.

`click` is a core dependency of `slb_glossary`, so this subpackage is
always importable once the package itself is installed - this is what
lets `slb-glossary`/`slb` work immediately via `pipx install slb-glossary`,
`uvx slb-glossary`, or the curl installer, none of which let a user opt
into an extra first. Only `--tui` needs anything further: install
`slb-glossary[tui]` (`trogon`/`textual`) to use it.
"""

__all__: list[str] = []
