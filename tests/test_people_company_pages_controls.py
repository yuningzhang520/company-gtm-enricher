import io
from pathlib import Path
from unittest.mock import Mock

import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from company_gtm_enricher.cli import _run_people, build_parser
from company_gtm_enricher.people.config import create_people_provider
from company_gtm_enricher.people.providers import MockPeopleProvider


ROOT = Path(__file__).resolve().parents[1]
CONTROL = "Check company founder links"


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("SERPER_API_KEY", "test-serper-key")
    monkeypatch.setattr("company_gtm_enricher.people.config.load_dotenv", lambda: None)


@pytest.mark.parametrize("enabled", [False, True])
def test_factory_only_constructs_unauthenticated_company_source_when_requested(monkeypatch, enabled):
    openai_factory, search_factory, live_factory = Mock(), Mock(), Mock()
    page_factory, source_factory = Mock(), Mock()
    monkeypatch.setattr("openai.OpenAI", openai_factory)
    monkeypatch.setattr("company_gtm_enricher.people.search.SerperSearchClient", search_factory)
    monkeypatch.setattr("company_gtm_enricher.people.live.LiveSearchPeopleProvider", live_factory)
    monkeypatch.setattr("company_gtm_enricher.people.public_pages.PublicPageClient", page_factory)
    monkeypatch.setattr("company_gtm_enricher.people.company_pages.CompanyFounderSource", source_factory)

    provider = create_people_provider("openai", company_founder_pages=enabled)

    assert provider is live_factory.return_value
    if enabled:
        page_factory.assert_called_once_with()
        source_factory.assert_called_once_with(client=page_factory.return_value, max_pages=3)
        assert live_factory.call_args.kwargs["company_pages"] is source_factory.return_value
    else:
        page_factory.assert_not_called()
        source_factory.assert_not_called()
        assert live_factory.call_args.kwargs["company_pages"] is None
    source_factory.return_value.discover.assert_not_called()
    openai_factory.return_value.responses.create.assert_not_called()
    search_factory.return_value.search.assert_not_called()


def test_mock_ignores_company_page_flag_and_all_live_configuration(monkeypatch):
    settings = Mock(side_effect=AssertionError("Mock must not read live configuration"))
    page_factory = Mock(side_effect=AssertionError("Mock must not construct a public-page client"))
    monkeypatch.setattr("company_gtm_enricher.people.config.PeopleSettings.from_env", settings)
    monkeypatch.setattr("company_gtm_enricher.people.public_pages.PublicPageClient", page_factory)

    assert create_people_provider("mock", company_founder_pages=True).is_mock
    settings.assert_not_called()
    page_factory.assert_not_called()


@pytest.mark.parametrize("enabled", [False, True])
def test_cli_routes_company_page_opt_in_and_still_exports(monkeypatch, tmp_path, enabled):
    source = tmp_path / "companies.csv"
    source.write_text("company,domain\nExample,example.com\n")
    output = tmp_path / "people.xlsx"
    argv = ["--mode", "people", "--provider", "mock", "--input", str(source), "--output", str(output)]
    if enabled:
        argv.append("--company-founder-pages")
    factory = Mock(return_value=MockPeopleProvider())
    monkeypatch.setattr("company_gtm_enricher.people.config.create_people_provider", factory)

    args = build_parser().parse_args(argv)
    assert _run_people(args, pd.read_csv(source), output) == 0
    assert factory.call_args.kwargs["company_founder_pages"] is enabled
    assert output.exists()


@pytest.mark.parametrize("enabled", [False, True])
def test_ui_company_pages_are_live_only_and_explicitly_routed(monkeypatch, enabled):
    uploaded = io.BytesIO(b"company,domain\nExample,example.com\n")
    uploaded.name = "companies.csv"
    monkeypatch.setattr(st, "file_uploader", lambda *args, **kwargs: uploaded)
    factory = Mock(return_value=MockPeopleProvider())
    monkeypatch.setattr("company_gtm_enricher.people.ui.create_people_provider", factory)
    page = AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()
    page.sidebar.radio[0].set_value("People").run()
    assert not any(item.label == CONTROL for item in page.checkbox)
    next(item for item in page.selectbox if item.label == "People source").set_value("Search + LLM").run()
    control = next(item for item in page.checkbox if item.label == CONTROL)
    assert control.value is False
    assert "No LinkedIn pages are fetched" in control.proto.help
    if enabled:
        control.check().run()
    next(item for item in page.button if item.label == "Find people").click().run()
    page.session_state["people_job"].thread.join(5)
    page.run()

    assert not page.exception
    assert factory.call_args.args == ("openai",)
    assert factory.call_args.kwargs["company_founder_pages"] is enabled
    assert page.session_state["people_job"].status == "completed"


def test_company_page_control_is_locked_during_active_run(monkeypatch):
    def render():
        from company_gtm_enricher.people.ui import render_people_page
        render_people_page()

    page = AppTest.from_function(render).run()
    next(item for item in page.selectbox if item.label == "People source").set_value("Search + LLM").run()
    next(item for item in page.checkbox if item.label == CONTROL).check().run()
    # Isolate the active-render controls; no worker or rerun loop is needed here.
    monkeypatch.setattr("company_gtm_enricher.people.ui.is_active", lambda job: True)
    monkeypatch.setattr(st, "rerun", lambda: None)
    page.run()

    assert not page.exception
    control = next(item for item in page.checkbox if item.label == CONTROL)
    assert control.value is True
    assert control.disabled
