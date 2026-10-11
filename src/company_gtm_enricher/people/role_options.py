"""Editable role presets and department guidance, shared by UI and CLI."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from importlib.resources import files
import json


def normalize_department_definitions(definitions: object) -> dict[str, str]:
    """Validate a text mapping and canonicalize keys; blank text clears guidance."""
    if not isinstance(definitions, Mapping):
        raise ValueError("Department definitions must be a JSON object mapping labels to text.")
    normalized = {}
    for label, definition in definitions.items():
        if not isinstance(label, str) or not label.strip() or not isinstance(definition, str):
            raise ValueError("Department definitions require nonblank text labels and text values.")
        key = label.strip().casefold()
        if key in normalized:
            raise ValueError("Department definitions contain duplicate labels after normalization.")
        normalized[key] = definition.strip()
    return normalized


def load_role_options() -> dict:
    return json.loads(files("company_gtm_enricher.people").joinpath("role_options.json").read_text(encoding="utf-8"))


def department_definitions_for(
    departments: Sequence[str], overrides: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Resolve presets for selected labels; overrides can also clear a preset."""
    definitions = normalize_department_definitions(load_role_options().get("department_definitions", {}))
    if overrides is not None:
        definitions.update(normalize_department_definitions(overrides))
    selected = {}
    for label in departments:
        if not isinstance(label, str) or not label.strip():
            raise ValueError("Selected department labels must be nonblank text.")
        selected.setdefault(label.strip().casefold(), label.strip())
    return {label: definitions[key] for key, label in selected.items() if definitions.get(key)}
