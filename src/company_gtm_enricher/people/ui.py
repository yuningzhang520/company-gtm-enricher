from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import time

import pandas as pd
import streamlit as st

from company_gtm_enricher.csv_tools import (
    CSVValidationError, detect_company_column, load_dataframe_from_csv_bytes,
)
from .excel_export import PEOPLE_COLUMNS, excel_bytes
from .config import PeopleSettings, create_people_provider
from .job_runner import is_active, start_people_job
from .models import PeopleCriteria
from .role_options import department_definitions_for, load_role_options
from .service import read_companies


def _department_definition_inputs(departments: list[str], *, disabled: bool) -> dict[str, str]:
    defaults = department_definitions_for(departments)
    # Keep edits separately because Streamlit removes state for hidden widgets.
    edits = st.session_state.setdefault("people_department_definition_edits", {})
    selected = {}
    for department in departments:
        identity = department.casefold()
        key = f"people_department_definition_{identity}"
        if key not in st.session_state:
            st.session_state[key] = edits.get(identity, defaults.get(department, ""))
        selected[department] = st.text_area(f"{department} definition", key=key, disabled=disabled, height=100)
        edits[identity] = selected[department]
    return department_definitions_for(departments, overrides=selected)


def render_people_page(
    *, openai_api_key_override: str = "", serper_api_key_override: str = "",
) -> None:
    job = st.session_state.get("people_job")
    active = is_active(job)
    source = st.selectbox("People source", ["Demo (no API calls)", "Search + LLM"], disabled=active)
    provider_name = "mock" if source == "Demo (no API calls)" else "openai"
    settings = None
    if provider_name == "mock":
        st.info("People demo: all names are synthetic. No web requests or API charges. LinkedIn URLs are blank.")
    else:
        st.info("Find contacts from public profile search results. People includes source-supported names and profile links, with original titles when available. Department searches may retain missing titles as title_missing; employment uncertainty appears in Status or Notes. Coverage is partial.")
        try:
            settings = PeopleSettings.from_env(
                openai_api_key_override=openai_api_key_override,
                serper_api_key_override=serper_api_key_override,
            )
            if settings.missing_keys:
                st.warning("Configure " + " and ".join(settings.missing_keys) + " in the API keys sidebar or local .env before running.")
        except ValueError as exc:
            st.error(str(exc))
    query_limit = st.number_input("Search queries per company", min_value=1, max_value=20, value=settings.max_queries_per_company if settings else 4, disabled=active) if provider_name == "openai" else None
    candidate_limit = st.number_input("Candidates to classify per company", min_value=1, max_value=100, value=settings.max_candidates if settings else 40, disabled=active) if provider_name == "openai" else None
    company_founder_pages = False
    if provider_name == "openai":
        st.caption("These limits bound work per company. A capped search does not establish a complete employee list.")
        company_founder_pages = st.checkbox(
            "Check company founder links", value=False, disabled=active,
            help="Read up to 3 public company/about/careers pages per company; only explicitly linked founders are added. No LinkedIn pages are fetched.",
        )
    uploaded = st.file_uploader("Upload companies CSV", type=["csv"], key="people_upload", disabled=active)
    if st.button("Use demo companies", disabled=active or provider_name != "mock"):
        st.session_state["people_use_demo"] = True

    dataframe = None
    filename = "people_demo.csv"
    try:
        if uploaded is not None:
            dataframe = load_dataframe_from_csv_bytes(uploaded.getvalue())
            filename = uploaded.name
        elif st.session_state.get("people_use_demo"):
            demo = Path(__file__).resolve().parents[3] / "examples" / "people_demo.csv"
            dataframe = load_dataframe_from_csv_bytes(demo.read_bytes())
    except (CSVValidationError, OSError) as exc:
        st.error(str(exc))

    if dataframe is not None:
        try:
            guessed = detect_company_column(dataframe)
        except CSVValidationError:
            guessed = "input_name" if "input_name" in dataframe else str(dataframe.columns[0])
        company_column = st.selectbox(
            "Company name column", list(dataframe.columns),
            index=list(dataframe.columns).index(guessed), disabled=active, key="people_company_column",
        )
        optional = ["(none)", *list(dataframe.columns)]
        mappings = st.columns(2)
        domain_column = mappings[0].selectbox(
            "Domain column (optional)", optional,
            index=optional.index("domain") if "domain" in optional else 0, disabled=active,
        )
        lists_column = mappings[1].selectbox(
            "List tags column (optional)", optional,
            index=optional.index("lists") if "lists" in optional else 0, disabled=active,
        )
        aliases_column = st.selectbox(
            "Company aliases column (optional)", optional,
            index=optional.index("aliases") if "aliases" in optional else 0, disabled=active,
            help="Known previous or alternate names for the same company, separated by ; or |. For example, Repl.it for Replit. Aliases support evidence matching; they do not merge different company rows.",
        )
        st.dataframe(dataframe.head(10), use_container_width=True)

        founders = st.checkbox("Founders and co-founders", value=True, disabled=active,
                               help="Include a founder search. Without an active department search, results are limited to the founder/C-level categories selected here.")
        c_level = st.checkbox("C-level executives", value=True, disabled=active,
                             help="Include a C-level search. Without an active department search, results are limited to the founder/C-level categories selected here.")
        with st.expander("Department roles (optional)"):
            st.caption("Choose a department and at least one leadership or individual contributor level to guide the search. Labels and levels are approximate preferences; supported profiles in adjacent roles may be included. Judge relevance from the original titles and Notes.")
            options = load_role_options()
            selected_departments = st.multiselect("Departments", options["departments"], default=options["departments"], accept_new_options=True, disabled=active)
            unique_departments = {}
            for department in selected_departments:
                label = " ".join(department.split())
                if label:
                    unique_departments.setdefault(label.casefold(), label)
            departments = list(unique_departments.values())
            leadership = st.multiselect("Leadership levels", options["leadership_levels"], accept_new_options=True, disabled=active)
            ic = st.multiselect("Individual contributor levels", options["ic_levels"], accept_new_options=True, disabled=active)
            st.caption("Definitions guide suggested department grouping. Leave a definition blank to use the department label alone. Definitions do not expand search queries.")
            department_definitions = _department_definition_inputs(departments, disabled=active)
        columns = st.multiselect("People output columns", list(PEOPLE_COLUMNS), default=list(PEOPLE_COLUMNS), disabled=active)
        st.caption("Status is always included. Results whose source text mentions none of the target company name, domain or configured aliases are discarded from both People and Review. Source-supported contacts may stay in People when employment is unconfirmed. In department searches, a missing title alone stays blank and is labelled title_missing; use a general introduction without assuming a role. Founder/C-level-only searches still require a supported title category. Review holds missing or unsupported identity/profile data, unsupported extracted titles and explicit company/role conflicts. Processing failures have a separate status. Department and level labels are advisory.")
        unavailable = provider_name == "openai" and (settings is None or bool(settings.missing_keys))
        if provider_name == "openai":
            planned_groups = int(founders) + int(c_level) + len(departments) * (int(bool(leadership)) + int(bool(ic)))
            if query_limit < planned_groups:
                st.warning(f"The query cap covers at most {query_limit} of {planned_groups} selected role groups per company. Founders/C-level run first, then departments in selection order; later groups will be skipped.")
            if uploaded is None and st.session_state.get("people_use_demo"):
                st.info("Upload your company CSV for live search. The built-in demo companies are fictional.")
                unavailable = True
        if st.button("Run people demo" if provider_name == "mock" else "Find people", type="primary", disabled=active or unavailable):
            try:
                if not columns:
                    raise ValueError("Select at least one output column.")
                criteria = PeopleCriteria(
                    founders, c_level, tuple(departments), tuple(leadership), tuple(ic),
                    department_definitions=department_definitions,
                )
                companies = read_companies(
                    dataframe, company_column,
                    domain_column=None if domain_column == "(none)" else domain_column,
                    lists_column=None if lists_column == "(none)" else lists_column,
                    aliases_column=None if aliases_column == "(none)" else aliases_column,
                )
                st.session_state["people_job"] = start_people_job(
                    companies, criteria,
                    create_people_provider(
                        provider_name, max_queries_per_company=query_limit, max_candidates=candidate_limit,
                        openai_api_key_override=openai_api_key_override,
                        serper_api_key_override=serper_api_key_override,
                        company_founder_pages=company_founder_pages,
                    ), columns,
                    Path(filename).stem + ("_people_demo.xlsx" if provider_name == "mock" else "_people.xlsx"),
                )
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    if job is not None:
        with job.lock:
            status, result, processed, total = job.status, job.result, job.processed_companies, job.total_companies
            current, error, backup = job.current_company, job.error, job.backup_path
        st.subheader("People run")
        st.write(f"{status} · {processed}/{total} companies · {current}")
        if active:
            st.caption("Pause and stop take effect after the current company finishes.")
        st.progress(min(processed / max(total, 1), 1.0))
        controls = st.columns(3)
        if status in {"running", "paused"} and controls[0].button("Resume" if status == "paused" else "Pause", key="people_pause"):
            with job.lock:
                if job.status == "paused" and status == "paused":
                    job.pause_event.clear()
                    job.status = "running"
                elif job.status == "running" and status == "running":
                    job.pause_event.set()
                    job.status = "paused"
            st.rerun()
        if status in {"running", "paused"} and controls[1].button("Stop", key="people_stop"):
            with job.lock:
                if job.status in {"running", "paused"}:
                    job.stop_event.set()
                    job.pause_event.clear()
                    job.status = "stopping"
            st.rerun()
        if not active and controls[2].button("Clear run", key="people_clear"):
            st.session_state.pop("people_job", None)
            st.rerun()
        if error:
            st.error(error)
        if status == "failed" and not error:
            st.error("The run stopped on a provider/account error. See Companies for details; later companies remain pending.")
        if status == "completed_with_errors":
            st.warning("Some companies failed. See Companies for details; other results are retained.")
        if status == "stopped":
            st.warning("Stopped. Unprocessed companies are marked pending in the workbook.")
        if result is not None:
            with st.expander("Settings used for this result"):
                st.json(result.run_settings or asdict(job.criteria))
            label = "demo people" if result.is_mock else "contacts"
            st.caption(f"{len(result.people)} {label} · {len(result.review)} for review · {result.provider_calls} company lookups · {result.elapsed_seconds:.2f}s")
            if not result.is_mock:
                unconfirmed = sum(row.get("Status") == "employment_unconfirmed" for row in result.people)
                missing_titles = sum(row.get("Status") == "title_missing" for row in result.people)
                failed = sum(row.get("Status") == "processing_failed" for row in result.review)
                st.caption(f"People includes {unconfirmed} contacts labelled employment_unconfirmed and {missing_titles} labelled title_missing. Missing titles stay blank; check Notes for employment uncertainty too. Review includes {failed} records affected by processing failure. Inspect Status and Notes before using a contact.")
            if result.usage:
                st.caption(f"Search requests: {result.usage.get('search_requests', 0)} · Classification requests: {result.usage.get('llm_requests', 0)} · Input/output tokens: {result.usage.get('input_tokens', 0)}/{result.usage.get('output_tokens', 0)} · API charges not measured")
                if "page_requests" in result.usage:
                    st.caption(f"Company page requests: {result.usage['page_requests']}")
            tabs = st.tabs(["People", "Companies", "Review"])
            for tab, rows in zip(tabs, [result.people, result.companies, result.review]):
                tab.dataframe(pd.DataFrame(rows), use_container_width=True)
            st.download_button(
                "Download demo Excel" if result.is_mock and status == "completed" else "Download current Excel",
                data=excel_bytes(result, columns=job.columns), file_name=job.output_filename,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        if backup:
            st.caption(f"Local backup: {backup}")
    # A job can finish after this render captured its status and disabled inputs.
    # Refresh once more so that the completed state and unlocked controls appear.
    if active or is_active(job):
        time.sleep(0.2)
        st.rerun()
