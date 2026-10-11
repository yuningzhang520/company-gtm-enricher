from dataclasses import replace

import pandas as pd
import pytest

from company_gtm_enricher.people import (
    Candidate, CompanyTarget, MockPeopleProvider, PeopleCriteria, PeopleService, read_companies,
)
from company_gtm_enricher.people.service import canonical_linkedin_url


class FixtureProvider:
    is_mock = False

    def __init__(self, candidates):
        self.candidates = candidates
        self.calls = []

    def discover(self, company, criteria):
        self.calls.append(company.name)
        if company.name == "Failure":
            raise RuntimeError("Discovery unavailable")
        return self.candidates


def verified_candidate(**overrides):
    candidate = Candidate(
        name="Alex Example", title="Co-founder", is_founder=True,
        linkedin_url="https://www.linkedin.com/in/alex-example",
        evidence_url="https://example.org/team", identity_verified=True,
        employment_verified=True, role_verified=True,
        evidence_text="Alex Example - Co-founder at Example",
    )
    return replace(candidate, **overrides)


def run_candidates(candidates, criteria=None):
    return PeopleService(FixtureProvider(candidates)).run(
        [CompanyTarget("Example", "example.org", "Core; Apps")], criteria or PeopleCriteria(),
    )


def test_read_companies_merges_tags_but_preserves_different_domains_and_blank_rows():
    frame = pd.DataFrame({
        "name": [" Example ", "EXAMPLE", "Example", " ", "Unnamed", "unnamed"],
        "domain": ["https://WWW.example.org/team", "example.org/", "other.example.org", None, None, None],
        "tags": ["Core; Apps", "apps | Agents", "Other", "Empty", "One", "two, ONE"],
    })
    companies = read_companies(frame, "name", "domain", "tags")
    assert companies == [
        CompanyTarget("Example", "example.org", "Core; Apps; Agents"),
        CompanyTarget("Example", "other.example.org", "Other"),
        CompanyTarget("", "", "Empty"),
        CompanyTarget("Unnamed", "", "One; two"),
    ]


def test_read_companies_rejects_empty_input_or_missing_columns():
    with pytest.raises(ValueError, match="nonblank"):
        read_companies(pd.DataFrame({"company": [None, float("nan"), " "]}), "company")
    with pytest.raises(ValueError, match="does not exist"):
        read_companies(pd.DataFrame({"company": ["Example"]}), "company", "missing")


def test_read_companies_does_not_guess_missing_domain_identity():
    companies = read_companies(pd.DataFrame({
        "company": ["Example", "Example"], "domain": [None, "example.org"],
    }), "company", "domain")
    assert len(companies) == 2


def test_results_keep_domains_for_same_named_companies():
    result = PeopleService(MockPeopleProvider()).run(
        [CompanyTarget("Example", "first.example"), CompanyTarget("Example", "second.example")],
        PeopleCriteria(),
    )
    assert [row["Domain"] for row in result.people] == ["first.example", "first.example", "second.example", "second.example"]
    assert [row["Domain"] for row in result.review] == ["first.example", "second.example"]


def test_case_variant_criteria_do_not_generate_duplicate_demo_roles():
    criteria = PeopleCriteria(
        founders=False, c_level=False, departments=("AI", " ai "),
        leadership_levels=("Director", "director"),
    )
    result = PeopleService(MockPeopleProvider()).run([CompanyTarget("Example")], criteria)
    assert len(result.people) == 1


@pytest.mark.parametrize("criteria", [
    {"founders": False, "c_level": False},
    {"founders": False, "c_level": False, "departments": ("Engineering",)},
    {"founders": False, "c_level": False, "departments": (" ",), "ic_levels": ("Staff",)},
])
def test_criteria_requires_an_actionable_role_path(criteria):
    with pytest.raises(ValueError, match="Select"):
        PeopleCriteria(**criteria)


def test_department_search_keeps_supported_titles_with_advisory_labels():
    candidates = [
        verified_candidate(name="CTO", is_founder=False, is_c_level=True, department="Other"),
        verified_candidate(name="Founder", linkedin_url="https://linkedin.com/in/founder"),
        verified_candidate(name="Director", is_founder=False, title="Director of Engineering", role_type="leadership", department="engineering", seniority="Director", linkedin_url="https://linkedin.com/in/director"),
        verified_candidate(name="Staff IC", is_founder=False, title="Staff Engineer", role_type="ic", department="Engineering", seniority="Staff", linkedin_url="https://linkedin.com/in/staff"),
        verified_candidate(name="Senior IC", is_founder=False, title="Senior Engineer", role_type="ic", department="Engineering", seniority="Senior", linkedin_url="https://linkedin.com/in/senior"),
        verified_candidate(name="Staff Product", is_founder=False, title="Staff Product Manager", role_type="ic", department="Product", seniority="Staff", linkedin_url="https://linkedin.com/in/product"),
    ]
    result = run_candidates(candidates, PeopleCriteria(founders=False, c_level=True, departments=("Engineering",), leadership_levels=("Director",), ic_levels=("Staff",)))
    assert [row["Name"] for row in result.people] == ["CTO", "Founder", "Director", "Staff IC", "Senior IC", "Staff Product"]
    assert not result.review
    for row in result.people:
        if row["Name"] in ("Founder", "Senior IC", "Staff Product"):
            assert "differ from the search preferences" in row["Notes"]
    assert "labels are advisory" in result.run_settings["candidate_policy"]


DEPARTMENT_SEARCH = PeopleCriteria(
    founders=False, c_level=False, departments=("Engineering",), leadership_levels=("Director",),
)


@pytest.mark.parametrize("labels", [
    {"department": "", "seniority": "", "role_type": "unknown"},
    {"department": "Product", "seniority": "Director", "role_type": "leadership"},
    {"department": "Engineering", "seniority": "Senior Director", "role_type": "leadership"},
    {"department": "Engineering", "seniority": "", "role_type": "leadership"},
    {"department": "Engineering", "seniority": "Director", "role_type": "unknown"},
])
def test_supported_person_and_original_role_survive_uncertain_or_different_labels(labels):
    candidate = verified_candidate(
        title="Senior Director of Engineering", is_founder=False,
        evidence_text="Alex Example - Senior Director of Engineering at Example", **labels,
    )
    result = run_candidates([candidate], DEPARTMENT_SEARCH)
    assert len(result.people) == 1 and result.review == []
    row = result.people[0]
    assert (row["Name"], row["Title"], row["LinkedIn URL"]) == (
        candidate.name, candidate.title, candidate.linkedin_url,
    )
    assert row["Evidence Text"] == candidate.evidence_text
    assert row["Department"] == candidate.department
    assert row["Seniority"] == candidate.seniority
    assert "assess the original title" in row["Notes"].lower()


@pytest.mark.parametrize("missing,reason", [
    ({"name": ""}, "Name or title is missing"),
    ({"linkedin_url": "https://linkedin.com/company/example"}, "profile URL is missing"),
    ({"identity_verified": False}, "identity has not been verified"),
    ({"role_verified": False}, "Role has not been verified"),
    ({"employment_verified": False, "employment_status": "conflict"}, "Employment evidence conflicts"),
    ({"evidence_url": ""}, "evidence URL is missing"),
    ({"review_reason": "Classification failed; original evidence retained."}, "Classification failed"),
])
def test_advisory_labels_never_bypass_person_title_profile_or_employer_checks(missing, reason):
    candidate = verified_candidate(
        is_founder=False, department="Unselected", seniority="", role_type="unknown", **missing,
    )
    result = run_candidates([candidate], DEPARTMENT_SEARCH)
    assert result.people == [] and len(result.review) == 1
    assert reason in result.review[0]["Review Reason"]
    assert "Role classification is missing" not in result.review[0]["Review Reason"]


def test_label_uncertainty_does_not_disable_profile_deduplication_or_identity_conflicts():
    candidate = verified_candidate(is_founder=False, department="", seniority="", role_type="unknown")
    duplicate = replace(candidate, linkedin_url="https://uk.linkedin.com/in/alex-example?trk=search")
    result = run_candidates([candidate, duplicate], DEPARTMENT_SEARCH)
    assert len(result.people) == 1 and result.review == []
    conflict = run_candidates([candidate, replace(duplicate, name="Different Person")], DEPARTMENT_SEARCH)
    assert not conflict.people and len(conflict.review) == 2
    assert all("conflicting names" in row["Review Reason"] for row in conflict.review)


@pytest.mark.parametrize("departments", [(), ("Engineering",)])
def test_founder_only_search_still_excludes_supported_unselected_title_categories(departments):
    criteria = PeopleCriteria(founders=True, c_level=False, departments=departments)
    result = run_candidates([
        verified_candidate(),
        verified_candidate(name="Other Person", title="Staff Engineer", is_founder=False,
                           department="Engineering", seniority="Staff", role_type="ic",
                           linkedin_url="https://linkedin.com/in/other-person"),
    ], criteria)
    assert [row["Name"] for row in result.people] == ["Alex Example"]
    assert result.review == []
    assert result.run_settings["candidate_policy"].startswith("Selected founder/C-level categories with supporting evidence.")
    assert "employment_unconfirmed" in result.run_settings["candidate_policy"]


@pytest.mark.parametrize("url,expected", [
    ("http://uk.linkedin.com/in/Alex-Example/?trk=test#fragment", "https://www.linkedin.com/in/alex-example"),
    ("www.linkedin.com/in/alex-example", "https://www.linkedin.com/in/alex-example"),
    ("https://www.linkedin.com/company/example", ""),
    ("https://linkedin.com.evil.org/in/alex-example", ""),
    ("https://evil@linkedin.com/in/alex-example", ""),
    ("https://www.linkedin.com/in/alex%2Fexample", ""),
    ("https://www.linkedin.com:invalid/in/alex", ""),
    ("", ""),
])
def test_canonical_profiles_reject_wrong_hosts_and_nonprofiles(url, expected):
    assert canonical_linkedin_url(url) == expected


@pytest.mark.parametrize("overrides,reason", [
    ({"linkedin_url": ""}, "profile URL is missing"),
    ({"identity_verified": False}, "identity has not been verified"),
    ({"employment_verified": False, "employment_status": "former"}, "former employment"),
    ({"role_verified": False}, "Role has not been verified"),
    ({"evidence_url": ""}, "evidence URL is missing"),
    ({"is_founder": False, "role_type": ""}, "selected founder or C-level role"),
])
def test_missing_evidence_goes_to_review(overrides, reason):
    result = run_candidates([verified_candidate(**overrides)])
    assert result.people == []
    assert len(result.review) == 1
    assert reason in result.review[0]["Review Reason"]
    assert result.review[0]["Status"] == "needs_review"
    assert result.companies[0]["Review"] == 1


def test_indexed_profile_alone_does_not_verify_identity_or_employment():
    candidate = Candidate("Example Person", "Co-founder", is_founder=True, linkedin_url="https://linkedin.com/in/example-person", evidence_url="https://linkedin.com/in/example-person", evidence_text="A profile indexed for Example; identity and role remain unsupported.")
    result = run_candidates([candidate])
    assert not result.people
    assert "identity has not been verified" in result.review[0]["Review Reason"]
    assert "Role has not been verified" in result.review[0]["Review Reason"]
    assert "Current employment at the target company is unconfirmed" in result.review[0]["Notes"]


@pytest.mark.parametrize("criteria", [PeopleCriteria(), DEPARTMENT_SEARCH])
def test_supported_identity_title_and_profile_with_uncertain_employment_remain_in_people(criteria):
    candidate = verified_candidate(
        employment_verified=False, employment_status="uncertain",
        employment_note="The indexed headline has no dated employment history.",
        notes="Original provider note.", evidence_text="Alex Example - Co-founder at Example",
    )
    result = run_candidates([candidate], criteria)
    assert len(result.people) == 1 and result.review == []
    row = result.people[0]
    assert row["Status"] == "employment_unconfirmed"
    assert (row["Name"], row["Title"], row["LinkedIn URL"], row["Evidence Text"]) == (
        candidate.name, candidate.title, candidate.linkedin_url, candidate.evidence_text,
    )
    assert "Original provider note." in row["Notes"]
    assert candidate.employment_note in row["Notes"]
    assert "no independent verification" in row["Notes"]
    assert result.companies[0]["People"] == 1 and result.companies[0]["Review"] == 0


@pytest.mark.parametrize("employment_status", ["current", "uncertain"])
def test_verified_employment_preserves_supported_status_including_legacy_candidates(employment_status):
    candidate = verified_candidate(employment_status=employment_status)
    assert Candidate("Name", "Title").employment_status == "uncertain"
    assert Candidate("Name", "Title").employment_note == ""
    result = run_candidates([candidate])
    assert result.people[0]["Status"] == "supported"
    assert "employment is unconfirmed" not in result.people[0]["Notes"]
    assert result.review == []


@pytest.mark.parametrize("employment_status,reason", [
    ("former", "former employment"), ("conflict", "Employment evidence conflicts"),
])
@pytest.mark.parametrize("employment_verified", [False, True])
def test_former_or_conflicting_employment_requires_review_even_without_a_review_reason(
    employment_status, reason, employment_verified,
):
    candidate = verified_candidate(
        employment_status=employment_status, employment_verified=employment_verified,
        employment_note="The evidence identifies a different current employer.",
    )
    result = run_candidates([candidate])
    assert result.people == [] and len(result.review) == 1
    assert result.review[0]["Status"] == "needs_review"
    assert reason in result.review[0]["Review Reason"]
    assert candidate.employment_note in result.review[0]["Notes"]


@pytest.mark.parametrize("overrides,reason", [
    ({"name": ""}, "Name or title is missing"),
    ({"linkedin_url": "https://linkedin.com.evil.example/in/person"}, "profile URL is missing"),
    ({"identity_verified": False}, "identity has not been verified"),
    ({"role_verified": False}, "Role has not been verified"),
    ({"evidence_url": ""}, "evidence URL is missing"),
    ({"review_reason": "The source supports a different person."}, "different person"),
])
def test_uncertain_employment_never_bypasses_other_evidence_checks(overrides, reason):
    candidate = verified_candidate(employment_verified=False, employment_status="uncertain", **overrides)
    result = run_candidates([candidate], DEPARTMENT_SEARCH)
    assert not result.people and len(result.review) == 1
    assert result.review[0]["Status"] == "needs_review"
    assert reason in result.review[0]["Review Reason"]


def test_uncertain_employment_keeps_profile_identity_conflicts_in_review():
    candidate = verified_candidate(employment_verified=False)
    result = run_candidates([candidate, replace(candidate, name="Different Person")], DEPARTMENT_SEARCH)
    assert not result.people and len(result.review) == 2
    assert all(row["Status"] == "needs_review" for row in result.review)
    assert all("conflicting names" in row["Review Reason"] for row in result.review)


@pytest.mark.parametrize("employment_status", ["current", "invalid"])
def test_inconsistent_or_invalid_employment_status_is_not_treated_as_uncertainty(employment_status):
    result = run_candidates([verified_candidate(employment_verified=False, employment_status=employment_status)])
    assert not result.people and len(result.review) == 1
    assert result.review[0]["Status"] == "needs_review"


def test_uncertain_employment_does_not_expand_founder_only_title_categories():
    candidate = verified_candidate(
        title="Staff Engineer", is_founder=False, department="Engineering",
        seniority="Staff", role_type="ic", employment_verified=False,
    )
    result = run_candidates([candidate], PeopleCriteria(founders=True, c_level=False))
    assert result.people == [] and result.review == []


@pytest.mark.parametrize("employment_status", ["former", "conflict"])
def test_explicit_employment_problem_remains_reviewable_with_an_unselected_role(employment_status):
    candidate = verified_candidate(
        title="Staff Engineer", is_founder=False, department="Engineering",
        seniority="Staff", role_type="ic", employment_status=employment_status,
    )
    result = run_candidates([candidate], PeopleCriteria(founders=True, c_level=False))
    assert result.people == [] and len(result.review) == 1
    assert result.review[0]["Status"] == "needs_review"


def test_dedup_uses_canonical_profile_and_keeps_same_name_different_people():
    candidate = verified_candidate()
    result = run_candidates([
        candidate,
        replace(candidate, linkedin_url="https://uk.linkedin.com/in/Alex-Example/?trk=source"),
        replace(candidate, linkedin_url="https://linkedin.com/in/alex-example-2"),
    ])
    assert len(result.people) == 2
    assert result.people[0]["Name"] == result.people[1]["Name"]
    assert not result.review


def test_same_profile_conflicting_names_requires_review():
    candidate = verified_candidate()
    result = run_candidates([candidate, replace(candidate, name="Different Person")])
    assert not result.people
    assert len(result.review) == 2
    assert all("conflicting names" in row["Review Reason"] for row in result.review)


def test_mock_is_deterministic_and_explicitly_synthetic_for_any_company():
    service = PeopleService(MockPeopleProvider())
    companies = [CompanyTarget("Arbitrary Unresearched Company", lists="Apps")]
    first = service.run(companies, PeopleCriteria())
    second = service.run(companies, PeopleCriteria())
    assert first.people == second.people
    assert [row["Name"] for row in first.people] == ["Demo Founder", "Demo CTO"]
    assert len(first.review) == 1
    assert first.is_mock
    for row in first.people + first.review:
        assert row["LinkedIn URL"] == row["Evidence URL"] == ""
        assert "Synthetic" in row["Notes"]
        assert row["Status"].startswith("mock")
        assert row["List Tags"] == "Apps"


def test_failures_are_visible_and_other_companies_continue():
    provider = FixtureProvider([verified_candidate()])
    result = PeopleService(provider).run([CompanyTarget("Failure"), CompanyTarget("Example")], PeopleCriteria())
    assert result.status == "completed_with_errors"
    assert result.provider_calls == 2
    assert [row["Status"] for row in result.companies] == ["error", "processed"]
    assert "Discovery unavailable" in result.companies[0]["Notes"]
    assert len(result.people) == 1


def test_stop_preserves_partial_results_and_pending_company_rows():
    stop = False
    snapshots = []

    def on_update(result, processed, total, current):
        nonlocal stop
        snapshots.append((result, processed, total, current))
        if processed == 1:
            stop = True

    result = PeopleService(MockPeopleProvider()).run(
        [CompanyTarget("First"), CompanyTarget("Second")], PeopleCriteria(),
        should_stop=lambda: stop, on_update=on_update,
    )
    assert result.status == "stopped"
    assert result.provider_calls == 1
    assert [row["Status"] for row in result.companies] == ["mock", "pending"]
    initial = snapshots[0][0]
    assert initial.status == "running" and not initial.people
    assert [row["Status"] for row in initial.companies] == ["pending", "pending"]
    assert snapshots[-1][0].status == "stopped"


def test_stop_while_paused_makes_no_provider_calls(monkeypatch):
    stop = False

    def sleep(_):
        nonlocal stop
        stop = True

    monkeypatch.setattr("company_gtm_enricher.people.service.time.sleep", sleep)
    provider = FixtureProvider([])
    result = PeopleService(provider).run([CompanyTarget("Example")], PeopleCriteria(), should_pause=lambda: True, should_stop=lambda: stop)
    assert result.status == "stopped"
    assert result.provider_calls == 0
    assert not provider.calls


def test_resume_from_pause_and_blank_rows_have_visible_progress(monkeypatch):
    pauses = iter([True, False, False])
    sleeps = []
    updates = []
    monkeypatch.setattr("company_gtm_enricher.people.service.time.sleep", sleeps.append)
    result = PeopleService(MockPeopleProvider()).run(
        [CompanyTarget(""), CompanyTarget("Example")], PeopleCriteria(),
        should_pause=lambda: next(pauses, False),
        on_update=lambda result, processed, total, current: updates.append((processed, total)),
    )
    assert sleeps
    assert result.status == "completed"
    assert result.provider_calls == 1
    assert result.companies[0]["Status"] == "skipped_empty"
    assert updates == [(0, 2), (1, 2), (1, 2), (2, 2), (2, 2)]
