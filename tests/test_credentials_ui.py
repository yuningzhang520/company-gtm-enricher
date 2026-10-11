import io
import os
from pathlib import Path

import pytest
import streamlit as st
from streamlit.proto.TextInput_pb2 import TextInput
from streamlit.testing.v1 import AppTest

from company_gtm_enricher.people.providers import MockPeopleProvider
from company_gtm_enricher.providers.mock import MockEnrichmentProvider


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("SERPER_API_KEY", "")


def app():
    return AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()


def button(page, label):
    return next(item for item in page.button if item.label == label)


def test_keys_are_masked_session_specific_and_survive_mode_switches(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "server-openai-test")
    monkeypatch.setenv("SERPER_API_KEY", "server-serper-test")
    first, second = app(), app()
    for page in (first, second):
        assert not page.exception
        assert page.text_input(key="session_openai_api_key").value == ""
        assert page.text_input(key="session_serper_api_key").value == ""
        assert page.text_input(key="session_openai_api_key").proto.type == TextInput.PASSWORD
        assert page.text_input(key="session_serper_api_key").proto.type == TextInput.PASSWORD
    first.text_input(key="session_openai_api_key").set_value("first-openai-test").run()
    first.text_input(key="session_serper_api_key").set_value("first-serper-test").run()
    first.sidebar.radio[0].set_value("People").run()
    first.sidebar.radio[0].set_value("Company facts").run()
    assert not first.exception
    assert first.text_input(key="session_openai_api_key").value == "first-openai-test"
    second.run()
    assert second.text_input(key="session_openai_api_key").value == ""
    assert second.text_input(key="session_serper_api_key").value == ""
    assert os.environ["OPENAI_API_KEY"] == "server-openai-test"
    assert os.environ["SERPER_API_KEY"] == "server-serper-test"
    button(first, "Clear entered keys").click().run()
    assert not first.exception
    assert first.text_input(key="session_openai_api_key").value == ""
    assert first.text_input(key="session_serper_api_key").value == ""
    assert any(caption.value == "OpenAI: app owner's key" for caption in first.caption)


def test_people_uses_entered_keys_for_validation_and_provider(monkeypatch):
    uploaded = io.BytesIO(b"company,domain\nExample,example.com\n")
    uploaded.name = "companies.csv"
    monkeypatch.setattr(st, "file_uploader", lambda *args, **kwargs: uploaded)
    captured = []

    def provider(name, **kwargs):
        captured.append((name, kwargs))
        return MockPeopleProvider()

    monkeypatch.setattr("company_gtm_enricher.people.ui.create_people_provider", provider)
    page = app()
    page.sidebar.radio[0].set_value("People").run()
    next(item for item in page.selectbox if item.label == "People source").set_value("Search + LLM").run()
    assert button(page, "Find people").disabled
    page.text_input(key="session_openai_api_key").set_value(" session-openai-test ").run()
    assert button(page, "Find people").disabled
    page.text_input(key="session_serper_api_key").set_value(" session-serper-test ").run()
    assert not page.exception
    assert not button(page, "Find people").disabled
    assert not any("Configure OPENAI_API_KEY" in warning.value for warning in page.warning)
    button(page, "Find people").click().run()
    job = page.session_state["people_job"]
    job.thread.join(5)
    page.run()
    assert not page.exception
    assert job.status == "completed"
    assert captured == [("openai", {
        "max_queries_per_company": 4, "max_candidates": 40,
        "openai_api_key_override": "session-openai-test",
        "serper_api_key_override": "session-serper-test",
        "company_founder_pages": False,
    })]
    assert "session-openai-test" not in str(job.result.run_settings)
    assert "session-serper-test" not in str(job.result.run_settings)
    assert os.environ["OPENAI_API_KEY"] == os.environ["SERPER_API_KEY"] == ""
    button(page, "Clear entered keys").click().run()
    assert button(page, "Find people").disabled


def test_company_provider_uses_session_key_then_server_fallback(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "server-openai-test")
    uploaded = io.BytesIO(b"company\nExample\n")
    uploaded.name = "companies.csv"
    monkeypatch.setattr(st, "file_uploader", lambda *args, **kwargs: uploaded)
    captured = []

    def provider(provider_name, config, model_override):
        captured.append(config.openai_api_key)
        return MockEnrichmentProvider()

    monkeypatch.setattr("company_gtm_enricher.providers.factory.create_provider", provider)
    page = app()
    page.text_input(key="session_openai_api_key").set_value("session-openai-test").run()
    button(page, "Enrich CSV").click().run()
    job = page.session_state["enrichment_job"]
    job.thread.join(5)
    page.run()
    assert not page.exception
    assert job.status == "completed"
    assert captured == ["session-openai-test"]
    button(page, "Clear entered keys").click().run()
    button(page, "Enrich CSV").click().run()
    page.session_state["enrichment_job"].thread.join(5)
    assert not page.exception
    assert captured == ["session-openai-test", "server-openai-test"]
    assert os.environ["OPENAI_API_KEY"] == "server-openai-test"


def test_credentials_locked_during_active_run():
    def controls():
        import streamlit as st
        from company_gtm_enricher.credentials_ui import render_api_keys
        render_api_keys(disabled=st.checkbox("Simulate active run"))

    page = AppTest.from_function(controls).run()
    page.text_input(key="session_openai_api_key").set_value("session-openai-test").run()
    page.checkbox[0].check().run()
    assert not page.exception
    assert page.text_input(key="session_openai_api_key").disabled
    assert page.text_input(key="session_serper_api_key").disabled
    assert button(page, "Clear entered keys").disabled
    page.checkbox[0].uncheck().run()
    assert page.text_input(key="session_openai_api_key").value == "session-openai-test"
    assert not button(page, "Clear entered keys").disabled
