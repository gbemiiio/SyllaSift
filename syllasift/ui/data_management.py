import streamlit as st

from syllasift.state.widgets import clear_saved_widget_state
from syllasift.storage.database import clear_user_data


def _clear_saved_data(user_id: str) -> None:
    clear_user_data(user_id)
    clear_saved_widget_state(st.session_state)
    st.session_state["clear_saved_confirmation"] = False


def display_clear_saved_data(user_id: str) -> None:
    st.subheader("Clear Saved Data")
    st.warning("This permanently removes all of your saved courses and deadlines.")
    confirmed = st.checkbox(
        "I understand that all saved data will be deleted.",
        key="clear_saved_confirmation",
    )
    st.button(
        "Clear saved data",
        disabled=not confirmed,
        type="primary",
        on_click=_clear_saved_data,
        args=(user_id,),
    )
