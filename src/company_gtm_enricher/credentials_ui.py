from __future__ import annotations

import os

from dotenv import load_dotenv
import streamlit as st


def _clear_session_keys() -> None:
    st.session_state["session_openai_api_key"] = ""
    st.session_state["session_serper_api_key"] = ""


def render_api_keys(*, disabled: bool = False) -> tuple[str, str]:
    """Return session overrides; server credentials never populate the widgets."""
    load_dotenv()
    with st.sidebar.expander("API keys", expanded=True):
        st.caption("Leave blank to use keys configured by the app owner.")
        openai_key = st.text_input(
            "OpenAI API key", type="password", key="session_openai_api_key",
            disabled=disabled, autocomplete="off",
            help="Used for Company facts and People classification.",
        ).strip()
        serper_key = st.text_input(
            "Serper API key", type="password", key="session_serper_api_key",
            disabled=disabled, autocomplete="off",
            help="Used only for People → Search + LLM, to find public search results.",
        ).strip()
        for label, override, variable in (
            ("OpenAI", openai_key, "OPENAI_API_KEY"),
            ("Serper", serper_key, "SERPER_API_KEY"),
        ):
            source = "session key" if override else (
                "app owner's key" if os.getenv(variable, "").strip() else "not configured"
            )
            st.caption(f"{label}: {source}")
        st.caption(
            "Entered keys are sent to this app's server for API requests and kept "
            "in this session's memory. They are not saved to .env or result files."
        )
        st.button(
            "Clear entered keys", on_click=_clear_session_keys,
            disabled=disabled or not (openai_key or serper_key),
            help="Removes your session overrides; app-owner keys remain available.",
        )
        if disabled:
            st.caption("Keys can be changed after the current run finishes or stops.")
    return openai_key, serper_key
