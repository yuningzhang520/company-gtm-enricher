from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from .role_options import normalize_department_definitions


@dataclass(frozen=True)
class CompanyTarget:
    name: str
    domain: str = ""
    lists: str = ""
    aliases: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.aliases, str):
            raise ValueError("Company aliases must be a sequence of names, not a single string.")
        unique = {}
        for alias in self.aliases:
            if not isinstance(alias, str):
                raise ValueError("Company aliases must contain only names as strings.")
            alias = " ".join(alias.split())
            if alias:
                unique.setdefault(alias.casefold(), alias)
        object.__setattr__(self, "aliases", tuple(unique.values()))


@dataclass(frozen=True)
class PeopleCriteria:
    founders: bool = True
    c_level: bool = True
    departments: tuple[str, ...] = ()
    leadership_levels: tuple[str, ...] = ()
    ic_levels: tuple[str, ...] = ()
    department_definitions: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in ("departments", "leadership_levels", "ic_levels"):
            values = {}
            for value in getattr(self, field_name):
                if value.strip():
                    values.setdefault(value.strip().casefold(), value.strip())
            object.__setattr__(self, field_name, tuple(values.values()))
        definitions = normalize_department_definitions(self.department_definitions)
        selected = {value.casefold(): value for value in self.departments}
        if definitions.keys() - selected.keys():
            raise ValueError("Department definitions must refer to selected departments.")
        object.__setattr__(self, "department_definitions", {
            selected[key]: definition for key, definition in definitions.items() if definition
        })
        department_path = self.departments and (self.leadership_levels or self.ic_levels)
        if not (self.founders or self.c_level or department_path):
            raise ValueError("Select founders, C-level, or departments with leadership/IC levels.")


@dataclass(frozen=True)
class Candidate:
    """Provider observations; flags denote checked evidence support, not independent verification."""

    name: str
    title: str
    linkedin_url: str = ""
    department: str = ""
    seniority: str = ""
    role_type: str = ""
    is_founder: bool = False
    is_c_level: bool = False
    evidence_url: str = ""
    identity_verified: bool = False
    employment_verified: bool = False
    role_verified: bool = False
    notes: str = ""
    review_reason: str = ""
    evidence_text: str = ""
    observed_at: str = ""
    employment_status: str = "uncertain"
    employment_note: str = ""


@dataclass
class DiscoveryBatch:
    candidates: Sequence[Candidate]
    notes: str = ""
    limited: bool = False
    usage: dict[str, int] = field(default_factory=dict)


@dataclass
class PeopleResult:
    people: list[dict] = field(default_factory=list)
    companies: list[dict] = field(default_factory=list)
    review: list[dict] = field(default_factory=list)
    status: str = "completed"
    elapsed_seconds: float = 0.0
    provider_calls: int = 0
    is_mock: bool = False
    usage: dict[str, int] = field(default_factory=dict)
    run_settings: dict = field(default_factory=dict)
