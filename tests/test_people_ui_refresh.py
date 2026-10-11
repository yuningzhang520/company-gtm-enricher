from pathlib import Path

from streamlit.testing.v1 import AppTest

from company_gtm_enricher.people import ui
from company_gtm_enricher.people.excel_export import PEOPLE_COLUMNS
from company_gtm_enricher.people.job_runner import PeopleJob
from company_gtm_enricher.people.models import CompanyTarget, PeopleCriteria, PeopleResult
from company_gtm_enricher.people.providers import MockPeopleProvider
from company_gtm_enricher.people.service import PeopleService


ROOT = Path(__file__).resolve().parents[1]


def test_completion_during_render_refreshes_status_and_unlocks_controls(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("SERPER_API_KEY", "")
    criteria = PeopleCriteria()
    result = PeopleService(MockPeopleProvider()).run([CompanyTarget("Demo")], criteria)
    job = PeopleJob(
        "demo.xlsx", tuple(PEOPLE_COLUMNS), criteria, total_companies=1,
        processed_companies=1, result=result,
    )
    render_statuses = []
    export = ui.excel_bytes

    def complete_during_export(*args, **kwargs):
        # The worker finishes after controls and the status have been rendered,
        # but before the page decides whether another refresh is necessary.
        with job.lock:
            render_statuses.append(job.status)
            job.status = "completed"
        return export(*args, **kwargs)

    monkeypatch.setattr(ui, "excel_bytes", complete_during_export)
    monkeypatch.setattr(ui, "start_people_job", lambda *args, **kwargs: job)
    page = AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()
    page.sidebar.radio[0].set_value("People").run()
    next(item for item in page.button if item.label == "Use demo companies").click().run()
    next(item for item in page.button if item.label == "Run people demo").click().run()

    # No additional page.run(): completion must trigger its own final refresh.
    assert not page.exception
    assert render_statuses == ["running", "completed"]
    assert any("completed · 1/1 companies" in item.value for item in page.markdown)
    assert not page.sidebar.radio[0].disabled
    assert not page.text_input(key="session_openai_api_key").disabled
    assert not next(item for item in page.selectbox if item.label == "People source").disabled
    assert not next(item for item in page.button if item.label == "Run people demo").disabled
    assert any(item.label == "Clear run" for item in page.button)


def test_live_result_explains_title_missing_and_employment_uncertainty_counts():
    result = PeopleResult(
        people=[
            {"Name": "Known Role", "Title": "Director", "Status": "employment_unconfirmed"},
            {"Name": "No Role", "Title": "", "Status": "title_missing"},
            {"Name": "Supported Role", "Title": "Engineer", "Status": "supported"},
        ],
        review=[{"Status": "processing_failed"}],
    )
    job = PeopleJob(
        "contacts.xlsx", tuple(PEOPLE_COLUMNS), PeopleCriteria(), total_companies=1,
        processed_companies=1, result=result, status="completed",
    )
    page = AppTest.from_string(
        "from company_gtm_enricher.people.ui import render_people_page\nrender_people_page()",
    )
    page.session_state["people_job"] = job
    page.run()

    assert not page.exception
    summary = next(item.value for item in page.caption if "labelled title_missing" in item.value)
    assert "1 contacts labelled employment_unconfirmed and 1 labelled title_missing" in summary
    assert "Missing titles stay blank; check Notes for employment uncertainty too" in summary
    assert "1 records affected by processing failure" in summary
