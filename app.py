from __future__ import annotations

import io
import time
from dataclasses import replace
from pathlib import Path
from typing import Optional

import pandas as pd
import streamlit as st

from company_gtm_enricher.config import AppConfig
from company_gtm_enricher.credentials_ui import render_api_keys
from company_gtm_enricher.cost_estimator import (
    DEFAULT_PRICING_MODELS,
    CostEstimatorInputs,
    estimate_costs,
)
from company_gtm_enricher.csv_tools import (
    CSVValidationError,
    dataframe_to_csv_bytes,
    detect_company_column,
    load_dataframe_from_csv_bytes,
)
from company_gtm_enricher.job_runner import EnrichmentJob, start_enrichment_job
from company_gtm_enricher.providers.factory import create_provider
from company_gtm_enricher.people.job_runner import is_active as is_people_job_active
from company_gtm_enricher.people.ui import render_people_page


ACTIVE_JOB_STATUSES = {"running", "paused", "stopping"}


def main() -> None:
    job = st.session_state.get("enrichment_job")

    st.set_page_config(page_title="Company GTM Enricher", page_icon=":bar_chart:")
    st.title("Company GTM Enricher")
    active = _is_job_active(job) or is_people_job_active(st.session_state.get("people_job"))
    mode = st.sidebar.radio(
        "Enrichment", ("Company facts", "People"),
        disabled=active,
    )
    openai_key, serper_key = render_api_keys(disabled=active)
    if mode == "People":
        render_people_page(openai_api_key_override=openai_key, serper_api_key_override=serper_key)
        return

    config = AppConfig.from_env()
    if openai_key:
        config = replace(config, openai_api_key=openai_key)
    st.caption(
        "Upload a CSV of company names, enrich public GTM fields, and download a refreshed CSV."
    )

    with st.sidebar:
        st.header("Run Settings")
        provider_name = st.selectbox(
            "Provider",
            options=["openai", "mock"],
            help="Use mock to test the workflow without live API calls.",
        )
        model_name = st.text_input("OpenAI model", value=config.openai_model)
        batch_size = st.number_input(
            "Batch size",
            min_value=1,
            value=config.openai_batch_size,
            step=1,
            help="Unique companies are grouped into batches of this size before sending requests.",
        )
        include_audit_columns = st.checkbox(
            "Include audit columns",
            value=True,
            help="Adds enrichment confidence, source URLs, status, and notes.",
        )

        st.markdown("**Environment**")
        st.write(
            "Max companies per run: "
            + (f"`{config.max_companies_per_run}`" if config.max_companies_per_run else "`unlimited`")
        )
        st.write(
            "OpenAI API key loaded: "
            + ("`yes`" if bool(config.openai_api_key) else "`no`")
        )

    _render_job_controls(job)

    uploaded_file = st.file_uploader("Upload a CSV", type=["csv"])
    dataframe: Optional[pd.DataFrame] = None
    estimator_company_count = 800
    if uploaded_file is None:
        _render_cost_estimator(
            default_company_count=estimator_company_count,
            default_batch_size=int(batch_size),
        )
        st.info("Upload a CSV file to begin.")
        _schedule_refresh(job)
        return

    try:
        dataframe = load_dataframe_from_csv_bytes(uploaded_file.getvalue())
        estimator_company_count = len(dataframe.index) or estimator_company_count
    except CSVValidationError as exc:
        _render_cost_estimator(
            default_company_count=estimator_company_count,
            default_batch_size=int(batch_size),
        )
        st.error(str(exc))
        return

    _render_cost_estimator(
        default_company_count=estimator_company_count,
        default_batch_size=int(batch_size),
    )

    if len(dataframe.index) == 0:
        st.error("The CSV file is empty.")
        return

    if config.max_companies_per_run and len(dataframe.index) > config.max_companies_per_run:
        st.error(
            "This file has "
            f"{len(dataframe.index)} rows, which exceeds the configured limit of "
            f"{config.max_companies_per_run}."
        )
        return

    try:
        guessed_company_column = detect_company_column(dataframe)
    except CSVValidationError:
        guessed_company_column = str(dataframe.columns[0])
    company_column = st.selectbox(
        "Company name column",
        options=list(dataframe.columns),
        index=list(dataframe.columns).index(guessed_company_column),
    )

    st.subheader("Preview")
    st.dataframe(dataframe.head(10), width="stretch")

    if not _is_job_active(job):
        if not st.button("Enrich CSV", type="primary"):
            _render_job_result(job)
            return

        try:
            provider = create_provider(
                provider_name=provider_name,
                config=config,
                model_override=model_name.strip() or None,
            )
        except ValueError as exc:
            st.error(str(exc))
            return

        st.session_state["enrichment_job"] = start_enrichment_job(
            dataframe=dataframe,
            company_column=company_column,
            provider=provider,
            include_audit_columns=include_audit_columns,
            batch_size=int(batch_size),
            input_filename=uploaded_file.name,
            output_filename=uploaded_file.name.rsplit(".", 1)[0] + "_enriched.csv",
        )
        st.rerun()

    _render_job_result(st.session_state.get("enrichment_job"))
    _schedule_refresh(st.session_state.get("enrichment_job"))


def _render_job_controls(job: Optional[EnrichmentJob]) -> None:
    if job is None:
        return

    with job.lock:
        status = job.status
        total_companies = job.total_companies
        processed_companies = job.processed_companies
        current_company = job.current_company
        error_message = job.error_message
        started_at = job.started_at
        finished_at = job.finished_at
        backup_count = job.backup_count
        last_backup_path = job.last_backup_path
        last_backup_at = job.last_backup_at

    st.subheader("Run Status")
    st.write(f"Status: `{status}`")
    st.write(f"Processed companies: `{processed_companies}` / `{total_companies}`")
    st.write(f"Current company: `{current_company or 'waiting'}`")
    st.write(f"Elapsed time: `{_format_duration((finished_at or time.time()) - started_at)}`")
    st.write(f"Interim backups written: `{backup_count}`")
    if last_backup_at is not None and last_backup_path:
        st.write(
            "Latest backup: "
            + f"`{last_backup_path}` at `{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(last_backup_at))}`"
        )
        backup_file = Path(last_backup_path)
        if backup_file.exists():
            st.download_button(
                label="Download latest backup CSV",
                data=backup_file.read_bytes(),
                file_name=backup_file.name,
                mime="text/csv",
            )

    progress_total = total_companies or 1
    progress_value = min(processed_companies / progress_total, 1.0)
    progress_label = (
        f"Processing {processed_companies}/{total_companies}: {current_company or 'waiting'}"
        if status in ACTIVE_JOB_STATUSES
        else f"{status.capitalize()} {processed_companies}/{total_companies}"
    )
    st.progress(progress_value, text=progress_label)

    controls = st.columns(3)
    if status == "running" and controls[0].button("Pause"):
        job.pause_event.set()
        with job.lock:
            job.status = "paused"
        st.rerun()
    if status == "paused" and controls[0].button("Resume"):
        job.pause_event.clear()
        with job.lock:
            job.status = "running"
        st.rerun()
    if status in {"running", "paused"} and controls[1].button("Stop"):
        job.stop_event.set()
        job.pause_event.clear()
        with job.lock:
            job.status = "stopping"
        st.rerun()
    if status in {"completed", "failed", "stopped"} and controls[2].button("Clear run state"):
        st.session_state.pop("enrichment_job", None)
        st.rerun()

    if status == "failed" and error_message:
        st.error(error_message)
    if status == "stopped":
        st.warning("The enrichment run was stopped before completion.")


def _render_cost_estimator(default_company_count: int, default_batch_size: int) -> None:
    with st.expander("Cost Estimator", expanded=False):
        st.caption(
            "Estimate total cost across curated OpenAI, Claude, and MiniMax models using your row count and token assumptions."
        )
        estimator_columns = st.columns(5)
        company_count = estimator_columns[0].number_input(
            "Companies",
            min_value=1,
            value=max(default_company_count, 1),
            step=1,
        )
        batch_size = estimator_columns[1].number_input(
            "Batch size",
            min_value=1,
            value=max(default_batch_size, 1),
            step=1,
        )
        shared_input_tokens = estimator_columns[2].number_input(
            "Shared input / request",
            min_value=0,
            value=900,
            step=50,
        )
        input_tokens_per_company = estimator_columns[3].number_input(
            "Input / company",
            min_value=0,
            value=90,
            step=10,
        )
        output_tokens_per_company = estimator_columns[4].number_input(
            "Output / company",
            min_value=0,
            value=180,
            step=10,
        )

        inputs = CostEstimatorInputs(
            company_count=int(company_count),
            batch_size=int(batch_size),
            shared_input_tokens_per_request=int(shared_input_tokens),
            input_tokens_per_company=int(input_tokens_per_company),
            output_tokens_per_company=int(output_tokens_per_company),
        )
        estimates = estimate_costs(inputs)

        summary = st.columns(3)
        summary[0].metric("Estimated requests", estimates[0].request_count)
        summary[1].metric("Estimated input tokens", f"{estimates[0].total_input_tokens:,}")
        summary[2].metric("Estimated output tokens", f"{estimates[0].total_output_tokens:,}")

        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Provider": estimate.provider,
                        "Model": estimate.model,
                        "Currency": estimate.currency,
                        "Input / 1M tokens": _format_money(
                            estimate.currency,
                            _find_rate(
                                provider=estimate.provider,
                                model=estimate.model,
                                cost_type="input",
                            ),
                        ),
                        "Output / 1M tokens": _format_money(
                            estimate.currency,
                            _find_rate(
                                provider=estimate.provider,
                                model=estimate.model,
                                cost_type="output",
                            ),
                        ),
                        "Estimated input cost": _format_money(
                            estimate.currency, estimate.estimated_input_cost
                        ),
                        "Estimated output cost": _format_money(
                            estimate.currency, estimate.estimated_output_cost
                        ),
                        "Estimated total cost": _format_money(
                            estimate.currency, estimate.estimated_total_cost
                        ),
                    }
                    for estimate in estimates
                ]
            ),
            width="stretch",
        )
        st.caption(
            "Estimator uses standard online pricing with provider-native currency. It does not model prompt caching, discounts, or exchange-rate conversion."
        )


def _render_job_result(job: Optional[EnrichmentJob]) -> None:
    if job is None:
        return

    with job.lock:
        status = job.status
        result_dataframe = job.result_dataframe
        output_filename = job.output_filename

    if status != "completed" or result_dataframe is None:
        return

    st.success("Enrichment complete.")
    st.subheader("Enriched Preview")
    st.dataframe(result_dataframe.head(25), width="stretch")

    csv_bytes = dataframe_to_csv_bytes(result_dataframe)
    st.download_button(
        label="Download enriched CSV",
        data=io.BytesIO(csv_bytes),
        file_name=output_filename,
        mime="text/csv",
    )


def _is_job_active(job: Optional[EnrichmentJob]) -> bool:
    if job is None:
        return False
    with job.lock:
        return job.status in ACTIVE_JOB_STATUSES


def _schedule_refresh(job: Optional[EnrichmentJob]) -> None:
    if not _is_job_active(job):
        return
    time.sleep(1)
    st.rerun()


def _format_duration(duration_seconds: float) -> str:
    total_seconds = max(int(duration_seconds), 0)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def _format_money(currency: str, amount: float) -> str:
    symbols = {"USD": "$", "CNY": "CNY "}
    return f"{symbols.get(currency, currency + ' ')}{amount:,.4f}"


def _find_rate(provider: str, model: str, cost_type: str) -> float:
    for pricing_model in DEFAULT_PRICING_MODELS:
        if pricing_model.provider == provider and pricing_model.model == model:
            return (
                pricing_model.input_price_per_million_tokens
                if cost_type == "input"
                else pricing_model.output_price_per_million_tokens
            )
    raise ValueError(f"Unknown pricing model: {provider} / {model}")


if __name__ == "__main__":
    main()
