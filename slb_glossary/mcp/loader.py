"""
Load a pre-built MCP server from a dotted import path, uvicorn-style.

Lets `slb mcp serve` run an app a user assembled themselves in Python -
with custom hooks, a hand-built `AuthBackend`, extra tools bolted on, or a
plain `fastmcp.FastMCP` with its own middleware - instead of one this CLI
builds from flags:

```
slb mcp serve app.main:app
```

where `app/main.py` has something like:

```python
from slb_glossary.mcp import MCPApp, MCPConfig, LocalAccessConfig

app = MCPApp(MCPConfig(local=LocalAccessConfig(allow_write=True)))
```

`app` there can be an `MCPApp`, a raw `fastmcp.FastMCP` (e.g. for a server
that doesn't use `slb_glossary.mcp.tools` at all), or a zero-argument
callable/factory returning either - resolved the same way uvicorn's
`--factory` targets are, but without needing a separate flag: this module
just calls whatever it finds if it's callable and not already a server instance.
"""

import importlib
import inspect

from fastmcp import FastMCP

from slb_glossary.mcp.api import MCPApp

__all__ = ["load_app"]


def load_app(dotted_path: str) -> MCPApp | FastMCP:
    """
    Import `dotted_path` and return the `MCPApp`/`FastMCP` instance it points to.

    :param dotted_path: `"module:attr"` or `"package.module:attr"` - the
        part after `:` is looked up with `getattr` on the imported module.
        If that attribute is callable and not already an `MCPApp`/`FastMCP`,
        it's called with no arguments and its return value is used instead
        (a factory function, e.g. `def create_app() -> MCPApp: ...`).
    :return: The resolved `MCPApp` or `FastMCP` instance.
    :raises ValueError: If `dotted_path` doesn't contain a `:` separator.
    :raises ImportError: If the module can't be imported, or has no such attribute.
    :raises TypeError: If, after resolving/calling it, the result still
        isn't an `MCPApp` or `FastMCP`.
    """
    module_path, sep, attr = dotted_path.partition(":")
    if not sep or not module_path or not attr:
        raise ValueError(
            f"{dotted_path!r} is not a valid app import path. Use "
            f"'module:attr' or 'package.module:attr', e.g. 'app.main:app'."
        )

    module = importlib.import_module(module_path)
    try:
        target = getattr(module, attr)
    except AttributeError as exc:
        raise ImportError(f"Module {module_path!r} has no attribute {attr!r}") from exc

    app = target
    if callable(app) and not isinstance(app, (MCPApp, FastMCP)):
        app = app()
        if inspect.isawaitable(app):
            raise TypeError(
                f"{dotted_path!r} resolved to an async factory ({target!r}); "
                f"only synchronous zero-argument factories are supported. Build the "
                f"MCPApp/FastMCP instance at import time instead (e.g. module-level "
                f"`app = MCPApp(...)`), or call your async setup yourself and expose "
                f"the already-built instance as the target attribute."
            )

    if not isinstance(app, (MCPApp, FastMCP)):
        raise TypeError(
            f"{dotted_path!r} resolved to {app!r}, which is neither an MCPApp, a "
            f"FastMCP, nor a zero-argument factory returning one."
        )
    return app
