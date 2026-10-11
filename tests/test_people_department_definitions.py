from dataclasses import asdict
import json
from types import SimpleNamespace

import pytest

from company_gtm_enricher.people.classification import OpenAIRoleClassifier
from company_gtm_enricher.people.live import LiveSearchPeopleProvider, build_search_queries
from company_gtm_enricher.people.models import CompanyTarget, PeopleCriteria
from company_gtm_enricher.people.role_options import department_definitions_for
from company_gtm_enricher.people.search import SearchHit
from company_gtm_enricher.people.service import PeopleService


def test_definitions_resolve_selected_presets_and_custom_overrides_without_mutating_input():
    overrides = {" PRODUCT ": "  Product management only.\nExclude marketing.  ",
                 " Customer Success ": "Retention and adoption.", "AI": ""}
    before = dict(overrides)
    actual = department_definitions_for(("product", "Customer Success", "AI"), overrides)
    assert actual == {"product": "Product management only.\nExclude marketing.",
                      "Customer Success": "Retention and adoption."}
    assert overrides == before
    assert department_definitions_for(("Unknown Function",)) == {}


def test_approved_product_scope_is_editable_data_and_blank_can_disable_it():
    definition = department_definitions_for(("Product",))["Product"]
    assert "Product Marketing" in definition and "Product Partnerships" in definition
    assert department_definitions_for(("Product",), {"Product": ""}) == {}
    assert department_definitions_for(()) == {}


@pytest.mark.parametrize("invalid", [
    [], "Product: marketing", None, {"": "x"}, {1: "x"}, {"Product": None},
    {"Product": ["marketing"]}, {"Product": "x", " product ": "y"},
    {"Unselected": {"nested": "x"}},
])
def test_invalid_definitions_fail_even_when_the_entry_is_not_selected(invalid):
    with pytest.raises(ValueError, match="[Dd]epartment definitions"):
        department_definitions_for(("Product",), invalid) if invalid is not None else PeopleCriteria(department_definitions=invalid)


def test_criteria_copies_definitions_and_uses_selected_label_spelling():
    definitions = {" product ": "  Broad product functions.  "}
    criteria = PeopleCriteria(departments=("Product",), department_definitions=definitions)
    definitions[" product "] = "Changed after construction."
    assert criteria.department_definitions == {"Product": "Broad product functions."}
    assert asdict(criteria)["department_definitions"] == criteria.department_definitions
    assert PeopleCriteria().department_definitions == {}
    with pytest.raises(ValueError, match="selected departments"):
        PeopleCriteria(department_definitions={"Product": "Not selected."})


class Search:
    def search(self, query):
        return [SearchHit("search-1", "https://www.linkedin.com/in/alex-example",
                          "Alex Example - Director of Product Marketing at Example",
                          "Director of Product Marketing at Example.")]


class Responses:
    def __init__(self, mapped_department):
        self.mapped_department = mapped_department
        self.calls = []
        self.responses = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        observation = {
            "source_id": "hit-1", "name": "Alex Example",
            "title": "Director of Product Marketing at Example",
            "department": self.mapped_department, "seniority": "Director", "role_type": "leadership",
            "current_employment": "current", "employment_quote": "Director of Product Marketing at Example.",
            "classification_notes": "Classification supplied by the offline fixture.",
            "is_founder": False, "is_c_level": False,
        }
        return SimpleNamespace(status="completed", output=[],
                               output_text=json.dumps({"observations": [observation]}))


@pytest.mark.parametrize("mapped_department", ["Product", "Marketing", ""])
def test_definition_guides_labels_without_suppressing_supported_title_and_profile(mapped_department):
    # This checks the integration boundary, not the model's ability to classify.
    definitions = {"Product": "Include Product Marketing and Product Partnerships."}
    criteria = PeopleCriteria(False, False, ("Product",), ("Director",), (), definitions)
    company = CompanyTarget("Example", "example.org")
    responses = Responses(mapped_department)
    result = PeopleService(LiveSearchPeopleProvider(Search(), OpenAIRoleClassifier(responses))).run([company], criteria)

    assert len(responses.calls) == 1
    payload = json.loads(responses.calls[0]["input"])
    assert payload["criteria"]["department_definitions"] == definitions
    assert result.run_settings["criteria"]["department_definitions"] == definitions
    assert len(result.people) == 1 and result.review == []
    row = result.people[0]
    assert row["Title"] == "Director of Product Marketing at Example"
    assert row["LinkedIn URL"] == "https://www.linkedin.com/in/alex-example"
    assert row["Department"] == mapped_department
    if mapped_department != "Product":
        assert "assess the original title" in row["Notes"].lower()
    # Search budget/query text depends on labels, not the explanatory paragraphs.
    assert build_search_queries(company, criteria) == build_search_queries(
        company, PeopleCriteria(False, False, ("Product",), ("Director",)))


def test_result_keeps_a_snapshot_of_the_used_definition():
    criteria = PeopleCriteria(False, False, ("Product",), ("Director",), (), {"Product": "Before run."})
    result = PeopleService(LiveSearchPeopleProvider(Search(), OpenAIRoleClassifier(Responses("Product")))).run(
        [CompanyTarget("Example", "example.org")], criteria)
    criteria.department_definitions["Product"] = "After run."
    assert result.run_settings["criteria"]["department_definitions"] == {"Product": "Before run."}


@pytest.mark.parametrize("changed", [{"Unselected": "Hidden guidance."}, {"Product": ["not text"]}])
def test_direct_classifier_revalidates_mutated_criteria_before_spending(changed):
    criteria = PeopleCriteria(departments=("Product",), department_definitions={"Product": "Initial."})
    criteria.department_definitions.update(changed)
    client = Responses("Product")
    with pytest.raises(ValueError, match="Department definitions"):
        OpenAIRoleClassifier(client).classify(CompanyTarget("Example", "example.org"), criteria, Search().search("unused"))
    assert client.calls == []


def test_one_criteria_snapshot_is_used_for_every_company_in_a_run():
    criteria = PeopleCriteria(departments=("Product",), department_definitions={"Product": "Initial."})
    observed = []

    class Provider:
        is_mock = False

        def discover(self, company, selected):
            observed.append(dict(selected.department_definitions))
            # Simulate edits made by the caller while this run is in progress.
            criteria.department_definitions["Product"] = "Edited during run."
            return []

    result = PeopleService(Provider()).run([CompanyTarget("First"), CompanyTarget("Second")], criteria)
    assert observed == [{"Product": "Initial."}, {"Product": "Initial."}]
    assert result.run_settings["criteria"]["department_definitions"] == {"Product": "Initial."}
