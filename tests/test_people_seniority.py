import pytest

from company_gtm_enricher.people import seniority
from company_gtm_enricher.people.seniority import (
    load_seniority_aliases, normalize_seniority, seniority_conflict,
)


@pytest.mark.parametrize("value,expected", [
    ("Vice President", "VP"), ("vice-president", "VP"),
    ("Senior Vice President", "SVP"), ("Senior VP", "SVP"),
    (" Sr.  Vice President ", "SVP"), ("Executive Vice President", "EVP"),
    ("Executive VP", "EVP"), ("Sr.", "Senior"), ("Jr", "Junior"),
    ("Sr. Director", "Senior Director"), ("Sr Staff", "Senior Staff"),
    ("  Quantum Fellow  ", "Quantum Fellow"), ("", ""), ("  ", ""),
])
def test_only_explicit_equivalent_spellings_are_canonicalized(value, expected):
    assert normalize_seniority(value) == expected


@pytest.mark.parametrize("value,selected,expected", [
    ("Senior Vice President", ("SVP",), "SVP"),
    ("SVP", ("Senior Vice President",), "Senior Vice President"),
    ("svp", ("Senior Vice President", "SVP"), "SVP"),
    ("Senior VP", ("SVP", "Senior Vice President"), "SVP"),
    ("Senior Vice President", ("VP",), "SVP"),
    ("Vice President", ("SVP", "EVP"), "VP"),
    ("Senior Director", ("Director",), "Senior Director"),
    ("Director", ("Senior Director",), "Director"),
    ("Principal", ("Staff", "Senior"), "Principal"),
    (" quantum   fellow ", ("Quantum Fellow",), "Quantum Fellow"),
    ("Custom Level", ("CUSTOM LEVEL",), "CUSTOM LEVEL"),
    ("SVP Engineering", ("SVP",), "SVP Engineering"),
])
def test_selection_preserves_exact_lexical_equivalence_without_rank_inclusion(value, selected, expected):
    assert normalize_seniority(value, selected) == expected


def test_alias_context_is_fresh_and_editable_without_mutating_future_calls():
    first = load_seniority_aliases()
    assert "Senior Vice President" in first["SVP"]
    first["SVP"].append("unrelated label")
    first["VP"] = []
    second = load_seniority_aliases()
    assert "unrelated label" not in second["SVP"]
    assert "Vice President" in second["VP"]
    assert normalize_seniority("unrelated label") == "unrelated label"


def test_new_configured_equivalence_works_without_processing_code_changes(monkeypatch):
    config = seniority._configuration()
    config["aliases"]["Distinguished"] = ["Dist."]
    monkeypatch.setattr(seniority, "_configuration", lambda: config)
    assert normalize_seniority("Dist.", ("Distinguished",)) == "Distinguished"
    assert seniority_conflict("Dist. Engineer", "Distinguished") == ""
    assert seniority_conflict("Senior Dist. Engineer", "Distinguished")


@pytest.mark.parametrize("title,level", [
    ("Senior Vice President of Engineering", "VP"),
    ("SVP of Engineering", "Vice President"),
    ("Sr. Vice President of Engineering", "VP"),
    ("Executive Vice President of Engineering", "SVP"),
    ("Vice President of Engineering", "SVP"),
    ("Senior Director of Engineering", "Director"),
    ("Sr. Director of Engineering", "Director"),
    ("Director of Engineering", "Senior Director"),
    ("Senior Staff Engineer", "Staff"),
    ("Senior Principal Engineer", "Principal"),
    ("Deputy Director of Engineering", "Director"),
    ("Senior Research Fellow", "Research Fellow"),
    ("senior\n  vice president of Engineering", "vp"),
    ("VP and Senior VP of Engineering", "VP"),
    ("Director | Senior Director", "Director"),
])
def test_explicit_title_modifiers_cannot_be_silently_dropped_added_or_changed(title, level):
    reason = seniority_conflict(title, level)
    assert "conflicts with the explicit level" in reason
    assert level in reason


@pytest.mark.parametrize("title,level", [
    ("Senior Vice President of Engineering", "SVP"),
    ("SVP of Engineering", "Senior VP"),
    ("Executive Vice President of Engineering", "EVP"),
    ("Sr. Director of Engineering", "Senior Director"),
    ("Senior Staff Engineer", "Senior Staff"),
    ("Director of Senior Staff Programs", "Director"),
    ("Director of Engineering and Senior Staff Engineer", "Director"),
    ("Engineering leader", "VP"),
    ("Experienced technical leader", "SVP"),
    ("Quantum Fellow", "Quantum Fellow"),
    ("Senior Directors Council member", "Director"),
    ("Senior Staffers Program member", "Staff"),
    ("SVPology researcher", "VP"),
    ("ASVP engineer", "VP"),
    ("", "Director"), ("Director", ""),
])
def test_equivalence_unknowns_other_role_modifiers_and_substrings_do_not_invent_conflicts(title, level):
    assert seniority_conflict(title, level) == ""
