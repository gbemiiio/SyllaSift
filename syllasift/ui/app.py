import streamlit as st

from syllasift.state.reload_guard import render_reload_guard
from syllasift.state.uploads import has_unsaved_work, uploader_widget_key
from syllasift.storage.database import initialize_database
from syllasift.ui.calendar_export import display_calendar_export
from syllasift.ui.dashboard import display_dashboard
from syllasift.ui.data_management import display_clear_saved_data
from syllasift.ui.imports import display_manual_import, display_pdf_import
from syllasift.ui.saved_courses import display_saved_courses


def main() -> None:
    initialize_database()
    st.title("SyllaSift")
    st.caption(
        "Upload syllabus PDFs, extract deadlines, and track course progress."
    )

    display_dashboard()
    st.divider()
    display_pdf_import()
    display_manual_import()
    st.divider()
    display_saved_courses()
    st.divider()
    display_calendar_export()
    st.divider()
    display_clear_saved_data()

    current_uploads = st.session_state.get(
        uploader_widget_key(st.session_state), []
    )
    render_reload_guard(
        has_unsaved_work(st.session_state, bool(current_uploads))
    )
