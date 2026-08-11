"""Streamlit entrypoint and backward-compatible UI exports."""

import streamlit as st


st.set_page_config(
    page_title="SyllaSift",
    page_icon="📚",
    layout="wide",
)

from syllasift.config import (  # noqa: E402,F401
    COMPLETION_INSTRUCTION,
    NO_DATED_ASSIGNMENTS_MESSAGE,
    PREVIEW_COLUMNS,
)
from syllasift.state.widgets import (  # noqa: E402,F401
    initialize_calendar_export_selection,
    reset_deadline_and_export_state,
    synchronize_deadline_widget_state,
)
from syllasift.ui.app import main  # noqa: E402
from syllasift.ui.calendar_export import finish_calendar_export  # noqa: E402,F401
from syllasift.ui.imports import clean_uploaded_filename  # noqa: E402,F401


if __name__ == "__main__":
    main()
