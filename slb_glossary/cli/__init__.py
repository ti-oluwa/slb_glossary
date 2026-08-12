"""Command-line interface for `slb_glossary`.

This subpackage is an optional extra: it depends on `click` (and, for
`--tui`, `trogon`/`textual`), neither of which the core `slb_glossary`
library requires. Install them with `pip install slb-glossary[cli]` (add
`[cli,tui]` for the TUI too) before importing anything from this package.
"""

try:
    import click  # noqa: F401
except ImportError as exc:  # pragma: no cover - exercised only when click is absent
    raise ImportError(
        "The slb_glossary CLI requires the 'click' package, which is not installed. "
        "Install it with `pip install slb-glossary[cli]`."
    ) from exc

__all__: list[str] = []
