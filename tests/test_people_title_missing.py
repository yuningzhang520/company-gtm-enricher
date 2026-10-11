from dataclasses import replace
from io import BytesIO

from openpyxl import load_workbook
import pytest

from company_gtm_enricher.people.excel_export import excel_bytes
from company_gtm_enricher.people.models import Candidate, CompanyTarget, DiscoveryBatch, PeopleCriteria
from company_gtm_enricher.people.providers import DiscoveryFailure
from company_gtm_enricher.people.service import PeopleService


COMPANY = CompanyTarget("Example", "example.org", aliases=("Old Example",))
DEPARTMENTS = PeopleCriteria(
    founders=False, c_level=False, departments=("Engineering",), leadership_levels=("Director",),
)
MISSING_TITLE = Candidate(
    name="Alex Rivera", title="", linkedin_url="https://www.linkedin.com/in/alex-rivera",
    evidence_url="https://www.linkedin.com/in/alex-rivera",
    evidence_text="Alex Rivera - Example - LinkedIn\nPublic profile information.",
    identity_verified=True, employment_verified=False, role_verified=False,
    employment_status="uncertain", employment_note="No dated employment history is available.",
)


class FixtureProvider:
    is_mock = False

    def __init__(self, candidates, *, fail=False):
        self.candidates = candidates
        self.fail = fail

    def discover(self, company, criteria):
        if self.fail:
            raise DiscoveryFailure("Classification did not finish.", DiscoveryBatch(self.candidates))
        return self.candidates


def run(candidates, criteria=DEPARTMENTS, *, fail=False, is_mock=False):
    provider = FixtureProvider(candidates, fail=fail)
    provider.is_mock = is_mock
    return PeopleService(provider).run([COMPANY], criteria)


@pytest.mark.parametrize("criteria", [
    DEPARTMENTS,
    PeopleCriteria(founders=False, c_level=False, departments=("Engineering",), ic_levels=("Staff",)),
])
@pytest.mark.parametrize("employment_verified", [False, True])
def test_department_search_preserves_missing_title_without_inventing_a_role(criteria, employment_verified):
    candidate = replace(
        MISSING_TITLE, employment_verified=employment_verified,
        employment_status="current" if employment_verified else "uncertain",
    )
    result = run([candidate], criteria)

    assert not result.review and len(result.people) == 1
    row = result.people[0]
    assert row["Status"] == "title_missing"
    assert (row["Name"], row["Title"], row["LinkedIn URL"]) == (candidate.name, "", candidate.linkedin_url)
    assert row["Evidence Text"] == candidate.evidence_text
    assert "Title is blank" in row["Notes"]
    assert "Use a general introduction without assuming a role" in row["Notes"]
    assert candidate.employment_note in row["Notes"]
    assert ("Current employment at the target company is unconfirmed" in row["Notes"]) is not employment_verified
    assert result.companies[0]["People"] == 1 and result.companies[0]["Review"] == 0
    assert "title_missing" in result.run_settings["candidate_policy"]
    assert candidate.title == "" and not candidate.role_verified


def test_whitespace_title_is_exported_as_blank():
    result = run([replace(MISSING_TITLE, title=" \n ")])
    assert result.people[0]["Title"] == ""
    assert result.people[0]["Status"] == "title_missing"


@pytest.mark.parametrize("overrides,reason", [
    ({"name": ""}, "Name or title is missing"),
    ({"identity_verified": False}, "identity has not been verified"),
    ({"linkedin_url": "https://linkedin.com/company/example"}, "profile URL is missing"),
    ({"evidence_url": ""}, "evidence URL is missing"),
    ({"title": "Chief Invented Officer"}, "Role has not been verified"),
    ({"employment_status": "former"}, "former employment"),
    ({"employment_status": "conflict"}, "Employment evidence conflicts"),
    ({"employment_status": "current"}, "Current employment has not been verified"),
    ({"employment_status": "unknown"}, "Employment evidence status is invalid"),
    ({"review_reason": "Extracted title conflicts with source evidence."}, "title conflicts"),
])
def test_missing_title_does_not_bypass_hard_evidence_gates(overrides, reason):
    result = run([replace(MISSING_TITLE, **overrides)])
    assert result.people == [] and len(result.review) == 1
    assert result.review[0]["Status"] == "needs_review"
    assert reason in result.review[0]["Review Reason"]


def test_missing_title_does_not_bypass_conflicting_profile_identities():
    result = run([MISSING_TITLE, replace(MISSING_TITLE, name="Another Person")])
    assert result.people == [] and len(result.review) == 2
    assert all("conflicting names" in row["Review Reason"] for row in result.review)


@pytest.mark.parametrize("missing_first", [True, False])
def test_supported_title_wins_over_missing_title_for_the_same_profile(missing_first):
    known = replace(
        MISSING_TITLE, title="Staff Engineer", role_verified=True,
        linkedin_url="https://uk.linkedin.com/in/alex-rivera?trk=index",
        evidence_text="Alex Rivera - Staff Engineer at Example - LinkedIn",
    )
    other = replace(MISSING_TITLE, name="Sam Jones", linkedin_url="https://linkedin.com/in/sam-jones")
    candidates = [MISSING_TITLE, other, known] if missing_first else [known, other, MISSING_TITLE]
    result = run(candidates)
    assert result.review == []
    assert [row["Name"] for row in result.people] == [MISSING_TITLE.name, other.name]
    assert result.people[0]["Title"] == known.title
    assert result.people[0]["Evidence Text"] == known.evidence_text
    assert result.people[0]["Status"] == "employment_unconfirmed"
    assert "Title is blank" not in result.people[0]["Notes"]


def test_unsupported_later_title_cannot_replace_missing_title_contact():
    unsupported = replace(MISSING_TITLE, title="Invented Chief Officer")
    result = run([MISSING_TITLE, unsupported])
    assert len(result.people) == len(result.review) == 1
    assert result.people[0]["Title"] == "" and result.people[0]["Status"] == "title_missing"
    assert "Role has not been verified" in result.review[0]["Review Reason"]


def test_first_supported_title_still_wins_between_two_complete_observations():
    first = replace(MISSING_TITLE, title="Staff Engineer", role_verified=True)
    second = replace(first, title="Engineering Lead")
    result = run([first, second])
    assert not result.review and len(result.people) == 1
    assert result.people[0]["Title"] == first.title


def test_missing_title_without_company_evidence_is_discarded_before_conflict_checks():
    unsupported = replace(
        MISSING_TITLE, name="Another Person", evidence_text="Another Person - Public profile",
        notes="Example", evidence_url="https://example.org/team",
    )
    result = run([MISSING_TITLE, unsupported])
    assert [row["Name"] for row in result.people] == [MISSING_TITLE.name]
    assert result.review == []
    assert "Discarded 1 candidates" in result.companies[0]["Notes"]


@pytest.mark.parametrize("criteria,flags", [
    (PeopleCriteria(founders=True, c_level=False, departments=("Engineering",)), {"is_founder": True}),
    (PeopleCriteria(founders=False, c_level=True), {"is_c_level": True}),
])
def test_founder_or_c_level_only_search_requires_title_support(criteria, flags):
    # Even category flags cannot replace the missing original title.
    result = run([replace(MISSING_TITLE, **flags)], criteria)
    assert result.people == [] and len(result.review) == 1
    assert "Name or title is missing" in result.review[0]["Review Reason"]
    assert "Role has not been verified" in result.review[0]["Review Reason"]
    assert "title_missing" not in result.run_settings["candidate_policy"]


def test_mock_still_treats_missing_title_as_mock_review():
    result = run([MISSING_TITLE], is_mock=True)
    assert result.people == [] and len(result.review) == 1
    assert result.review[0]["Status"] == "mock_review"
    assert "Name or title is missing" in result.review[0]["Review Reason"]


def test_failed_batch_does_not_promote_missing_title_contact():
    result = run([MISSING_TITLE], fail=True)
    assert result.people == [] and len(result.review) == 1
    assert result.review[0]["Status"] == "processing_failed"
    assert "Discovery did not complete" in result.review[0]["Review Reason"]
    assert result.review[0]["Evidence Text"] == MISSING_TITLE.evidence_text


def test_selected_export_columns_keep_title_missing_status_and_blank_title():
    result = run([MISSING_TITLE])
    workbook = load_workbook(BytesIO(excel_bytes(result, columns=["Name", "Title", "Notes"])))
    assert [cell.value for cell in workbook["People"][5]] == ["Name", "Title", "Notes", "Status"]
    assert workbook["People"]["A6"].value == MISSING_TITLE.name
    assert workbook["People"]["B6"].value is None
    assert "Current employment at the target company is unconfirmed" in workbook["People"]["C6"].value
    assert workbook["People"]["D6"].value == "title_missing"
