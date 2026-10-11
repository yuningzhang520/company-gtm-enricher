"""Literal-title recovery must not erase employment or extraction conflicts."""
import pytest

from company_gtm_enricher.people.evidence import candidate_from_observation
from company_gtm_enricher.people.models import CompanyTarget, PeopleCriteria
from company_gtm_enricher.people.search import SearchHit


def extract(headline, snippet="Experience: Example", *, name="Jordan Example", title="", company=None, employment="unclear"):
    company = company or CompanyTarget("Example", "example.org")
    hit = SearchHit("s1", "https://www.linkedin.com/in/jordan-example", headline, snippet)
    item = {
        "name": name, "title": title, "employment_quote": "", "current_employment": employment,
        "department": "", "seniority": "", "role_type": "unknown", "is_founder": False,
        "is_c_level": False, "classification_notes": "",
    }
    candidate = candidate_from_observation(
        company, hit, item, "2026-09-17T00:00:00+00:00",
        PeopleCriteria(departments=("Engineering",), leadership_levels=("Director",)),
    )
    assert candidate.evidence_text == headline + "\n" + snippet
    return candidate


@pytest.mark.parametrize("employment", ["current", "unclear", "former"])
def test_missing_title_is_copied_before_uncertain_employer_is_judged(employment):
    candidate = extract(
        "John Gross - Chief Innovation Officer | LinkedIn",
        "... IREN · Education: Texas A&M University · Location: Greater Houston · "
        "Associate Principal, Senior Project Manager, Mechanical Engineer. Page ...",
        name="John Gross", company=CompanyTarget("IREN", "iren.com"), employment=employment,
    )
    assert candidate.title == "Chief Innovation Officer"
    assert candidate.identity_verified and candidate.role_verified
    assert candidate.employment_status == "uncertain" and not candidate.employment_verified
    assert candidate.review_reason == "" and "Recovered the missing literal title" in candidate.notes
    assert not candidate.is_c_level  # Recovery does not manufacture model category flags.


def test_stitched_parenthetical_narrative_is_replaced_only_by_its_complete_headline_prefix():
    candidate = extract(
        "Mark Butler - Technical Recruiting @ Deepgram - LinkedIn",
        "Deepgram is a research-driven, foundational AI company. "
        "I managed a distributed team of Principal / Senior Technical Recruiters and Recruiting Coordinators.",
        name="Mark Butler", company=CompanyTarget("Deepgram", "deepgram.com"),
        title="Technical Recruiting (managed a distributed team of Principal / Senior Technical Recruiters)",
    )
    assert candidate.title == "Technical Recruiting" and candidate.role_verified
    assert candidate.employment_status == "current" and candidate.review_reason == ""
    assert "removed unsupported appended narrative" in candidate.notes


@pytest.mark.parametrize("body", [
    "Example", "Greater Houston", "Building the future of AI", "Follow me for engineering advice",
    "Technical", "Director of", "Example - LinkedIn", "I help CEOs hire great teams",
])
def test_company_location_slogan_or_fragment_does_not_become_a_title(body):
    candidate = extract(f"Jordan Example - {body} - LinkedIn")
    assert candidate.identity_verified and not candidate.role_verified
    assert candidate.title == ""


def test_target_company_itself_is_not_used_as_a_job_title():
    candidate = extract(
        "Jordan Example - Chief Innovation Officer - LinkedIn",
        "Experience: Chief Innovation Officer", company=CompanyTarget("Chief Innovation Officer", "example.org"),
    )
    assert candidate.title == "" and not candidate.role_verified


@pytest.mark.parametrize("headline", [
    "Other Person - Chief Innovation Officer at Example - LinkedIn",
    "Other Person - Technical Recruiting @ Example - LinkedIn",
])
def test_another_persons_headline_never_repairs_the_extracted_person(headline):
    candidate = extract(headline, "Experience: Example")
    assert candidate.title == "" and not candidate.identity_verified and not candidate.role_verified


@pytest.mark.parametrize("body", [
    "CTO @ Other | Director of Engineering @ Example",
    "CTO at Other and Director of Engineering at Example",
    "Director | Engineering | Example", "Chief Innovation Officer ...", "CTO |",
])
def test_composite_or_truncated_headlines_do_not_supply_an_arbitrary_role_fragment(body):
    candidate = extract(f"Jordan Example - {body} - LinkedIn")
    assert candidate.title == "" and not candidate.role_verified
    assert "cannot be isolated safely" in candidate.review_reason


@pytest.mark.parametrize("title", [
    "Invented Galactic Engineer", "CTO |", "CTO ·", "CTO - invented narrative",
    "Director of Engineering (managed a team)",
])
def test_unrelated_inventions_or_unsupported_display_suffixes_are_blanked_for_review(title):
    candidate = extract("Jordan Example - CTO at Example - LinkedIn", title=title)
    assert candidate.title == "" and not candidate.role_verified
    assert "not supported as one source phrase" in candidate.review_reason


def test_recovered_title_retains_the_other_employer_clause_in_employment_checks():
    candidate = extract("Jordan Example - Chief Innovation Officer at Other - LinkedIn")
    assert candidate.title == "Chief Innovation Officer" and candidate.role_verified
    assert candidate.employment_status == "conflict" and candidate.review_reason


def test_recovered_former_title_is_still_former():
    candidate = extract("Jordan Example - Former CTO at Example - LinkedIn")
    assert candidate.title == "CTO" and candidate.role_verified
    assert candidate.employment_status == "former" and candidate.review_reason


def test_recovered_current_headline_does_not_erase_an_ended_same_role_card():
    candidate = extract(
        "Jordan Example - CTO at Example - LinkedIn",
        "CTO. Example. Jan 2018 - Dec 2020", employment="current",
    )
    assert candidate.title == "CTO" and candidate.employment_status == "former"
    assert candidate.review_reason


def test_stitched_repair_does_not_erase_an_explicit_original_employer_conflict():
    candidate = extract(
        "Jordan Example - CTO at Example - LinkedIn", title="CTO (advisor at Other)",
    )
    assert candidate.title == "CTO" and candidate.role_verified
    assert candidate.employment_status == "conflict" and candidate.review_reason


def test_blanking_unsupported_composite_keeps_its_explicit_employer_conflict():
    candidate = extract(
        "Jordan Example - CTO at Example - LinkedIn",
        "CTO at Other. Director of Engineering at Example.",
        title="CTO at Other | Director of Engineering (invented narrative)",
    )
    assert candidate.title == "" and not candidate.role_verified
    assert candidate.employment_status == "conflict"
    assert "not supported as one source phrase" in candidate.review_reason
    assert "another employer" in candidate.review_reason


def test_distinct_named_headline_roles_are_not_arbitrarily_chosen():
    candidate = extract(
        "Jordan Example - CTO at Example - LinkedIn\nJordan Example - Director of Engineering at Example - LinkedIn",
    )
    assert candidate.title == "" and not candidate.role_verified
    assert "different role titles" in candidate.review_reason


def test_grounded_original_title_is_preserved_despite_a_different_headline_role():
    candidate = extract(
        "Jordan Example - Chief Innovation Officer - LinkedIn",
        "Director of Engineering. Other. Jan 2018 - Dec 2020. Experience: Example",
        title="Director of Engineering",
    )
    assert candidate.title == "Director of Engineering" and candidate.role_verified
    assert candidate.employment_status == "conflict" and candidate.review_reason


@pytest.mark.parametrize("company,employer", [
    (CompanyTarget("Cohere", "cohere.com"), "Cohere Health"),
    (CompanyTarget("Runway", "runway.com"), "Rent the Runway"),
    (CompanyTarget("Anomaly", "anomaly.co"), "True Anomaly"),
    (CompanyTarget("Runway", "runway.com"), "cfo.ai"),
])
def test_new_recovery_requires_the_explicit_employer_to_match_the_complete_target_identity(company, employer):
    candidate = extract(
        f"Jordan Example - CEO at {employer} - LinkedIn",
        f"Experience: {company.name}. I got a demotion to CEO. {company.name}.", company=company,
    )
    assert candidate.title == "CEO" and candidate.role_verified
    assert candidate.employment_status == "conflict" and not candidate.employment_verified
    assert "explicit headline employer does not match" in candidate.review_reason


def test_new_recovery_accepts_an_exact_configured_company_alias():
    candidate = extract(
        "Jordan Example - CTO at Repl.it - LinkedIn", "Experience: Replit",
        company=CompanyTarget("Replit", "replit.com", aliases=("Repl.it",)),
    )
    assert candidate.title == "CTO" and candidate.role_verified
    assert candidate.employment_status == "current" and candidate.review_reason == ""


@pytest.mark.parametrize("annotation", ["formerly OldName", "we're hiring", "we’re hiring", "I'm hiring"])
def test_known_company_rename_or_hiring_annotation_does_not_change_the_recovered_employer(annotation):
    candidate = extract(f"Jordan Example - CTO at Example ({annotation}) - LinkedIn")
    assert candidate.title == "CTO" and candidate.role_verified
    assert candidate.employment_status == "current" and candidate.review_reason == ""


@pytest.mark.parametrize("body", [
    "Chief Innovation Officer (formerly at Example)",
    "Chief Innovation Officer at Example (2018-2020)",
])
def test_recovery_preserves_parenthetical_former_or_dated_role_context(body):
    candidate = extract(f"Jordan Example - {body} - LinkedIn")
    assert candidate.title == "Chief Innovation Officer" and candidate.role_verified
    assert not candidate.employment_verified and candidate.review_reason


@pytest.mark.parametrize("title", ["", "CTO"])
def test_another_profiles_name_cannot_be_borrowed_from_a_recommended_profile_snippet(title):
    candidate = extract(
        "Alex Rivera - CTO at Example - LinkedIn", "Recommended profile: Jordan Example.", title=title,
    )
    assert not candidate.identity_verified
    assert "Extracted name does not match the named profile headline" in candidate.review_reason


def test_distinct_person_headlines_merged_onto_one_profile_remain_a_conflict():
    candidate = extract(
        "Alex Rivera - CTO at Example - LinkedIn\nJordan Example - CTO at Example - LinkedIn",
    )
    assert not candidate.identity_verified
    assert "Profile headlines contain conflicting displayed names; identity needs review" in candidate.review_reason


def test_possible_nickname_variation_is_reviewed_without_claiming_two_different_people():
    candidate = extract(
        "Joe Boys - Talent | San Francisco - LinkedIn\nJoseph Boys - Talent & Engineering - LinkedIn",
        "Founding Technical Recruiter. Paraform.", name="Joe Boys", title="Founding Technical Recruiter",
        company=CompanyTarget("Paraform", "paraform.com"),
    )
    assert not candidate.identity_verified
    assert "conflicting displayed names; identity needs review" in candidate.review_reason
    assert "different person" not in candidate.review_reason


@pytest.mark.parametrize("prefix", ["Jordan Example, PhD", "Jordan Example MBA", "Jordan Example\u200f", "Jordan   Example"])
def test_display_marks_whitespace_and_degree_suffixes_do_not_invent_a_different_person(prefix):
    candidate = extract(f"{prefix} - CTO at Example - LinkedIn", title="CTO")
    assert candidate.identity_verified
    assert "different person" not in candidate.review_reason


def test_duplicate_same_person_headlines_do_not_invent_an_identity_conflict():
    candidate = extract(
        "Jordan Example - CTO at Example - LinkedIn\njordan example - CTO at Example - LinkedIn",
    )
    assert candidate.identity_verified and candidate.role_verified and candidate.review_reason == ""
