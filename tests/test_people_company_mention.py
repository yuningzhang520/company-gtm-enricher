from dataclasses import replace

import pytest

from company_gtm_enricher.people.models import Candidate, CompanyTarget, DiscoveryBatch, PeopleCriteria
from company_gtm_enricher.people.providers import DiscoveryFailure, MockPeopleProvider
from company_gtm_enricher.people.service import PeopleService, _validate_candidates, has_company_mention


COMPANY = CompanyTarget("Acme Labs", "acme.example", aliases=("Old Acme",))
CRITERIA = PeopleCriteria(founders=False, c_level=False, departments=("Engineering",), leadership_levels=("Director",))


def candidate(**changes):
    original = Candidate(
        name="Alex Person", title="Director of Engineering",
        linkedin_url="https://www.linkedin.com/in/alex-person",
        evidence_url="https://www.linkedin.com/in/alex-person",
        evidence_text="Alex Person - Director of Engineering at Acme Labs",
        identity_verified=True, role_verified=True,
        employment_verified=False, employment_status="uncertain",
        department="Engineering", seniority="Director", role_type="leadership",
    )
    return replace(original, **changes)


class Provider:
    is_mock = False
    settings = {"search_query": 'site:linkedin.com/in/ "Acme Labs"'}

    def __init__(self, candidates, failure=None):
        self.candidates, self.failure = candidates, failure

    def discover(self, company, criteria):
        batch = DiscoveryBatch(self.candidates, notes="Original discovery note.")
        if self.failure is not None:
            raise DiscoveryFailure("Processing failed.", batch, fatal=self.failure)
        return batch


@pytest.mark.parametrize("text", [
    "Works at ACME LABS.", "Works at Acme\n\t Labs.",
    "Company website: https://ACME.EXAMPLE/team", "Joined OLD ACME.",
])
def test_company_name_domain_and_explicit_alias_are_case_insensitive_whole_phrases(text):
    assert has_company_mention(text, COMPANY)
    people, review = _validate_candidates([candidate(evidence_text=text)], COMPANY, CRITERIA, False)
    assert len(people) == 1 and not review
    assert people[0]["Status"] == "employment_unconfirmed"


@pytest.mark.parametrize("text", [
    "Acme Labsware", "PreAcme Labs", "Old Acmeish", "notacme.example",
    "Acme Laboratory", "Acme", "Former Acme", "No employer is stated.", "",
])
def test_partial_words_and_unconfigured_names_do_not_count_as_mentions(text):
    assert not has_company_mention(text, COMPANY)


def test_target_whitespace_is_normalized_and_alias_punctuation_is_literal():
    company = CompanyTarget("  Acme \n Labs  ", aliases=("Old.Acme",))
    assert has_company_mention("Acme\tLabs", company)
    assert has_company_mention("Company: Old.Acme", company)
    assert not has_company_mention("Company: OldXAcme", company)
    assert not has_company_mention("Anything", CompanyTarget(" "))


@pytest.mark.parametrize("changes", [
    {"employment_status": "current", "employment_verified": True},
    {"employment_status": "uncertain"},
    {"employment_status": "former"},
    {"employment_status": "conflict", "review_reason": "Wrong current employer."},
    {"identity_verified": False, "role_verified": False, "review_reason": "Missing identity and title proof."},
])
def test_candidates_without_a_company_mention_are_dropped_from_people_and_review(changes):
    item = candidate(evidence_text="Alex Person - Director of Engineering", **changes)
    result = PeopleService(Provider([item])).run([COMPANY], CRITERIA)
    assert result.people == result.review == []
    assert result.companies[0]["People"] == result.companies[0]["Review"] == 0
    assert "Discarded 1 candidates" in result.companies[0]["Notes"]
    assert "Original discovery note" in result.companies[0]["Notes"]
    assert "discarded from People and Review" in result.run_settings["candidate_policy"]


@pytest.mark.parametrize("metadata", [
    {"notes": "Acme Labs was the target search."},
    {"employment_note": "The model mentions Acme Labs."},
    {"evidence_url": "https://acme.example/team"},
    {"title": "Director of Engineering at Acme Labs"},
    {"name": "Acme Labs"},
    {"review_reason": "Could not establish Acme Labs employment."},
])
def test_only_source_text_counts_not_query_company_columns_or_model_metadata(metadata):
    item = candidate(evidence_text="No employer is stated in this source.", **metadata)
    result = PeopleService(Provider([item])).run([COMPANY], CRITERIA)
    assert result.run_settings["companies"][0]["name"] == "Acme Labs"
    assert "Acme Labs" in result.run_settings["search_query"]
    assert result.people == result.review == []


@pytest.mark.parametrize("reverse", [False, True])
def test_dropped_same_profile_name_cannot_poison_a_retained_identity(reverse):
    valid = candidate()
    unrelated = candidate(name="Different Person", evidence_text="Different Person - Director at Other Business")
    candidates = [valid, unrelated] if not reverse else [unrelated, valid]
    result = PeopleService(Provider(candidates)).run([COMPANY], CRITERIA)
    assert [row["Name"] for row in result.people] == ["Alex Person"]
    assert result.review == []
    assert "Discarded 1 candidates" in result.companies[0]["Notes"]


def test_company_word_presence_does_not_establish_current_employment_or_override_evidence_conflicts():
    uncertain = candidate(evidence_text="Alex Person - Director of Engineering. Uses Acme Labs software.")
    people, review = _validate_candidates([uncertain], COMPANY, CRITERIA, False)
    assert people[0]["Status"] == "employment_unconfirmed" and not review
    for change in ({"identity_verified": False}, {"role_verified": False}, {"employment_status": "former"}):
        people, review = _validate_candidates([replace(uncertain, **change)], COMPANY, CRITERIA, False)
        assert not people and len(review) == 1


@pytest.mark.parametrize("fatal", [False, True])
def test_discovery_failure_drops_unrelated_raw_hits_but_preserves_matching_failed_evidence(fatal):
    matching = candidate(name="", title="", identity_verified=False, role_verified=False,
                         evidence_text="Unclassified search result mentioning Acme Labs.")
    unrelated = candidate(name="", title="", evidence_text="Unclassified search result about another employer.")
    result = PeopleService(Provider([matching, unrelated], failure=fatal)).run([COMPANY], CRITERIA)
    assert result.status == ("failed" if fatal else "completed_with_errors")
    assert result.people == [] and len(result.review) == 1
    assert result.review[0]["Status"] == "processing_failed"
    assert result.review[0]["Evidence Text"] == matching.evidence_text
    assert result.companies[0]["Review"] == 1
    assert "Discarded 1 candidates" in result.companies[0]["Notes"]
    assert "Original discovery note" in result.companies[0]["Notes"]


def test_mock_still_produces_four_people_two_review_without_source_company_mentions():
    result = PeopleService(MockPeopleProvider()).run([COMPANY, CompanyTarget("Other Business")], PeopleCriteria())
    assert len(result.people) == 4 and len(result.review) == 2
    assert all(not row["Evidence Text"] for row in result.people + result.review)
    assert all("Discarded" not in row["Notes"] for row in result.companies)


@pytest.mark.parametrize("title", ["", "Director of Research"])
def test_company_word_only_inside_person_name_is_not_company_evidence(title):
    company = CompanyTarget("Lindy", "lindy.ai")
    item = candidate(name="Lindy Smart", title=title,
                     evidence_text="LINDY\nSMART - Director of Research. Experience: Other University. View Lindy Smart's profile.")
    result = PeopleService(Provider([item])).run([company], CRITERIA)
    assert result.people == result.review == []
    assert "Discarded 1 candidates" in result.companies[0]["Notes"]


@pytest.mark.parametrize("independent_mention", ["Works at Lindy.", "Company site: lindy.ai", "Works at Acquired Company."])
def test_real_company_mention_survives_name_exclusion(independent_mention):
    company = CompanyTarget("Lindy", "lindy.ai", aliases=("Acquired Company",))
    text = "Lindy Smart - Director of Research. " + independent_mention
    assert has_company_mention(text, company, person_name="Lindy Smart")
    result = PeopleService(Provider([candidate(name="Lindy Smart", evidence_text=text)])).run([company], CRITERIA)
    assert len(result.people) == 1 and not result.review
