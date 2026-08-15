from datetime import date

import streamlit as st

from syllasift.calendar.ics import build_ics_calendar
from syllasift.state.widgets import (
    CALENDAR_EXPORT_SELECTION_KEY,
    finish_calendar_export as preserve_export_selection,
    initialize_calendar_export_selection,
)
from syllasift.storage.database import (
    get_courses_for_export,
    get_deadlines_for_export,
)


def finish_calendar_export(session_state=None) -> None:
    state = st.session_state if session_state is None else session_state
    preserve_export_selection(state)


def display_calendar_export(user_id: str) -> None:
    st.subheader("Export Calendar")
    st.caption(
        "Download incomplete deadlines for Google Calendar, "
        "Apple Calendar, or Outlook."
    )
    courses = get_courses_for_export(user_id)
    if not courses:
        st.info("Save a course before exporting a calendar.")
        return

    labels_by_id = {}
    used_labels = set()
    for course in courses:
        identity = course["course_code"] or course["course_name"]
        if identity == course["course_name"]:
            base = f"{course['course_name']} ({course['semester']} {course['year']})"
        else:
            base = (
                f"{identity} — {course['course_name']} "
                f"({course['semester']} {course['year']})"
            )
        label = base if base not in used_labels else (
            f"{base} — Course {course['course_id']}"
        )
        used_labels.add(label)
        labels_by_id[course["course_id"]] = label

    initialize_calendar_export_selection(st.session_state, labels_by_id)
    selected_course_ids = st.multiselect(
        "Choose courses",
        list(labels_by_id),
        format_func=labels_by_id.__getitem__,
        key=CALENDAR_EXPORT_SELECTION_KEY,
    )
    deadlines = get_deadlines_for_export(user_id, selected_course_ids)
    if selected_course_ids:
        if deadlines:
            st.caption(f"{len(deadlines)} incomplete deadlines ready to export.")
        else:
            st.info("The selected courses have no incomplete deadlines to export.")

    st.download_button(
        "Download calendar (.ics)",
        data=build_ics_calendar(deadlines) if deadlines else "",
        file_name=f"syllasift-deadlines-{date.today().isoformat()}.ics",
        mime="text/calendar; charset=utf-8",
        on_click="ignore",
        disabled=not selected_course_ids or not deadlines,
    )
