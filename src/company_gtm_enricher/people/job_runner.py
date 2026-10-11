from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, replace
from pathlib import Path
from threading import Event, Lock, Thread
import time
from typing import Optional, Sequence
from uuid import uuid4

from .excel_export import excel_bytes
from .models import CompanyTarget, PeopleCriteria, PeopleResult
from .providers import PeopleProvider
from .service import PeopleService


ACTIVE_STATUSES = {"running", "paused", "stopping"}


@dataclass
class PeopleJob:
    output_filename: str
    columns: tuple[str, ...]
    criteria: PeopleCriteria
    total_companies: int
    status: str = "running"
    processed_companies: int = 0
    current_company: str = ""
    result: Optional[PeopleResult] = None
    error: str = ""
    backup_path: str = ""
    pause_event: Event = field(default_factory=Event, repr=False)
    stop_event: Event = field(default_factory=Event, repr=False)
    lock: Lock = field(default_factory=Lock, repr=False)
    thread: Optional[Thread] = field(default=None, repr=False)


def is_active(job: Optional[PeopleJob]) -> bool:
    if job is None:
        return False
    with job.lock:
        return job.status in ACTIVE_STATUSES


def start_people_job(
    companies: Sequence[CompanyTarget],
    criteria: PeopleCriteria,
    provider: PeopleProvider,
    columns: Sequence[str],
    output_filename: str,
    backup_directory: Path = Path("backups"),
) -> PeopleJob:
    # Freeze submitted inputs before the worker can race with its caller.
    companies = tuple(companies)
    criteria = replace(criteria)
    job = PeopleJob(output_filename, tuple(columns), criteria, len(companies))
    backup_file = backup_directory / f"people_{uuid4().hex}.xlsx"

    def save_backup(result: PeopleResult) -> None:
        backup_directory.mkdir(parents=True, exist_ok=True)
        backup_file.write_bytes(excel_bytes(result, columns=job.columns))
        with job.lock:
            job.backup_path = str(backup_file)

    def run() -> None:
        next_backup_at = time.monotonic() + 600

        def on_update(result: PeopleResult, processed: int, total: int, company: str) -> None:
            nonlocal next_backup_at
            # Service callbacks already provide independent snapshots.
            with job.lock:
                job.result = result
                job.processed_companies = processed
                job.total_companies = total
                job.current_company = company
            if time.monotonic() >= next_backup_at and processed:
                save_backup(result)
                next_backup_at = time.monotonic() + 600

        try:
            result = PeopleService(provider).run(
                companies, criteria,
                should_pause=job.pause_event.is_set,
                should_stop=job.stop_event.is_set,
                on_update=on_update,
            )
            with job.lock:
                job.result = result
            save_backup(result)
            with job.lock:
                job.status = result.status
        except Exception as exc:
            with job.lock:
                job.status = "failed"
                job.error = str(exc)
                partial = deepcopy(job.result)
            if partial is not None:
                partial.status = "failed"
                with job.lock:
                    job.result = partial
                try:
                    save_backup(partial)
                except Exception as backup_error:
                    with job.lock:
                        job.error += f"; partial backup failed: {backup_error}"
        finally:
            with job.lock:
                job.current_company = ""

    job.thread = Thread(target=run, daemon=True)
    job.thread.start()
    return job
