"""Deterministic grounding of extracted people in supplied source evidence."""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from company_gtm_enricher.people.identity import canonical_linkedin_url, company_names, contains_phrase
from company_gtm_enricher.people.models import Candidate, CompanyTarget, PeopleCriteria
from company_gtm_enricher.people.seniority import normalize_seniority, seniority_conflict

if TYPE_CHECKING:
    from company_gtm_enricher.people.search import SearchHit


_C_LEVEL_TITLE = re.compile(
    r"\bchief\s+(?:[\w&/-]+\s+){0,4}officer\b"
    r"|\bchief\s+(?:executive|scientist)\b"
    r"|\b(?:CEO|CFO|CTO|COO|CIO|CPO|CMO|CHRO|CSO|CISO|CDO|CAO|CRO|CCO)\b",
    re.IGNORECASE,
)
_PERIOD_BREAK = r"(?<!\bSr)(?<!\bJr)\.\s+"
_EMPLOYER_END = r"(?=\s*(?:$|[,;·|()]|\.+(?=\s|$)|[-–—](?=\s|$)))"
_ROLE_DATE = re.compile(
    r"^[\s.,;·|]*(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+)?"
    r"\d{4}\s*[-–—]\s*(?P<end>Present|Current|Now|"
    r"(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+)?\d{4})(?!\w)",
    re.IGNORECASE,
)
_MONTHS = {name: number for number, name in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), start=1,
)}


def _title_names_company(title: str, names: tuple[str, ...]) -> bool:
    """Accept an explicit employer suffix, not a company word inside a job title."""
    for company_name in names:
        match = re.fullmatch(
            r"(?P<role>.+?)(?:\s+(?:at|of|for)\s+|\s*[@,·|]\s*|\.\s+)"
            + re.escape(company_name) + r"\.?\s*", title, re.IGNORECASE,
        )
        # Only one role/company pair can establish this link. A copied composite
        # such as Founder. Other. Engineer. Target. must not transfer its labels.
        if match and not re.search(r"[|;\n@]|" + _PERIOD_BREAK, match.group("role"), re.IGNORECASE):
            return True
    return False


def _role_links_company(quote: str, title: str, names: tuple[str, ...]) -> bool:
    if not title or not contains_phrase(quote, title):
        return False
    # A composite headline can describe roles at several employers. Keep it for
    # review if an explicit employer clause refers elsewhere; do not transfer its
    # founder/C-level label to the target employer's different role.
    for clause in re.split(r"\s*[|;\n]\s*|" + _PERIOD_BREAK, title, flags=re.IGNORECASE):
        explicit_employer = re.search(
            r"(?:\bat\s+|@\s*|\b(?:founder|CEO|CTO|CFO|COO)\s+of\s+)(.+)$",
            clause, re.IGNORECASE,
        )
        if explicit_employer and not any(
            explicit_employer.group(1).strip().casefold() in (value.casefold(), value.casefold() + ".")
            for value in names
        ):
            return False
    if _title_names_company(title, names):
        return True
    if re.search(r"[|;\n]|" + _PERIOD_BREAK, title, re.IGNORECASE):
        return False
    # Search snippets often flatten LinkedIn experience cards into Title. Company.
    # Require adjacency rather than a company mention somewhere in the quote.
    # The model may copy that separator period as part of the title. In that case
    # the period already supplies the delimiter; preserve the copied title/evidence.
    separator = r"\s+" if title.endswith(".") else r"(?:\s+(?:at|of|for)\s+|\s*[@,·|–—-]\s*|\.\s+)"
    return any(re.search(
        r"(?<!\w)" + re.escape(title) + separator
        # A complete employer label ends at a clause boundary. A word boundary
        # alone would incorrectly turn Sierra Space into evidence for Sierra.
        + re.escape(company_name) + _EMPLOYER_END,
        quote, re.IGNORECASE,
    ) for company_name in names)


def _omitted_level_modifier(title: str, seniority: str) -> str:
    """Find an explicit omitted modifier without assigning a rank or new label."""
    level = " ".join(seniority.split())
    if not level:
        return ""
    match = re.search(
        r"(?<!\w)(?:Senior|Junior|Principal|Staff|Lead|Associate|Assistant|Deputy|Executive)\s+"
        + re.escape(level) + r"(?!\w)", " ".join(title.split()), re.IGNORECASE,
    )
    return match.group(0) if match else ""


def _named_headline_roles(hit: SearchHit, name: str, *, strip_annotations: bool = True):
    if not name:
        return
    for line in hit.title.splitlines():
        headline = _display_name(line)
        match = re.fullmatch(
            re.escape(_display_name(name)) + r"\s*[-–—|]\s*"
            + r"(?P<role>.+?)(?:\s*[-–—|]\s*LinkedIn)?", headline, re.IGNORECASE,
        )
        if not match:
            continue
        # Company rename/hiring annotations describe the company or page, not a
        # former role. Do not drop arbitrary parenthetical job facts.
        role = re.sub(
            r"\s*\((?:formerly\b|previously\b|I['’]m hiring\b|we['’]re hiring\b).*$",
            "", match.group("role"), flags=re.IGNORECASE,
        ).strip() if strip_annotations else match.group("role").strip()
        yield role


def _display_name(value: str) -> str:
    """Ignore invisible direction/display marks when comparing headline names."""
    return " ".join("".join(char for char in value if unicodedata.category(char) != "Cf").split())


def _headline_identity_issue(hit: SearchHit, name: str, names: tuple[str, ...]) -> str:
    """A different named profile cannot borrow the extracted name from its snippet."""
    if not name:
        return ""

    def person_key(value: str) -> str:
        value = _display_name(value)
        value = re.sub(r"(?:,\s*|\s+)(?:Ph\.?D\.?|M\.?D\.?|MBA|MSc|BSc)$", "", value, flags=re.IGNORECASE)
        return value.casefold()

    displayed_names = set()
    for line in hit.title.splitlines():
        match = re.match(r"(?P<person>.+?)\s+[-–—|]\s+.+", line)
        if not match:
            continue
        person = person_key(match["person"])
        # Restrict the check to a plausible full-name prefix, not a company-only
        # header, occupational phrase, or other display text.
        if (len(person.split()) < 2 or not re.fullmatch(r"[^\W\d_][\w'’ .-]+", person)
                or any(char.isdigit() for char in person)
                or person in {person_key(value) for value in names}
                or _C_LEVEL_TITLE.search(person)
                or re.search(r"\b(?:Director|Engineering|Engineer|Recruiting|Experience|LinkedIn)\b", person, re.IGNORECASE)):
            continue
        displayed_names.add(person)
    if displayed_names - {person_key(name)}:
        if len(displayed_names) > 1:
            return "Profile headlines contain conflicting displayed names; identity needs review."
        return "Extracted name does not match the named profile headline."
    return ""


def _recovered_role_issue(hit: SearchHit, name: str, title: str, names: tuple[str, ...]) -> tuple[str, str]:
    """New recovery cannot discard explicit employer or dated/former context."""
    for headline, clean_headline in zip(
        _named_headline_roles(hit, name, strip_annotations=False), _named_headline_roles(hit, name),
    ):
        if not contains_phrase(headline, title):
            continue
        if re.search(r"\((?:formerly|previously)\s+(?:at|with|for)\b", headline, re.IGNORECASE):
            return "uncertain", "Recovered headline title includes explicit former-role context; review its employment association."
        if re.search(r"\([^)]*\b\d{4}\s*[-–—]\s*(?:[A-Za-z]+\s+)?\d{4}\b[^)]*\)", headline):
            return "uncertain", "Recovered headline title includes an employment date range; review its current association."
        parts = re.split(r"\s+at\s+|\s*@\s*", clean_headline, maxsplit=1, flags=re.IGNORECASE)
        if len(parts) == 2:
            employer = parts[1].strip().rstrip(".")
            if not any(employer.casefold() == value.casefold().rstrip(".") for value in names):
                return "conflict", "Recovered title's explicit headline employer does not match the configured target-company identity."
    return "", ""


def _headline_title(hit: SearchHit, name: str, names: tuple[str, ...]) -> tuple[str, str]:
    """Recover only a complete, plainly occupational, single named headline role."""
    titles = {}
    for headline in _named_headline_roles(hit, name):
        # Do not select one fragment from several roles/employers or a truncated
        # display. A missing model title is not permission to guess between them.
        if (re.search(r"[|;·]|\s[-–—]\s|\.\.|…", headline)
                or len(re.findall(r"\bat\s+|@", headline, re.IGNORECASE)) > 1):
            if re.search(r"\b(?:Chief|CEO|CFO|CTO|COO|Founder|Director|Head|VP|Engineer|Recruiting)\b", headline, re.IGNORECASE):
                return "", "A complete title cannot be isolated safely from the composite or truncated named headline."
            continue
        # Keep the complete source for subsequent employment checks. Only the
        # displayed role excludes an explicit employer suffix.
        role = re.split(r"\s+at\s+|\s*@\s*", headline, maxsplit=1, flags=re.IGNORECASE)[0].strip()
        role = re.sub(r"^(?:Former|Previously|Ex[- ])\s*", "", role, flags=re.IGNORECASE)
        if any(role.casefold() == value.casefold() for value in names):
            continue
        if re.search(r"[|;·(),]|\d|\.\.|…", role) or re.search(r"\b(?:of|at|for|and)\s*$", role, re.IGNORECASE):
            continue
        # This is deliberately a small structural guard, not a title taxonomy.
        # Unrecognized headline wording stays missing instead of becoming a fact.
        occupational = _C_LEVEL_TITLE.fullmatch(role) or re.fullmatch(
            r"(?:(?:Senior|Junior|Executive|Global)\s+)?(?:Director|Head|VP|SVP|EVP|Vice President)\s+(?:of\s+)?[\w/&+ -]+"
            r"|(?:Technical|Executive|Campus|University)\s+Recruit(?:ing|er)",
            role, re.IGNORECASE,
        )
        if occupational and contains_phrase(hit.title, role):
            titles.setdefault(role.casefold(), role)
    if len(titles) > 1:
        return "", "Named headlines contain different role titles; no single literal title can be recovered safely."
    return next(iter(titles.values()), ""), ""


def _headline_affiliation(hit: SearchHit, name: str, title: str, names: tuple[str, ...]) -> bool:
    """Repair a missing/garbled quote only from a direct named profile headline."""
    if not name or not title:
        return False
    for role in _named_headline_roles(hit, name):
        # Both legacy employer-suffixed titles and clean role-only extraction
        # must match the beginning of one explicit role/company headline pair.
        if (
            role.casefold().startswith(" ".join(title.split()).casefold())
            and _title_names_company(role, names)
            and _role_links_company(role, title, names)
        ):
            return True
    return False


def _role_target_spans(text: str, title: str, names: tuple[str, ...]):
    """Yield local role/company spans so dates cannot drift between experience cards."""
    if not title:
        return
    if _title_names_company(title, names):
        pattern = r"(?<!\w)" + re.escape(title) + r"(?!\w)"
        yield from re.finditer(pattern, text, re.IGNORECASE)
        return
    if re.search(r"[|;\n]|" + _PERIOD_BREAK, title, re.IGNORECASE):
        return
    separator = r"\s+" if title.endswith(".") else r"(?:\s+(?:at|of|for)\s+|\s*[@,·|–—-]\s*|\.\s+)"
    for company_name in names:
        yield from re.finditer(
            r"(?<!\w)" + re.escape(title) + separator + re.escape(company_name) + _EMPLOYER_END,
            text, re.IGNORECASE,
        )


def _other_employer(text: str, title: str, names: tuple[str, ...]) -> bool:
    """Find an explicit other-employer binding of the copied role, not a mere mention."""
    if not title:
        return False
    allowed = {value.casefold().rstrip(".") for value in names}

    def clearly_foreign(employer: str) -> bool:
        employer = employer.strip()
        # A partial label, a company-name variant, or a target name followed by
        # narrative is not affirmative evidence for a different employer. These
        # forms remain unconfirmed; they do not gain an alias or a verified link.
        if not employer or ".." in employer or "…" in employer or "," in employer:
            return False
        employer = employer.rstrip(".")
        if any(contains_phrase(employer, value) or contains_phrase(value, employer) for value in names):
            return False
        if any(re.sub(r"[\W_]+", "", employer.casefold()) == re.sub(r"[\W_]+", "", value.casefold()) for value in names):
            return False
        return not re.search(r"\b(?:is|was|I|you|my|our|years?|months?|Present)\b|\d", employer, re.IGNORECASE)

    components = [value.strip().rstrip(".") for value in re.split(r"\s*\|\s*|" + _PERIOD_BREAK, title, flags=re.IGNORECASE) if value.strip()]
    # A target-ending sequence of two role/company pairs is distinct from a
    # list of interests or memberships separated by pipes.
    if len(components) >= 4 and len(components) % 2 == 0 and components[-1].casefold() in allowed and any(clearly_foreign(value) for value in components[1:-1:2]):
        return True
    # Explicit employer clauses inside a composite copied title cannot transfer
    # a founder/executive category to the target's different role.
    for clause in re.split(r"[|;\n]|" + _PERIOD_BREAK, title, flags=re.IGNORECASE):
        match = re.search(r"(?:\bat\s+|@\s*|\b(?:co[- ]?)?founder\s+(?:of\s+|,\s*))(.+)$", clause, re.IGNORECASE)
        if match and clearly_foreign(match.group(1)):
            return True
    # Flattened Title. Employer. Dates cards and explicit at/@ employer phrases.
    role = title.rstrip(".").strip()
    pattern = (
        r"(?<!\w)" + re.escape(role)
        + r"(?:\s+(?:at|of|for)\s+|\s*@\s*|\.\s+)"
        + r"(?P<employer>[^·|;\n()]+?)(?=\.\s+|[·|;\n()]|\s+[-–—]\s+LinkedIn|\s+(?:and|where|since|with)\b|$)"
    )
    for match in re.finditer(pattern, text, re.IGNORECASE):
        # An older Principal Software Engineer role is not the copied Software
        # Engineer role. Do not move the old role's employer onto the shorter one.
        if re.search(r"\b(?:Senior|Junior|Principal|Staff|Lead|Associate|Assistant|Deputy|Executive|Sr\.?|Jr\.?)\s+$", text[max(0, match.start() - 30):match.start()], re.IGNORECASE):
            continue
        employer = match.group("employer").strip()
        if clearly_foreign(employer):
            return True
    return False


def _employment_evidence(company: CompanyTarget, hit: SearchHit, name: str, title: str, model_label: str):
    names = company_names(company)
    evidence = hit.title + "\n" + hit.snippet
    spans = list(_role_target_spans(evidence, title, names))
    ended = present = False
    for span in spans:
        date = _ROLE_DATE.match(evidence[span.end():])
        if date:
            present |= date["end"].casefold() in {"present", "current", "now"}
            end_year = re.search(r"\d{4}", date["end"])
            if end_year:
                now = datetime.now(timezone.utc)
                year = int(end_year[0])
                month = _MONTHS.get(date["end"][:3].casefold())
                ended |= year < now.year or (year == now.year and (month is None or month <= now.month))
        prefix = evidence[max(0, span.start() - 70):span.start()]
        ended |= bool(re.search(
            r"\b(?:former|formerly|previous|previously|used to be|worked as|was)\s*$|\bex[- ]$",
            prefix, re.IGNORECASE,
        ) or re.match(r"(?:former|previous|ex[- ])\b", title, re.IGNORECASE))
    headline = _headline_affiliation(hit, name, title, names)
    linked = _role_links_company(hit.snippet, title, names)
    # A copied composite's explicit other-employer clause is never repaired by
    # a headline about the person's different role at the target company.
    foreign_title = _other_employer("", title, names)
    if foreign_title:
        return "conflict", "Copied title explicitly links a role to another employer.", False
    if ended and not present:
        return "former", "Supplied text explicitly ends or marks the copied target-company role as former.", False
    current = present or headline or (linked and model_label == "current")
    if not linked and not headline:
        for role in _named_headline_roles(hit, name):
            if contains_phrase(role, title) and (
                _other_employer(role, title, names)
                or (_title_names_company(role, names) and not _role_links_company(role, title, names))
                or (_title_names_company(role, names) and not role.casefold().startswith(title.casefold()))
            ):
                return "conflict", "Copied title is a fragment of a different or multi-employer headline role.", False
        for line in hit.title.splitlines():
            other = re.fullmatch(r"(?P<person>.+?)\s+[-–—|]\s+(?P<role>.+?)(?:\s+[-–—|]\s+LinkedIn)?", line, re.IGNORECASE)
            if other and _display_name(other["person"]).casefold() != _display_name(name).casefold():
                if contains_phrase(other["role"], title) and _role_links_company(other["role"], title, names):
                    return "conflict", "Copied role belongs to a differently named profile headline.", False
    if not current and not linked and _other_employer(evidence, title, names):
        return "conflict", "Supplied text links the copied title to another employer, not the target company.", False
    if current and company.domain:
        return "current", "Current role is supported by the supplied profile text; freshness is not independently verified.", headline
    note = "Current employment is uncertain; the supplied text does not conclusively establish this role's current association with the target company."
    if not company.domain:
        note += " Company identity is also uncertain because no domain was supplied."
    return "uncertain", note, False


def candidate_from_observation(
    company: CompanyTarget, hit: SearchHit, item: dict, observed_at: str,
    criteria: PeopleCriteria | None = None,
) -> Candidate:
    """Ground one structured observation in its original source text."""
    evidence = hit.title + "\n" + hit.snippet
    name, title = item["name"].strip(), item["title"].strip()
    # Display-only delimiters are not part of a role. Preserve other copied
    # punctuation and keep the original source text for audit.
    clean_title = title.rstrip(" ·|")
    title_note = ""
    if clean_title != title and clean_title and contains_phrase(evidence, title):
        title_note = "Removed trailing profile display separators from the copied title."
        title = clean_title
    quote = item["employment_quote"]
    names = company_names(company)
    original_title = title
    extraction_reason = ""
    recovered_status, recovered_issue = "", ""
    if not title or not contains_phrase(evidence, title):
        recovered, headline_reason = _headline_title(hit, name, names)
        # Repair a stitched narrative only when the entire source headline role
        # is the original extraction's prefix. An unrelated invention cannot be
        # silently replaced with another role found somewhere in the source.
        related_appendix = bool(recovered and re.fullmatch(
            re.escape(recovered) + r"\s+\([^|;·]*\)", title, re.IGNORECASE,
        ))
        if recovered and (not title or related_appendix):
            title_note = (
                "Recovered the missing literal title from the named profile headline."
                if not title else
                "Recovered the literal headline title; removed unsupported appended narrative."
            )
            title = recovered
            recovered_status, recovered_issue = _recovered_role_issue(hit, name, title, names)
        else:
            extraction_reason = (
                "Extracted title was not supported as one source phrase and could not be repaired safely."
                if title else headline_reason
            )
            title = ""
    employment_status, employment_note, used_headline = _employment_evidence(
        company, hit, name, title, item["current_employment"],
    )
    if original_title and original_title != title:
        original_status, original_note, _ = _employment_evidence(
            company, hit, name, original_title, item["current_employment"],
        )
        if original_status in {"former", "conflict"}:
            employment_status, employment_note, used_headline = original_status, original_note, False
    if recovered_issue:
        extraction_reason = recovered_issue
        if employment_status not in {"former", "conflict"}:
            employment_status, employment_note, used_headline = recovered_status, recovered_issue, False
    affiliation = employment_status == "current"
    corrections = [title_note] if title_note else []
    selected_levels = (*criteria.leadership_levels, *criteria.ic_levels) if criteria else ()
    seniority = normalize_seniority(item["seniority"], selected_levels)
    if seniority != item["seniority"].strip():
        corrections.append(f"Normalized equivalent seniority spelling '{item['seniority'].strip()}' to '{seniority}'.")
    if used_headline and not (quote.strip() and quote in evidence and _role_links_company(quote, title, names)):
        corrections.append("Employment quote was unsupported; used the direct named profile headline.")
    reasons = [extraction_reason] if extraction_reason else []
    identity_issue = _headline_identity_issue(hit, name, names)
    if identity_issue:
        reasons.append(identity_issue)
    if employment_status in {"former", "conflict"}:
        reasons.append(employment_note)
    founder_supported = bool(re.search(r"\b(?:co[- ]?)?founder\b", title, re.IGNORECASE))
    c_level_supported = bool(_C_LEVEL_TITLE.search(title))
    is_founder = item["is_founder"] and founder_supported
    is_c_level = item["is_c_level"] and c_level_supported
    if (item["is_founder"] and not founder_supported) or (item["is_c_level"] and not c_level_supported):
        corrections.append("Discarded an unsupported Founder or C-level flag; only categories supported by the copied title are retained.")
    omitted_modifier = _omitted_level_modifier(title, seniority)
    level_note = seniority_conflict(title, seniority)
    if omitted_modifier:
        level_note = (
            f"Mapped seniority '{seniority}' omits an explicit modifier "
            f"from the copied title ('{omitted_modifier}'); review the level."
        )
    if level_note:
        corrections.append(level_note)
    return Candidate(
        name=name, title=title, linkedin_url=hit.url,
        department=item["department"].strip(), seniority=seniority, role_type=item["role_type"],
        is_founder=is_founder, is_c_level=is_c_level,
        evidence_url=hit.url, evidence_text=evidence, observed_at=observed_at,
        identity_verified=bool(canonical_linkedin_url(hit.url) and contains_phrase(evidence, name) and not identity_issue),
        role_verified=contains_phrase(evidence, title), employment_verified=affiliation,
        employment_status=employment_status, employment_note=employment_note,
        notes="; ".join(filter(None, (
            "Affiliation based on search evidence; not independent employment verification.",
            item["classification_notes"].strip(),
            *corrections,
        ))),
        review_reason=" ".join(reasons),
    )
