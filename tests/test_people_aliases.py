import io
from pathlib import Path

import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from company_gtm_enricher.cli import _run_people, build_parser
from company_gtm_enricher.people.models import CompanyTarget
from company_gtm_enricher.people.providers import MockPeopleProvider
from company_gtm_enricher.people.service import read_companies


ROOT = Path(__file__).resolve().parents[1]


class RecordingMock(MockPeopleProvider):
    def __init__(self):
        self.companies = []

    def discover(self, company, criteria):
        self.companies.append(company)
        return super().discover(company, criteria)


def test_company_aliases_normalize_without_guessing_equivalent_spellings():
    company = CompanyTarget("Example", aliases=("  Old   Example ", "OLD EXAMPLE", "", "Old.Example"))
    assert company.aliases == ("Old Example", "Old.Example")


@pytest.mark.parametrize("aliases", ["Old Example", ("Old Example", 42)])
def test_company_aliases_reject_malformed_direct_input(aliases):
    with pytest.raises(ValueError, match="Company aliases"):
        CompanyTarget("Example", aliases=aliases)


def test_csv_aliases_merge_only_matching_company_identities():
    frame = pd.DataFrame({
        "company": ["Example", "EXAMPLE", "Old Example", "Example", ""],
        "domain": ["example.org", "example.org", "example.org", "other.example", ""],
        "aliases": ["Old Example; Example Labs", "old example | Example, Inc.", "Example", None, "Ignored"],
    })
    targets = read_companies(frame, "company", "domain", aliases_column="aliases")
    assert targets == [
        CompanyTarget("Example", "example.org", aliases=("Old Example", "Example Labs", "Example, Inc.")),
        CompanyTarget("Old Example", "example.org", aliases=("Example",)),
        CompanyTarget("Example", "other.example"),
        CompanyTarget(""),
    ]


def test_missing_alias_column_fails_before_discovery():
    with pytest.raises(ValueError, match="Column `old_names` does not exist"):
        read_companies(pd.DataFrame({"company": ["Example"]}), "company", aliases_column="old_names")


@pytest.mark.parametrize("column,flags", [("aliases", []), ("previous_names", ["--aliases-column", "previous_names"])])
def test_cli_routes_detected_and_mapped_aliases_to_provider(tmp_path, monkeypatch, column, flags):
    csv_path = tmp_path / "companies.csv"
    csv_path.write_text(f"company,domain,{column}\nExample,example.org,Old Example; Example Labs\n")
    output = tmp_path / "people.xlsx"
    args = build_parser().parse_args([
        "--mode", "people", "--provider", "mock", "--input", str(csv_path), "--output", str(output), *flags,
    ])
    provider = RecordingMock()
    monkeypatch.setattr("company_gtm_enricher.people.config.create_people_provider", lambda *args, **kwargs: provider)
    assert _run_people(args, pd.read_csv(csv_path), output) == 0
    assert provider.companies == [CompanyTarget("Example", "example.org", aliases=("Old Example", "Example Labs"))]
    assert output.exists()


@pytest.mark.parametrize("column", ["aliases", "previous_names"])
def test_ui_routes_detected_and_mapped_aliases_to_provider(tmp_path, monkeypatch, column):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("SERPER_API_KEY", "")
    uploaded = io.BytesIO(f"company,domain,{column}\nExample,example.org,Old Example|Example Labs\n".encode())
    uploaded.name = "companies.csv"
    monkeypatch.setattr(st, "file_uploader", lambda *args, **kwargs: uploaded)
    provider = RecordingMock()
    monkeypatch.setattr("company_gtm_enricher.people.ui.create_people_provider", lambda *args, **kwargs: provider)
    page = AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()
    page.sidebar.radio[0].set_value("People").run()
    mapping = next(item for item in page.selectbox if item.label == "Company aliases column (optional)")
    if column == "aliases":
        assert mapping.value == "aliases"
    else:
        assert mapping.value == "(none)"
        mapping.set_value(column).run()
    next(button for button in page.button if button.label == "Run people demo").click().run()
    job = page.session_state["people_job"]
    job.thread.join(5)
    page.run()
    assert not page.exception
    assert job.status == "completed"
    assert provider.companies == [CompanyTarget("Example", "example.org", aliases=("Old Example", "Example Labs"))]
