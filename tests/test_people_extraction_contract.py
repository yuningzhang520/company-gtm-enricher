"""Classifier/provider contracts exercised through extraction and final filtering."""
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from company_gtm_enricher.people.classification import OpenAIRoleClassifier
from company_gtm_enricher.people.live import LiveSearchPeopleProvider
from company_gtm_enricher.people.models import CompanyTarget, PeopleCriteria
from company_gtm_enricher.people.search import SearchHit
from company_gtm_enricher.people.service import PeopleService


COMPANY = CompanyTarget("Example", "example.org")


def criteria(*levels, founders=False, c_level=False):
    return PeopleCriteria(
        founders=founders, c_level=c_level, departments=("Engineering",),
        leadership_levels=levels or ("Director",),
    )


def evidence(role="Director of Engineering", *, copied=None, level="Director", quote=None):
    quote = quote if quote is not None else f"{role} at Example · Experience: Example"
    source = SearchHit(
        "source-1", "https://www.linkedin.com/in/jordan-example",
        f"Jordan Example - {role} - LinkedIn", quote,
    )
    item = {
        "source_id": source.id, "name": "Jordan Example", "title": role if copied is None else copied,
        "department": "Engineering", "seniority": level, "role_type": "leadership",
        "is_founder": False, "is_c_level": False, "current_employment": "current",
        "employment_quote": quote, "classification_notes": "",
    }
    return source, item


class Client:
    def __init__(self, observations):
        self.observations = observations
        self.calls = []
        self.responses = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            status="completed", output=[],
            output_text=json.dumps({"observations": self.observations}),
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        )


def extract(sources, observations, selected):
    client = Client(observations)
    candidates = OpenAIRoleClassifier(client).classify(COMPANY, selected, sources)

    class Provider:
        is_mock = False

        def discover(self, company, selected_criteria):
            return candidates

    result = PeopleService(Provider()).run([COMPANY], selected)
    return candidates, result, client


def test_request_demands_every_source_and_supplies_equivalent_spellings_as_context():
    source, item = evidence()
    unknown = SearchHit("source-2", "https://www.linkedin.com/in/unknown-example", "An unclassified profile", "Experience: Example")
    empty = {
        **item, "source_id": unknown.id, "name": "", "title": "", "department": "",
        "seniority": "", "role_type": "unknown", "current_employment": "unclear",
        "employment_quote": "", "classification_notes": "No supported job facts.",
    }
    _, result, client = extract([source, unknown], [item, empty], criteria())
    request = client.calls[0]
    observation_schema = request["text"]["format"]["schema"]["properties"]["observations"]
    assert observation_schema["minItems"] == observation_schema["maxItems"] == 2
    assert observation_schema["items"]["properties"]["source_id"]["enum"] == [source.id, unknown.id]
    assert "EVERY supplied source_id" in request["instructions"]
    assert "Never skip a hit" in request["instructions"]
    payload = json.loads(request["input"])
    assert "Senior Vice President" in payload["seniority_aliases"]["SVP"]
    assert len(result.people) == 1 and len(result.review) == 1
    assert result.review[0]["Evidence Text"] == unknown.title + "\n" + unknown.snippet


def test_legacy_missing_observation_still_preserves_unknown_hit_for_review():
    source, item = evidence()
    missing = SearchHit("source-2", "https://www.linkedin.com/in/missing-example", "Missing Example", "Unknown role")
    candidates, result, _ = extract([source, missing], [item], criteria())
    assert len(candidates) == 2
    assert len(result.people) == 1 and len(result.review) == 1
    row = result.review[0]
    assert row["LinkedIn URL"] == missing.url
    assert row["Name"] == row["Title"] == ""
    assert row["Evidence Text"] == missing.title + "\n" + missing.snippet
    assert "did not extract" in row["Review Reason"]


@pytest.mark.parametrize("role,mapped,selected", [
    ("Vice President of Engineering", "Vice President", "VP"),
    ("Senior Vice President of Engineering", "Senior Vice President", "SVP"),
    ("SVP of Engineering", "SVP", "Senior Vice President"),
    ("Executive Vice President of Engineering", "Executive Vice President", "EVP"),
])
def test_equivalent_level_spellings_reach_selected_exact_level(role, mapped, selected):
    source, item = evidence(role, level=mapped)
    candidates, result, _ = extract([source], [item], criteria(selected))
    assert candidates[0].seniority == selected
    assert len(result.people) == 1 and result.review == []
    assert result.people[0]["Seniority"] == selected
    assert result.people[0]["Title"] == role


@pytest.mark.parametrize("role,mapped,selected", [
    ("Senior Vice President of Engineering", "Senior Vice President", "VP"),
    ("Senior Director of Engineering", "Senior Director", "Director"),
])
def test_department_search_retains_supported_titles_outside_preferred_level(role, mapped, selected):
    source, item = evidence(role, level=mapped)
    _, result, _ = extract([source], [item], criteria(selected))
    assert len(result.people) == 1
    assert result.review == []
    assert result.people[0]["Title"] == role


def test_wrong_vp_mapping_from_explicit_svp_title_is_advisory():
    source, item = evidence("Senior Vice President of Engineering", level="VP")
    _, result, _ = extract([source], [item], criteria("VP"))
    assert len(result.people) == 1
    assert result.review == []
    assert result.people[0]["Title"] == "Senior Vice President of Engineering"
    assert "conflicts with the explicit level" in result.people[0]["Notes"]


@pytest.mark.parametrize("flag,role", [
    ("is_founder", "Co-Founder and Senior Vice President of Engineering"),
    ("is_c_level", "CTO and Senior Vice President of Engineering"),
])
def test_level_conflicts_are_advisory_in_both_executive_and_department_searches(flag, role):
    source, item = evidence(role, level="VP")
    item[flag] = True
    selected = criteria("VP", founders=flag == "is_founder", c_level=flag == "is_c_level")
    _, result, _ = extract([source], [item], selected)
    assert len(result.people) == 1 and result.review == []
    assert "conflicts with the explicit level" in result.people[0]["Notes"]
    _, department_result, _ = extract([source], [item], criteria("VP"))
    assert len(department_result.people) == 1 and department_result.review == []
    assert "conflicts with the explicit level" in department_result.people[0]["Notes"]


@pytest.mark.parametrize("labels", [
    {"department": "", "seniority": "", "role_type": "unknown"},
    {"department": "Marketing", "seniority": "Manager", "role_type": "leadership"},
    {"department": "Engineering", "seniority": "Principal", "role_type": "ic"},
])
def test_department_search_keeps_source_supported_person_when_grouping_labels_are_unknown_or_different(labels):
    source, item = evidence()
    item.update(labels)
    candidates, result, _ = extract([source], [item], criteria())
    assert candidates[0].review_reason == ""
    assert len(result.people) == 1 and result.review == []
    row = result.people[0]
    assert row["Name"] == "Jordan Example"
    assert row["Title"] == "Director of Engineering"
    assert row["LinkedIn URL"] == source.url
    assert row["Department"] == labels["department"]
    assert row["Seniority"] == labels["seniority"]


@pytest.mark.parametrize("role,flag", [
    ("Founding Engineer", "is_founder"), ("Chief of Staff", "is_c_level"),
])
def test_bad_category_flag_is_advisory_but_cannot_admit_a_nonexecutive_in_executive_only_search(role, flag):
    source, item = evidence(role)
    item[flag] = True
    candidates, department_result, _ = extract([source], [item], criteria())
    assert not getattr(candidates[0], flag)
    assert candidates[0].review_reason == ""
    assert len(department_result.people) == 1 and department_result.review == []
    assert department_result.people[0]["Title"] == role
    assert "Discarded an unsupported" in department_result.people[0]["Notes"]
    executive_only = PeopleCriteria(founders=flag == "is_founder", c_level=flag == "is_c_level")
    _, restricted_result, _ = extract([source], [item], executive_only)
    assert restricted_result.people == []


@pytest.mark.parametrize("problem", ["former", "invented_title", "other_person", "invalid_profile", "wrong_employer"])
def test_unknown_grouping_labels_never_override_a_failed_source_fact(problem):
    source, item = evidence()
    item.update(department="", seniority="", role_type="unknown")
    if problem == "former":
        item["current_employment"] = "former"
        source = replace(source, snippet="Director of Engineering. Example. Jan 2020 - Jun 2022")
    elif problem == "invented_title":
        item["title"] = "Invented Executive Role"
    elif problem == "other_person":
        item["name"] = "Different Person"
    elif problem == "invalid_profile":
        source = replace(source, url="https://www.linkedin.com/company/example")
    else:
        item["employment_quote"] = "Director of Engineering at Other"
        source = replace(source, snippet=item["employment_quote"] + " · Experience: Example")
    _, result, _ = extract([source], [item], criteria())
    assert result.people == [] and len(result.review) == 1
    assert result.review[0]["Evidence Text"] == source.title + "\n" + source.snippet


@pytest.mark.parametrize("separator", ["·", "|"])
def test_grounded_trailing_display_separator_is_trimmed_without_changing_evidence(separator):
    role = "Director of Engineering"
    quote = f"{role} {separator} Example · Experience: Example"
    source, item = evidence(role, copied=f"{role} {separator}", quote=quote)
    candidates, result, _ = extract([source], [item], criteria())
    assert candidates[0].title == role
    assert len(result.people) == 1 and result.review == []
    assert result.people[0]["Evidence Text"] == source.title + "\n" + source.snippet


@pytest.mark.parametrize("separator", ["·", "|"])
def test_separator_cleanup_cannot_ground_an_invented_title(separator):
    source, item = evidence("Software Engineer", copied=f"Director of Engineering {separator}")
    candidates, result, _ = extract([source], [item], criteria())
    assert not candidates[0].role_verified
    assert result.people == [] and len(result.review) == 1
    assert result.review[0]["Evidence Text"] == source.title + "\n" + source.snippet


def test_single_company_pipe_suffix_supplies_affiliation_for_legacy_copied_title():
    role = "Director of Engineering | Example"
    source, item = evidence(role, quote=role + " · Experience: Example")
    candidates, result, _ = extract([source], [item], criteria())
    assert candidates[0].employment_verified
    assert len(result.people) == 1 and result.review == []


@pytest.mark.parametrize("role", [
    "Founder at Other | Director of Engineering | Example",
    "Founder | Other | Director of Engineering | Example",
])
def test_company_pipe_does_not_transfer_another_employers_role_or_match_name_prefix(role):
    source, item = evidence(role, quote=role + " · Experience: Example")
    item["is_founder"] = "Founder" in role
    candidates, result, _ = extract([source], [item], criteria(founders=True))
    assert not candidates[0].employment_verified
    assert result.people == [] and len(result.review) == 1


@pytest.mark.parametrize("key,value", [
    ("Engineering", []), ("Unselected Department", "Unsupported mapping"),
])
def test_direct_live_discovery_revalidates_mutated_definitions_before_any_paid_work(key, value):
    selected = criteria()
    selected.department_definitions[key] = value
    calls = []

    def unexpected_search(query):
        calls.append(query)
        pytest.fail("Invalid definitions reached a paid search boundary")

    client = Client([])
    provider = LiveSearchPeopleProvider(SimpleNamespace(search=unexpected_search), OpenAIRoleClassifier(client))
    with pytest.raises(ValueError, match="[Dd]efinitions"):
        provider.discover(COMPANY, selected)
    assert calls == []
    assert client.calls == []


def headline_evidence(headline, *, copied="VP Engineering AI/ML", quote="", snippet=""):
    source, item = evidence(copied, level="VP", quote=quote)
    return SearchHit(source.id, source.url, headline, snippet), item


@pytest.mark.parametrize("quote", ["", "Vice President of Engineering at Example · Experience: Example"])
def test_named_headline_supports_clean_role_when_quote_is_missing_or_uses_different_wording(quote):
    source, item = headline_evidence(
        "Jordan Example - VP Engineering AI/ML @Example - LinkedIn",
        quote=quote, snippet="Vice President of Engineering at Example · Experience: Example",
    )
    candidates, result, _ = extract([source], [item], criteria("VP"))
    assert candidates[0].employment_verified and candidates[0].role_verified
    assert len(result.people) == 1 and result.review == []
    assert result.people[0]["Title"] == "VP Engineering AI/ML"
    assert "used the direct named profile headline" in result.people[0]["Notes"]
    assert result.people[0]["Evidence Text"] == source.title + "\n" + source.snippet


def test_deduplicated_multiline_search_titles_can_contain_one_complete_supporting_headline():
    source, item = headline_evidence(
        "Jordan Example - Example - LinkedIn\n"
        "Jordan Example - VP Engineering AI/ML @Example - LinkedIn",
    )
    candidates, result, _ = extract([source], [item], criteria("VP"))
    assert candidates[0].employment_verified
    assert len(result.people) == 1 and result.review == []
    assert result.people[0]["Evidence Text"] == source.title + "\n"


@pytest.mark.parametrize("headline,copied", [
    ("Jordan Example - VP Engineering AI/ML @ Other - LinkedIn", "VP Engineering AI/ML"),
    ("Jordan Example - Founder @Other | VP Engineering AI/ML @Example - LinkedIn", "Founder @Other | VP Engineering AI/ML"),
    ("Jordan Example - Senior VP Engineering AI/ML @Example - LinkedIn", "VP Engineering AI/ML"),
    ("Jordan Example - VP Engineering AI/ML @Example - LinkedIn", "Engineering AI/ML"),
    ("Jordan Example - VP Engineering AI/ML @Example - LinkedIn", "VP Engineering"),
    ("Other Person - VP Engineering AI/ML @Example - LinkedIn", "VP Engineering AI/ML"),
    ("Jordan Example - Other - LinkedIn\nOther Person - VP Engineering AI/ML @Example - LinkedIn", "VP Engineering AI/ML"),
])
def test_headline_fallback_requires_one_complete_named_role_employer_pair(headline, copied):
    source, item = headline_evidence(headline, copied=copied, snippet="Experience: Example")
    candidates, result, _ = extract([source], [item], criteria("VP"))
    assert not candidates[0].employment_verified
    assert result.people == [] and len(result.review) == 1
    assert result.review[0]["Review Reason"]


@pytest.mark.parametrize("employment", ["former", "unclear"])
def test_clean_current_headline_overrides_unsupported_model_employment_labels(employment):
    source, item = headline_evidence("Jordan Example - VP Engineering AI/ML @Example - LinkedIn")
    item["current_employment"] = employment
    candidates, result, _ = extract([source], [item], criteria("VP"))
    assert candidates[0].employment_verified
    assert candidates[0].employment_status == "current"
    assert len(result.people) == 1 and result.review == []


def test_clean_role_headline_fallback_does_not_override_explicit_past_employment_text():
    source, item = headline_evidence(
        "Jordan Example - VP Engineering AI/ML @Example - LinkedIn",
        snippet="Former VP Engineering AI/ML at Example.",
    )
    candidates, result, _ = extract([source], [item], criteria("VP"))
    assert not candidates[0].employment_verified
    assert result.people == [] and len(result.review) == 1
