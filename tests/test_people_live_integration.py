import json
from io import BytesIO
from types import SimpleNamespace
from urllib.error import HTTPError

from openpyxl import load_workbook

from company_gtm_enricher.people.classification import OpenAIRoleClassifier
from company_gtm_enricher.people.excel_export import excel_bytes
from company_gtm_enricher.people.live import LiveSearchPeopleProvider
from company_gtm_enricher.people.models import CompanyTarget, PeopleCriteria
from company_gtm_enricher.people.search import SERPER_ENDPOINT, SerperSearchClient
from company_gtm_enricher.people.service import PeopleService


def offline_pipeline():
    calls = []
    source_rows = [
        ("Alex Example", "Director of ML Platform", "alex-example"),
        ("Blair Example", "VP of ML Platform", "blair-example"),
        ("Unknown", "Unclear role", "unclear-example"),
    ]
    organic = [
        {"title": f"{name} - {title} at Example", "link": f"https://uk.linkedin.com/in/{slug}/?trk=test",
         "snippet": f"{name} is {title} at Example (example.org)."}
        for name, title, slug in source_rows
    ]

    def opener(request, timeout):
        calls.append(request.full_url)
        assert request.full_url == SERPER_ENDPOINT
        if len(calls) > 1:
            raise HTTPError(SERPER_ENDPOINT, 403, "secret must not leak", {}, BytesIO())
        response = BytesIO(json.dumps({"organic": organic}).encode())
        response.status = 200
        return response

    class Responses:
        def create(self, **kwargs):
            payload = json.loads(kwargs["input"])
            assert payload["criteria"]["leadership_levels"] == ["Director"]
            items = []
            for index, (name, title, slug) in enumerate(source_rows[:2], 1):
                items.append({
                    "source_id": f"hit-{index}", "name": name, "title": title,
                    "department": "Infrastructure", "seniority": "Director" if index == 1 else "VP",
                    "role_type": "leadership", "is_founder": False, "is_c_level": False,
                    "current_employment": "current", "employment_quote": organic[index - 1]["snippet"],
                    "classification_notes": "Platform maps to Infrastructure.",
                })
            return SimpleNamespace(
                status="completed", output=[], output_text=json.dumps({"observations": items}),
                usage=SimpleNamespace(input_tokens=600, output_tokens=160),
            )

    provider = LiveSearchPeopleProvider(
        SerperSearchClient("test-key", opener=opener),
        OpenAIRoleClassifier(SimpleNamespace(responses=Responses())),
    )
    return provider, calls


def test_search_classification_filter_export_chain_and_fatal_stop():
    provider, calls = offline_pipeline()
    result = PeopleService(provider).run(
        [CompanyTarget("Example", "example.org"), CompanyTarget("Account failure", "second.example"), CompanyTarget("Pending", "third.example")],
        PeopleCriteria(founders=False, c_level=False, departments=("Infrastructure",), leadership_levels=("Director",)),
    )
    assert result.status == "failed"
    assert len(result.people) == 2  # Source-supported VP remains as an adjacent search result.
    assert result.people[0]["Name"] == "Alex Example"
    assert result.people[0]["Status"] == "supported"
    assert result.people[0]["LinkedIn URL"] == "https://www.linkedin.com/in/alex-example"
    assert result.people[0]["Observed At"]
    assert "Director of ML Platform" in result.people[0]["Evidence Text"]
    assert result.people[1]["Title"] == "VP of ML Platform"
    assert "differ from the search preferences" in result.people[1]["Notes"]
    assert len(result.review) == 1  # Omitted model observation retains its search evidence.
    assert "did not extract" in result.review[0]["Review Reason"]
    assert [row["Status"] for row in result.companies] == ["partial", "error", "pending"]
    assert "secret" not in result.companies[1]["Notes"]
    assert calls == [SERPER_ENDPOINT, SERPER_ENDPOINT]
    assert result.usage == {"search_requests": 2, "llm_requests": 1, "input_tokens": 600, "output_tokens": 160}
    assert result.run_settings["criteria"]["leadership_levels"] == ("Director",)
    workbook = load_workbook(BytesIO(excel_bytes(result)))
    assert "failed" in workbook["People"]["A2"].value
    assert "input/output tokens: 600/160" in workbook["People"]["A3"].value
    assert workbook["People"]["E6"].hyperlink.target == result.people[0]["LinkedIn URL"]
    assert workbook["People"]["E7"].hyperlink.target == result.people[1]["LinkedIn URL"]
