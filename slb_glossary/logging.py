"""
Pluggable logging sinks for `slb_glossary`, meant for CLI/bug-report use.

`slb_glossary.__init__` calls `logging.basicConfig` so the package logs
somewhere useful out of the box. This module exists for callers who want
more control over *where* those log records end up. May be a file for bug
reports, `stderr`/`stdout` explicitly, or a fully custom destination,
without having to hand-roll `logging.Handler` boilerplate themselves.

```python
from slb_glossary.logging import FileSink, configure_logging

# Route every slb_glossary log record to a file for this run.
configure_logging(sinks=FileSink("slb-glossary.log"), level="DEBUG")
```

The CLI exposes this via `--log-to`/`--log-sink` (see
`slb_glossary.cli.session_options`), and `slb_glossary.browser.open_session`
accepts a `log_sink` argument so library users get the same control over a
single `BrowserSession` without reaching into `logging` themselves.
"""

import contextlib
import importlib
import logging
import pathlib
import sys
import typing

__all__ = [
    "LogSink",
    "ConsoleSink",
    "StdoutSink",
    "StderrSink",
    "FileSink",
    "SinkHandler",
    "DEFAULT_LOG_FORMAT",
    "import_sink",
    "resolve_sink",
    "configure_logging",
]


DEFAULT_LOG_FORMAT = "%(asctime)s - [%(name)s] - %(levelname)s - %(message)s"
"""Format string used for every sink, matching `slb_glossary`'s `logging.basicConfig` default."""


@typing.runtime_checkable
class LogSink(typing.Protocol):
    """
    Protocol for a destination formatted log lines can be written to.

    Implement this (no base class required, just the three methods) to
    route `slb_glossary`'s logging anywhere: a file, a socket, a queue for
    an in-app log viewer, a bug-report buffer, etc. Pass an instance (or
    the class itself, for a no-argument constructor) to `configure_logging`,
    `resolve_sink`, `--log-to`/`--log-sink`, or `open_session(log_sink=...)`.
    """

    def write(self, message: str) -> None:
        """Write one already-formatted log line to the sink."""
        ...

    def flush(self) -> None:
        """Flush any buffered output. May be a no-op."""
        ...

    def close(self) -> None:
        """Release any resources held by the sink. May be a no-op."""
        ...


class ConsoleSink:
    """A `LogSink` that writes to a given text stream (`sys.stderr` by default)."""

    def __init__(self, stream: typing.TextIO | None = None) -> None:
        self._stream = stream if stream is not None else sys.stderr

    def write(self, message: str) -> None:
        self._stream.write(message + "\n")

    def flush(self) -> None:
        with contextlib.suppress(Exception):
            self._stream.flush()

    def close(self) -> None:
        # Never close a std stream out from under the rest of the process.
        pass

    def __repr__(self) -> str:
        name = getattr(self._stream, "name", self._stream)
        return f"{type(self).__name__}({name!r})"


class StderrSink(ConsoleSink):
    """A `LogSink` that writes to `sys.stderr`. The default when no sink is configured."""

    def __init__(self) -> None:
        super().__init__(sys.stderr)


class StdoutSink(ConsoleSink):
    """A `LogSink` that writes to `sys.stdout`."""

    def __init__(self) -> None:
        super().__init__(sys.stdout)


class FileSink:
    """A `LogSink` that appends formatted log lines to a file, opened lazily on first write."""

    def __init__(
        self, path: str | pathlib.Path, *, mode: str = "a", encoding: str = "utf-8"
    ) -> None:
        """
        :param path: File to write log lines to. Its parent directory is
            created on first write if it doesn't exist.
        :param mode: File open mode. `"a"` (the default) appends across
            runs, so a single `--log-to` file can double as a running log
            for bug reports; pass `"w"` to truncate on each run instead.
        :param encoding: Text encoding to open the file with.
        """
        self.path = pathlib.Path(path)
        self._mode = mode
        self._encoding = encoding
        self._file: typing.IO | None = None

    def _ensure_open(self) -> typing.IO:
        if self._file is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._file = open(self.path, self._mode, encoding=self._encoding)
        return self._file

    def write(self, message: str) -> None:
        self._ensure_open().write(message + "\n")

    def flush(self) -> None:
        if self._file is not None:
            with contextlib.suppress(Exception):
                self._file.flush()

    def close(self) -> None:
        if self._file is not None:
            with contextlib.suppress(Exception):
                self._file.close()
            self._file = None

    def __repr__(self) -> str:
        return f"{type(self).__name__}({str(self.path)!r})"


class SinkHandler(logging.Handler):
    """A `logging.Handler` that formats records and forwards them to one or more `LogSink`s."""

    def __init__(self, sinks: typing.Iterable[LogSink], *, level: int = logging.NOTSET) -> None:
        super().__init__(level=level)
        self.sinks: list[LogSink] = list(sinks)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
        except Exception:
            self.handleError(record)
            return
        for sink in self.sinks:
            try:
                sink.write(message)
            except Exception:
                self.handleError(record)

    def flush(self) -> None:
        for sink in self.sinks:
            with contextlib.suppress(Exception):
                sink.flush()

    def close(self) -> None:
        for sink in self.sinks:
            with contextlib.suppress(Exception):
                sink.close()
        super().close()


def import_sink(dotted_path: str) -> typing.Any:
    """
    Import a `LogSink` class or instance given its `"module:attr"`/`"package.module.attr"` path.

    :param dotted_path: Either `"module:attr"` (splitting on the last
        `":"`) or `"package.module.attr"` (splitting on the last `"."`).
    :return: Whatever `attr` resolves to. Typically a `LogSink` subclass
        or an already-constructed `LogSink` instance.
    :raises ValueError: If `dotted_path` doesn't look like a valid import path.
    :raises ImportError: If the module can't be imported, or has no such attribute.
    """
    module_path, _, attr = dotted_path.partition(":")
    if not attr:
        module_path, _, attr = dotted_path.rpartition(".")
    if not module_path or not attr:
        raise ValueError(
            f"{dotted_path!r} is not a valid sink import path. Use 'module:ClassName' "
            f"or 'package.module.ClassName'."
        )
    module = importlib.import_module(module_path)
    try:
        return getattr(module, attr)
    except AttributeError as exc:
        raise ImportError(f"Module {module_path!r} has no attribute {attr!r}") from exc


def _looks_like_import_path(text: str) -> bool:
    """Heuristic: `"module:Class"` or a dotted path with no filesystem-style suffix."""
    if ":" in text:
        return True
    return "." in text and not pathlib.Path(text).suffix


def resolve_sink(
    spec: LogSink | type[LogSink] | str | pathlib.Path | None,
    *,
    default: LogSink | None = None,
) -> LogSink:
    """
    Resolve `--log-to`/`--log-sink`-style input (or a library-level equivalent) into a `LogSink`.

    :param spec: Any of:
        - `None`: returns `default`, or a `StderrSink()` if `default` is also `None`.
        - An already-constructed `LogSink`: returned as-is.
        - A `LogSink` subclass: instantiated with no arguments.
        - `"stderr"`/`"console"` or `"stdout"` (case-insensitive): the matching built-in sink.
        - A dotted import path (`"module:ClassName"` or
          `"package.module.ClassName"`): imported via `import_sink`, and
          instantiated with no arguments if it's a class rather than an
          already-built instance.
        - Anything else (a `str`/`pathlib.Path`): treated as a file path
          and wrapped in a `FileSink`.
    :param default: Fallback sink used when `spec` is `None`.
    :return: A ready-to-use `LogSink`.
    :raises ImportError: If `spec` looks like an import path but the
        module/attribute couldn't be found.
    """
    if spec is None:
        return default if default is not None else StderrSink()
    if isinstance(spec, LogSink):
        return spec
    if isinstance(spec, type):
        return spec()  # type: ignore[call-arg]
    if isinstance(spec, pathlib.Path):
        return FileSink(spec)

    text = str(spec).strip()
    lowered = text.lower()
    if lowered in ("stderr", "console"):
        return StderrSink()
    if lowered == "stdout":
        return StdoutSink()

    if _looks_like_import_path(text):
        target = import_sink(text)
        return target() if isinstance(target, type) else target

    return FileSink(text)


def configure_logging(
    *,
    sinks: typing.Iterable[LogSink] | LogSink | None = None,
    level: int | str | None = None,
    logger_name: str = "slb_glossary",
    fmt: str = DEFAULT_LOG_FORMAT,
    propagate: bool = False,
) -> SinkHandler:
    """
    Route every `logger_name` (and descendant) log record to `sinks`.

    Intended for the CLI (`--log-to`/`--log-sink`) and for library callers
    who want `slb_glossary`'s entire logging output funneled to one place -
    a file for bug reports, an in-memory sink for a test harness, several
    sinks at once, etc. Calling this again (e.g. because `--log-to`
    changed mid-process) cleanly tears down the handler it previously set
    up before attaching the new one, so repeat calls don't pile up duplicate handlers.

    :param sinks: One `LogSink`, several, or `None` for a single `StderrSink()`.
    :param level: Logging level (name or numeric) to set on `logger_name`'s
        logger. `None` leaves the logger's current level untouched, so this
        can be called purely to redirect output without also changing verbosity.
    :param logger_name: Name of the logger to attach the handler to.
        Defaults to `"slb_glossary"`, the package's root logger, so every
        module's `logging.getLogger(__name__)` call propagates up to it.
    :param fmt: `logging.Formatter` format string used for every sink.
    :param propagate: Whether `logger_name`'s logger should still propagate
        records to its own ancestor loggers (e.g. the root logger) after
        also sending them to `sinks`. Defaults to `False` to avoid
        duplicate output alongside the root handler `logging.basicConfig`
        sets up in `slb_glossary.__init__`.
    :return: The `SinkHandler` now attached to `logger_name`'s logger.
    """
    if sinks is None:
        resolved_sinks: list[LogSink] = [StderrSink()]
    elif isinstance(sinks, LogSink):
        resolved_sinks = [sinks]
    else:
        resolved_sinks = list(sinks)

    logger = logging.getLogger(logger_name)
    if level is not None:
        logger.setLevel(level.upper() if isinstance(level, str) else level)
    logger.propagate = propagate

    for existing in list(logger.handlers):
        if isinstance(existing, SinkHandler):
            logger.removeHandler(existing)
            existing.close()

    handler = SinkHandler(resolved_sinks, level=logger.level)
    handler.setFormatter(logging.Formatter(fmt))
    logger.addHandler(handler)
    logger.debug(
        "Routed %r logging to: %s", logger_name, ", ".join(repr(sink) for sink in resolved_sinks)
    )
    return handler
