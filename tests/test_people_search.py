import io
import json
from urllib.error import HTTPError, URLError

import pytest

from company_gtm_enricher.people.live import LiveSearchPeopleProvider, build_search_queries
from company_gtm_enricher.people.models import Candidate, CompanyTarget, PeopleCriteria
from company_gtm_enricher.people.providers import DiscoveryFailure, FatalProviderError
from company_gtm_enricher.people.search import SERPER_ENDPOINT, SearchHit, SearchProviderError, SerperSearchClient


class Response(io.BytesIO):
    def __init__(self, payload, status=200):
        super().__init__(payload if isinstance(payload, bytes) else json.dumps(payload).encode())
        self.status = status


class Transport:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def __call__(self, request, timeout):
        self.calls.append((request, timeout))
        result = self.outcomes.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def http_error(status, message="upstream-secret"):
    return HTTPError(SERPER_ENDPOINT, status, message, {}, io.BytesIO(json.dumps({"message": message}).encode()))


def hit(index, url=None, snippet="Current founder at Acme."):
    return SearchHit(str(index), url or f"https://www.linkedin.com/in/person-{index}", f"Person {index} - Acme", snippet)


class Search:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.usage = {"search_requests": 0}
        self.queries = []

    def search(self, query):
        self.usage["search_requests"] += 1
        self.queries.append(query)
        result = self.outcomes.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class Classifier:
    model = "test-model"

    def __init__(self):
        self.calls = []
        self.usage = {"llm_requests": 0, "input_tokens": 0, "output_tokens": 0}

    def classify(self, company, criteria, hits):
        self.calls.append((company, criteria, hits))
        self.usage["llm_requests"] += 1
        self.usage["input_tokens"] += 42
        self.usage["output_tokens"] += 8
        return [Candidate("Person", "Founder", linkedin_url=entry.url, is_founder=True) for entry in hits]


def test_serper_request_uses_verified_contract_and_preserves_original_evidence():
    transport = Transport(Response({"organic": [{"title": "Name - CTO", "link": "https://www.linkedin.com/in/name?trk=foo", "snippet": "Original evidence."}], "credits": 1}))
    client = SerperSearchClient("test-key", opener=transport)
    results = client.search('site:linkedin.com/in/ "Acme"')
    request, timeout = transport.calls[0]
    assert request.full_url == SERPER_ENDPOINT
    assert request.get_method() == "POST"
    assert request.get_header("X-api-key") == "test-key"
    assert request.get_header("Content-type") == "application/json"
    assert json.loads(request.data) == {"q": 'site:linkedin.com/in/ "Acme"', "num": 10}
    assert timeout == 30
    assert results == [SearchHit("1", "https://www.linkedin.com/in/name?trk=foo", "Name - CTO", "Original evidence.")]
    assert client.usage == {"search_requests": 1, "search_credits": 1}


@pytest.mark.parametrize("first", [http_error(429), http_error(500), http_error(503), URLError("secret"), TimeoutError("secret")])
def test_transient_failures_retry_and_count_actual_requests(first):
    pauses = []
    transport = Transport(first, Response({"organic": []}))
    client = SerperSearchClient("test-key", opener=transport, sleeper=pauses.append)
    assert client.search("company") == []
    assert client.usage == {"search_requests": 2}
    assert len(transport.calls) == 2
    assert pauses == [0.25]


@pytest.mark.parametrize("failure", [http_error(401), http_error(402), http_error(403), http_error(429, "Not enough credits: test-key"), Response({"statusCode": 403, "message": "test-key"}), Response({"message": "Invalid API key: test-key"})])
def test_authentication_or_credit_failure_is_fatal_without_retry_or_secret_leak(failure):
    transport = Transport(failure)
    client = SerperSearchClient("test-key", opener=transport, sleeper=lambda _: pytest.fail("unexpected retry"))
    with pytest.raises(FatalProviderError) as error:
        client.search("company")
    assert "test-key" not in str(error.value)
    assert "upstream-secret" not in str(error.value)
    assert client.usage == {"search_requests": 1}


@pytest.mark.parametrize("failure", [http_error(400), http_error(302), Response(b"not json with test-key"), Response({}), Response({"organic": {}}), Response({"organic": [None]}), Response({"organic": [{"title": "Name", "link": None}]}), Response({"organic": [], "error": "test-key"}), RuntimeError("test-key")])
def test_invalid_responses_are_failure_not_empty_success_and_are_redacted(failure):
    client = SerperSearchClient("test-key", opener=Transport(failure))
    with pytest.raises(SearchProviderError) as error:
        client.search("company")
    assert "test-key" not in str(error.value)
    assert "upstream-secret" not in str(error.value)
    assert client.usage["search_requests"] == 1


def test_exhausted_retries_are_bounded_and_counted():
    transport = Transport(http_error(503), http_error(503))
    client = SerperSearchClient("test-key", opener=transport, sleeper=lambda _: None)
    with pytest.raises(SearchProviderError, match="bounded retries"):
        client.search("company")
    assert client.usage["search_requests"] == 2


def test_default_transport_refuses_redirects():
    client = SerperSearchClient("test-key")
    redirect = next(handler for handler in client._open.__self__.handlers if hasattr(handler, "redirect_request"))
    assert redirect.redirect_request(None, None, 302, "", {}, "https://example.com/") is None


def test_query_plan_keeps_founders_executives_and_exact_department_levels_separate():
    criteria = PeopleCriteria(departments=("Engineering", "AI"), leadership_levels=("Director", "VP"), ic_levels=("Staff", "Principal"))
    queries = build_search_queries(CompanyTarget("Acme", "acme.example"), criteria)
    assert len(queries) == 6
    assert all(query.startswith('site:linkedin.com/in/ ("Acme" OR "acme.example") ') for query in queries)
    assert queries[0].endswith('("founder" OR "co-founder")')
    assert '"CEO"' in queries[1]
    assert queries[2].endswith('"Engineering" ("Director" OR "VP")')
    assert queries[3].endswith('"Engineering" ("Staff" OR "Principal")')
    assert queries[4].endswith('"AI" ("Director" OR "VP")')
    assert queries[5].endswith('"AI" ("Staff" OR "Principal")')


def test_query_user_input_cannot_inject_search_operators():
    criteria = PeopleCriteria(False, False, ('AI" OR site:evil.example\n',), ('Director) -site:linkedin.com',))
    queries = build_search_queries(CompanyTarget('Acme" OR site:evil.example\n', 'evil.example" -site:linkedin.com'), criteria)
    assert len(queries) == 1
    assert queries[0].count("site:") == 1
    assert "\n" not in queries[0]
    assert queries[0].count('"') == 8


def test_empty_literal_identity_cannot_launch_an_unscoped_search():
    search = Search()
    with pytest.raises(ValueError, match="letters or numbers"):
        LiveSearchPeopleProvider(search, Classifier()).discover(CompanyTarget('"*"'), PeopleCriteria())
    assert not search.queries


def test_provider_deduplicates_profiles_preserves_evidence_and_does_not_fetch_linkedin():
    transport = Transport(Response({"organic": [
        {"title": "Alice - Acme", "link": "https://uk.linkedin.com/in/Alice?trk=123", "snippet": "First observation."},
        {"title": "Alice - Founder", "link": "https://www.linkedin.com/in/alice/", "snippet": "Second observation."},
        {"title": "Company", "link": "https://www.linkedin.com/company/acme/", "snippet": "Company page."},
        {"title": "Other site", "link": "https://linkedin.com.evil.example/in/alice", "snippet": "Not LinkedIn."},
    ]}))
    search = SerperSearchClient("test-key", opener=transport)
    classifier = Classifier()
    provider = LiveSearchPeopleProvider(search, classifier)
    criteria = PeopleCriteria(c_level=False)
    batch = provider.discover(CompanyTarget("Acme", "acme.example"), criteria)
    received = classifier.calls[0][2]
    assert len(received) == 1
    assert received[0].id == "hit-1"
    assert received[0].url == "https://www.linkedin.com/in/alice"
    assert "First observation." in received[0].snippet
    assert "Second observation." in received[0].snippet
    assert "Alice - Founder" in received[0].title
    assert len(transport.calls) == 1
    assert all(call[0].full_url == SERPER_ENDPOINT for call in transport.calls)
    assert batch.limited
    assert "not exhaustive" in batch.notes
    assert len(batch.candidates) == 1


def test_query_cap_discloses_omitted_groups_and_classifier_keeps_full_criteria():
    criteria = PeopleCriteria(departments=("AI", "Engineering"), leadership_levels=("Director",), ic_levels=("Staff",))
    classifier = Classifier()
    provider = LiveSearchPeopleProvider(Search([hit(1)], [hit(2)]), classifier, max_queries_per_company=2)
    company = CompanyTarget("Acme")
    batch = provider.discover(company, criteria)
    assert len(provider.search_client.queries) == 2
    assert classifier.calls[0][:2] == (company, criteria)
    assert len({entry.id for entry in classifier.calls[0][2]}) == 2
    assert "2/6 planned" in batch.notes
    assert "limits: 4" in batch.notes
    assert "domain was not supplied" in batch.notes
    assert batch.limited


def test_candidate_cap_limits_classification_without_skipping_selected_queries():
    search = Search([hit(1), hit(2), hit(3), hit(3)], [hit(4), hit(5)])
    classifier = Classifier()
    provider = LiveSearchPeopleProvider(search, classifier, max_candidates=2)
    batch = provider.discover(CompanyTarget("Acme"), PeopleCriteria())
    assert len(search.queries) == 2
    assert len(classifier.calls) == 1
    assert [entry.url for entry in classifier.calls[0][2]] == [hit(1).url, hit(4).url]
    assert "3 additional distinct profiles omitted" in batch.notes
    assert "Unsearched query groups" not in batch.notes


def test_default_query_budget_gives_later_departments_candidate_slots():
    criteria = PeopleCriteria(departments=("AI", "Product"), leadership_levels=("Director",))
    company = CompanyTarget("Acme", "acme.example")
    search = Search(
        [hit(index) for index in range(1, 9)],
        [hit(10), hit(11)], [hit(20), hit(21)], [hit(30), hit(31)],
    )
    classifier = Classifier()
    batch = LiveSearchPeopleProvider(search, classifier, max_candidates=4).discover(company, criteria)

    assert search.queries == build_search_queries(company, criteria)
    assert len(search.queries) == 4
    assert len(classifier.calls) == 1
    received = classifier.calls[0][2]
    assert [entry.url for entry in received] == [hit(index).url for index in (1, 10, 20, 30)]
    assert [entry.id for entry in received] == ["hit-1", "hit-2", "hit-3", "hit-4"]
    assert batch.usage["search_requests"] == 4 and batch.usage["llm_requests"] == 1
    assert "10 additional distinct profiles omitted" in batch.notes


def test_overlapping_groups_merge_all_evidence_and_skip_duplicates_fairly():
    shared = hit(1, snippet="First group evidence.")
    second = SearchHit("second-id", "https://uk.linkedin.com/in/PERSON-1/?trk=second",
                       "Person 1 - Chief Engineer", "Second group evidence.")
    third = SearchHit("third-id", shared.url, "Person 1 - AI Director", "Third group evidence.")
    criteria = PeopleCriteria(departments=("AI",), leadership_levels=("Director",))
    outcomes = [[shared, hit(2)], [second, second, hit(3)], [third, hit(4)]]
    received_runs = []
    for _ in range(2):
        search, classifier = Search(*outcomes), Classifier()
        batch = LiveSearchPeopleProvider(search, classifier, max_candidates=3).discover(CompanyTarget("Acme"), criteria)
        received = classifier.calls[0][2]
        received_runs.append(received)
        assert len(search.queries) == 3 and len(classifier.calls) == 1
        assert [entry.url for entry in received] == [hit(index).url for index in (1, 3, 4)]
        assert received[0].snippet.splitlines() == ["First group evidence.", "Second group evidence.", "Third group evidence."]
        assert received[0].title.splitlines() == [shared.title, second.title, third.title]
        assert "1 additional distinct profiles omitted" in batch.notes
    assert received_runs[0] == received_runs[1]
    assert [entry.id for entry in received_runs[0]] == ["hit-1", "hit-2", "hit-3"]


@pytest.mark.parametrize("cap,expected", [
    (1, [1]), (2, [1, 3]), (4, [1, 3, 5, 2]), (6, [1, 3, 5, 2, 4, 6]),
    (10, [1, 3, 5, 2, 4, 6]),
])
def test_round_robin_respects_exact_candidate_cap_with_fewer_or_more_groups(cap, expected):
    search, classifier = Search([hit(1), hit(2)], [hit(3), hit(4)], [hit(5), hit(6)]), Classifier()
    criteria = PeopleCriteria(departments=("AI",), leadership_levels=("Director",))
    batch = LiveSearchPeopleProvider(search, classifier, max_candidates=cap).discover(CompanyTarget("Acme"), criteria)
    assert len(search.queries) == 3 and len(classifier.calls) == 1
    assert [entry.url for entry in classifier.calls[0][2]] == [hit(index).url for index in expected]
    if cap <= 6:
        assert f"{6 - cap} additional distinct profiles omitted" in batch.notes
    else:
        assert "Candidate cap reached" not in batch.notes


def test_empty_and_exhausted_groups_return_unused_slots_to_remaining_group():
    search, classifier = Search([hit(1)], [], [hit(1), hit(2), hit(3), hit(4)]), Classifier()
    criteria = PeopleCriteria(departments=("AI",), leadership_levels=("Director",))
    LiveSearchPeopleProvider(search, classifier, max_candidates=4).discover(CompanyTarget("Acme"), criteria)
    assert len(search.queries) == 3
    assert [entry.url for entry in classifier.calls[0][2]] == [hit(index).url for index in (1, 2, 3, 4)]


def test_partial_failure_does_not_prevent_later_group_from_receiving_a_slot():
    search = Search([hit(1), hit(2)], SearchProviderError("safe failure"), [hit(3), hit(4)])
    classifier = Classifier()
    criteria = PeopleCriteria(departments=("AI",), leadership_levels=("Director",))
    batch = LiveSearchPeopleProvider(search, classifier, max_candidates=2).discover(CompanyTarget("Acme"), criteria)
    assert len(search.queries) == 3
    assert [entry.url for entry in classifier.calls[0][2]] == [hit(1).url, hit(3).url]
    assert "Search queries failed: 1" in batch.notes
    assert "2 additional distinct profiles omitted" in batch.notes
    assert batch.usage["search_requests"] == 3


def test_classification_failure_retains_fairly_selected_and_merged_search_evidence():
    class FailingClassifier(Classifier):
        def classify(self, company, criteria, hits):
            super().classify(company, criteria, hits)
            raise RuntimeError("unsafe upstream details")

    search = Search([hit(1), hit(2)], [hit(1, snippet="Later profile evidence."), hit(3)])
    classifier = FailingClassifier()
    provider = LiveSearchPeopleProvider(search, classifier, max_candidates=2)
    with pytest.raises(DiscoveryFailure) as error:
        provider.discover(CompanyTarget("Acme"), PeopleCriteria())
    batch = error.value.batch
    assert not error.value.fatal
    assert "unsafe" not in str(error.value)
    assert [candidate.linkedin_url for candidate in batch.candidates] == [hit(1).url, hit(3).url]
    assert "Later profile evidence." in batch.candidates[0].evidence_text
    assert all(not candidate.identity_verified and not candidate.employment_verified for candidate in batch.candidates)
    assert batch.usage["search_requests"] == 2 and batch.usage["llm_requests"] == 1


def test_partial_search_failure_retains_results_and_reports_usage_per_company():
    search = Search([hit(1)], SearchProviderError("safe failure"), [hit(2)], [])
    classifier = Classifier()
    provider = LiveSearchPeopleProvider(search, classifier)
    first = provider.discover(CompanyTarget("Acme"), PeopleCriteria())
    second = provider.discover(CompanyTarget("Beta"), PeopleCriteria())
    assert len(first.candidates) == 1
    assert "Search queries failed: 1" in first.notes
    assert first.usage == second.usage == {"search_requests": 2, "llm_requests": 1, "input_tokens": 42, "output_tokens": 8}
    assert provider.usage == {"search_requests": 4, "llm_requests": 2, "input_tokens": 84, "output_tokens": 16}
    assert provider.settings["classification_model"] == "test-model"


def test_complete_search_failure_raises_and_does_not_invoke_classifier():
    classifier = Classifier()
    provider = LiveSearchPeopleProvider(Search(SearchProviderError("safe"), SearchProviderError("safe")), classifier)
    with pytest.raises(SearchProviderError, match="All planned search requests failed"):
        provider.discover(CompanyTarget("Acme"), PeopleCriteria())
    assert not classifier.calls
    assert provider.usage["search_requests"] == 2


def test_fatal_failure_stops_search_even_after_partial_results():
    search = Search([hit(1), hit(2)], FatalProviderError("auth"), [hit(3)])
    classifier = Classifier()
    provider = LiveSearchPeopleProvider(search, classifier, max_candidates=1)
    criteria = PeopleCriteria(departments=("AI",), leadership_levels=("Director",))
    with pytest.raises(FatalProviderError):
        provider.discover(CompanyTarget("Acme"), criteria)
    assert provider.usage["search_requests"] == 2
    assert len(search.outcomes) == 1
    assert not classifier.calls


def test_empty_index_results_are_visible_without_an_llm_request():
    classifier = Classifier()
    provider = LiveSearchPeopleProvider(Search([]), classifier)
    batch = provider.discover(CompanyTarget("Acme"), PeopleCriteria(c_level=False))
    assert batch.candidates == []
    assert "not exhaustive" in batch.notes
    assert not classifier.calls


@pytest.mark.parametrize("kwargs", [{"max_queries_per_company": 0}, {"max_candidates": 0}, {"max_queries_per_company": True}, {"max_candidates": True}])
def test_invalid_live_limits_fail_before_network(kwargs):
    with pytest.raises(ValueError):
        LiveSearchPeopleProvider(Search(), Classifier(), **kwargs)


@pytest.mark.parametrize("kwargs", [{"max_retries": True}, {"max_retries": -1}, {"max_retries": 4}, {"timeout": 0}, {"timeout": True}])
def test_invalid_search_settings_fail_before_network(kwargs):
    with pytest.raises(ValueError):
        SerperSearchClient("test-key", **kwargs)
