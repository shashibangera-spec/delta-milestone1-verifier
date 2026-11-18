"""Small state helpers for the Streamlit session-date selector."""

LIVE_SESSION_LABEL = "Live / Current Session"
SESSION_SELECTOR_KEY = "session_date_selector"


def normalize_session_selection(session_state, available_options):
    """Keep the current choice if valid; otherwise safely fall back to Live."""
    current = session_state.get(SESSION_SELECTOR_KEY, LIVE_SESSION_LABEL)
    if current not in available_options:
        current = LIVE_SESSION_LABEL
    session_state[SESSION_SELECTOR_KEY] = current
    return current


def return_to_live_session():
    """Streamlit button callback: select Live before the next script rerun."""
    import streamlit as st

    st.session_state[SESSION_SELECTOR_KEY] = LIVE_SESSION_LABEL
