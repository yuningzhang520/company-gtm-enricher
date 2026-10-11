import json
import traceback
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest
from openai import APIConnectionError, APIError, APIStatusError, AuthenticationError

from company_gtm_enricher.enrichment_service import CompanyEnrichmentService
from company_gtm_enricher.providers.openai_provider import OpenAIEnrichmentProvider


SECRET = "sk-private-test-credential"
UPSTREAM_TEXT = "private-upstream-response"


def api_error(kind):
    request = SimpleNamespace(url="https://api.openai.com/v1/chat/completions")
    message = f"{UPSTREAM_TEXT}: rejected API key {SECRET}"
    body = {"message": message}
    if kind == "connection":
        return APIConnectionError(message=message, request=request)
    if kind == "generic":
        return APIError(message, request=request, body=body)
    status = {"authentication": 401, "permissions": 403, "quota": 429, "rate": 429, "request": 400, "server": 503}[kind]
    if kind == "quota":
        body["code"] = "insufficient_quota"
    response = SimpleNamespace(status_code=status, request=request, headers={})
    error_type = AuthenticationError if kind == "authentication" else APIStatusError
    return error_type(message, response=response, body=body)


@pytest.fixture
def provider_and_client(monkeypatch):
    client = Mock()
    monkeypatch.setattr("openai.OpenAI", Mock(return_value=client))
    provider = OpenAIEnrichmentProvider(SECRET, "existing-company-model", 45)
    return provider, client


@pytest.mark.parametrize("batch", [False, True], ids=["single", "batch"])
@pytest.mark.parametrize("kind,expected", [
    ("authentication", "HTTP 401"),
    ("permissions", "permissions"),
    ("quota", "credits and billing quota"),
    ("rate", "rate or quota limit"),
    ("request", "selected model"),
    ("server", "temporarily unavailable"),
    ("connection", "network connection"),
    ("generic", "Check API configuration"),
])
def test_api_errors_never_surface_key_or_response_body(provider_and_client, batch, kind, expected):
    provider, client = provider_and_client
    client.chat.completions.create.side_effect = api_error(kind)

    with pytest.raises(RuntimeError, match=expected) as captured:
        if batch:
            provider.enrich_companies(["Example One", "Example Two"])
        else:
            provider.enrich_company("Example One")

    rendered = "".join(traceback.format_exception(captured.value))
    assert SECRET not in rendered
    assert UPSTREAM_TEXT not in rendered
    assert captured.value.__suppress_context__
    assert client.chat.completions.create.call_count == 1


def test_authentication_error_is_safe_in_company_csv_and_batch_fallback(provider_and_client):
    provider, client = provider_and_client
    client.chat.completions.create.side_effect = api_error("authentication")
    enriched = CompanyEnrichmentService(provider).enrich_dataframe(
        pd.DataFrame({"company": ["Example One", "Example Two"]}), "company", batch_size=2,
    )
    csv = enriched.to_csv(index=False)
    assert SECRET not in csv
    assert UPSTREAM_TEXT not in csv
    assert enriched["Enrichment Status"].tolist() == ["error", "error"]
    assert enriched["Research Notes"].str.contains("HTTP 401", regex=False).all()
    assert client.chat.completions.create.call_count == 3


@pytest.mark.parametrize("batch", [False, True], ids=["single", "batch"])
def test_successful_requests_keep_company_model_and_result_behavior(provider_and_client, batch):
    provider, client = provider_and_client
    record = {"company_name": "Example One", "hq_city": "Example City", "confidence": "high"}
    payload = {"companies": [record]} if batch else record
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))],
    )

    result = provider.enrich_companies(["Example One"])["Example One"] if batch else provider.enrich_company("Example One")

    assert result.hq_city == "Example City"
    assert result.confidence == "high"
    assert client.chat.completions.create.call_args.kwargs["model"] == "existing-company-model"
    assert client.chat.completions.create.call_args.kwargs["response_format"] == {"type": "json_object"}
