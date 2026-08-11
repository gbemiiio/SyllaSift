import streamlit as st

from syllasift.state.widgets import clear_saved_widget_state
from syllasift.storage.database import clear_all_data


def display_clear_saved_data() -> None:
    st.subheader("Clear Saved Data")
    st.warning("This permanently removes every saved course and deadline.")
    confirmed = st.checkbox(
        "I understand that all saved data will be deleted.",
        key="clear_saved_confirmation",
    )
    if st.button(
        "Clear saved data", disabled=not confirmed, type="primary",
    ):
        clear_all_data()
        clear_saved_widget_state(st.session_state)
        st.rerun()
