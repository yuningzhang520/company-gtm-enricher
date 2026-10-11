import os
from unittest.mock import Mock

import pytest

from company_gtm_enricher.people.config import PeopleSettings, create_people_provider


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch):
    monkeypatch.setattr("company_gtm_enricher.people.config.load_dotenv", lambda: None)
    for name in ("OPENAI_API_KEY", "SERPER_API_KEY", "OPENAI_PEOPLE_MODEL", "PEOPLE_TIMEOUT_SECONDS", "PEOPLE_MAX_QUERIES_PER_COMPANY", "PEOPLE_MAX_CANDIDATES", "PEOPLE_LLM_MAX_RETRIES"):
        monkeypatch.delenv(name, raising=False)


def test_mock_needs_no_keys_and_live_fails_before_client_construction():
    assert create_people_provider("mock").is_mock
    with pytest.raises(ValueError, match="OPENAI_API_KEY and SERPER_API_KEY"):
        create_people_provider("openai")


def test_people_config_is_independent_of_company_model_and_hides_keys(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "company-model")
    monkeypatch.setenv("OPENAI_PEOPLE_MODEL", "people-model")
    monkeypatch.setenv("OPENAI_API_KEY", "private-openai-test-key")
    monkeypatch.setenv("SERPER_API_KEY", "private-search-test-key")
    settings = PeopleSettings.from_env()
    assert settings.model == "people-model"
    assert not settings.missing_keys
    assert "private" not in repr(settings)


def test_session_keys_override_environment_without_leaking_to_other_sessions(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "server-openai-key")
    monkeypatch.setenv("SERPER_API_KEY", "server-serper-key")
    first = PeopleSettings.from_env(
        openai_api_key_override="  first-openai-key  ",
        serper_api_key_override="  first-serper-key  ",
    )
    second = PeopleSettings.from_env(openai_api_key_override="second-openai-key")
    server = PeopleSettings.from_env()

    assert (first.openai_api_key, first.serper_api_key) == ("first-openai-key", "first-serper-key")
    assert (second.openai_api_key, second.serper_api_key) == ("second-openai-key", "server-serper-key")
    assert (server.openai_api_key, server.serper_api_key) == ("server-openai-key", "server-serper-key")
    assert os.environ["OPENAI_API_KEY"] == "server-openai-key"
    assert os.environ["SERPER_API_KEY"] == "server-serper-key"
    assert "first-openai-key" not in repr(first)
    assert "first-serper-key" not in repr(first)


def test_blank_session_keys_fall_back_to_environment(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "  server-openai-key  ")
    settings = PeopleSettings.from_env(openai_api_key_override=" \n", serper_api_key_override=" ")
    assert settings.openai_api_key == "server-openai-key"
    assert settings.missing_keys == ["SERPER_API_KEY"]


@pytest.mark.parametrize("serper_override,expected_serper", [
    ("  session-serper-key  ", "session-serper-key"),
    ("", "server-serper-key"),
])
def test_factory_passes_session_keys_only_to_clients(monkeypatch, serper_override, expected_serper):
    monkeypatch.setenv("OPENAI_API_KEY", "server-openai-key")
    monkeypatch.setenv("SERPER_API_KEY", "server-serper-key")
    openai_factory = Mock()
    search_factory = Mock()
    monkeypatch.setattr("openai.OpenAI", openai_factory)
    monkeypatch.setattr("company_gtm_enricher.people.search.SerperSearchClient", search_factory)

    provider = create_people_provider(
        "openai", openai_api_key_override="  session-openai-key  ",
        serper_api_key_override=serper_override,
    )

    openai_factory.assert_called_once_with(
        api_key="session-openai-key", base_url="https://api.openai.com/v1", timeout=90.0, max_retries=0,
    )
    search_factory.assert_called_once_with(expected_serper, timeout=90.0, max_retries=1)
    openai_factory.return_value.responses.create.assert_not_called()
    search_factory.return_value.search.assert_not_called()
    assert provider.classifier.client is openai_factory.return_value
    assert provider.search_client is search_factory.return_value
    assert provider.settings == {
        "search_source": "Serper Google Search", "classification_model": "gpt-5-mini",
        "max_queries_per_company": 4, "max_candidates": 40,
        "llm_max_retries": 2,
    }
    assert os.environ["OPENAI_API_KEY"] == "server-openai-key"
    assert os.environ["SERPER_API_KEY"] == "server-serper-key"


def test_mock_bypasses_session_and_environment_settings(monkeypatch):
    monkeypatch.setenv("PEOPLE_TIMEOUT_SECONDS", "invalid")
    assert create_people_provider("mock", openai_api_key_override="session-openai-key").is_mock


@pytest.mark.parametrize("key,value", [
    ("PEOPLE_TIMEOUT_SECONDS", "nan"), ("PEOPLE_TIMEOUT_SECONDS", "inf"),
    ("PEOPLE_MAX_QUERIES_PER_COMPANY", "0"), ("PEOPLE_MAX_CANDIDATES", "-1"),
    ("PEOPLE_MAX_CANDIDATES", "many"),
    ("PEOPLE_LLM_MAX_RETRIES", "-1"), ("PEOPLE_LLM_MAX_RETRIES", "3"),
    ("PEOPLE_LLM_MAX_RETRIES", "bad"),
])
def test_invalid_people_limits_rejected_before_requests(monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with pytest.raises(ValueError):
        PeopleSettings.from_env()


def test_model_retries_can_be_disabled_for_a_frozen_budget(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("SERPER_API_KEY", "test")
    client = Mock()
    monkeypatch.setattr("openai.OpenAI", client)
    provider = create_people_provider("openai", llm_max_retries=0)
    assert provider.classifier.max_retries == 0
    assert provider.settings["llm_max_retries"] == 0
    client.return_value.responses.create.assert_not_called()


def test_invalid_model_retry_override_rejected_before_client_creation(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("SERPER_API_KEY", "test")
    client = Mock()
    monkeypatch.setattr("openai.OpenAI", client)
    with pytest.raises(ValueError, match="retries"):
        create_people_provider("openai", llm_max_retries=3)
    client.assert_not_called()


@pytest.mark.parametrize("option,value", [
    ("max_queries_per_company", 0), ("max_queries_per_company", 51),
    ("max_queries_per_company", True), ("max_queries_per_company", 1.5),
    ("max_candidates", 0), ("max_candidates", 201),
    ("max_candidates", False), ("max_candidates", "2"),
    ("llm_max_retries", False),
])
def test_invalid_budget_overrides_rejected_before_allocating_clients(monkeypatch, option, value):
    client = Mock()
    search = Mock()
    monkeypatch.setattr("openai.OpenAI", client)
    monkeypatch.setattr("company_gtm_enricher.people.search.SerperSearchClient", search)

    with pytest.raises(ValueError, match="must be between"):
        create_people_provider(
            "openai", openai_api_key_override="test", serper_api_key_override="test",
            **{option: value},
        )

    client.assert_not_called()
    search.assert_not_called()


def test_budget_overrides_preserve_provider_supported_upper_limits(monkeypatch):
    client = Mock()
    search = Mock()
    monkeypatch.setattr("openai.OpenAI", client)
    monkeypatch.setattr("company_gtm_enricher.people.search.SerperSearchClient", search)

    provider = create_people_provider(
        "openai", openai_api_key_override="test", serper_api_key_override="test",
        max_queries_per_company=50, max_candidates=200,
    )

    assert provider.max_queries_per_company == 50
    assert provider.max_candidates == 200
    client.return_value.responses.create.assert_not_called()
    search.return_value.search.assert_not_called()
