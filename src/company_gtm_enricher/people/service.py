from __future__ import annotations

import re
import time
from copy import deepcopy
from dataclasses import asdict, replace
from typing import Callable, Optional, Sequence
from urllib.parse import urlsplit

import pandas as pd

from company_gtm_enricher.people.models import Candidate, CompanyTarget, DiscoveryBatch, PeopleCriteria, PeopleResult
from company_gtm_enricher.people.providers import DiscoveryFailure, FatalProviderError, PeopleProvider
# Keep the existing service imports available to callers and saved-run tooling.
from company_gtm_enricher.people.identity import (
    canonical_linkedin_url as canonical_linkedin_url,
    has_company_mention as has_company_mention,
)

StateCallback = Callable[[], bool]
UpdateCallback = Callable[[PeopleResult, int, int, str], None]
MOCK_NOTICE = "Synthetic demo only; no research performed."


def _text(value: object) -> str:
    return "" if pd.isna(value) else " ".join(str(value).split())


def _domain(value: str) -> str:
    if not value:
        return ""
    parsed = urlsplit(value if "://" in value else "https://" + value)
    host = (parsed.hostname or "").casefold().rstrip(".")
    if parsed.scheme not in ("http", "https") or parsed.username or parsed.password or not host or " " in host:
        raise ValueError(f"Invalid company domain: {value}")
    return host.removeprefix("www.")


def _tags(*values: str) -> str:
    unique = {}
    for value in values:
        for tag in re.split(r"[;,|]", value):
            tag = tag.strip()
            if tag:
                unique.setdefault(tag.casefold(), tag)
    return "; ".join(unique.values())


def read_companies(
    dataframe: pd.DataFrame,
    company_column: str,
    domain_column: Optional[str] = None,
    lists_column: Optional[str] = None,
    aliases_column: Optional[str] = None,
) -> list[CompanyTarget]:
    """Merge duplicate identities, tags, and aliases; preserve blank rows for visible skipping."""
    for column in (company_column, domain_column, lists_column, aliases_column):
        if column is not None and column not in dataframe.columns:
            raise ValueError(f"Column `{column}` does not exist in the uploaded CSV.")
    targets = []
    indexes = {}
    for _, row in dataframe.iterrows():
        name = _text(row[company_column])
        domain = _domain(_text(row[domain_column])) if domain_column and name else ""
        tags = _tags(_text(row[lists_column])) if lists_column else ""
        aliases = tuple(re.split(r"[;|]", _text(row[aliases_column]))) if aliases_column and name else ()
        if not name:
            targets.append(CompanyTarget(name="", lists=tags))
            continue
        key = (name.casefold(), domain)
        if key in indexes:
            index = indexes[key]
            targets[index] = replace(
                targets[index], lists=_tags(targets[index].lists, tags),
                aliases=targets[index].aliases + aliases,
            )
        else:
            indexes[key] = len(targets)
            targets.append(CompanyTarget(name, domain, tags, aliases))
    if not indexes:
        raise ValueError("The CSV must contain at least one nonblank company name.")
    return targets


def _valid_evidence_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        return bool(parsed.scheme in ("https", "http") and parsed.hostname and not parsed.username and not parsed.password)
    except ValueError:
        return False


def _discarded_company_note(candidates: Sequence[Candidate], company: CompanyTarget, is_mock: bool) -> str:
    count = 0 if is_mock else sum(
        not has_company_mention(candidate.evidence_text, company, person_name=candidate.name)
        for candidate in candidates
    )
    return f"Discarded {count} candidates with no target-company mention in evidence text." if count else ""


def _matches(candidate: Candidate, criteria: PeopleCriteria) -> Optional[bool]:
    """Describe suggested-label agreement, not evidence or department eligibility."""
    if (candidate.is_founder and criteria.founders) or (candidate.is_c_level and criteria.c_level):
        return True
    role_type = candidate.role_type.strip().casefold()
    if role_type in ("leadership", "ic") and candidate.department and candidate.seniority:
        levels = criteria.leadership_levels if role_type == "leadership" else criteria.ic_levels
        return candidate.department.strip().casefold() in {v.casefold() for v in criteria.departments} and candidate.seniority.strip().casefold() in {v.casefold() for v in levels}
    if candidate.is_founder or candidate.is_c_level:
        return False
    return None


def _candidate_row(candidate: Candidate, company: CompanyTarget, is_mock: bool) -> dict:
    employment_unconfirmed = not candidate.employment_verified and candidate.employment_status == "uncertain"
    employment_notice = (
        "Current employment at the target company is unconfirmed; no independent verification was performed."
        if employment_unconfirmed and not is_mock else ""
    )
    return {
        "Company": company.name,
        "List Tags": company.lists,
        "Name": candidate.name.strip(),
        "Title": candidate.title.strip(),
        "LinkedIn URL": canonical_linkedin_url(candidate.linkedin_url),
        "Department": candidate.department,
        "Seniority": candidate.seniority,
        "Status": "mock" if is_mock else "employment_unconfirmed" if employment_unconfirmed else "supported",
        "Evidence URL": candidate.evidence_url,
        "Notes": "; ".join(filter(None, (
            MOCK_NOTICE if is_mock else "", candidate.notes, candidate.employment_note, employment_notice,
        ))),
        "Domain": company.domain,
        "Evidence Text": candidate.evidence_text,
        "Observed At": candidate.observed_at,
    }


def _validate_candidates(candidates: Sequence[Candidate], company: CompanyTarget, criteria: PeopleCriteria, is_mock: bool) -> tuple[list[dict], list[dict]]:
    people, review = [], []
    department_search = bool(criteria.departments and (criteria.leadership_levels or criteria.ic_levels))
    profile_names = {}
    retained = []
    for candidate in candidates:
        if not isinstance(candidate, Candidate):
            raise TypeError("People provider must return Candidate records.")
        if not is_mock and not has_company_mention(candidate.evidence_text, company, person_name=candidate.name):
            continue
        retained.append(candidate)
        url = canonical_linkedin_url(candidate.linkedin_url)
        if url:
            profile_names.setdefault(url, set()).add(" ".join(candidate.name.split()).casefold())
    seen_profiles = {}
    for candidate in retained:
        matches = _matches(candidate, criteria)
        allow_missing_title = not is_mock and department_search and not candidate.title.strip()
        if (not department_search and matches is False and not candidate.review_reason
                and candidate.employment_status not in ("former", "conflict")):
            continue
        row = _candidate_row(candidate, company, is_mock)
        url = row["LinkedIn URL"]
        reasons = [candidate.review_reason] if candidate.review_reason else []
        if department_search and matches is not True:
            assessment = "no job title is available for personalization." if allow_missing_title else "assess the original title."
            advisory = (
                "Suggested role labels are incomplete or uncertain; " + assessment
                if matches is None else
                "Suggested role labels differ from the search preferences; this may be an adjacent role. " + assessment.capitalize()
            )
            row["Notes"] = "; ".join(filter(None, (row["Notes"], advisory)))
        elif matches is None:
            reasons.append("A selected founder or C-level role has not been established.")
        if not candidate.name.strip() or (not candidate.title.strip() and not allow_missing_title):
            reasons.append("Name or title is missing.")
        if url and len(profile_names[url]) > 1:
            reasons.append("The same LinkedIn profile is associated with conflicting names.")
        if not is_mock:
            if not url:
                reasons.append("A valid LinkedIn personal profile URL is missing.")
            if not _valid_evidence_url(candidate.evidence_url):
                reasons.append("Supporting evidence URL is missing or invalid.")
            if not candidate.identity_verified:
                reasons.append("Profile identity has not been verified.")
            if candidate.employment_status == "former":
                reasons.append("Evidence describes former employment at the target company.")
            elif candidate.employment_status == "conflict":
                reasons.append("Employment evidence conflicts with the target-company association.")
            elif candidate.employment_status not in ("current", "uncertain"):
                reasons.append("Employment evidence status is invalid.")
            elif not candidate.employment_verified and candidate.employment_status != "uncertain":
                reasons.append("Current employment has not been verified.")
            if not candidate.role_verified and not allow_missing_title:
                reasons.append("Role has not been verified.")
        if reasons:
            row["Status"] = "mock_review" if is_mock else "needs_review"
            row["Review Reason"] = " ".join(reasons)
            review.append(row)
        else:
            if allow_missing_title:
                row["Status"] = "title_missing"
                row["Notes"] = "; ".join(filter(None, (
                    row["Notes"], "The original title is unavailable; Title is blank. Use a general introduction without assuming a role.",
                )))
            if not url or url not in seen_profiles:
                if url:
                    seen_profiles[url] = len(people)
                people.append(row)
            elif people[seen_profiles[url]]["Status"] == "title_missing" and row["Title"]:
                people[seen_profiles[url]] = row
    return people, review


class PeopleService:
    def __init__(self, provider: PeopleProvider) -> None:
        self.provider = provider

    def run(
        self,
        companies: Sequence[CompanyTarget],
        criteria: PeopleCriteria,
        should_pause: Optional[StateCallback] = None,
        should_stop: Optional[StateCallback] = None,
        on_update: Optional[UpdateCallback] = None,
    ) -> PeopleResult:
        # Hold one validated snapshot for both model calls and exported settings.
        criteria = replace(criteria)
        if not any(company.name.strip() for company in companies):
            raise ValueError("At least one nonblank company is required.")
        started = time.monotonic()
        result = PeopleResult(is_mock=self.provider.is_mock, status="running")
        result.run_settings = {
            **getattr(self.provider, "settings", {}),
            "provider": type(self.provider).__name__, "criteria": asdict(criteria),
            "companies": [asdict(company) for company in companies],
            "candidate_policy": (
                "Evidence-supported search results; department and seniority labels are advisory, and adjacent roles may appear."
                " Grounded identities with missing titles may remain as title_missing, with a blank Title and employment uncertainty in Notes."
                if criteria.departments and (criteria.leadership_levels or criteria.ic_levels) else
                "Selected founder/C-level categories with supporting evidence."
            ) + " Current employment uncertainty is retained as employment_unconfirmed; former or conflicting affiliations require review."
            " Live candidates without a company-name, domain, or supplied-alias mention in evidence text are discarded from People and Review."
            " Occurrences only inside the person's full name do not count as company evidence.",
        }
        initial_usage = dict(getattr(self.provider, "usage", {}))
        for company in companies:
            result.companies.append({
                "Company": company.name, "Domain": company.domain, "List Tags": company.lists,
                "Status": "pending" if company.name else "skipped_empty", "People": 0, "Review": 0,
                "Notes": "This company has not been processed yet." if company.name else "The company name cell was blank.",
            })

        def update(processed: int, company_name: str) -> None:
            result.elapsed_seconds = time.monotonic() - started
            result.usage = {
                key: value - initial_usage.get(key, 0)
                for key, value in getattr(self.provider, "usage", {}).items()
            }
            if on_update is not None:
                on_update(deepcopy(result), processed, len(companies), company_name)

        def stopped() -> bool:
            return should_stop is not None and should_stop()

        update(0, "")
        processed = 0
        has_errors = False
        for index, company in enumerate(companies):
            while should_pause is not None and should_pause() and not stopped():
                time.sleep(0.05)
            if stopped():
                result.status = "stopped"
                update(processed, "")
                return result
            row = result.companies[index]
            if company.name:
                update(processed, company.name)
                result.provider_calls += 1
                try:
                    discovery = self.provider.discover(company, criteria)
                    batch = discovery if isinstance(discovery, DiscoveryBatch) else DiscoveryBatch(list(discovery))
                    candidates = list(batch.candidates)
                    people, review = _validate_candidates(candidates, company, criteria, result.is_mock)
                    result.people.extend(people)
                    result.review.extend(review)
                    notes = MOCK_NOTICE if result.is_mock else "Discovery finished; completeness is not established."
                    row.update({
                        "Status": "mock" if result.is_mock else ("partial" if batch.limited else "processed"),
                        "People": len(people), "Review": len(review),
                        "Notes": "; ".join(filter(None, (
                            notes, batch.notes, _discarded_company_note(candidates, company, result.is_mock),
                        ))),
                    })
                except DiscoveryFailure as exc:
                    # A failed discovery cannot promote partially classified records,
                    # but paid-for source evidence should remain available for review.
                    candidates = [
                        replace(candidate, review_reason=" ".join(filter(None, (
                            candidate.review_reason,
                            "Discovery did not complete; candidate requires review.",
                        ))))
                        for candidate in exc.batch.candidates
                    ]
                    _, review = _validate_candidates(candidates, company, criteria, result.is_mock)
                    for candidate_row in review:
                        candidate_row["Status"] = "processing_failed"
                        candidate_row["Notes"] = "; ".join(filter(None, (
                            candidate_row["Notes"],
                            "Processing failed before discovery completed; source evidence is retained for retry.",
                        )))
                    result.review.extend(review)
                    row.update({
                        "Status": "error", "Review": len(review),
                        "Notes": "; ".join(filter(None, (
                            str(exc), exc.batch.notes, _discarded_company_note(candidates, company, result.is_mock),
                        ))),
                    })
                    if exc.fatal:
                        result.status = "failed"
                        update(processed + 1, "")
                        return result
                    has_errors = True
                except FatalProviderError as exc:
                    row.update({"Status": "error", "Notes": str(exc)})
                    result.status = "failed"
                    update(processed + 1, "")
                    return result
                except Exception as exc:
                    has_errors = True
                    row.update({"Status": "error", "Notes": f"{type(exc).__name__}: {exc}"})
            processed += 1
            update(processed, company.name)
        result.status = "completed_with_errors" if has_errors else "completed"
        update(processed, "")
        return result
