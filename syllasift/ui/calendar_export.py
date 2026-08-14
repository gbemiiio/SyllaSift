from datetime import date

import streamlit as st

from syllasift.calendar.ics import build_ics_calendar
from syllasift.state.widgets import (
    finish_calendar_export as clear_export_selection,
    initialize_calendar_export_selection,
)
from syllasift.storage.database import (
    get_courses_for_export,
    get_deadlines_for_export,
)


def finish_calendar_export(session_state=None) -> None:
    state = st.session_state if session_state is None else session_state
    clear_export_selection(state)


def display_calendar_export(user_id: str) -> None:
    st.subheader("Export Calendar")
    st.caption(
        "Download incomplete deadlines for Google Calendar, "
        "Apple Calendar, or Outlook."
    )
    if st.session_state.pop("calendar_export_completed", False):
        st.success("Calendar downloaded. The export selection was cleared.")

    courses = get_courses_for_export(user_id)
    if not courses:
        st.info("Save a course before exporting a calendar.")
        return

    course_labels = {}
    for course in courses:
        identity = course["course_code"] or course["course_name"]
        if identity == course["course_name"]:
            base = f"{course['course_name']} ({course['semester']} {course['year']})"
        else:
            base = (
                f"{identity} — {course['course_name']} "
                f"({course['semester']} {course['year']})"
            )
        label = base if base not in course_labels else (
            f"{base} — Course {course['course_id']}"
        )
        course_labels[label] = course["course_id"]

    initialize_calendar_export_selection(st.session_state, course_labels)
    selected_labels = st.multiselect(
        "Choose courses", list(course_labels), key="calendar_export_courses",
    )
    deadlines = get_deadlines_for_export(user_id, [
        course_labels[label] for label in selected_labels
    ])
    if selected_labels:
        if deadlines:
            st.caption(f"{len(deadlines)} incomplete deadlines ready to export.")
        else:
            st.info("The selected courses have no incomplete deadlines to export.")

    st.download_button(
        "Download calendar (.ics)",
        data=build_ics_calendar(deadlines) if deadlines else "",
        file_name=f"syllasift-deadlines-{date.today().isoformat()}.ics",
        mime="text/calendar; charset=utf-8",
        on_click=finish_calendar_export,
        disabled=not selected_labels or not deadlines,
    )
