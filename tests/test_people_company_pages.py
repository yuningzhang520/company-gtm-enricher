import json
from dataclasses import replace

import pytest

from company_gtm_enricher.people.company_pages import CompanyFounderSource
from company_gtm_enricher.people.live import LiveSearchPeopleProvider, _add_company_founders
from company_gtm_enricher.people.models import Candidate, CompanyTarget, DiscoveryBatch, PeopleCriteria
from company_gtm_enricher.people.public_pages import FetchedPage, PageFetchError
from company_gtm_enricher.people.service import _validate_candidates


COMPANY = CompanyTarget("Example", "example.org")
PROFILE = "https://www.linkedin.com/in/alex-example"
JOB = "https://jobs.ashbyhq.com/Example/job-id"
FOUNDERS = f'<p>Our co-founders are<a href="{PROFILE}"> <u>Alex Example</u></a> and <a href="https://www.linkedin.com/in/blair-person">Blair Person</a>. Previously, Alex was CTO elsewhere.</p>'


class Pages:
    def __init__(self, outcomes):
        self.outcomes = outcomes
        self.usage = {"page_requests": 0}
        self.calls = []

    def fetch(self, url, **kwargs):
        self.calls.append((url, kwargs))
        self.usage["page_requests"] += 1
        outcome = self.outcomes[url]
        if isinstance(outcome, Exception):
            raise outcome
        return FetchedPage(url, outcome)


def job_html(description=FOUNDERS, **organization):
    return '<script type="application/ld+json">' + json.dumps({
        "@type": "JobPosting", "hiringOrganization": {"name": "Example", "sameAs": "https://example.org", **organization},
        "description": description,
    }) + "</script>"


def source_for_job(html=None):
    pages = Pages({
        "https://example.org/about": "<p>About Example</p>",
        "https://example.org/careers": f'<a href="{JOB}">Open role</a><a href="https://jobs.ashbyhq.com/Example/other">Other role</a>',
        JOB: job_html() if html is None else html,
    })
    return CompanyFounderSource(pages), pages


def test_direct_linked_founders_need_no_llm_and_preserve_source_statement():
    pages = Pages({"https://example.org/about": FOUNDERS})
    batch = CompanyFounderSource(pages).discover(COMPANY)
    assert [(c.name, c.title, c.linkedin_url) for c in batch.candidates] == [
        ("Alex Example", "Co-Founder", PROFILE),
        ("Blair Person", "Co-Founder", "https://www.linkedin.com/in/blair-person"),
    ]
    assert all(c.identity_verified and c.employment_verified and c.role_verified for c in batch.candidates)
    assert "Previously, Alex was CTO elsewhere" in batch.candidates[0].evidence_text
    assert batch.candidates[0].evidence_url == "https://example.org/about"
    assert batch.usage == {"page_requests": 1}
    assert len(pages.calls) == 1


def test_job_evidence_requires_official_link_and_matching_organization_metadata():
    source, pages = source_for_job()
    batch = source.discover(COMPANY)
    assert len(batch.candidates) == 2
    assert batch.usage == {"page_requests": 3}
    assert all(c.evidence_url == JOB for c in batch.candidates)
    assert all("https://example.org/careers -> " + JOB in c.notes for c in batch.candidates)
    assert [call[1]["max_requests"] for call in pages.calls] == [3, 2, 1]
    assert pages.calls[-1][1]["allowed_hosts"] == {"jobs.ashbyhq.com"}


@pytest.mark.parametrize("html", [
    job_html(name="Example Other"), job_html(sameAs="https://example.org.evil.test"),
    job_html(sameAs=""), FOUNDERS, '<script type="application/ld+json">not json</script>',
    '<script>document.write("' + FOUNDERS.replace('"', '\\"') + '")</script>',
])
def test_unrelated_or_unstructured_job_pages_cannot_supply_founders(html):
    source, _ = source_for_job(html)
    assert not source.discover(COMPANY).candidates


@pytest.mark.parametrize("html", [
    f'<p>Our former co-founders are <a href="{PROFILE}">Alex Example</a>.</p>',
    f'<p>Our customers include founder <a href="{PROFILE}">Alex Example</a>.</p>',
    f'<p>Our co-founders are Alex Example.</p><a href="{PROFILE}">Alex Example</a>',
    f'<p>Our co-founders are <a href="{PROFILE}">Alex Example</a> and CTO <a href="https://www.linkedin.com/in/blair-person">Blair Person</a>.</p>',
    '<p>Our co-founders are <a href="https://linkedin.com.evil.test/in/alex">Alex Example</a>.</p>',
    '<p>Our co-founders are <a href="https://www.linkedin.com/company/example">Example Company</a>.</p>',
])
def test_names_or_unrelated_profile_links_are_not_founder_evidence(html):
    pages = Pages({"https://example.org/about": html})
    assert not CompanyFounderSource(pages, max_pages=1).discover(COMPANY).candidates


@pytest.mark.parametrize("html", [
    f'<blockquote><p>Our founders are <a href="{PROFILE}">Alex Example</a>.</p></blockquote>',
    f'<p><q>Our founders are <a href="{PROFILE}">Alex Example</a>.</q></p>',
    f'<p>Our founders are <q>definitely not</q> <a href="{PROFILE}">Alex Example</a>.</p>',
    f'<blockquote><q><p>Our founders are <a href="{PROFILE}">Alex Example</a>.</p></q></blockquote>',
])
def test_quoted_statements_do_not_establish_the_target_company_founders(html):
    pages = Pages({"https://example.org/about": html})
    assert not CompanyFounderSource(pages, max_pages=1).discover(COMPANY).candidates


def test_plain_separately_linked_names_after_a_quote_remain_supported():
    html = f'<blockquote><p>Our founder is <a href="{PROFILE}">Customer Founder</a>.</p></blockquote>' + FOUNDERS
    pages = Pages({"https://example.org/about": html})
    candidates = CompanyFounderSource(pages, max_pages=1).discover(COMPANY).candidates
    assert [(candidate.name, candidate.linkedin_url) for candidate in candidates] == [
        ("Alex Example", PROFILE),
        ("Blair Person", "https://www.linkedin.com/in/blair-person"),
    ]


@pytest.mark.parametrize("separator", ["and", "OR", "and/or", "&amp;", ",", "/", "+"])
def test_one_profile_link_cannot_identify_multiple_people(separator):
    html = f'<p>Our founders are <a href="{PROFILE}">Alex Example {separator} Jordan Example</a>.</p>'
    pages = Pages({"https://example.org/about": html})
    assert not CompanyFounderSource(pages, max_pages=1).discover(COMPANY).candidates


def test_failures_and_page_limit_do_not_launch_unbounded_followups():
    source, pages = source_for_job()
    source.max_pages = 2
    assert not source.discover(COMPANY).candidates
    assert len(pages.calls) == 2
    pages = Pages({"https://example.org/about": PageFetchError("safe failure"), "https://example.org/careers": ""})
    result = CompanyFounderSource(pages).discover(COMPANY)
    assert "page failures: 1" in result.notes
    assert not CompanyFounderSource(pages).discover(CompanyTarget("No domain")).candidates
    assert len(pages.calls) == 2


def founder():
    # A source used for final admission must name the company independently of
    # Alex Example's surname; its source URL alone does not satisfy that gate.
    html = FOUNDERS.replace("Previously,", "Example builds developer tools. Previously,")
    return CompanyFounderSource(Pages({"https://example.org/about": html}), max_pages=1).discover(COMPANY).candidates[0]


def test_explicit_profile_link_resolves_blank_review_without_duplicate_or_lost_evidence():
    weak = Candidate("", "", linkedin_url=PROFILE, evidence_text="Original indexed snippet.", review_reason="Unknown role.")
    merged, omitted = _add_company_founders([weak], [founder()], 1)
    assert omitted == 0 and len(merged) == 1
    people, review = _validate_candidates(merged, COMPANY, PeopleCriteria(), False)
    assert not review and people[0]["Name"] == "Alex Example"
    assert "Original indexed snippet" in people[0]["Evidence Text"]


def test_different_full_name_on_same_profile_stays_review_instead_of_overwritten():
    existing = Candidate("Wrong Person", "CEO", linkedin_url=PROFILE, is_c_level=True,
                         evidence_text="Wrong Person is CEO at Example.")
    merged, _ = _add_company_founders([existing], [founder()], 1)
    people, review = _validate_candidates(merged, COMPANY, PeopleCriteria(), False)
    assert not people and len(review) == 2
    assert all("conflicting names" in row["Review Reason"] for row in review)


def test_supported_executive_role_is_preserved_when_founder_source_adds_another_role():
    existing = Candidate("Alex Example", "CTO", linkedin_url=PROFILE, is_c_level=True,
                         identity_verified=True, employment_verified=True, role_verified=True,
                         evidence_url=PROFILE, evidence_text="Alex Example is CTO at Example.")
    merged, _ = _add_company_founders([existing], [founder()], 1)
    assert merged[0].title == "CTO; Co-Founder"
    assert merged[0].is_founder and merged[0].is_c_level


def test_new_company_profile_respects_candidate_cap():
    existing = Candidate("Other Person", "CEO", linkedin_url="https://www.linkedin.com/in/other-person")
    merged, omitted = _add_company_founders([existing], [founder()], 1)
    assert merged == [existing] and omitted == 1


def test_conflicting_names_use_one_profile_slot_and_do_not_hide_another_founder():
    first = founder()
    conflict = replace(first, name="Different Person")
    second = replace(first, name="Blair Person", linkedin_url="https://www.linkedin.com/in/blair-person")
    merged, omitted = _add_company_founders([first], [conflict, second], 2)
    assert omitted == 0 and len({item.linkedin_url for item in merged}) == 2
    people, review = _validate_candidates(merged, COMPANY, PeopleCriteria(), False)
    assert [row["Name"] for row in people] == ["Blair Person"]
    assert len(review) == 2 and all("conflicting names" in row["Review Reason"] for row in review)


def test_optional_company_source_is_skipped_when_founders_are_not_selected():
    class Search:
        def search(self, query):
            return []
    class Classifier:
        def classify(self, *args):
            pytest.fail("No search profiles to classify")
    class Source:
        max_pages = 3
        def discover(self, *args):
            pytest.fail("Founders were not requested")
    provider = LiveSearchPeopleProvider(Search(), Classifier(), company_pages=Source())
    assert not provider.discover(COMPANY, PeopleCriteria(founders=False, c_level=True)).candidates


def test_company_pages_can_fill_empty_search_results_without_an_llm_call():
    class Search:
        def search(self, query):
            return []
    class Classifier:
        def classify(self, *args):
            pytest.fail("No LLM call required")
    source = CompanyFounderSource(Pages({"https://example.org/about": FOUNDERS}))
    provider = LiveSearchPeopleProvider(Search(), Classifier(), company_pages=source)
    batch = provider.discover(COMPANY, PeopleCriteria())
    assert len(batch.candidates) == 2 and batch.usage == {"page_requests": 1}
    assert provider.settings["company_page_request_limit"] == 3
