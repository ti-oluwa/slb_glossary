"""Built-in writers for `slb_glossary.store.save`."""

import asyncio
import csv
import json
import pathlib
import typing
from collections.abc import Sequence

from slb_glossary.store.records import RecordLike

__all__ = [
    "WRITERS",
    "Writer",
    "field_names",
    "humanize_field",
    "records_to_dicts",
    "write_csv",
    "write_json",
    "write_jsonl",
    "write_txt",
    "write_xlsx",
]


Writer = typing.Callable[[Sequence[RecordLike], pathlib.Path], typing.Awaitable[None]]
"""
An async callable that writes a list of records to a destination path.

Register one with `@slb_glossary.store.writer(format)` decorator to teach `store.save`
a new file format:

```python
@slb_glossary.store.writer("yaml")
async def write_yaml(records: Sequence[RecordLike], destination: pathlib.Path) -> None:
    import yaml

    with open(destination, "w") as file:
        yaml.dump(records_to_dicts(records), file)

```

A writer only needs to write the file; it does not need to create
`destination`'s parent directory (`store.save` does that first) or catch
I/O errors (`store.save` wraps those in `WriterError` with format/path
context already attached).
"""


def field_names(records: Sequence[RecordLike]) -> list[str]:
    """Return the field names of `records`, or `[]` if `records` is empty."""
    return list(records[0].fields) if records else []


ACRONYMS = frozenset({"url", "id"})
"""Field-name words rendered upper-case rather than title-cased by `humanize_field`."""


def humanize_field(field: str) -> str:
    """Turn a `snake_case` field name into a `Title Case` header."""
    words = field.split("_")
    return " ".join(word.upper() if word in ACRONYMS else word.title() for word in words)


def make_json_safe(value: typing.Any) -> typing.Any:
    """
    Recursively convert `value` into something `json.dump` can serialize.

    Handles the shapes `slb_glossary` records actually nest: `NamedTuple`
    values (e.g. `RelatedTerm`), and plain lists/tuples/dicts of those.
    Anything else is returned unchanged and left to `json.dump` itself.

    :param value: A field value from `record.asdict()`.
    :return: A JSON-serializable equivalent of `value`.
    """
    if hasattr(value, "_asdict"):
        return {key: make_json_safe(item) for key, item in value._asdict().items()}
    if isinstance(value, (list, tuple)):
        return [make_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: make_json_safe(item) for key, item in value.items()}
    return value


def render_display_text(value: typing.Any) -> str:
    """
    Render a field value as flat, human-readable text for a CSV/TXT/XLSX cell.

    `None` becomes `""`. A nested `NamedTuple` (e.g. a single `RelatedTerm`)
    renders as its most identifying field. A list/tuple of values (e.g.
    `SearchResult.related`) renders as a `"; "`-joined list of each item's
    display text.

    :param value: A field value from `record.asdict()`.
    :return: Flat text suitable for a single spreadsheet/CSV cell.
    """
    if value is None:
        return ""
    if hasattr(value, "asdict"):
        record_dict = value.asdict()
        fallback = next(iter(record_dict.values()), "")
        return str(record_dict.get("term") or record_dict.get("name") or fallback)
    if isinstance(value, (list, tuple)):
        return "; ".join(render_display_text(item) for item in value)
    return str(value)


def records_to_dicts(
    records: Sequence[RecordLike], exclude: Sequence[str] = ()
) -> list[dict[str, typing.Any]]:
    """
    Convert `records` into a list of plain, JSON-safe `dict`s, one per record.

    Field order is preserved from each record's `asdict()`, and nested
    values (e.g. a `SearchResult.related` list of `RelatedTerm`) are
    recursively converted rather than flattened to text, unlike
    `write_json`, which additionally re-keys the list by each record's
    first field for on-disk storage, this stays a flat list, which is
    usually what you want for `json.dumps`, piping to `jq`, or embedding
    in a larger JSON payload. It's what powers the CLI's `--json` output.

    :param records: The records to convert.
    :param exclude: Field names to omit from each record's dict.
    :return: One JSON-safe `dict` per record, in the same order as `records`.
    """
    excluded = frozenset(exclude)
    return [
        {
            key: make_json_safe(value)
            for key, value in record.asdict().items()
            if key not in excluded
        }
        for record in records
    ]


async def write_csv(records: Sequence[RecordLike], destination: pathlib.Path) -> None:
    """Write `records` to `destination` as CSV, with a humanized header row."""

    def _write() -> None:
        fields = field_names(records)
        with open(destination, "w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow([humanize_field(field) for field in fields])
            for record in records:
                writer.writerow([render_display_text(value) for value in record.asdict().values()])

    await asyncio.to_thread(_write)


async def write_json(records: Sequence[RecordLike], destination: pathlib.Path) -> None:
    """
    Write `records` to `destination` as JSON, keyed by each record's first field.

    Records whose first field repeats overwrite earlier entries with the
    same key. Nested values (e.g. a `SearchResult.related` list of
    `RelatedTerm`) are preserved as native JSON arrays/objects rather than
    flattened to text.
    """

    def _write() -> None:
        data: dict[typing.Any, dict[str, typing.Any]] = {}
        for record, record_dict in zip(records, records_to_dicts(records), strict=True):
            record_dict = dict(record_dict)
            key_field = record.fields[0]
            key = record_dict.pop(key_field)
            data[key] = record_dict
        with open(destination, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=2, ensure_ascii=False)

    await asyncio.to_thread(_write)


async def write_jsonl(records: Sequence[RecordLike], destination: pathlib.Path) -> None:
    """
    Write `records` to `destination` as newline-delimited JSON (one object per line).

    Unlike `write_json`, records keep their original field order and are
    not re-keyed or deduplicated by their first field - useful for
    streaming/appending workflows, or piping straight into tools like `jq`.
    """

    def _write() -> None:
        with open(destination, "w", encoding="utf-8") as file:
            for record_dict in records_to_dicts(records):
                file.write(json.dumps(record_dict, ensure_ascii=False))
                file.write("\n")

    await asyncio.to_thread(_write)


async def write_txt(records: Sequence[RecordLike], destination: pathlib.Path) -> None:
    """Write `records` to `destination` as a numbered, human-readable list."""

    def _write() -> None:
        lines: list[str] = []
        for index, record in enumerate(records, start=1):
            record_dict = record.asdict()
            fields = record.fields
            title_field, *restfields = fields
            lines.append(f"({index}) {record_dict[title_field]}")
            for field in restfields:
                lines.append(
                    f"    {humanize_field(field)}: {render_display_text(record_dict[field])}"
                )
            lines.append("")
        with open(destination, "w", encoding="utf-8") as file:
            file.write("\n".join(lines))

    await asyncio.to_thread(_write)


async def write_xlsx(records: Sequence[RecordLike], destination: pathlib.Path) -> None:
    """
    Write `records` to `destination` as an Excel workbook.

    :raises ImportError: If `openpyxl` is not installed. Install it with
        `uv add openpyxl` or `pip install openpyxl`.
    """
    try:
        import openpyxl  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            '"openpyxl" is required to save .xlsx files. '
            "Install it with `uv add openpyxl` or `pip install openpyxl`."
        ) from exc

    def _write() -> None:
        fields = field_names(records)
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        if sheet is None:
            raise RuntimeError("openpyxl failed to create a workbook sheet")

        sheet.append([humanize_field(field) for field in fields])
        for record in records:
            sheet.append([render_display_text(value) for value in record.asdict().values()])
        workbook.save(destination)

    await asyncio.to_thread(_write)


WRITERS: dict[str, Writer] = {
    "csv": write_csv,
    "json": write_json,
    "jsonl": write_jsonl,
    "ndjson": write_jsonl,
    "txt": write_txt,
    "xlsx": write_xlsx,
}
"""Registry of file format to writer, mutated by `@slb_glossary.store.writer(format)`."""
