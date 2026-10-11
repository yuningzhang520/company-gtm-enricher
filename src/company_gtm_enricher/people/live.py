from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime, timezone

from company_gtm_enricher.people.models import Candidate, CompanyTarget, DiscoveryBatch, PeopleCriteria
from company_gtm_enricher.people.providers import DiscoveryFailure, FatalProviderError
from company_gtm_enricher.people.search import SearchHit, SearchProviderError
from company_gtm_enricher.people.identity import canonical_linkedin_url


def _literal(value: str) -> str:
    # User input remains a quoted phrase; quotes, colons and other operators cannot escape it.
    cleaned = " ".join(re.sub(r"[^\w .-]", " ", value, flags=re.UNICODE).split())
    if not any(character.isalnum() for character in cleaned):
        raise ValueError("Company and role search labels must contain letters or numbers.")
    return '"' + cleaned + '"'


def build_search_queries(company: CompanyTarget, criteria: PeopleCriteria) -> list[str]:
    """Plan independently of budget, so omitted role groups can be reported."""
    identities = list(dict.fromkeys(_literal(value) for value in (company.name, company.domain, *company.aliases) if value))
    identity = identities[0] if len(identities) == 1 else "(" + " OR ".join(identities) + ")"
    prefix = "site:linkedin.com/in/ " + identity + " "
    queries = []
    if criteria.founders:
        queries.append(prefix + '("founder" OR "co-founder")')
    if criteria.c_level:
        queries.append(prefix + '("chief" OR "CEO" OR "CTO" OR "CFO" OR "COO" OR "CIO" OR "CMO" OR "CPO" OR "CRO" OR "CISO")')
    for department in criteria.departments:
        for levels in (criteria.leadership_levels, criteria.ic_levels):
            if levels:
                queries.append(prefix + _literal(department) + " (" + " OR ".join(_literal(level) for level in levels) + ")")
    return list(dict.fromkeys(queries))


def _add_company_founders(candidates: list[Candidate], founders, limit: int) -> tuple[list[Candidate], int]:
    """Cap unique profiles; retain conflicting-name observations for review."""
    candidates = list(candidates)
    omitted = 0
    for founder in founders:
        url = canonical_linkedin_url(founder.linkedin_url)
        indexes = [i for i, candidate in enumerate(candidates) if canonical_linkedin_url(candidate.linkedin_url) == url]
        names = {" ".join(candidates[i].name.split()).casefold() for i in indexes if candidates[i].name.strip()}
        if names and names != {" ".join(founder.name.split()).casefold()}:
            candidates.append(founder)  # The service reports the identity conflict.
            continue
        if indexes:
            previous = candidates[indexes[0]]
            previous_supported = all((previous.identity_verified, previous.employment_verified, previous.role_verified)) and not previous.review_reason
            if previous_supported:
                combined = replace(
                    previous, is_founder=True,
                    title=previous.title if previous.is_founder else f"{previous.title}; {founder.title}",
                    evidence_url=founder.evidence_url,
                )
            else:
                combined = founder
            combined = replace(
                combined,
                evidence_text=f"Company-published evidence:\n{founder.evidence_text}\n\nOriginal profile-index evidence:\n{previous.evidence_text}",
                notes="; ".join(filter(None, (founder.notes, previous.notes))),
            )
            candidates[indexes[0]] = combined
            for index in reversed(indexes[1:]):
                del candidates[index]
        elif len({canonical_linkedin_url(item.linkedin_url) for item in candidates}) < limit:
            candidates.append(founder)
        else:
            omitted += 1
    return candidates, omitted


class LiveSearchPeopleProvider:
    """Bounded index discovery followed by classification; service applies final filters."""

    is_mock = False

    def __init__(self, search_client, classifier, max_queries_per_company: int = 4, max_candidates: int = 40, company_pages=None) -> None:
        if type(max_queries_per_company) is not int or not 1 <= max_queries_per_company <= 50:
            raise ValueError("Queries per company must be between 1 and 50.")
        if type(max_candidates) is not int or not 1 <= max_candidates <= 200:
            raise ValueError("Candidate limit must be between 1 and 200.")
        self.search_client = search_client
        self.classifier = classifier
        self.max_queries_per_company = max_queries_per_company
        self.max_candidates = max_candidates
        self.company_pages = company_pages

    @property
    def settings(self) -> dict:
        settings = {
            "search_source": "Serper Google Search",
            "classification_model": getattr(self.classifier, "model", ""),
            "max_queries_per_company": self.max_queries_per_company,
            "max_candidates": self.max_candidates,
            "llm_max_retries": getattr(self.classifier, "max_retries", 0),
        }
        if self.company_pages is not None:
            settings.update(company_founder_pages=True, company_page_request_limit=self.company_pages.max_pages)
        return settings

    @property
    def usage(self) -> dict[str, int]:
        totals: dict[str, int] = {}
        for component in (self.search_client, self.classifier, self.company_pages):
            for key, value in getattr(component, "usage", {}).items():
                if type(value) is int and value >= 0:
                    totals[key] = totals.get(key, 0) + value
        return totals

    def discover(self, company: CompanyTarget, criteria: PeopleCriteria) -> DiscoveryBatch:
        criteria = replace(criteria)  # Validate direct callers before search spending.
        before = self.usage
        planned = build_search_queries(company, criteria)
        selected = planned[:self.max_queries_per_company]
        retrieved: dict[str, SearchHit] = {}
        query_groups: list[list[str]] = []
        failed = attempted = successful = 0
        for query in selected:
            attempted += 1
            try:
                results = self.search_client.search(query)
            except FatalProviderError:
                raise
            except SearchProviderError:
                failed += 1
                continue
            successful += 1
            group = {}
            for hit in results:
                url = canonical_linkedin_url(hit.url)
                if not url:
                    continue
                group[url] = None
                if url in retrieved:
                    previous = retrieved[url]
                    retrieved[url] = replace(
                        previous,
                        title="\n".join(dict.fromkeys((*previous.title.split("\n"), *hit.title.split("\n")))),
                        snippet="\n".join(dict.fromkeys((*previous.snippet.split("\n"), *hit.snippet.split("\n")))),
                    )
                else:
                    retrieved[url] = replace(hit, url=url)
            query_groups.append(list(group))
        if failed and not successful:
            raise SearchProviderError("All planned search requests failed; no discovery results are available.")
        # Finish the selected searches before allocating the classification budget.
        # Each group contributes its next unseen profile per round; shared profiles
        # keep every retrieved observation without consuming another group's turn.
        hits: dict[str, SearchHit] = {}
        groups = [iter(group) for group in query_groups]
        while len(hits) < self.max_candidates:
            added = False
            for group in groups:
                for url in group:
                    if url not in hits:
                        hits[url] = replace(retrieved[url], id=f"hit-{len(hits) + 1}")
                        added = True
                        break
                if len(hits) == self.max_candidates:
                    break
            if not added:
                break
        omitted_profiles = len(retrieved) - len(hits)
        omitted_queries = len(planned) - attempted
        notes = [
            "Search-index coverage is not exhaustive; results do not establish all qualifying employees.",
            f"Queries attempted: {attempted}/{len(planned)} planned; query cap: {self.max_queries_per_company}.",
            f"Unique profiles retained: {len(hits)}; candidate cap: {self.max_candidates}.",
            "Candidates are selected round-robin across successful query groups.",
        ]
        if omitted_queries:
            notes.append(f"Unsearched query groups due to configured limits: {omitted_queries}.")
        if len(hits) >= self.max_candidates:
            notes.append(f"Candidate cap reached; {omitted_profiles} additional distinct profiles omitted from returned search results.")
        if failed:
            notes.append(f"Search queries failed: {failed}; results from successful queries were retained.")
        if not company.domain:
            notes.append("Company domain was not supplied; company identity requires review.")
        try:
            candidates = self.classifier.classify(company, criteria, list(hits.values())) if hits else []
        except Exception as exc:
            observed_at = datetime.now(timezone.utc).isoformat()
            candidates = [Candidate(
                name="", title="", linkedin_url=hit.url, evidence_url=hit.url,
                evidence_text=hit.title + "\n" + hit.snippet, observed_at=observed_at,
                review_reason="Classification failed; the original search evidence is retained for review.",
            ) for hit in hits.values()]
            # The built-in classifier exposes credential-safe messages only. Suppress
            # arbitrary injected exceptions rather than exporting upstream bodies.
            safe_messages = (
                "OpenAI quota is exhausted; check account billing.",
                "OpenAI authentication or account access failed; check the API key and permissions.",
                "OpenAI rejected the model or request configuration; check the people model and API compatibility.",
                "OpenAI classification request timed out; try again or increase the request timeout.",
                "OpenAI classification could not connect; check the network connection and retry.",
            )
            message = str(exc) if str(exc) in safe_messages else "Role classification failed; retrieved evidence was retained for review."
            after = self.usage
            batch = DiscoveryBatch(
                candidates, notes=" ".join(notes), limited=True,
                usage={key: value - before.get(key, 0) for key, value in after.items()},
            )
            raise DiscoveryFailure(message, batch, fatal=isinstance(exc, FatalProviderError)) from None
        if self.company_pages is not None and criteria.founders:
            try:
                supplemental = self.company_pages.discover(company)
                candidates, omitted = _add_company_founders(candidates, supplemental.candidates, self.max_candidates)
                notes.append(supplemental.notes)
                if omitted:
                    notes.append(f"Additional company-linked profiles omitted by candidate cap: {omitted}.")
            except Exception:
                notes.append("Company founder page lookup failed; original search evidence was retained.")
        after = self.usage
        usage = {key: value - before.get(key, 0) for key, value in after.items()}
        return DiscoveryBatch(candidates=candidates, notes=" ".join(notes), limited=True, usage=usage)
