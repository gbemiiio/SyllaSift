import pandas as pd
import streamlit as st

from syllasift.config import COMPLETION_INSTRUCTION
from syllasift.state.widgets import synchronize_deadline_widget_state
from syllasift.storage.database import (
    get_course_options,
    get_deadlines,
    update_deadline_status,
)


def display_saved_courses(user_id: str) -> None:
    st.subheader("Saved Courses")
    course_options = get_course_options(user_id)
    if not course_options:
        st.info("No saved courses yet.")
        return

    labels = {}
    counts = {}
    for course_id, course_name in course_options:
        counts[course_name] = counts.get(course_name, 0) + 1
        suffix = f" ({counts[course_name]})" if counts[course_name] > 1 else ""
        labels[f"{course_name}{suffix}"] = course_id

    selected_label = st.selectbox("Choose a course", list(labels))
    deadlines = get_deadlines(user_id, labels[selected_label])
    if not deadlines:
        st.info("No deadlines are saved for this course.")
        return

    frame = pd.DataFrame(
        deadlines,
        columns=[
            "Deadline ID", "Course ID", "Item", "Raw Date", "Due Date",
            "Completed", "Created At", "Completed At",
        ],
    )
    st.caption(f"{int(frame['Completed'].sum())} of {len(frame)} completed")
    st.caption(COMPLETION_INSTRUCTION)

    for _, row in frame.iterrows():
        deadline_id = int(row["Deadline ID"])
        is_completed = bool(row["Completed"])
        widget_key, sync_key = synchronize_deadline_widget_state(
            st.session_state, deadline_id, is_completed,
        )
        checked = st.checkbox(
            f"{row['Item']} — {row['Due Date']}", key=widget_key,
        )
        if checked != is_completed:
            update_deadline_status(user_id, deadline_id, checked)
            st.session_state[sync_key] = checked
            st.rerun()
