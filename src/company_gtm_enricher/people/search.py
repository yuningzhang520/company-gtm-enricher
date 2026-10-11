from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Callable, Optional
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from company_gtm_enricher.people.providers import FatalProviderError

SERPER_ENDPOINT = "https://google.serper.dev/search"
MAX_RESPONSE_BYTES = 1_000_000


@dataclass(frozen=True)
class SearchHit:
    id: str
    url: str
    title: str
    snippet: str


class SearchProviderError(RuntimeError):
    """A search failed; messages deliberately exclude response bodies and keys."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _fatal_payload(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("statusCode") in (401, 402, 403):
        return True
    details = str(payload.get("message", "")) + " " + str(payload.get("error", ""))
    return any(word in details.casefold() for word in (
        "credit", "insufficient_quota", "insufficient balance", "invalid api key",
        "invalid api-key", "unauthorized", "unauthorised", "authentication",
    ))


class SerperSearchClient:
    """Search the index only. Returned profile URLs are never fetched.

    ``opener`` is an injectable urllib-compatible callable for offline tests.
    The default opener rejects redirects, keeping credentials on the fixed endpoint.
    """

    def __init__(
        self, api_key: str, timeout: float = 30, max_retries: int = 1,
        *, opener: Optional[Callable] = None, sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key.strip():
            raise ValueError("SERPER_API_KEY is required for live people search.")
        if isinstance(timeout, bool) or not 0 < timeout <= 120:
            raise ValueError("Search timeout must be between 0 and 120 seconds.")
        if type(max_retries) is not int or not 0 <= max_retries <= 3:
            raise ValueError("Search max_retries must be an integer between 0 and 3.")
        self._api_key = api_key.strip()
        self.timeout = timeout
        self.max_retries = max_retries
        self._open = opener or build_opener(_NoRedirect()).open
        self._sleep = sleeper
        self.usage: dict[str, int] = {"search_requests": 0}

    def search(self, query: str) -> list[SearchHit]:
        if not query.strip():
            raise ValueError("Search query must not be empty.")
        request = Request(
            SERPER_ENDPOINT, method="POST",
            headers={"X-API-KEY": self._api_key, "Content-Type": "application/json"},
            data=json.dumps({"q": query, "num": 10}).encode("utf-8"),
        )
        for attempt in range(self.max_retries + 1):
            self.usage["search_requests"] += 1
            payload = None
            status = 200
            try:
                with self._open(request, timeout=self.timeout) as response:
                    status = response.status
                    body = response.read(MAX_RESPONSE_BYTES + 1)
            except HTTPError as exc:
                status = exc.code
                try:
                    body = exc.read(MAX_RESPONSE_BYTES + 1)
                except Exception:
                    body = b""
                finally:
                    exc.close()
            except (URLError, OSError, TimeoutError):
                if attempt < self.max_retries:
                    self._sleep(0.25 * (2 ** attempt))
                    continue
                raise SearchProviderError("Serper network request failed after bounded retries.") from None
            except Exception:
                raise SearchProviderError("Serper transport failed.") from None

            try:
                if len(body) <= MAX_RESPONSE_BYTES:
                    payload = json.loads(body)
            except (ValueError, UnicodeError):
                pass
            if isinstance(payload, dict):
                credits = payload.get("credits")
                if type(credits) is int and credits >= 0:
                    self.usage["search_credits"] = self.usage.get("search_credits", 0) + credits
                reported_status = payload.get("statusCode")
                if type(reported_status) is int and reported_status >= 400:
                    status = reported_status
            if status in (401, 402, 403) or _fatal_payload(payload):
                raise FatalProviderError("Serper authentication or credit limit requires attention.") from None
            if status == 429 or 500 <= status < 600:
                if attempt < self.max_retries:
                    self._sleep(0.25 * (2 ** attempt))
                    continue
                raise SearchProviderError(f"Serper request failed (HTTP {status}) after bounded retries.") from None
            if status != 200:
                raise SearchProviderError(f"Serper request failed (HTTP {status}).") from None
            if not isinstance(payload, dict) or payload.get("error") or payload.get("message") or "organic" not in payload:
                raise SearchProviderError("Serper returned an invalid search response.")
            organic = payload["organic"]
            if not isinstance(organic, list):
                raise SearchProviderError("Serper returned malformed organic results.")
            hits = []
            for index, item in enumerate(organic):
                if (
                    not isinstance(item, dict)
                    or not isinstance(item.get("title"), str) or not item["title"].strip()
                    or not isinstance(item.get("link"), str) or not item["link"].strip()
                    or not isinstance(item.get("snippet", ""), str)
                ):
                    raise SearchProviderError("Serper returned a malformed search result.")
                hits.append(SearchHit(str(index + 1), item["link"], item["title"], item.get("snippet", "")))
            return hits
        raise AssertionError("Unreachable search retry state.")
