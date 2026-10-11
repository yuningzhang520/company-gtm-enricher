"""Optional, bounded founder evidence from explicit links published by a company."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
import re
from urllib.parse import urljoin, urlsplit

from .models import Candidate, CompanyTarget, DiscoveryBatch
from .public_pages import PageFetchError, PublicPageClient
from .identity import canonical_linkedin_url

# External job pages are followed only when linked directly from the company's
# own site, and their JobPosting metadata must identify that same company.
_JOB_HOSTS = {"jobs.ashbyhq.com", "boards.greenhouse.io", "job-boards.greenhouse.io", "jobs.lever.co"}


@dataclass(frozen=True)
class _Link:
    url: str
    label: str
    start: int
    end: int


class _PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks = []
        self.links = []
        self.structured = []
        self._block = None
        self._block_tag = ""
        self._block_links = []
        self._block_quoted = False
        self._anchor = None
        self._script = None
        self._ignored = 0
        self._quoted = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("blockquote", "q") and not self._ignored:
            # "Our" in a quoted customer statement does not identify this company.
            # Reject an enclosing block too, rather than joining text around a quote.
            self._block_quoted = self._block is not None or self._block_quoted
            self._quoted += 1
            return
        if self._quoted:
            return
        if tag == "script":
            self._script = [] if attrs.get("type", "").casefold() == "application/ld+json" else None
            self._ignored += 1
            return
        if tag == "style":
            self._ignored += 1
            return
        if self._ignored:
            return
        if tag in ("p", "li"):
            self._finish_block()
            self._block, self._block_links, self._block_tag = [], [], tag
        if tag == "a":
            self._anchor = [attrs.get("href", ""), [], len("".join(self._block or []))]

    def handle_data(self, data):
        if self._quoted:
            return
        if self._script is not None:
            self._script.append(data)
        if self._ignored:
            return
        if self._block is not None:
            self._block.append(data)
        if self._anchor is not None:
            self._anchor[1].append(data)

    def handle_endtag(self, tag):
        if tag in ("blockquote", "q"):
            self._quoted = max(0, self._quoted - 1)
            return
        if self._quoted:
            return
        if tag == "script":
            if self._script is not None:
                try:
                    self.structured.append(json.loads("".join(self._script)))
                except (ValueError, TypeError):
                    pass
            self._script = None
            self._ignored = max(0, self._ignored - 1)
            return
        if tag == "style":
            self._ignored = max(0, self._ignored - 1)
            return
        if self._ignored:
            return
        if tag == "a" and self._anchor is not None:
            url, text, start = self._anchor
            link = _Link(url, "".join(text).strip(), start, len("".join(self._block or [])))
            self.links.append(link)
            if self._block is not None:
                self._block_links.append(link)
            self._anchor = None
        if tag == self._block_tag:
            self._finish_block()

    def _finish_block(self):
        if self._block is not None and not self._block_quoted:
            self.blocks.append(("".join(self._block), self._block_links))
        self._block, self._block_links, self._block_tag = None, [], ""
        self._block_quoted = False

    def close(self):
        super().close()
        self._finish_block()


def _parse(html: str) -> _PageParser:
    parser = _PageParser()
    parser.feed(html)
    parser.close()
    return parser


def _host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").casefold().rstrip(".")
    except ValueError:
        return ""


def _job_descriptions(value, company: CompanyTarget):
    if isinstance(value, list):
        for item in value:
            yield from _job_descriptions(item, company)
    elif isinstance(value, dict):
        yield from _job_descriptions(value.get("@graph", []), company)
        organization = value.get("hiringOrganization", {})
        if not isinstance(organization, dict):
            return
        same_as = organization.get("sameAs", "")
        name = organization.get("name", "")
        description = value.get("description")
        if (value.get("@type") == "JobPosting" and isinstance(same_as, str)
                and isinstance(name, str) and name.casefold() in {company.name.casefold(), *(alias.casefold() for alias in company.aliases)}
                and _host(same_as).removeprefix("www.") == company.domain.removeprefix("www.")
                and isinstance(description, str)):
            yield description


def _linked_founders(parser: _PageParser, company: CompanyTarget, source_url: str, provenance: str):
    for text, links in parser.blocks:
        intro = re.match(r"\s*Our\s+(co[- ]?founders?|founders?)\s+(?:are|is)\b", text, re.IGNORECASE)
        if not intro:
            continue
        end = re.search(r"[.!?](?:\s|$)", text[intro.end():])
        stop = intro.end() + end.start() if end else len(text)
        named = [link for link in links if link.start >= intro.end() and link.end <= stop]
        if not named:
            continue
        # Only a list of explicitly linked names can follow the founder label.
        # Other role clauses, unlinked names, and unrelated links stay unsupported.
        remainder = text[intro.end():stop]
        valid = True
        for link in reversed(named):
            if (not canonical_linkedin_url(link.url)
                    or re.search(r"\b(?:and|or)\b|[&,/;|+]", link.label, re.IGNORECASE)
                    or not re.fullmatch(r"[^\W\d_][\w.'’ -]+\s+[^\W\d_][\w.'’ -]+", link.label, re.UNICODE)):
                valid = False
                break
            remainder = remainder[:link.start - intro.end()] + remainder[link.end - intro.end():]
        if not valid or not re.fullmatch(r"(?:\s|,|&|\band\b)*", remainder, re.IGNORECASE):
            continue
        title = "Co-Founder" if intro.group(1).casefold().startswith("co") else "Founder"
        for link in named:
            yield Candidate(
                name=link.label, title=title, linkedin_url=canonical_linkedin_url(link.url),
                is_founder=True, seniority="Founder", role_type="leadership",
                identity_verified=True, employment_verified=True, role_verified=True,
                evidence_url=source_url, evidence_text=text,
                observed_at=datetime.now(timezone.utc).isoformat(),
                notes=f"Company-published founder statement explicitly links this person's name to the profile. {provenance} Published evidence may be stale; no LinkedIn page was fetched.",
            )


class CompanyFounderSource:
    """Read at most three public pages; no paid search, LLM, or LinkedIn requests."""

    def __init__(self, client: PublicPageClient, max_pages: int = 3):
        if type(max_pages) is not int or not 1 <= max_pages <= 3:
            raise ValueError("Company founder evidence is limited to 1–3 page requests.")
        self.client, self.max_pages = client, max_pages

    @property
    def usage(self):
        return self.client.usage

    def discover(self, company: CompanyTarget) -> DiscoveryBatch:
        if not company.domain:
            return DiscoveryBatch([], notes="Company founder pages skipped: a company domain is required.", limited=True)
        before = self.usage.get("page_requests", 0)
        domain = company.domain.removeprefix("www.")
        own_hosts = {domain, "www." + domain}
        queue = [(f"https://{domain}/about", ""), (f"https://{domain}/careers", "")]
        visited, candidates = set(), []
        failures = 0
        while queue and self.usage.get("page_requests", 0) - before < self.max_pages:
            url, parent = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)
            try:
                page = self.client.fetch(url, allowed_hosts={_host(url)} if parent else own_hosts,
                                         max_requests=self.max_pages - (self.usage.get("page_requests", 0) - before))
            except PageFetchError:
                failures += 1
                continue
            parser = _parse(page.html)
            if not parent:
                candidates.extend(_linked_founders(parser, company, page.url, f"Company source: {page.url}."))
                for link in parser.links:
                    target = urljoin(page.url, link.url)
                    if _host(target) in _JOB_HOSTS:
                        queue.append((target, page.url))
                        break  # One linked public job page, never an entire job board.
            else:
                for data in parser.structured:
                    for description in _job_descriptions(data, company):
                        candidates.extend(_linked_founders(
                            _parse(description), company, page.url,
                            f"Company source chain: {parent} -> {page.url}; JobPosting hiringOrganization matches {company.name} and {company.domain}.",
                        ))
            if candidates:
                break
        count = self.usage.get("page_requests", 0) - before
        return DiscoveryBatch(candidates, notes=f"Company founder page requests: {count}/{self.max_pages}; linked founder records: {len(candidates)}; page failures: {failures}. Only explicit founder links are supported; coverage is partial.", limited=True,
                              usage={"page_requests": count})
