from pathlib import Path

from company_gtm_enricher.people import job_runner
from company_gtm_enricher.people.excel_export import PEOPLE_COLUMNS
from company_gtm_enricher.people.models import CompanyTarget, PeopleCriteria
from company_gtm_enricher.people.providers import MockPeopleProvider


def test_background_job_captures_inputs_before_worker_starts(tmp_path, monkeypatch):
    class DeferredThread:
        def __init__(self, *, target, daemon):
            self.target = target

        def start(self):
            pass

    monkeypatch.setattr(job_runner, "Thread", DeferredThread)
    companies = [CompanyTarget("Submitted Company")]
    criteria = PeopleCriteria(
        departments=("Engineering",), leadership_levels=("Director",),
        department_definitions={"Engineering": "Builds software products."},
    )
    job = job_runner.start_people_job(
        companies, criteria, MockPeopleProvider(), PEOPLE_COLUMNS, "people.xlsx", tmp_path,
    )

    # Simulate the caller editing inputs after submission but before the worker runs.
    companies.append(CompanyTarget("Later Company"))
    criteria.department_definitions["Engineering"] = "Changed after submission."
    job.thread.target()

    assert job.status == "completed"
    assert job.total_companies == job.processed_companies == 1
    assert [row["Company"] for row in job.result.companies] == ["Submitted Company"]
    expected = {"Engineering": "Builds software products."}
    assert job.criteria.department_definitions == expected
    assert job.result.run_settings["criteria"]["department_definitions"] == expected
    assert Path(job.backup_path).is_file()
