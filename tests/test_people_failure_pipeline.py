import json

import pytest

from company_gtm_enricher.people.live import LiveSearchPeopleProvider, build_search_queries
from company_gtm_enricher.people.models import CompanyTarget, PeopleCriteria
from company_gtm_enricher.people.providers import FatalProviderError
from company_gtm_enricher.people.search import SearchHit
from company_gtm_enricher.people.service import PeopleService


def test_explicit_alias_is_quoted_in_existing_query_budget():
    queries = build_search_queries(CompanyTarget("Example", "example.org", aliases=("Old Example",)), PeopleCriteria())
    assert len(queries) == 2
    assert all('("Example" OR "example.org" OR "Old Example")' in query for query in queries)
    injected = build_search_queries(CompanyTarget("Example", aliases=('Old" site:evil.org',)), PeopleCriteria())
    assert all(query.count("site:") == 1 for query in injected)


@pytest.mark.parametrize("error,fatal,expected", [
    (RuntimeError("secret response: test-api-key"), False, "Role classification failed"),
    (RuntimeError("OpenAI classification request timed out; try again or increase the request timeout."), False, "timed out"),
    (FatalProviderError("OpenAI quota is exhausted; check account billing."), True, "quota is exhausted"),
    (ValueError("Role classification returned invalid JSON."), False, "Role classification failed"),
])
def test_classification_failure_retains_every_search_hit_and_charged_usage(error, fatal, expected):
    class Search:
        usage = {"search_requests": 0}

        def search(self, query):
            self.usage["search_requests"] += 1
            company = "Next" if '"Next"' in query else "Example"
            return [SearchHit("1", "https://www.linkedin.com/in/alex-example", f"Alex Example - {company}", "Raw evidence.")]

    class Classifier:
        usage = {"llm_requests": 0}

        def classify(self, company, criteria, hits):
            self.usage["llm_requests"] += 1
            raise error

    provider = LiveSearchPeopleProvider(Search(), Classifier(), max_queries_per_company=1)
    result = PeopleService(provider).run([CompanyTarget("Example", "example.org"), CompanyTarget("Next", "next.org")], PeopleCriteria())
    assert result.status == ("failed" if fatal else "completed_with_errors")
    assert len(result.review) == (1 if fatal else 2)
    assert all(row["Status"] == "processing_failed" for row in result.review)
    assert not result.people
    assert result.review[0]["Evidence Text"] == "Alex Example - Example\nRaw evidence."
    assert result.review[0]["LinkedIn URL"] == "https://www.linkedin.com/in/alex-example"
    assert result.review[0]["Observed At"]
    assert result.companies[0]["Status"] == "error"
    assert result.companies[0]["Review"] == 1
    assert expected in result.companies[0]["Notes"]
    assert result.companies[1]["Status"] == ("pending" if fatal else "error")
    assert result.usage == {"search_requests": 1 if fatal else 2, "llm_requests": 1 if fatal else 2}
    assert "test-api-key" not in json.dumps(result.__dict__)
