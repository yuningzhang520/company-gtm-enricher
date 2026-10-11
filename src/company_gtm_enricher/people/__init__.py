"""People enrichment alongside the existing company enrichment workflow."""

from company_gtm_enricher.people.models import (
    Candidate, CompanyTarget, PeopleCriteria, PeopleResult,
)
from company_gtm_enricher.people.providers import MockPeopleProvider, PeopleProvider
from company_gtm_enricher.people.service import PeopleService, read_companies

__all__ = [
    "Candidate", "CompanyTarget", "PeopleCriteria", "PeopleResult", "PeopleProvider",
    "MockPeopleProvider", "PeopleService", "read_companies",
]
