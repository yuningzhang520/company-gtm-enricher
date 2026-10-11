"""Current/freshness claims are local to a source role, never global model vetoes."""
from datetime import datetime, timezone

from company_gtm_enricher.people import evidence
from company_gtm_enricher.people.models import CompanyTarget, PeopleCriteria
from company_gtm_enricher.people.search import SearchHit
from company_gtm_enricher.people.service import PeopleService
import pytest


CRITERIA = PeopleCriteria(departments=("Engineering",), leadership_levels=("Director",))


def assess(name, title, headline, snippet, *, company=None, model="current"):
    company = company or CompanyTarget("Example", "example.org")
    hit = SearchHit("source-1", "https://www.linkedin.com/in/example-person", headline, snippet)
    item = {
        "source_id": hit.id, "name": name, "title": title, "department": "Engineering",
        "seniority": "Director", "role_type": "leadership", "is_founder": False, "is_c_level": False,
        "current_employment": model, "employment_quote": snippet, "classification_notes": "",
    }
    candidate = evidence.candidate_from_observation(company, hit, item, "2026-09-17T00:00:00+00:00", CRITERIA)

    class Provider:
        is_mock = False

        def discover(self, target, selected):
            return [candidate]

    return candidate, PeopleService(Provider()).run([company], CRITERIA)


@pytest.mark.parametrize("model", ["current", "unclear", "former"])
def test_no_freshness_claim_preserves_complete_grounded_person_with_uncertain_status(model):
    candidate, result = assess(
        "Jordan Example", "Director of Engineering", "Jordan Example - Director of Engineering - LinkedIn",
        "Engineering leadership and platform development. Experience: Example.", model=model,
    )
    assert candidate.identity_verified and candidate.role_verified
    assert not candidate.employment_verified and candidate.employment_status == "uncertain"
    assert candidate.review_reason == "" and candidate.employment_note
    assert len(result.people) == 1 and result.review == []


@pytest.mark.parametrize("name,title", [("Eoghan McCabe", "CEO and founder"), ("Paul Adams", "CPO and Marketing")])
def test_company_rename_and_unrelated_ex_history_do_not_mark_role_former(name, title):
    candidate, result = assess(
        name, title, f"{name} - {title} at Fin (formerly Intercom) - LinkedIn",
        f"{title} at Fin (formerly Intercom) · Experience: Fin. Ex Facebook and previous startup work.",
        company=CompanyTarget("Fin", "fin.ai", aliases=("Intercom",)),
    )
    assert candidate.employment_status == "current" and candidate.employment_verified
    assert len(result.people) == 1 and result.review == []


@pytest.mark.parametrize("abbreviation", ["Sr.", "Jr."])
def test_abbreviation_period_is_part_of_the_grounded_title_not_an_experience_card_boundary(abbreviation):
    title = f"{abbreviation} Director of Engineering"
    candidate, result = assess(
        "Jordan Example", title, f"Jordan Example - {title} @Example - LinkedIn",
        f"{title}. Example. Jan 2024 - Present",
    )
    assert candidate.title == title
    assert candidate.employment_status == "current" and candidate.employment_verified
    assert len(result.people) == 1 and result.review == []


def test_current_svp_headline_is_not_ended_by_a_previous_vp_experience_card():
    candidate, result = assess(
        "Max Freeman", "SVP of Sales", "Max Freeman - SVP of Sales @ Ramp (I'm hiring | - LinkedIn",
        "SVP of Sales @ Ramp (I'm hiring - ramp.com/careers) · Experience: Ramp ... "
        "VP of Sales. Ramp. Sep 2024 - Jun 2026 1 year 10 months.",
        company=CompanyTarget("Ramp", "ramp.com"), model="former",
    )
    assert candidate.employment_status == "current" and candidate.employment_verified
    assert len(result.people) == 1 and result.review == []


@pytest.mark.parametrize("model", ["current", "unclear", "former"])
def test_ended_date_range_attached_to_the_exact_target_role_remains_former(model):
    candidate, result = assess(
        "Nik Koblov", "Head Of Engineering", "Nik Koblov - OpenRouter - LinkedIn",
        "Head Of Engineering. Ramp. Aug 2022 - May 2026. New role elsewhere.",
        company=CompanyTarget("Ramp", "ramp.com"), model=model,
    )
    assert candidate.employment_status == "former" and not candidate.employment_verified
    assert result.people == [] and len(result.review) == 1


@pytest.mark.parametrize("end,expected", [
    ("Dec 2026", "uncertain"), ("December 2026", "uncertain"),
    ("Jan 2027", "uncertain"), ("Aug 2026", "former"), ("Dec 2025", "former"),
])
def test_explicit_future_end_month_does_not_mark_a_role_as_already_ended(monkeypatch, end, expected):
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 9, 17, 12, tzinfo=timezone.utc)

    monkeypatch.setattr(evidence, "datetime", FrozenDatetime)
    candidate, result = assess(
        "Jordan Example", "Director of Engineering", "Jordan Example - Example - LinkedIn",
        f"Director of Engineering. Example. Jan 2024 - {end}", model="former",
    )
    assert candidate.employment_status == expected and not candidate.employment_verified
    assert (len(result.people), len(result.review)) == ((1, 0) if expected == "uncertain" else (0, 1))


def test_present_card_for_same_role_can_resolve_a_separate_old_tenure():
    candidate, result = assess(
        "Jordan Example", "Director of Engineering", "Jordan Example - Example - LinkedIn",
        "Director of Engineering. Example. Jan 2025 - Present · "
        "Director of Engineering. Example. Jan 2018 - Jun 2020", model="former",
    )
    assert candidate.employment_status == "current" and candidate.employment_verified
    assert len(result.people) == 1 and result.review == []


def test_past_director_at_another_employer_cannot_be_attached_to_current_company_header():
    candidate, result = assess(
        "Camille Fournier", "Head of Engineering, SVP Engineering", "Camille Fournier - CoreWeave - LinkedIn",
        "Head of Engineering, SVP Engineering. Rent The Runway. Aug 2012 - Aug 2014. "
        "Director of Engineering. Rent The Runway. Nov 2011 - Aug 2012. Experience: CoreWeave.",
        company=CompanyTarget("CoreWeave", "coreweave.com"), model="unclear",
    )
    assert candidate.identity_verified and candidate.role_verified
    assert candidate.employment_status == "conflict"
    assert result.people == [] and len(result.review) == 1


def test_explicit_former_role_in_named_headline_remains_review_without_a_model_veto():
    candidate, result = assess(
        "Jordan Example", "Director of Engineering", "Jordan Example - Former Director of Engineering at Example - LinkedIn", "",
    )
    assert candidate.employment_status == "former"
    assert result.people == [] and len(result.review) == 1


def test_unrelated_ended_role_does_not_get_assigned_to_uncertain_current_title():
    candidate, result = assess(
        "Jordan Example", "Head of Engineering", "Jordan Example - Head of Engineering - LinkedIn",
        "Director of Engineering. Other. Jan 2018 - Jun 2020. Experience: Example", model="former",
    )
    assert candidate.employment_status == "uncertain" and candidate.review_reason == ""
    assert len(result.people) == 1 and result.review == []


@pytest.mark.parametrize("company,name,title,headline,snippet", [
    (CompanyTarget("SpaceXAI", "x.ai", aliases=("xAI",)), "Steven Aiello", "CISO",
     "Steven Aiello - CISO | CVSS SIG Voting Member | Jujutsu Lover",
     "Steven Aiello. CISO | CVSS SIG Voting Member | Jujutsu Lover. xAI Eastern Michigan University."),
    (CompanyTarget("CoreWeave", "coreweave.com"), "Cameron Frantz", "VP of Commercial Finance",
     "Cameron Frantz - AI Infrastructure Finance @ CoreWeave - LinkedIn",
     "Cameron is the VP of Commercial Finance at CoreWeave leading the finance teams who partner with Operations, Sales, ..."),
    (CompanyTarget("StackAI", "stack-ai.com"), "Fonsi Hernández", "Founding AI Engineer",
     "Fonsi Hernández - Founding AI Engineer @ StackAI (YC, acq. ASAN)",
     "AI Engineer. StackAI. Jan 2025 - Present · Lead Software Engineer. Tesedi. Feb 2024 - Jan 2025"),
    (CompanyTarget("Pylon", "usepylon.com"), "Omar Radi", "Co-Founder & CTO",
     "Omar Radi\u200f - \u200fCo-Founder & CTO of Pylon, Chairman of BuduCloud",
     "CEO. BuduCloud. July 2012 - July 2017"),
    (CompanyTarget("SpaceXAI", "x.ai", aliases=("xAI",)), "David Xing", "Staff Software Engineer",
     "David Xing - Staff Software Engineer at xAI - X-Doordash | LinkedIn",
     "Worked as a Senior Software Engineer at xAI, focusing on building and scaling core AI infrastructure."),
    (CompanyTarget("Nebius", "nebius.com"), "Maxim Akhmedov", "Director of Engineering",
     "Maxim Akhmedov - Director of Engineering @ Nebius, Tavily",
     "Director of Engineering, Agentic Search · Head of TractoAI RnD @ Nebius"),
    (CompanyTarget("SpaceXAI", "x.ai", aliases=("xAI",)), "Nathan Ziebart", "Software Engineer",
     "Nathan Ziebart - Understanding the universe @ xAI | LinkedIn",
     "Principal Software Engineer. Robinhood. Feb 2022 - Dec 2023 · "
     "Software Engineer · Experience: xAI · Senior Staff Software Engineer. Robinhood. Oct 2020 - Feb 2022"),
    (CompanyTarget("Perplexity", "perplexity.ai"), "Mihai Popa", "Engineering",
     "Mihai Popa - Engineering @ Perplexity AI - LinkedIn",
     "Engineering @ Perplexity AI · Member of Technical Staff. Perplexity. Jun 2024 - Present"),
    (CompanyTarget("Lambda", "lambda.ai"), "Matthew Froelich", "Supply Chain Operations Sourcing Manager",
     "Matthew Froelich - Supply Chain Operations Sourcing Manager at ...",
     "Experience: Lambda · Education: Cal Poly San Luis Obispo"),
    (CompanyTarget("LangChain", "langchain.com"), "Nithin Bose", "VP, Customer Engineering",
     "Nithin Bose - LangChain - LinkedIn",
     "VP, Customer Engineering. LangChain New Jersey Institute of Technology."),
    (CompanyTarget("Decagon", "decagon.ai"), "Eamon Garrity-Rokous", "Founder's Office",
     "Eamon Garrity-Rokous - Founder’s Office @ Decagon - LinkedIn",
     "Founder's Office @ Decagon: conversational AI Agents for customer support"),
    (CompanyTarget("Perplexity", "perplexity.ai"), "Andy Konwinski", "Co-founder",
     "Andy Konwinski - Co-founder of Laude, Databricks, and Perplexity - LinkedIn", ""),
    (CompanyTarget("OpenAI", "openai.com"), "Sarah Friar", "CFO OpenAI",
     "Sarah Friar - CFO OpenAI | Co-Launcher @ Ladies Who Launch",
     "CFO OpenAI | Co-Launcher @ Ladies Who Launch | Board Member @ Walmart ..."),
    (CompanyTarget("Ollama", "ollama.com"), "Grace G.", "Software Engineer Intern",
     "Grace G. - prev. swe @ ollama, ml infra @ xAI/X, cs @ uwaterloo",
     "Experience · Software Engineer Intern. Ollama · Machine Learning Infrastructure Intern. xAI · "
     "Software Engineer Intern. BotBuilt · Perception Intern. Industrial ..."),
    (CompanyTarget("StackAI", "stackai.com", aliases=("Stack AI",)), "Leon Troper", "AI Strategist",
     "Leon Troper - AI Strategist @ Stack-AI - LinkedIn",
     "AI Strategist @ Stack-AI · Experience: StackAI · Education: Berklee College of Music"),
    (CompanyTarget("Example", "example.org"), "Jordan Example", "VP Engineering AI/ML",
     "Jordan Example - Founder @Other | VP Engineering AI/ML @Example - LinkedIn", ""),
])
def test_saved_ambiguous_employer_formatting_is_not_positive_mismatch_proof(company, name, title, headline, snippet):
    candidate, result = assess(name, title, headline, snippet, company=company, model="unclear")
    assert candidate.identity_verified and candidate.role_verified
    assert candidate.employment_status == "uncertain" and not candidate.employment_verified
    assert candidate.review_reason == "" and candidate.employment_note
    assert len(result.people) == 1 and result.review == []
    assert result.people[0]["Evidence Text"] == headline + "\n" + snippet


def test_saved_ambiguous_title_without_target_company_mention_is_discarded():
    headline = "Brian Eiseman - Senior Mechanical Design Engineer. Product ..."
    snippet = "Senior Mechanical Design Engineer. Product Development Leader, Hardware Design, Robotics, CAD, Surfacing ..."
    candidate, result = assess(
        "Brian Eiseman", "Senior Mechanical Design Engineer", headline, snippet,
        company=CompanyTarget("Dust", "dust.tt"), model="unclear",
    )
    assert candidate.identity_verified and candidate.role_verified
    assert candidate.employment_status == "uncertain" and not candidate.employment_verified
    assert candidate.review_reason == "" and candidate.employment_note
    assert candidate.evidence_text == headline + "\n" + snippet
    assert result.people == [] and result.review == []


def test_legacy_copied_company_suffix_variant_stays_unconfirmed():
    title = "Director of Engineering | Example Labs"
    candidate, result = assess("Jordan Example", title, f"Jordan Example - {title} - LinkedIn", "")
    assert candidate.employment_status == "uncertain" and not candidate.employment_verified
    assert len(result.people) == 1 and result.review == []


@pytest.mark.parametrize("employer", ["Example AI", "Example Learning Academy", "Example.space"])
def test_shared_company_words_leave_identity_unconfirmed_without_inventing_an_alias(employer):
    candidate, result = assess(
        "Jordan Example", "Director of Engineering", f"Jordan Example - Director of Engineering at {employer} - LinkedIn", "",
    )
    assert candidate.employment_status == "uncertain" and not candidate.employment_verified
    assert len(result.people) == 1 and result.review == []


@pytest.mark.parametrize("company,employer", [
    (CompanyTarget("CoreWeave", "coreweave.com"), "Rent The Runway"),
    (CompanyTarget("Cohere", "cohere.com"), "OpenAI"),
    (CompanyTarget("IREN", "iren.com"), "Oracle"),
])
def test_explicit_unrelated_employer_card_still_requires_review(company, employer):
    candidate, result = assess(
        "Jordan Example", "Director of Engineering", f"Jordan Example - {company.name} - LinkedIn",
        f"Director of Engineering. {employer}. Jan 2024 - Present", company=company,
    )
    assert candidate.employment_status == "conflict" and not candidate.employment_verified
    assert result.people == [] and len(result.review) == 1
