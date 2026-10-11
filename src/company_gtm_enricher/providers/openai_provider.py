from __future__ import annotations

import json
from typing import Any, Dict, Optional, Sequence

from company_gtm_enricher.models import CompanyEnrichment


COMMON_RULES = """
You enrich company records with public go-to-market research.

Rules:
- Use public web information and prefer official company pages, regulatory filings, Crunchbase, LinkedIn, or reputable business databases.
- If a value cannot be found confidently, use "Unknown".
- approximate_annual_revenue must stay approximate, for example "$50M-$100M" or "Unknown".
- current_total_funding must be the best current total funding estimate, for example "$290M" or "Public company".
- source_urls must be an array of up to 5 URLs.
- confidence must be one of: high, medium, low.
- notes must be one short sentence with any material caveat.
- Return JSON only. Do not wrap it in markdown.
""".strip()

SINGLE_SYSTEM_PROMPT = (
    COMMON_RULES
    + "\n\nReturn exactly one JSON object with these keys:\n"
    + "- hq_city\n- hq_state\n- country\n- approximate_annual_revenue\n"
    + "- current_total_funding\n- confidence\n- source_urls\n- notes"
)

BATCH_SYSTEM_PROMPT = (
    COMMON_RULES
    + "\n\nReturn exactly one JSON object with this shape:\n"
    + '{\n  "companies": [\n    {\n      "company_name": "...",\n      "hq_city": "...",\n'
    + '      "hq_state": "...",\n      "country": "...",\n'
    + '      "approximate_annual_revenue": "...",\n      "current_total_funding": "...",\n'
    + '      "confidence": "...",\n      "source_urls": ["..."],\n      "notes": "..."\n    }\n  ]\n}\n'
    + "Return one object for every input company. `company_name` must exactly match the input string."
)


class OpenAIEnrichmentProvider:
    def __init__(
        self,
        api_key: str,
        model: str,
        timeout_seconds: float,
    ) -> None:
        if not api_key:
            raise ValueError(
                "OPENAI_API_KEY is not set. Add it in the API keys sidebar or local .env, or switch to the mock provider."
            )

        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - depends on local env
            raise ValueError(
                "The `openai` package is not installed. Run `pip install -e .[dev]` first."
            ) from exc

        self._client = OpenAI(api_key=api_key, timeout=timeout_seconds)
        self._model = model

    def _create_completion(self, **kwargs: Any) -> Any:
        from openai import APIConnectionError, APIError

        try:
            return self._client.chat.completions.create(**kwargs)
        except APIError as exc:
            # SDK error messages/bodies can contain rejected credentials. Only
            # fixed guidance and a numeric HTTP status may reach the UI/export.
            status = getattr(exc, "status_code", None)
            status = status if type(status) is int and 100 <= status <= 599 else None
            prefix = "OpenAI request failed" + (f" (HTTP {status})" if status else "") + ". "
            if status == 401:
                guidance = "Check the OpenAI API key in the sidebar or local .env."
            elif status == 403:
                guidance = "Check the API key's project and model permissions."
            elif status == 429:
                if getattr(exc, "code", None) == "insufficient_quota":
                    guidance = "Check the OpenAI project's API credits and billing quota."
                else:
                    guidance = "A rate or quota limit was reached. Check API limits and billing before retrying."
            elif isinstance(exc, APIConnectionError):
                guidance = "Check the network connection and timeout, then retry."
            elif status in (400, 404, 422):
                guidance = "Check the selected model and request settings."
            elif status is not None and status >= 500:
                guidance = "The service is temporarily unavailable. Try again later."
            else:
                guidance = "Check API configuration and try again."
            raise RuntimeError(prefix + guidance) from None

    def enrich_company(self, company_name: str) -> CompanyEnrichment:
        response = self._create_completion(
            model=self._model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SINGLE_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Research the following company and return the requested JSON fields.\n"
                        f"Company name: {company_name}"
                    ),
                },
            ],
        )
        raw_content = _message_content_to_text(response.choices[0].message.content)
        payload = _parse_json_object(raw_content)
        return _company_enrichment_from_payload(company_name, payload)

    def enrich_companies(self, company_names: Sequence[str]) -> Dict[str, CompanyEnrichment]:
        if not company_names:
            return {}

        response = self._create_completion(
            model=self._model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": BATCH_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": "Research the following companies and return one entry for each.\n"
                    + "\n".join(
                        f"{index}. {company_name}"
                        for index, company_name in enumerate(company_names, start=1)
                    ),
                },
            ],
        )
        raw_content = _message_content_to_text(response.choices[0].message.content)
        payload = _parse_json_object(raw_content)
        company_payloads = payload.get("companies")
        if not isinstance(company_payloads, list):
            raise ValueError(f"Model response did not contain a `companies` list: {raw_content}")

        original_names = {company_name.casefold(): company_name for company_name in company_names}
        results: Dict[str, CompanyEnrichment] = {}
        for company_payload in company_payloads:
            if not isinstance(company_payload, dict):
                continue
            payload_name = str(company_payload.get("company_name", "")).strip()
            original_name = original_names.get(payload_name.casefold())
            if not original_name:
                continue
            results[original_name] = _company_enrichment_from_payload(original_name, company_payload)

        return results


def _parse_json_object(raw_content: str) -> Dict[str, Any]:
    try:
        return json.loads(raw_content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Model response was not valid JSON: {raw_content}") from exc


def _message_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content or "{}"
    if isinstance(content, list):
        text_parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(str(item.get("text", "")))
        return "".join(text_parts) or "{}"
    return "{}"


def _company_enrichment_from_payload(
    company_name: str,
    payload: Dict[str, Any],
) -> CompanyEnrichment:
    return CompanyEnrichment(
        company_name=company_name,
        hq_city=_string_value(payload, "hq_city"),
        hq_state=_string_value(payload, "hq_state"),
        country=_string_value(payload, "country"),
        approximate_annual_revenue=_string_value(payload, "approximate_annual_revenue"),
        current_total_funding=_string_value(payload, "current_total_funding"),
        confidence=_confidence_value(payload.get("confidence")),
        source_urls=_source_urls(payload.get("source_urls")),
        notes=_string_value(payload, "notes"),
    )


def _string_value(payload: Dict[str, Any], key: str) -> str:
    value = payload.get(key, "Unknown")
    if value is None:
        return "Unknown"
    return str(value).strip() or "Unknown"


def _confidence_value(value: Optional[Any]) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"high", "medium", "low"}:
        return normalized
    return "low"


def _source_urls(value: Optional[Any]) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()][:5]
    if value is None:
        return []
    text = str(value).strip()
    return [text] if text else []
