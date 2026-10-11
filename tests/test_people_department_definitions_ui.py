from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from company_gtm_enricher.people.role_options import department_definitions_for


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("SERPER_API_KEY", "")


def demo_page():
    page = AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()
    page.sidebar.radio[0].set_value("People").run()
    next(item for item in page.button if item.label == "Use demo companies").click().run()
    assert not page.exception
    return page


def departments(page):
    return next(item for item in page.multiselect if item.label == "Departments")


def definition(page, label):
    return next(item for item in page.text_area if item.label == f"{label} definition")


def run_demo(page):
    next(item for item in page.button if item.label == "Run people demo").click().run()
    job = page.session_state["people_job"]
    job.thread.join(5)
    page.run()
    assert not page.exception
    assert job.status == "completed"
    return job


def test_default_definitions_are_editable_and_recorded_with_run():
    page = demo_page()
    defaults = department_definitions_for(departments(page).value)
    assert {item.label: item.value for item in page.text_area} == {
        f"{name} definition": value for name, value in defaults.items()
    }
    assert "Product Marketing" in definition(page, "Product").value
    assert "Product Partnerships" in definition(page, "Product").value
    revised = "Product management, Product Marketing, and Product Partnerships for developer products."
    definition(page, "Product").set_value(revised).run()
    next(item for item in page.multiselect if item.label == "Leadership levels").set_value(["Director"]).run()
    job = run_demo(page)

    assert job.criteria.department_definitions == {**defaults, "Product": revised}
    assert job.result.run_settings["criteria"]["department_definitions"] == job.criteria.department_definitions
    assert any("Definitions do not expand search queries" in item.value for item in page.caption)


def test_edits_and_blank_guidance_survive_deselect_reselect_and_duplicate_labels():
    page = demo_page()
    departments(page).set_value(["Product", "Robotics"]).run()
    assert definition(page, "Robotics").value == ""
    revised = "Robot perception, motion planning, and manipulation research."
    definition(page, "Robotics").set_value(revised).run()
    definition(page, "Product").set_value("").run()
    departments(page).set_value(["Engineering"]).run()
    assert [item.label for item in page.text_area] == ["Engineering definition"]
    departments(page).set_value([" product ", "PRODUCT", " Robotics ", "robotics"]).run()

    assert not page.exception
    assert [item.label for item in page.text_area] == ["product definition", "Robotics definition"]
    assert definition(page, "product").value == ""
    assert definition(page, "Robotics").value == revised
    job = run_demo(page)
    assert job.criteria.departments == ("product", "Robotics")
    assert job.criteria.department_definitions == {"Robotics": revised}


def test_definition_edits_remain_local_to_the_streamlit_session():
    first = demo_page()
    revised = "Only product management for this session."
    definition(first, "Product").set_value(revised).run()
    second = demo_page()

    assert definition(second, "Product").value == department_definitions_for(["Product"])["Product"]
    first.run()
    assert definition(first, "Product").value == revised


def test_active_run_locks_department_definition_editors(monkeypatch):
    page = demo_page()
    definition(page, "Product").set_value("Selected product scope.").run()
    # Inspect an active render without starting a background worker or rerun loop.
    monkeypatch.setattr("company_gtm_enricher.people.ui.is_active", lambda job: True)
    monkeypatch.setattr(st, "rerun", lambda: None)
    page.run()

    assert not page.exception
    assert all(item.disabled for item in page.text_area)
    assert definition(page, "Product").value == "Selected product scope."
    assert departments(page).disabled
