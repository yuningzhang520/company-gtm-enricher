from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from company_gtm_enricher.config import AppConfig
from company_gtm_enricher.csv_tools import (
    CSVValidationError,
    dataframe_to_csv_bytes,
    detect_company_column,
    load_dataframe_from_csv_bytes,
)
from company_gtm_enricher.enrichment_service import CompanyEnrichmentService
from company_gtm_enricher.providers.factory import create_provider


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Enrich a CSV of company names with GTM data.")
    parser.add_argument("--input", required=True, help="Path to the input CSV file.")
    parser.add_argument("--output", required=True, help="Output CSV for company facts or .xlsx for people.")
    parser.add_argument("--mode", choices=("company", "people"), default="company", help="Company facts CSV or people Excel.")
    parser.add_argument(
        "--company-column",
        default="",
        help="Optional company-name column. If omitted, the tool tries to infer it.",
    )
    parser.add_argument(
        "--provider",
        choices=("openai", "mock"),
        default="openai",
        help="Enrichment provider to use.",
    )
    parser.add_argument(
        "--model",
        default="",
        help="Optional OpenAI model override.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=0,
        help="Companies to send in each request batch. Defaults to OPENAI_BATCH_SIZE.",
    )
    parser.add_argument(
        "--no-audit-columns",
        action="store_true",
        help="Exclude confidence, source URLs, status, and notes from the output.",
    )
    people = parser.add_argument_group(
        "People options",
        "Selecting departments and leadership/IC levels guides discovery and suggested grouping. "
        "Evidence-backed profiles in adjacent roles may be included; inspect original titles and Notes. "
        "Without an active department search, results are limited to selected founder/C-level categories. "
        "Complete grounded contacts remain in People with unconfirmed employment labelled. "
        "Records without the target company name, domain or configured alias in source text are discarded from both People and Review. "
        "During department searches, a missing title alone is retained as title_missing with a blank title. "
        "Missing identity/profile facts, unsupported title extractions, explicit conflicts, and processing failures remain in Review.",
    )
    people.add_argument("--domain-column", default=None, help="Optional company-domain column; defaults to domain if present.")
    people.add_argument("--lists-column", default=None, help="Optional list-tags column; defaults to lists if present.")
    people.add_argument("--aliases-column", default=None, help="Optional known company-aliases column, separated by ; or |; defaults to aliases if present.")
    people.add_argument("--company-founder-pages", action="store_true", help="Read up to 3 public company/about/careers pages for explicitly linked founders; never fetch LinkedIn pages.")
    people.add_argument("--no-founders", action="store_true", help="Skip the founder search group; without a department search, exclude founder-only titles.")
    people.add_argument("--no-c-level", action="store_true", help="Skip the C-level search group; without a department search, exclude C-level-only titles.")
    people.add_argument("--departments", default="", help="Comma-separated department search preferences; pair with leadership or IC levels.")
    people.add_argument("--department-definitions", default=None, metavar="PATH", help="Optional JSON object mapping departments to descriptions for suggested grouping; blank descriptions remove defaults.")
    people.add_argument("--leadership-levels", default="", help="Comma-separated leadership search preferences; adjacent levels may appear.")
    people.add_argument("--ic-levels", default="", help="Comma-separated individual contributor search preferences; adjacent levels may appear.")
    people.add_argument("--columns", default=None, help="Comma-separated People output column labels; Status is always included.")
    people.add_argument("--max-queries-per-company", type=int, default=None, help="Live search query cap per company (default from .env, or 4).")
    people.add_argument("--max-candidates", type=int, default=None, help="Live candidate cap per company (default from .env, or 40).")
    people.add_argument("--result-json", default=None, help="Also save results, evidence, settings, and usage as JSON for evaluation.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    try:
        dataframe = load_dataframe_from_csv_bytes(input_path.read_bytes())
        if args.mode == "people":
            return _run_people(args, dataframe, output_path)
        company_column = args.company_column or detect_company_column(dataframe)
        config = AppConfig.from_env()
        provider = create_provider(
            provider_name=args.provider,
            config=config,
            model_override=args.model or None,
        )
        service = CompanyEnrichmentService(provider=provider)
        enriched_dataframe = service.enrich_dataframe(
            dataframe=dataframe,
            company_column=company_column,
            include_audit_columns=not args.no_audit_columns,
            batch_size=args.batch_size or config.openai_batch_size,
        )
    except (CSVValidationError, OSError, ValueError) as exc:
        parser.exit(status=1, message=f"Error: {exc}\n")

    output_path.write_bytes(dataframe_to_csv_bytes(enriched_dataframe))
    print(f"Wrote enriched CSV to {output_path}")
    return 0


def _run_people(args: argparse.Namespace, dataframe, output_path: Path) -> int:
    from company_gtm_enricher.people.excel_export import excel_bytes
    from company_gtm_enricher.people.config import create_people_provider
    from company_gtm_enricher.people.models import PeopleCriteria, PeopleResult
    from company_gtm_enricher.people.role_options import department_definitions_for
    from company_gtm_enricher.people.service import PeopleService, read_companies

    if output_path.suffix.lower() != ".xlsx":
        raise ValueError("People output must use an .xlsx filename.")
    if output_path.resolve() == Path(args.input).resolve():
        raise ValueError("Output must differ from the input file.")
    if args.result_json and Path(args.result_json).resolve() in {output_path.resolve(), Path(args.input).resolve()}:
        raise ValueError("JSON output must differ from the input and Excel output paths.")
    definitions_path = Path(args.department_definitions) if args.department_definitions else None
    if definitions_path:
        destinations = [output_path] + ([Path(args.result_json)] if args.result_json else [])
        for destination in destinations:
            if (destination.resolve() == definitions_path.resolve()
                    or (destination.exists() and definitions_path.exists() and destination.samefile(definitions_path))):
                raise ValueError("Output paths must differ from the department definitions input file.")
    column = args.company_column
    if not column:
        try:
            column = detect_company_column(dataframe)
        except CSVValidationError:
            if "input_name" not in dataframe:
                raise
            column = "input_name"

    def terms(value: str) -> tuple[str, ...]:
        return tuple(term.strip() for term in value.split(",") if term.strip())

    departments = terms(args.departments)
    definitions = None
    if definitions_path:
        try:
            definitions = json.loads(definitions_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("Department definitions must contain valid JSON.") from exc
        if not isinstance(definitions, dict):
            raise ValueError("Department definitions must be a JSON object mapping department names to descriptions.")
    criteria = PeopleCriteria(
        founders=not args.no_founders, c_level=not args.no_c_level,
        departments=departments, leadership_levels=terms(args.leadership_levels),
        ic_levels=terms(args.ic_levels),
        department_definitions=department_definitions_for(departments, definitions),
    )
    companies = read_companies(
        dataframe, column,
        domain_column=args.domain_column or ("domain" if "domain" in dataframe else None),
        lists_column=args.lists_column or ("lists" if "lists" in dataframe else None),
        aliases_column=args.aliases_column or ("aliases" if "aliases" in dataframe else None),
    )
    columns = terms(args.columns) if args.columns is not None else None
    excel_bytes(PeopleResult(), columns=columns)  # Reject invalid columns before making any paid requests.
    provider = create_people_provider(
        args.provider, model_override=args.model,
        max_queries_per_company=args.max_queries_per_company, max_candidates=args.max_candidates,
        company_founder_pages=args.company_founder_pages,
    )
    result = PeopleService(provider).run(companies, criteria)
    output_path.write_bytes(excel_bytes(result, columns=columns))
    if args.result_json:
        Path(args.result_json).write_text(json.dumps(asdict(result), indent=2, ensure_ascii=False), encoding="utf-8")
    kind = "synthetic people demo" if result.is_mock else "people search results"
    print(f"Wrote {kind} to {output_path}: {len(result.people)} people, {len(result.review)} review rows; status={result.status}.")
    print("No live research or API charges." if result.is_mock else f"Observed usage: {json.dumps(result.usage)}. API charges not measured; coverage is partial.")
    return 0 if result.status == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
