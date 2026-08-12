"""Grammatical label lookups for glossary term definitions."""

import typing

from .models import Language


__all__ = ["resolve_grammatical_label"]


_GRAMMATICAL_LABELS: typing.Dict[Language, typing.Dict[str, str]] = {
    Language.ENGLISH: {
        "n.": "Noun",
        "pron.": "Pronoun",
        "vb.": "Verb",
        "adj.": "Adjective",
        "adv.": "Adverb",
        "prep.": "Preposition",
        "conj.": "Conjunction",
        "interj.": "Interjection",
        "art.": "Article",
        "det.": "Determiner",
        "num.": "Numeral",
        "aux.": "Auxiliary Verb",
        "modal": "Modal Verb",
        "participle": "Participle",
        "gerund": "Gerund",
    },
    Language.SPANISH: {
        "s.": "Sustantivo",
        "pron.": "Pronombre",
        "v.": "Verbo",
        "adj.": "Adjetivo",
        "adv.": "Adverbio",
        "prep.": "Preposición",
        "conj.": "Conjunción",
        "interj.": "Interjección",
        "art.": "Artículo",
        "det.": "Determinante",
        "num.": "Número",
        "aux.": "Verbo Auxiliar",
        "modal": "Verbo Modal",
        "participio": "Participio",
        "gerundio": "Gerundio",
    },
}
"""Abbreviation-to-full-label mappings, keyed by glossary language."""


def resolve_grammatical_label(language: Language, abbreviation: str) -> str:
    """
    Return the non-abbreviated grammatical label for `abbreviation`.

    :param language: The glossary language `abbreviation` was found in.
    :param abbreviation: The abbreviated grammatical label as it appears on
        the glossary page, e.g. `"n."`.
    :return: The full label, e.g. `"Noun"`. Returns `abbreviation` unchanged
        if there is no known mapping for it.
    """
    return _GRAMMATICAL_LABELS[language].get(abbreviation.lower(), abbreviation)
