import json
import os
import sys

import pytest

from company_gtm_enricher.cli import main


def run_cli(tmp_path, monkeypatch, *options):
    input_path = tmp_path / "companies.csv"
    input_path.write_text("company,domain\nExample,example.org\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [
        "company-gtm-enricher", "--mode", "people", "--provider", "mock",
        "--input", str(input_path), "--output", str(tmp_path / "people.xlsx"),
        "--result-json", str(tmp_path / "result.json"),
        "--departments", "Product", "--leadership-levels", "Director",
        *options,
    ])
    return main()


def saved_criteria(tmp_path):
    return json.loads((tmp_path / "result.json").read_text())["run_settings"]["criteria"]


@pytest.fixture
def no_provider(monkeypatch):
    def unexpected_provider(*args, **kwargs):
        pytest.fail("Invalid department definitions must fail before constructing a provider")

    monkeypatch.setattr("company_gtm_enricher.people.config.create_people_provider", unexpected_provider)


def test_omitted_file_uses_selected_department_defaults(tmp_path, monkeypatch):
    assert run_cli(tmp_path, monkeypatch) == 0
    definitions = saved_criteria(tmp_path)["department_definitions"]
    assert set(definitions) == {"Product"}
    assert all(term in definitions["Product"].lower() for term in ("management", "marketing", "partnership"))
    assert (tmp_path / "people.xlsx").exists()


def test_custom_definitions_are_case_insensitive_and_unselected_values_are_filtered(tmp_path, monkeypatch):
    path = tmp_path / "definitions.json"
    path.write_text(json.dumps({"pRoDuCt": "Only product management and research.", "Sales": "Revenue and sales teams."}))
    assert run_cli(tmp_path, monkeypatch, "--department-definitions", str(path)) == 0
    criteria = saved_criteria(tmp_path)
    assert criteria["department_definitions"] == {"Product": "Only product management and research."}
    assert criteria["departments"] == ["Product"]


def test_blank_definition_removes_default_and_keeps_unoverridden_defaults(tmp_path, monkeypatch):
    path = tmp_path / "definitions.json"
    path.write_text(json.dumps({"Product": "  "}))
    assert run_cli(tmp_path, monkeypatch, "--department-definitions", str(path),
                   "--departments", "Product,Infrastructure") == 0
    definitions = saved_criteria(tmp_path)["department_definitions"]
    assert set(definitions) == {"Infrastructure"}
    assert definitions["Infrastructure"]


def test_custom_department_description_reaches_the_provider(tmp_path, monkeypatch):
    from company_gtm_enricher.people.providers import MockPeopleProvider

    seen = []

    class ObservingMock(MockPeopleProvider):
        def discover(self, company, criteria):
            seen.append(criteria.department_definitions)
            return super().discover(company, criteria)

    monkeypatch.setattr("company_gtm_enricher.people.config.create_people_provider", lambda *args, **kwargs: ObservingMock())
    path = tmp_path / "definitions.json"
    path.write_text(json.dumps({"Robotics": "Robot perception and control."}))
    assert run_cli(tmp_path, monkeypatch, "--departments", "Robotics",
                   "--department-definitions", str(path)) == 0
    assert seen == [{"Robotics": "Robot perception and control."}]


def test_no_selected_departments_does_not_pass_reusable_definitions(tmp_path, monkeypatch):
    path = tmp_path / "definitions.json"
    path.write_text(json.dumps({"Product": "Management and marketing."}))
    assert run_cli(tmp_path, monkeypatch, "--departments", "",
                   "--department-definitions", str(path)) == 0
    assert saved_criteria(tmp_path)["department_definitions"] == {}


@pytest.mark.parametrize("content", ["not json", '{"Product":', "[", ""])
def test_malformed_definitions_fail_before_provider_construction(tmp_path, monkeypatch, no_provider, capsys, content):
    path = tmp_path / "definitions.json"
    path.write_text(content)
    with pytest.raises(SystemExit) as exc:
        run_cli(tmp_path, monkeypatch, "--department-definitions", str(path))
    assert exc.value.code == 1
    assert "Department definitions must contain valid JSON" in capsys.readouterr().err
    assert not (tmp_path / "people.xlsx").exists()
    assert not (tmp_path / "result.json").exists()
    assert path.read_text() == content


@pytest.mark.parametrize("definitions", [
    [], None, "text", 4, True,
    {"Product": None}, {"Product": 42}, {"Product": False}, {"Product": []},
    {"Product": {"description": "Nested values are not supported"}},
    {"": "Missing department name"}, {"  ": "Missing department name"},
    {"Product": "Valid selected definition", "Unselected": ["Still invalid"]},
])
def test_invalid_schema_including_unselected_values_fails_before_provider(tmp_path, monkeypatch, no_provider, capsys, definitions):
    path = tmp_path / "definitions.json"
    path.write_text(json.dumps(definitions))
    with pytest.raises(SystemExit) as exc:
        run_cli(tmp_path, monkeypatch, "--department-definitions", str(path))
    assert exc.value.code == 1
    assert "Error:" in capsys.readouterr().err
    assert not (tmp_path / "people.xlsx").exists()


def test_missing_definitions_file_fails_before_provider(tmp_path, monkeypatch, no_provider, capsys):
    with pytest.raises(SystemExit) as exc:
        run_cli(tmp_path, monkeypatch, "--department-definitions", str(tmp_path / "missing.json"))
    assert exc.value.code == 1
    assert "missing.json" in capsys.readouterr().err


@pytest.mark.parametrize("output_option", ["--output", "--result-json"])
@pytest.mark.parametrize("alias", ["same_path", "symlink", "hardlink"])
def test_output_paths_cannot_overwrite_definition_inputs(tmp_path, monkeypatch, no_provider, capsys, output_option, alias):
    # The definition file's extension is unrestricted; using .xlsx also covers
    # the Excel destination without failing its extension check first.
    path = tmp_path / "definitions.xlsx"
    original = json.dumps({"Product": "Management and marketing."})
    path.write_text(original)
    destination = path
    if alias != "same_path":
        destination = tmp_path / "output-alias.xlsx"
        if alias == "symlink":
            destination.symlink_to(path)
        else:
            os.link(path, destination)
    with pytest.raises(SystemExit) as exc:
        run_cli(tmp_path, monkeypatch, "--department-definitions", str(path), output_option, str(destination))
    assert exc.value.code == 1
    assert "department definitions input file" in capsys.readouterr().err
    assert path.read_text() == original
