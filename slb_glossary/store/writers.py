"""Built-in writers for `slb_glossary.store.save`."""

import asyncio
import csv
import json
import pathlib
import typing

from .records import RecordLike

__all__ = ["Writer", "WRITERS", "write_csv", "write_json", "write_txt", "write_xlsx"]


Writer = typing.Callable[[list[RecordLike], pathlib.Path], typing.Awaitable[None]]
"""An async callable that writes a list of records to a destination path."""


def field_names(records: list[RecordLike]) -> list[str]:
    """Return the field names of `records`, or `[]` if `records` is empty."""
    return list(records[0]._fields) if records else []


ACRONYMS = frozenset({"url", "id"})
"""Field-name words rendered upper-case rather than title-cased by `humanize_field`."""


def humanize_field(field: str) -> str:
    """Turn a `snake_case` field name into a `Title Case` header."""
    words = field.split("_")
    return " ".join(word.upper() if word in ACRONYMS else word.title() for word in words)


async def write_csv(records: list[RecordLike], destination: pathlib.Path) -> None:
    """Write `records` to `destination` as CSV, with a humanized header row."""

    def _write() -> None:
        fields = field_names(records)
        with open(destination, "w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow([humanize_field(field) for field in fields])
            for record in records:
                writer.writerow(record._asdict().values())

    await asyncio.to_thread(_write)


async def write_json(records: list[RecordLike], destination: pathlib.Path) -> None:
    """
    Write `records` to `destination` as JSON, keyed by each record's first field.

    Records whose first field repeats overwrite earlier entries with the
    same key.
    """

    def _write() -> None:
        data: dict[typing.Any, dict[str, typing.Any]] = {}
        for record in records:
            as_dict = record._asdict()
            key_field = record._fields[0]
            key = as_dict.pop(key_field)
            data[key] = as_dict
        with open(destination, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=2, ensure_ascii=False)

    await asyncio.to_thread(_write)


async def write_txt(records: list[RecordLike], destination: pathlib.Path) -> None:
    """Write `records` to `destination` as a numbered, human-readable list."""

    def _write() -> None:
        lines: list[str] = []
        for index, record in enumerate(records, start=1):
            as_dict = record._asdict()
            fields = record._fields
            title_field, *rest_fields = fields
            lines.append(f"({index}) {as_dict[title_field]}")
            for field in rest_fields:
                value = as_dict[field]
                lines.append(f"    {humanize_field(field)}: {value if value is not None else ''}")
            lines.append("")
        with open(destination, "w", encoding="utf-8") as file:
            file.write("\n".join(lines))

    await asyncio.to_thread(_write)


async def write_xlsx(records: list[RecordLike], destination: pathlib.Path) -> None:
    """
    Write `records` to `destination` as an Excel workbook.

    :raises ImportError: If `openpyxl` is not installed. Install it with
        `uv add openpyxl` or `pip install openpyxl`.
    """

    def _write() -> None:
        try:
            import openpyxl
        except ImportError as exc:
            raise ImportError(
                '"openpyxl" is required to save .xlsx files. '
                "Install it with `uv add openpyxl` or `pip install openpyxl`."
            ) from exc

        fields = field_names(records)
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.append([humanize_field(field) for field in fields])
        for record in records:
            sheet.append(list(record._asdict().values()))
        workbook.save(destination)

    await asyncio.to_thread(_write)


WRITERS: dict[str, Writer] = {
    "csv": write_csv,
    "json": write_json,
    "txt": write_txt,
    "xlsx": write_xlsx,
}
"""Registry of file format to writer, mutated by `slb_glossary.store.register_writer`."""
