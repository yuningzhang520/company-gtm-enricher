from __future__ import annotations

from typing import Protocol, Sequence, Union

from company_gtm_enricher.people.models import Candidate, CompanyTarget, DiscoveryBatch, PeopleCriteria


class FatalProviderError(RuntimeError):
    """Invalid credentials or account/configuration errors that should stop a run."""


class DiscoveryFailure(RuntimeError):
    """Safe provider failure with evidence already collected for manual review."""

    def __init__(self, message: str, batch: DiscoveryBatch, *, fatal: bool = False) -> None:
        super().__init__(message)
        self.batch = batch
        self.fatal = fatal


class PeopleProvider(Protocol):
    @property
    def is_mock(self) -> bool: ...

    def discover(self, company: CompanyTarget, criteria: PeopleCriteria) -> Union[Sequence[Candidate], DiscoveryBatch]: ...


class MockPeopleProvider:
    """Deterministic synthetic fixtures for any company; performs no research."""

    is_mock = True

    def discover(self, company: CompanyTarget, criteria: PeopleCriteria) -> Sequence[Candidate]:
        notes = "Synthetic demo person; no research performed and no LinkedIn URL provided."
        candidates = []
        if criteria.founders:
            candidates.append(Candidate("Demo Founder", "Co-founder", is_founder=True, seniority="Founder", notes=notes))
        if criteria.c_level:
            candidates.append(Candidate("Demo CTO", "Chief Technology Officer", is_c_level=True, seniority="C-level", department="Engineering", notes=notes))
        for department in criteria.departments:
            for level in criteria.leadership_levels:
                candidates.append(Candidate(f"Demo {department} {level}", f"{level} of {department}", department=department, seniority=level, role_type="leadership", notes=notes))
            for level in criteria.ic_levels:
                candidates.append(Candidate(f"Demo {department} {level} IC", f"{level} {department} Specialist", department=department, seniority=level, role_type="ic", notes=notes))
        candidates.append(Candidate("Demo Uncertain Person", "Unconfirmed role", notes=notes, review_reason="Synthetic uncertainty example: role and current employment require review."))
        return candidates
