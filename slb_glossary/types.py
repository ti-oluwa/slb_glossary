"""Core data types and structures."""

import enum
import typing
from collections.abc import AsyncIterable, Iterable, Sequence

__all__ = ["RecordLike", "materialize_records", "Language", "RelatedTerm", "SearchResult"]


@typing.runtime_checkable
class RecordLike(typing.Protocol):
    """Interface for a record like datastructure."""

    @property
    def fields(self) -> Sequence[str]:
        """Return a list of the field names in this record."""
        ...

    def asdict(self) -> dict[str, typing.Any]:
        """Return a dict mapping each field name to its value in this record."""
        ...


RecordT = typing.TypeVar("RecordT", bound=RecordLike)


async def materialize_records(
    records: Iterable[RecordT] | AsyncIterable[RecordT],
) -> list[RecordT]:
    """
    Collect `records` into a list, consuming it if it is a lazy iterable.

    :param records: A sync iterable, or an async iterable such as the
        generators `slb_glossary.search` yields results from.
    :return: `records` as a plain list.
    """
    if isinstance(records, AsyncIterable):
        return [record async for record in records]
    return list(records)


class Language(enum.Enum):
    """A language edition of the SLB glossary."""

    ENGLISH = "en"
    SPANISH = "es"


class RelatedTerm(typing.NamedTuple):
    """A single term linked from within another term's definition."""

    term: str
    """Display text of the link - usually the related term's name."""

    url: str
    """Glossary URL the link points to."""


class SearchResult(typing.NamedTuple):
    """A single term definition extracted from the glossary."""

    term: str
    """The glossary term this result defines."""

    definition: str | None
    """Full text of the definition, or `None` if it could not be parsed."""

    grammatical_label: str | None
    """Part of speech of the term (e.g. "Noun"), or `None` if unavailable."""

    topic: str | None
    """Topic/discipline this definition is filed under in the glossary."""

    url: str | None
    """URL of the glossary page the definition was extracted from."""

    image: str | None = None
    """URL of the term's illustrative image, or `None` if the page has none."""

    image_caption: str | None = None
    """Caption text accompanying `image`, or `None` if the page has none."""

    related: tuple[RelatedTerm, ...] | None = None
    """Terms linked from this definition's "See related terms" list, or
    `None` if the page has none."""

    language: str = "en"
    """Glossary language edition (`Language.value`, e.g. `"en"`/`"es"`) this result was found in."""

    @property
    def fields(self) -> list[str]:
        """Return a list of the field names in this result."""
        return list(self._fields)

    def asdict(self) -> dict[str, typing.Any]:
        """Return a dictionary representation of this result."""
        return self._asdict()
