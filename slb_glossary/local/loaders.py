"""Import user-provided CSV/JSON/XLSX data into the local database (and, optionally, its vector store)."""

import csv
import json
import pathlib
import typing

from slb_glossary.errors import DatabaseError
from slb_glossary.local.api import upsert_results
from slb_glossary.local.models import Database
from slb_glossary.local.vectors import upsert_vector
from slb_glossary.models import SearchResult

__all__ = ["load_file"]


def read_csv_rows(path: pathlib.Path) -> list[dict[str, typing.Any]]:
    """Read `path` as CSV into a list of `{column: value}` rows."""
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def read_json_rows(path: pathlib.Path) -> list[dict[str, typing.Any]]:
    """Read `path` as a JSON array of records (or an object containing one)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        for value in data.values():
            if isinstance(value, list):
                data = value
                break

    if not isinstance(data, list):
        raise DatabaseError(
            f"{path}: expected a JSON array of records (or an object containing one)."
        )
    return data


def read_xlsx_rows(path: pathlib.Path) -> list[dict[str, typing.Any]]:
    """Read `path`'s first worksheet into a list of `{header: value}` rows."""
    try:
        import openpyxl  # noqa: F401
    except ImportError as exc:
        raise DatabaseError(
            "Reading a .xlsx file requires the 'openpyxl' package. "
            "Install it with `pip install slb-glossary[xlsx]`."
        ) from exc

    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook.active
        rows_iter = sheet.iter_rows(values_only=True)  # type: ignore[union-attr]
        try:
            header = [str(cell) if cell is not None else "" for cell in next(rows_iter)]
        except StopIteration:
            return []
        return [
            {header[i]: value for i, value in enumerate(row) if i < len(header)}
            for row in rows_iter
        ]
    finally:
        workbook.close()


READERS: dict[str, typing.Callable[[pathlib.Path], list[dict[str, typing.Any]]]] = {
    "csv": read_csv_rows,
    "json": read_json_rows,
    "xlsx": read_xlsx_rows,
    "xlsm": read_xlsx_rows,
}


def _get_field(row: typing.Mapping[str, typing.Any], name: str | None) -> typing.Any:
    """Return `row[name]` matched case-insensitively, or `None` if absent/empty/unset."""
    if not name:
        return None
    for key, value in row.items():
        if str(key).strip().lower() == name.lower() and value not in (None, ""):
            return value
    return None


def _record_to_result(
    row: typing.Mapping[str, typing.Any],
    *,
    term_field: str,
    definition_field: str | None,
    topic_field: str | None,
    url_field: str | None,
    grammatical_label_field: str | None,
) -> SearchResult | None:
    """Build a `SearchResult` from one imported row, or `None` if it has no term."""
    term = _get_field(row, term_field)
    if not term:
        return None

    url = _get_field(row, url_field)
    if not url:
        # url is the local database's primary key; synthesize a stable one
        # from the term itself so rows without a URL column still
        # round-trip through upsert_results/get_term. Such rows just can't
        # be matched against a live glossary URL later.
        slug = "-".join(str(term).strip().lower().split())
        url = f"local://imported/{slug}"

    definition = _get_field(row, definition_field)
    grammatical_label = _get_field(row, grammatical_label_field)
    topic = _get_field(row, topic_field)

    return SearchResult(
        term=str(term),
        definition=str(definition) if definition is not None else None,
        grammatical_label=str(grammatical_label) if grammatical_label is not None else None,
        topic=str(topic) if topic is not None else None,
        url=str(url),
    )


def _parse_embedding(raw: typing.Any) -> list[float] | None:
    """Parse an embedding cell/value into a list of floats, or `None` if empty/unparsable."""
    if raw is None or raw == "":
        return None
    if isinstance(raw, list):
        try:
            return [float(x) for x in raw]
        except (TypeError, ValueError):
            return None

    text = str(raw).strip()
    if not text:
        return None
    if text.startswith("["):
        try:
            return [float(x) for x in json.loads(text)]
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

    for delimiter in (",", ";"):
        if delimiter in text:
            parts = text.split(delimiter)
            break
    else:
        parts = text.split()
    try:
        return [float(part.strip()) for part in parts if part.strip()]
    except ValueError:
        return None


async def load_file(
    db: Database,
    path: str | pathlib.Path,
    *,
    format: str | None = None,
    term_field: str = "term",
    definition_field: str | None = "definition",
    topic_field: str | None = "topic",
    url_field: str | None = "url",
    grammatical_label_field: str | None = "grammatical_label",
    embedding_field: str | None = None,
    embedding_model: str = "custom",
    source: str = "user",
) -> int:
    """
    Import term data from a CSV, JSON, or XLSX file into the local database.

    Each row/record needs at least `term_field`; every other field is
    optional and can be set to `None` to skip it entirely.

    :param db: The local database to write to.
    :param path: Path to the source file.
    :param format: One of `"csv"`, `"json"`, `"xlsx"`. Inferred from
        `path`'s extension if not given.
    :param term_field: Column/key holding each row's term name.
    :param definition_field: Column/key holding each row's definition
        text, or `None` to leave every imported row's definition unset.
    :param topic_field: Column/key holding each row's topic, or `None` to
        leave every imported row's topic unset.
    :param url_field: Column/key holding each row's source URL, or `None`
        to always synthesize a `local://imported/<slugified-term>` URL -
        needed since `url` is the local database's primary key.
    :param grammatical_label_field: Column/key holding each row's
        grammatical label (e.g. "Noun"), or `None` to leave it unset.
    :param embedding_field: Column/key holding a precomputed embedding
        vector for each row - either a JSON array, or a delimiter-separated
        (comma, semicolon, or whitespace) string of numbers. If given, a
        vector is stored for every row that has one (see
        `slb_glossary.local.vectors.upsert_vector`).
    :param embedding_model: Model label to store `embedding_field` vectors
        under. Only meaningful when `embedding_field` is given.
    :param source: Provenance tag stored on every imported row (see
        `slb_glossary.local.api.upsert_results`). Defaults to `"user"`
        so imported data can be told apart from live `"glossary"` rows.
    :return: Number of rows imported.
    :raises DatabaseError: If `format` (or `path`'s extension) is
        unsupported, `path` isn't a well-formed file of that format, or
        `.xlsx` support isn't installed.
    """
    resolved_path = pathlib.Path(path)
    resolved_format = (format or resolved_path.suffix.lstrip(".")).lower()
    reader = READERS.get(resolved_format)
    if reader is None:
        raise DatabaseError(
            f"Unsupported import format {resolved_format!r} for {resolved_path!s}. "
            f"Supported formats: {', '.join(sorted(set(READERS)))}."
        )

    try:
        rows = reader(resolved_path)
    except DatabaseError:
        raise
    except Exception as exc:
        raise DatabaseError(
            f"Could not read {resolved_path!s} as {resolved_format}: {exc}"
        ) from exc

    results: list[SearchResult] = []
    embeddings: dict[str, list[float]] = {}
    for row in rows:
        result = _record_to_result(
            row,
            term_field=term_field,
            definition_field=definition_field,
            topic_field=topic_field,
            url_field=url_field,
            grammatical_label_field=grammatical_label_field,
        )
        if result is None or not result.url:
            continue
        results.append(result)

        if embedding_field:
            parsed_embedding = _parse_embedding(_get_field(row, embedding_field))
            if parsed_embedding:
                embeddings[result.url] = parsed_embedding

    written = await upsert_results(db, results, source=source)
    for url, embedding in embeddings.items():
        await upsert_vector(db, url, embedding, model=embedding_model)
    return written
