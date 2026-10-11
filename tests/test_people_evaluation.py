import json
import socket

import dotenv
import pytest

from company_gtm_enricher.people.evaluation import evaluate_result, main


PROFILE = "https://www.linkedin.com/in/alex-example"


def row(name="Alex Example", company="Example", profile=PROFILE, status="supported"):
    return {"Company": company, "Name": name, "LinkedIn URL": profile, "Status": status}


def result(people=(), review=(), **metadata):
    return {"people": list(people), "review": list(review), **metadata}


def reference(**overrides):
    return {"company": "Example", "name": "Alex Example", "linkedin_url": PROFILE, **overrides}


def test_profile_match_normalizes_company_name_and_linkedin_tracking_only():
    report = evaluate_result(result([row("  ALEX   EXAMPLE ", " example ",
                                        "http://uk.linkedin.com/in/Alex-Example/?trk=abc")]), [reference()])
    assert report["supported_reference_count"] == 1
    assert report["supported_reference_rate"] == 1.0
    assert report["supported_profile_reference_count"] == 1
    assert report["supported_name_only_reference_count"] == 0
    assert report["references"][0]["placement"] == "people"
    assert report["references"][0]["issues"] == []


def test_blank_name_review_is_retained_without_claiming_identity_or_coverage():
    report = evaluate_result(result(review=[row(name="", status="needs_review")]), [reference()])
    assert report["references"][0]["placement"] == "review"
    assert "without an extracted name" in report["references"][0]["issues"][0]
    assert report["supported_reference_count"] == 0
    assert report["rows"] == {"people": 0, "review": 1, "review_rate": 1.0}


def test_matching_name_on_wrong_profile_is_missing_and_not_a_url_match():
    report = evaluate_result(result([row(profile=PROFILE + "-different")]), [reference()])
    entry = report["references"][0]
    assert entry["placement"] == "missing"
    assert entry["supported"] is False
    assert entry["related_rows"][0]["linkedin_url"] == PROFILE + "-different"
    assert "different or missing profile URL" in entry["issues"][0]


def test_matching_profile_on_wrong_company_is_missing():
    report = evaluate_result(result([row(company="Another company")]), [reference()])
    assert report["references"][0]["placement"] == "missing"
    assert report["supported_reference_count"] == 0
    assert "different company" in report["references"][0]["issues"][0]


def test_expected_profile_with_a_different_name_exposes_identity_discrepancy():
    report = evaluate_result(result([row(name="Someone Else")]), [reference()])
    assert report["references"][0]["placement"] == "people"
    assert report["supported_reference_count"] == 0
    assert "full name differs" in report["references"][0]["issues"][0]


@pytest.mark.parametrize("people,review", [
    ([row(), row()], []),
    ([row(), row(name="Another Person")], []),
    ([row()], [row(status="needs_review")]),
])
def test_duplicate_profiles_and_bucket_conflicts_do_not_inflate_coverage(people, review):
    report = evaluate_result(result(people, review), [reference()])
    assert report["supported_reference_count"] == 0
    assert "ambiguous" in report["references"][0]["issues"][0]


def test_name_only_coverage_is_separate_and_missing_references_remain_visible():
    report = evaluate_result(result([row()]), [reference(linkedin_url=""), reference(name="Missing Person", linkedin_url="")])
    assert report["supported_reference_count"] == 1
    assert report["supported_reference_rate"] == 0.5
    assert report["supported_profile_reference_count"] == 0
    assert report["supported_name_only_reference_count"] == 1
    assert report["name_only_reference_count"] == 2
    assert [entry["match_basis"] for entry in report["references"]] == ["name_only", "name_only"]
    assert [entry["placement"] for entry in report["references"]] == ["people", "missing"]


@pytest.mark.parametrize("people", [
    [row(), row(profile=PROFILE + "-another")],
    [row(), row(name="Different Person")],
])
def test_name_only_matching_rejects_same_name_or_profile_collisions(people):
    report = evaluate_result(result(people), [reference(linkedin_url="")])
    assert report["supported_reference_count"] == 0
    assert "ambiguous" in report["references"][0]["issues"][0]


def test_normalization_does_not_guess_company_aliases_or_partial_names():
    report = evaluate_result(result([row(company="Example Inc."), row(name="Alex")]), [reference()])
    assert report["supported_reference_count"] == 0
    assert "full name differs" in report["references"][0]["issues"][0]


@pytest.mark.parametrize("metadata,status", [({"is_mock": True}, "supported"), ({}, "mock")])
def test_synthetic_or_unsupported_people_rows_do_not_count(metadata, status):
    report = evaluate_result(result([row(status=status)], **metadata), [reference()])
    assert report["supported_reference_count"] == 0
    assert report["references"][0]["issues"]


def test_zero_references_and_zero_rows_report_undefined_rates():
    report = evaluate_result(result(), [])
    assert report["reference_count"] == report["supported_reference_count"] == 0
    assert report["supported_reference_rate"] is None
    assert report["rows"]["review_rate"] is None


def test_run_usage_and_model_settings_are_preserved_without_inventing_cost():
    original = result([row()], usage={"search_requests": 3, "llm_input_tokens": 40},
                      run_settings={"classification_model": "model-fixture", "criteria": {"founders": True}},
                      elapsed_seconds=1.5, provider_calls=1, status="completed_with_errors")
    report = evaluate_result(original, [reference(role_source_url="https://example.com/team")])
    assert report["run"]["usage"] == original["usage"]
    assert report["run"]["run_settings"] == original["run_settings"]
    assert report["run"]["elapsed_seconds"] == 1.5
    assert "cost" not in json.dumps(report)
    assert report["references"][0]["role_source_url"] == "https://example.com/team"
    report["run"]["run_settings"]["criteria"]["founders"] = False
    assert original["run_settings"]["criteria"]["founders"] is True


def test_role_expectations_require_the_exact_level_even_when_department_matches():
    observed = {**row(), "Title": "VP of Engineering", "Department": "Engineering", "Seniority": "VP"}
    report = evaluate_result(result([observed]), [reference(
        expected_departments=["Engineering"], expected_seniority=["Director"],
    )])
    entry = report["references"][0]
    assert entry["placement"] == "people"
    assert entry["supported"] is False
    assert report["people_reference_count"] == report["role_expected_reference_count"] == 1
    assert report["supported_reference_count"] == report["role_qualified_reference_count"] == 0
    assert entry["observed_rows"][0]["title"] == "VP of Engineering"
    assert entry["observed_rows"][0]["department"] == "Engineering"
    assert entry["observed_rows"][0]["seniority"] == "VP"
    assert len(entry["issues"]) == 1
    assert "seniority 'VP' does not match" in entry["issues"][0]


def test_role_expectations_reject_wrong_department_without_hiding_presence():
    observed = {**row(), "Title": "Product Director", "Department": "Product", "Seniority": "Director"}
    report = evaluate_result(result([observed]), [reference(
        expected_departments=["Engineering"], expected_seniority=["Director"],
    )])
    assert report["people_reference_count"] == 1
    assert report["supported_reference_count"] == report["supported_profile_reference_count"] == 0
    assert "department 'Product' does not match" in report["references"][0]["issues"][0]


def test_role_expectations_require_exported_fields_without_inferring_from_title():
    observed = {**row(), "Title": "Senior Engineering Manager"}
    report = evaluate_result(result([observed]), [reference(
        expected_departments=["Engineering"], expected_seniority=["Senior"],
    )])
    entry = report["references"][0]
    assert entry["placement"] == "people"
    assert entry["supported"] is False
    assert any("no department" in issue for issue in entry["issues"])
    assert any("no seniority" in issue for issue in entry["issues"])
    assert entry["observed_rows"][0]["department"] == entry["observed_rows"][0]["seniority"] == ""


def test_role_expectations_accept_multiple_normalized_alternatives_without_mutating_reference():
    observed = {**row(), "Title": "Principal Product Engineer", "Department": "  PRODUCT ", "Seniority": "Ｐｒｉｎｃｉｐａｌ"}
    expected = reference(expected_departments=["Engineering", " product "],
                         expected_seniority=["Senior", "Principal"])
    report = evaluate_result(result([observed]), [expected])
    assert report["supported_reference_count"] == report["role_qualified_reference_count"] == 1
    assert report["references"][0]["issues"] == []
    assert report["references"][0]["expected_departments"] == ["Engineering", "product"]
    assert expected["expected_departments"] == ["Engineering", " product "]


@pytest.mark.parametrize("expectations,fields", [
    ({"expected_departments": ["Engineering"]}, {"Department": "Engineering"}),
    ({"expected_seniority": ["Senior"]}, {"Seniority": "Senior"}),
])
def test_department_and_seniority_expectations_are_independently_optional(expectations, fields):
    report = evaluate_result(result([{**row(), **fields}]), [reference(**expectations)])
    assert report["supported_reference_count"] == report["role_qualified_reference_count"] == 1


def test_legacy_references_keep_coverage_without_role_labels_or_expectations():
    report = evaluate_result(result([row()]), [reference()])
    assert report["people_reference_count"] == report["supported_reference_count"] == 1
    assert report["role_expected_reference_count"] == report["role_qualified_reference_count"] == 0
    assert report["references"][0]["issues"] == []


def test_role_expectations_do_not_promote_review_missing_or_ambiguous_references():
    valid_roles = {"Department": "Engineering", "Seniority": "Senior"}
    observed = {**row(), **valid_roles}
    expected = reference(expected_departments=["Engineering"], expected_seniority=["Senior"])
    for original, placement in ((result(review=[observed]), "review"),
                                (result(), "missing"), (result([observed, observed]), "people")):
        report = evaluate_result(original, [expected])
        assert report["references"][0]["placement"] == placement
        assert report["supported_reference_count"] == report["role_qualified_reference_count"] == 0
        assert report[f"{placement}_reference_count"] == 1


def test_name_only_role_expectations_use_the_same_requirements_and_separate_counts():
    report = evaluate_result(result([{**row(), "Department": "Product", "Seniority": "Senior"}]),
                             [reference(linkedin_url="", expected_departments=["Engineering"])])
    assert report["people_reference_count"] == report["name_only_reference_count"] == 1
    assert report["supported_name_only_reference_count"] == 0
    assert report["references"][0]["placement"] == "people"


@pytest.mark.parametrize("field", ["expected_departments", "expected_seniority"])
@pytest.mark.parametrize("value", [None, "Engineering", [], [""], ["  "], [123], ["Engineering", None]])
def test_role_expectations_reject_malformed_arrays(field, value):
    with pytest.raises(ValueError, match=field + " must be a nonempty array of nonblank strings"):
        evaluate_result(result(), [reference(**{field: value})])


@pytest.mark.parametrize("field", ["Title", "Department", "Seniority"])
def test_present_exported_role_fields_must_be_strings(field):
    with pytest.raises(ValueError, match=field + " must be a string"):
        evaluate_result(result([{**row(), field: None}]), [reference()])


@pytest.mark.parametrize("bad_result,bad_reference,message", [
    ([], [], "PeopleResult JSON object"),
    ({"people": []}, [], "'review' must be an array"),
    (result([{"Company": "Example"}]), [], "Name must be a string"),
    (result([row(company=" ")]), [], "Company must not be blank"),
    (result(usage=[]), [], "'usage' must be an object"),
    (result(), {}, "Reference must be an array"),
    (result(), [{"company": "Example", "name": ""}], "name must be a nonblank string"),
    (result(), [reference(linkedin_url="https://evil.example/in/alex")], "personal LinkedIn profile"),
    (result(), [reference(linkedin_ur="typo")], "must contain only"),
    (result(), [reference(), reference(company=" EXAMPLE ", name="alex example")], "duplicates"),
    (result(), [reference(), reference(name="Another Person")], "duplicates"),
])
def test_invalid_input_and_duplicate_references_fail_clearly(bad_result, bad_reference, message):
    with pytest.raises(ValueError, match=message):
        evaluate_result(bad_result, bad_reference)


def test_cli_is_offline_and_does_not_load_or_report_credentials(tmp_path, monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError("Offline evaluation must not access network or credential configuration")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(dotenv, "load_dotenv", forbidden)
    monkeypatch.setenv("OPENAI_API_KEY", "secret-openai-not-for-report")
    monkeypatch.setenv("SERPER_API_KEY", "secret-serper-not-for-report")
    input_path, reference_path, output_path = [tmp_path / name for name in ("result.json", "reference.json", "report.json")]
    input_path.write_text(json.dumps(result([row()])))
    reference_path.write_text(json.dumps([reference()]))
    assert main(["--result", str(input_path), "--reference", str(reference_path), "--output", str(output_path)]) == 0
    output = capsys.readouterr().out
    assert output_path.read_text() == output
    assert json.loads(output)["supported_reference_count"] == 1
    assert "secret-" not in output


def test_cli_reports_invalid_json_and_prevents_input_overwrite(tmp_path, capsys):
    input_path, reference_path = tmp_path / "result.json", tmp_path / "reference.json"
    input_path.write_text("not json")
    reference_path.write_text("[]")
    with pytest.raises(SystemExit) as exc:
        main(["--result", str(input_path), "--reference", str(reference_path)])
    assert exc.value.code == 2
    assert "Expecting value" in capsys.readouterr().err
    with pytest.raises(SystemExit) as exc:
        main(["--result", str(input_path), "--reference", str(reference_path), "--output", str(input_path)])
    assert exc.value.code == 2
    assert "must differ from both input files" in capsys.readouterr().err
    assert input_path.read_text() == "not json"
