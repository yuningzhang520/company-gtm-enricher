"""Offline coverage of a predeclared reference list in an exported PeopleResult."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import unicodedata

from company_gtm_enricher.people.identity import canonical_linkedin_url


def _normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


def _validate(result: object, reference: object) -> None:
    if not isinstance(result, dict):
        raise ValueError("Result must be a PeopleResult JSON object.")
    for bucket in ("people", "review"):
        if not isinstance(result.get(bucket), list):
            raise ValueError(f"Result '{bucket}' must be an array.")
        for index, row in enumerate(result[bucket]):
            if not isinstance(row, dict):
                raise ValueError(f"Result {bucket}[{index}] must be an object.")
            for field in ("Company", "Name", "LinkedIn URL", "Status"):
                if not isinstance(row.get(field), str):
                    raise ValueError(f"Result {bucket}[{index}].{field} must be a string.")
            for field in ("Title", "Department", "Seniority"):
                if field in row and not isinstance(row[field], str):
                    raise ValueError(f"Result {bucket}[{index}].{field} must be a string.")
            if not row["Company"].strip():
                raise ValueError(f"Result {bucket}[{index}].Company must not be blank.")
    for field in ("usage", "run_settings"):
        if field in result and not isinstance(result[field], dict):
            raise ValueError(f"Result '{field}' must be an object.")
    if "is_mock" in result and not isinstance(result["is_mock"], bool):
        raise ValueError("Result 'is_mock' must be a boolean.")
    if not isinstance(reference, list):
        raise ValueError("Reference must be an array of company/name objects.")
    names, profiles = set(), set()
    allowed = {"company", "name", "linkedin_url", "role_source_url",
               "expected_departments", "expected_seniority"}
    for index, item in enumerate(reference):
        if not isinstance(item, dict) or set(item) - allowed:
            raise ValueError(f"Reference[{index}] must contain only company, name, linkedin_url, "
                             "role_source_url, expected_departments, expected_seniority.")
        for field in ("company", "name"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                raise ValueError(f"Reference[{index}].{field} must be a nonblank string.")
        for field in ("linkedin_url", "role_source_url"):
            if field in item and not isinstance(item[field], str):
                raise ValueError(f"Reference[{index}].{field} must be a string.")
        for field in ("expected_departments", "expected_seniority"):
            if field in item and (not isinstance(item[field], list) or not item[field] or
                                  any(not isinstance(value, str) or not value.strip()
                                      for value in item[field])):
                raise ValueError(f"Reference[{index}].{field} must be a nonempty array of nonblank strings.")
        company, name = _normalized(item["company"]), _normalized(item["name"])
        profile = canonical_linkedin_url(item.get("linkedin_url", ""))
        if item.get("linkedin_url", "").strip() and not profile:
            raise ValueError(f"Reference[{index}].linkedin_url must be a personal LinkedIn profile URL.")
        if (company, name) in names or (profile and (company, profile) in profiles):
            raise ValueError(f"Reference[{index}] duplicates a company/name or company/profile identity.")
        names.add((company, name))
        if profile:
            profiles.add((company, profile))


def evaluate_result(result: dict, reference: list[dict]) -> dict:
    """Count reference placements; this does not independently verify roles or employment."""
    _validate(result, reference)
    rows = [
        {"placement": bucket, "index": index, "company": row["Company"],
         "name": row["Name"], "linkedin_url": canonical_linkedin_url(row["LinkedIn URL"]),
         "status": row["Status"], "title": row.get("Title", ""),
         "department": row.get("Department", ""), "seniority": row.get("Seniority", "")}
        for bucket in ("people", "review")
        for index, row in enumerate(result[bucket])
    ]
    evaluated = []
    for item in reference:
        company, name = _normalized(item["company"]), _normalized(item["name"])
        profile = canonical_linkedin_url(item.get("linkedin_url", ""))
        company_rows = [row for row in rows if _normalized(row["company"]) == company]
        matches = [row for row in company_rows if (
            row["linkedin_url"] == profile if profile else _normalized(row["name"]) == name
        )]
        issues = []
        if len(matches) > 1:
            issues.append("Multiple rows share the reference identity; coverage is ambiguous.")
        if profile and any(_normalized(row["name"]) not in ("", name) for row in matches):
            issues.append("Profile URL matches but the full name differs from the reference.")
        if any(not _normalized(row["name"]) for row in matches):
            issues.append("The profile was retained without an extracted name.")
        # A name-only match must not hide a duplicate profile with a different name.
        for row in matches:
            duplicates = [other for other in company_rows if row["linkedin_url"] and
                          other["linkedin_url"] == row["linkedin_url"]]
            if len(duplicates) > 1 and len(matches) == 1:
                issues.append("The matched profile appears in multiple rows; coverage is ambiguous.")
        related = []
        if not matches:
            related = [row for row in company_rows if _normalized(row["name"]) == name]
            if profile and related:
                issues.append("The full name occurs under a different or missing profile URL.")
            other_companies = [row for row in rows if profile and row["linkedin_url"] == profile
                               and _normalized(row["company"]) != company]
            if other_companies:
                issues.append("The expected profile occurs under a different company.")
                related.extend(other_companies)
        placements = {row["placement"] for row in matches}
        placement = "people" if "people" in placements else "review" if placements else "missing"
        if len(placements) > 1:
            issues.append("The reference occurs in both People and Review.")
        expectations = {field: [value.strip() for value in item[field]]
                        for field in ("expected_departments", "expected_seniority") if field in item}
        for field, observed_field in (("expected_departments", "department"),
                                      ("expected_seniority", "seniority")):
            if field not in expectations:
                continue
            allowed_values = {_normalized(value) for value in expectations[field]}
            for row in matches:
                value = row[observed_field]
                if not _normalized(value):
                    issues.append(f"The matched row has no {observed_field}; expected one of "
                                  f"{expectations[field]}.")
                elif _normalized(value) not in allowed_values:
                    issues.append(f"The matched row {observed_field} '{value}' does not match "
                                  f"the expected values {expectations[field]}.")
        supported = bool(
            len(matches) == 1 and not issues and placement == "people"
            and matches[0]["status"] == "supported" and not result.get("is_mock", False)
        )
        if placement == "people" and any(row["status"] != "supported" for row in matches):
            issues.append("The People row is not marked supported.")
        if result.get("is_mock", False) and matches:
            issues.append("Synthetic demo results do not count as supported reference coverage.")
        evaluated.append({
            "company": item["company"].strip(), "name": item["name"].strip(),
            "linkedin_url": profile, "role_source_url": item.get("role_source_url", ""),
            "match_basis": "profile_url" if profile else "name_only",
            "placement": placement, "supported": supported,
            "issues": list(dict.fromkeys(issues)), "observed_rows": matches,
            "related_rows": related, **expectations,
        })
    supported = sum(item["supported"] for item in evaluated)
    people_count, review_count = len(result["people"]), len(result["review"])
    return {
        "scope": "Coverage against this reference only; not full-roster recall, precision, or independent identity/role verification. Name-only matches are weaker evidence. Optional role expectations compare exported labels, not independently verified current titles. People placement counts presence even when role expectations fail.",
        "rows": {"people": people_count, "review": review_count,
                 "review_rate": review_count / (people_count + review_count) if people_count + review_count else None},
        "reference_count": len(reference), "supported_reference_count": supported,
        "supported_reference_rate": supported / len(reference) if reference else None,
        "people_reference_count": sum(item["placement"] == "people" for item in evaluated),
        "review_reference_count": sum(item["placement"] == "review" for item in evaluated),
        "missing_reference_count": sum(item["placement"] == "missing" for item in evaluated),
        "role_expected_reference_count": sum(
            "expected_departments" in item or "expected_seniority" in item for item in evaluated),
        "role_qualified_reference_count": sum(
            item["supported"] and ("expected_departments" in item or "expected_seniority" in item)
            for item in evaluated),
        "profile_reference_count": sum(item["match_basis"] == "profile_url" for item in evaluated),
        "name_only_reference_count": sum(item["match_basis"] == "name_only" for item in evaluated),
        "supported_profile_reference_count": sum(item["supported"] and item["match_basis"] == "profile_url" for item in evaluated),
        "supported_name_only_reference_count": sum(item["supported"] and item["match_basis"] == "name_only" for item in evaluated),
        "references": evaluated,
        "run": deepcopy({field: result[field] for field in (
            "status", "is_mock", "elapsed_seconds", "provider_calls", "usage", "run_settings",
        ) if field in result}),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", required=True, type=Path, help="Exported PeopleResult JSON")
    parser.add_argument("--reference", required=True, type=Path, help="Predeclared reference JSON array")
    parser.add_argument("--output", type=Path, help="Optional report JSON file")
    args = parser.parse_args(argv)
    try:
        if args.output and args.output.resolve() in {args.result.resolve(), args.reference.resolve()}:
            raise ValueError("Report output must differ from both input files.")
        result = json.loads(args.result.read_text(encoding="utf-8"))
        reference = json.loads(args.reference.read_text(encoding="utf-8"))
        report = json.dumps(evaluate_result(result, reference), ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        if args.output:
            args.output.write_text(report, encoding="utf-8")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(report, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
