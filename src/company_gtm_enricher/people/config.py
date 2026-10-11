from __future__ import annotations

from dataclasses import dataclass, field
import os

from dotenv import load_dotenv

from .providers import MockPeopleProvider, PeopleProvider


@dataclass(frozen=True)
class PeopleSettings:
    openai_api_key: str = field(default="", repr=False)
    serper_api_key: str = field(default="", repr=False)
    model: str = "gpt-5-mini"
    timeout: float = 90.0
    max_queries_per_company: int = 4
    max_candidates: int = 40
    llm_max_retries: int = 2

    @classmethod
    def from_env(
        cls, *, openai_api_key_override: str = "", serper_api_key_override: str = "",
    ) -> "PeopleSettings":
        """Resolve per-session credentials without persisting the overrides."""
        load_dotenv()
        try:
            settings = cls(
                openai_api_key=openai_api_key_override.strip() or os.getenv("OPENAI_API_KEY", "").strip(),
                serper_api_key=serper_api_key_override.strip() or os.getenv("SERPER_API_KEY", "").strip(),
                model=os.getenv("OPENAI_PEOPLE_MODEL", cls.model).strip(),
                timeout=float(os.getenv("PEOPLE_TIMEOUT_SECONDS", str(cls.timeout))),
                max_queries_per_company=int(os.getenv("PEOPLE_MAX_QUERIES_PER_COMPANY", str(cls.max_queries_per_company))),
                max_candidates=int(os.getenv("PEOPLE_MAX_CANDIDATES", str(cls.max_candidates))),
                llm_max_retries=int(os.getenv("PEOPLE_LLM_MAX_RETRIES", str(cls.llm_max_retries))),
            )
        except ValueError as exc:
            raise ValueError("People timeout/query/candidate/retry settings must be numeric.") from exc
        if not settings.model or not 0 < settings.timeout <= 120:
            raise ValueError("Set a people model and a timeout between 0 and 120 seconds.")
        if not 1 <= settings.max_queries_per_company <= 20 or not 1 <= settings.max_candidates <= 100:
            raise ValueError("People limits must be 1–20 queries and 1–100 candidates per company.")
        if not 0 <= settings.llm_max_retries <= 2:
            raise ValueError("Model retries must be between 0 and 2.")
        return settings

    @property
    def missing_keys(self) -> list[str]:
        return [name for name, value in (
            ("OPENAI_API_KEY", self.openai_api_key), ("SERPER_API_KEY", self.serper_api_key),
        ) if not value]


def create_people_provider(
    name: str, *, model_override: str = "",
    max_queries_per_company: int | None = None, max_candidates: int | None = None,
    openai_api_key_override: str = "", serper_api_key_override: str = "",
    company_founder_pages: bool = False,
    llm_max_retries: int | None = None,
) -> PeopleProvider:
    if name == "mock":
        return MockPeopleProvider()
    if name != "openai":
        raise ValueError(f"Unknown people provider: {name}")
    settings = PeopleSettings.from_env(
        openai_api_key_override=openai_api_key_override,
        serper_api_key_override=serper_api_key_override,
    )
    missing_keys = settings.missing_keys
    if missing_keys:
        raise ValueError("Set " + " and ".join(missing_keys) + " in the API keys sidebar or local .env to run live people search.")
    query_limit = settings.max_queries_per_company if max_queries_per_company is None else max_queries_per_company
    candidate_limit = settings.max_candidates if max_candidates is None else max_candidates
    retries = settings.llm_max_retries if llm_max_retries is None else llm_max_retries
    # Match provider limits, but reject invalid overrides before allocating clients.
    for value, minimum, maximum, label in (
        (query_limit, 1, 50, "Queries per company"),
        (candidate_limit, 1, 200, "Candidate limit"),
        (retries, 0, 2, "Model retries"),
    ):
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError(f"{label} must be between {minimum} and {maximum}.")

    from openai import OpenAI
    from .classification import OpenAIRoleClassifier
    from .live import LiveSearchPeopleProvider
    from .search import SerperSearchClient

    client = OpenAI(
        api_key=settings.openai_api_key, base_url="https://api.openai.com/v1",
        timeout=settings.timeout, max_retries=0,
    )
    company_pages = None
    if company_founder_pages:
        from .company_pages import CompanyFounderSource
        from .public_pages import PublicPageClient

        company_pages = CompanyFounderSource(client=PublicPageClient(), max_pages=3)
    return LiveSearchPeopleProvider(
        SerperSearchClient(settings.serper_api_key, timeout=settings.timeout, max_retries=1),
        OpenAIRoleClassifier(client, model=model_override.strip() or settings.model, max_retries=retries),
        max_queries_per_company=query_limit,
        max_candidates=candidate_limit,
        company_pages=company_pages,
    )
