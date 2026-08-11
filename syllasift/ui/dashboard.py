import streamlit as st

from syllasift.storage.database import get_dashboard_stats


def display_dashboard() -> None:
    total_courses, total_deadlines, completed = get_dashboard_stats()
    remaining = total_deadlines - completed
    st.subheader("Dashboard")
    columns = st.columns(4)
    columns[0].metric("Courses", total_courses)
    columns[1].metric("Assignments", total_deadlines)
    columns[2].metric("Completed", completed)
    columns[3].metric("Remaining", remaining)

    if total_deadlines:
        progress = completed / total_deadlines
        st.progress(progress)
        st.caption(
            f"{completed} of {total_deadlines} assignments completed "
            f"({progress:.0%})"
        )
    else:
        st.info("Upload a syllabus to begin tracking deadlines.")
