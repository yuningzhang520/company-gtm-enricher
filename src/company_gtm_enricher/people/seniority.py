"""Exact lexical seniority equivalents; no ordering or minimum-rank policy."""
from __future__ import annotations

from collections.abc import Sequence
from importlib.resources import files
import json
import re


def _key(value: str) -> str:
    return " ".join(value.split()).casefold()


def _configuration() -> dict:
    return json.loads(files("company_gtm_enricher.people").joinpath("seniority_aliases.json").read_text(encoding="utf-8"))


def load_seniority_aliases() -> dict[str, list[str]]:
    """Return fresh editable spelling groups for the classifier's mapping context."""
    return _configuration()["aliases"]


def _alias_index(aliases: dict[str, list[str]]) -> dict[str, str]:
    index = {}
    for canonical, spellings in aliases.items():
        for spelling in (canonical, *spellings):
            key = _key(spelling)
            if key in index and index[key] != canonical:
                raise ValueError("A seniority spelling belongs to multiple canonical labels.")
            index[key] = canonical
    return index


def _canonical(value: str, index: dict[str, str]) -> str:
    return index.get(_key(value), value.strip())


def normalize_seniority(value: str, selected: Sequence[str] = ()) -> str:
    """Preserve an equivalent selected spelling; otherwise canonicalize known aliases.

    An exact selected spelling wins over an equivalent abbreviation. If several
    equivalent selections remain, the first wins. Unknown custom labels are only
    trimmed, never expanded into or collapsed onto another rank.
    """
    if not value.strip():
        return ""
    index = _alias_index(load_seniority_aliases())
    for label in selected:
        if label.strip() and _key(label) == _key(value):
            return label.strip()
    canonical = _canonical(value, index)
    for label in selected:
        if label.strip() and _key(_canonical(label, index)) == _key(canonical):
            return label.strip()
    return canonical


def _parts(value: str, index: dict[str, str], config: dict) -> tuple[tuple[str, ...], str]:
    """Expose explicit lexical modifiers, without declaring one level above another."""
    canonical = _canonical(value, index)
    expanded = config["expansions"].get(canonical, canonical)
    words = expanded.split()
    modifiers = {_key(word) for word in config["modifiers"]}
    prefix = []
    while len(words) > 1 and _key(_canonical(words[0], index)) in modifiers:
        prefix.append(_key(_canonical(words.pop(0), index)))
    return tuple(prefix), _key(_canonical(" ".join(words), index))


def seniority_conflict(title: str, level: str) -> str:
    """Explain a clear modifier conflict in the copied title, or return empty.

    This checks spellings sharing the same base level, such as VP versus SVP or
    Director versus Senior Director. It does not infer a level from a vague title,
    compare rank order, inspect other evidence, or guess which of multiple levels
    in a composite copied title the model meant.
    """
    if not title.strip() or not level.strip():
        return ""
    config = _configuration()
    index = _alias_index(config["aliases"])
    expected_modifiers, expected_base = _parts(level, index, config)
    spellings = {level.strip(), expected_base}
    for canonical, aliases in config["aliases"].items():
        if _parts(canonical, index, config)[1] == expected_base:
            spellings.update((canonical, *aliases))
    modifier_spellings = set(config["modifiers"])
    for modifier in config["modifiers"]:
        modifier_spellings.update(config["aliases"].get(modifier, ()))
    alternatives = "|".join(re.escape(value) for value in sorted(spellings, key=len, reverse=True))
    modifiers = "|".join(re.escape(value) for value in sorted(modifier_spellings, key=len, reverse=True))
    pattern = re.compile(
        r"(?<!\w)(?:(?:" + modifiers + r")\s+)*(?:" + alternatives + r")(?!\w)",
        re.IGNORECASE,
    )
    for match in pattern.finditer(" ".join(title.split())):
        observed_modifiers, observed_base = _parts(match.group(0), index, config)
        if observed_base == expected_base and observed_modifiers != expected_modifiers:
            return (
                f"Mapped seniority '{level.strip()}' conflicts with the explicit level "
                f"'{match.group(0)}' in the copied title; review the level."
            )
    return ""
