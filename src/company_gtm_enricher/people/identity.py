"""Shared identity checks, independent of providers and run orchestration."""
from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit

from .models import CompanyTarget


def canonical_linkedin_url(value: str) -> str:
    """Accept personal LinkedIn profiles only, removing tracking and locale hosts."""
    try:
        parsed = urlsplit(value.strip() if "://" in value else "https://" + value.strip())
        host = (parsed.hostname or "").casefold()
        parts = [unquote(part) for part in parsed.path.strip("/").split("/")]
        if (
            parsed.scheme not in ("http", "https")
            or parsed.username or parsed.password or parsed.port
            or not (host == "linkedin.com" or re.fullmatch(r"(?:www|[a-z]{2})\.linkedin\.com", host))
            or len(parts) != 2 or parts[0] != "in"
            or not re.fullmatch(r"[\w-]+", parts[1], flags=re.UNICODE)
        ):
            return ""
        return "https://www.linkedin.com/in/" + parts[1].casefold()
    except ValueError:
        return ""


def contains_phrase(text: str, phrase: str) -> bool:
    """Match whole phrases after whitespace normalization, not partial names."""
    phrase = " ".join(phrase.split())
    return bool(phrase and re.search(
        r"(?<!\w)" + re.escape(phrase) + r"(?!\w)",
        " ".join(text.split()), flags=re.IGNORECASE,
    ))


def company_names(company: CompanyTarget) -> tuple[str, ...]:
    return tuple(value for value in (company.name, company.domain, *company.aliases) if value)


def has_company_mention(evidence_text: str, company: CompanyTarget, *, person_name: str = "") -> bool:
    """Require a company phrase outside the supplied person's complete name."""
    if not isinstance(evidence_text, str):
        return False
    text = " ".join(evidence_text.split())
    person_name = " ".join(person_name.split())
    if person_name:
        text = re.sub(r"(?<!\w)" + re.escape(person_name) + r"(?!\w)", " ", text, flags=re.IGNORECASE)
    return any(contains_phrase(text, name) for name in company_names(company))
