from datetime import date

import pandas as pd
import streamlit as st

from calendar_export import build_ics_calendar
from database import (
    clear_all_data,
    get_course_options,
    get_courses_for_export,
    get_dashboard_stats,
    get_deadlines,
    get_deadlines_for_export,
    initialize_database,
    save_course,
    save_deadlines,
    update_deadline_status,
)
from parser import (
    detect_course_metadata,
    extract_deadline_candidates,
    extract_pdf_document,
    extract_deadlines,
)


st.set_page_config(
    page_title="SyllaSift",
    page_icon="📚",
    layout="wide",
)


SEMESTERS = [
    "Spring",
    "Summer",
    "Fall",
    "Winter",
]

PREVIEW_COLUMNS = ["Include", "Item", "Due Date", "Page"]
NO_DATED_ASSIGNMENTS_MESSAGE = (
    "No dated assignments are listed in this PDF. "
    "You can add rows or import the course without deadlines."
)
COMPLETION_INSTRUCTION = (
    "Check a deadline only after you finish it. "
    "New deadlines start incomplete and are included in calendar exports."
)


def synchronize_deadline_widget_state(
    session_state,
    deadline_id,
    is_completed,
):
    """Initialize a completion checkbox from its saved database value."""
    widget_key = f"deadline_{deadline_id}"
    sync_key = f"{widget_key}_saved_value"

    if session_state.get(sync_key) != is_completed:
        session_state[widget_key] = is_completed
        session_state[sync_key] = is_completed

    return widget_key, sync_key


def reset_deadline_and_export_state(session_state):
    """Forget widget state that must be rebuilt after an import."""
    for key in list(session_state):
        if (
            key in {
                "calendar_export_courses",
                "calendar_export_selection_initialized",
                "calendar_export_completed",
            }
            or key.startswith("deadline_")
        ):
            del session_state[key]


def initialize_calendar_export_selection(session_state, course_labels):
    """Select all courses once, then preserve the user's selection."""
    initialized_key = "calendar_export_selection_initialized"
    if not session_state.get(initialized_key, False):
        session_state["calendar_export_courses"] = list(course_labels)
        session_state[initialized_key] = True


def finish_calendar_export(session_state=None):
    """Clear the temporary export selection after a download."""
    state = st.session_state if session_state is None else session_state
    state["calendar_export_courses"] = []
    state["calendar_export_selection_initialized"] = True
    state["calendar_export_completed"] = True


def clean_uploaded_filename(filename):
    """Keep an accidentally concatenated download name readable in the preview."""
    first_pdf_end = filename.lower().find(".pdf")
    if first_pdf_end >= 0:
        return filename[:first_pdf_end + 4]
    return filename


def display_dashboard():
    total_courses, total_deadlines, completed = (
        get_dashboard_stats()
    )

    remaining = total_deadlines - completed

    st.subheader("Dashboard")

    column1, column2, column3, column4 = st.columns(4)

    column1.metric("Courses", total_courses)
    column2.metric("Assignments", total_deadlines)
    column3.metric("Completed", completed)
    column4.metric("Remaining", remaining)

    if total_deadlines > 0:
        progress = completed / total_deadlines

        st.progress(progress)
        st.caption(
            f"{completed} of {total_deadlines} assignments completed "
            f"({progress:.0%})"
        )
    else:
        st.info(
            "Upload a syllabus to begin tracking deadlines."
        )


def initialize_upload_state(uploaded_files):
    uploaded_names = [
        uploaded_file.name
        for uploaded_file in uploaded_files
    ]

    previous_names = st.session_state.get(
        "uploaded_file_names",
        [],
    )

    if uploaded_names != previous_names:
        st.session_state.uploaded_file_names = (
            uploaded_names
        )
        st.session_state.processed_syllabi = []


def process_uploaded_files(uploaded_files):
    processed_syllabi = []

    for file_index, uploaded_file in enumerate(
        uploaded_files
    ):
        try:
            document = extract_pdf_document(
                uploaded_file
            )
        except Exception as error:
            processed_syllabi.append(
                {
                    "file_index": file_index,
                    "filename": uploaded_file.name,
                    "error": str(error),
                }
            )
            continue

        syllabus_text = document["text"]

        if not syllabus_text.strip():
            processed_syllabi.append(
                {
                    "file_index": file_index,
                    "filename": uploaded_file.name,
                    "error": (
                        "No readable text was found. "
                        "This may be a scanned PDF."
                    ),
                }
            )
            continue

        metadata = detect_course_metadata(
            syllabus_text,
            uploaded_file.name,
        )

        processed_syllabi.append(
            {
                "file_index": file_index,
                "filename": uploaded_file.name,
                "text": syllabus_text,
                "document": document,
                "metadata": metadata,
                "error": None,
            }
        )

    st.session_state.processed_syllabi = (
        processed_syllabi
    )


def display_pdf_import():
    st.subheader("Import Syllabi")

    st.caption(
        "Upload one or more syllabus PDFs. "
        "Review the detected course information before saving."
    )

    uploaded_files = st.file_uploader(
        "Upload syllabus PDFs",
        type=["pdf"],
        accept_multiple_files=True,
    )

    if not uploaded_files:
        return

    initialize_upload_state(uploaded_files)

    if st.button("Analyze uploaded syllabi"):
        with st.spinner("Reading syllabi..."):
            process_uploaded_files(uploaded_files)

    processed_syllabi = st.session_state.get(
        "processed_syllabi",
        [],
    )

    if not processed_syllabi:
        return

    valid_course_count = 0

    with st.form("batch_import_form"):
        course_entries = []

        for syllabus in processed_syllabi:
            filename = syllabus["filename"]

            st.divider()
            st.subheader(clean_uploaded_filename(filename))

            if syllabus["error"]:
                st.error(syllabus["error"])
                continue

            metadata = syllabus["metadata"]
            file_index = syllabus["file_index"]

            default_semester = metadata["semester"]

            if default_semester not in SEMESTERS:
                default_semester = "Fall"

            semester_index = SEMESTERS.index(
                default_semester
            )

            left_column, right_column = st.columns(2)

            with left_column:
                course_name = st.text_input(
                    "Course name",
                    value=metadata["course_name"],
                    key=f"course_name_{file_index}",
                )

                course_code = st.text_input(
                    "Course code",
                    value=metadata["course_code"],
                    key=f"course_code_{file_index}",
                )

            with right_column:
                semester = st.selectbox(
                    "Semester",
                    SEMESTERS,
                    index=semester_index,
                    key=f"semester_{file_index}",
                )

                year = st.number_input(
                    "Year",
                    min_value=2000,
                    max_value=2100,
                    value=int(metadata["year"]),
                    step=1,
                    key=f"year_{file_index}",
                )

            candidates = extract_deadline_candidates(
                syllabus["document"],
                int(year),
            )

            for notice in syllabus["document"].get("notices", []):
                st.info(notice)

            preview_columns = PREVIEW_COLUMNS
            if candidates:
                preview_dataframe = pd.DataFrame(candidates).rename(
                    columns={"Normalized Date": "Due Date"}
                )[preview_columns]
                preview_dataframe["Due Date"] = pd.to_datetime(
                    preview_dataframe["Due Date"]
                ).dt.date
                st.caption(
                    f"{len(candidates)} deadlines found. "
                    "Review or edit them before importing."
                )
            else:
                preview_dataframe = pd.DataFrame(columns=preview_columns)
                st.info(
                    NO_DATED_ASSIGNMENTS_MESSAGE
                )

            edited_dataframe = st.data_editor(
                preview_dataframe,
                use_container_width=True,
                hide_index=True,
                num_rows="dynamic",
                disabled=["Page"],
                column_config={
                    "Include": st.column_config.CheckboxColumn(
                        "Include", default=True,
                    ),
                    "Due Date": st.column_config.DateColumn(
                        "Due Date", format="YYYY-MM-DD",
                    ),
                },
                key=f"deadline_editor_{file_index}",
            )

            deadlines = []
            review_errors = []
            for row_number, row in edited_dataframe.iterrows():
                if not bool(row.get("Include", False)):
                    continue
                item = str(row.get("Item", "")).strip()
                due_date = row.get("Due Date")
                if not item or pd.isna(due_date):
                    review_errors.append(
                        f"row {row_number + 1} needs an item and due date"
                    )
                    continue
                normalized_date = pd.Timestamp(due_date).strftime("%Y-%m-%d")
                deadlines.append({
                    "Item": item,
                    "Date": normalized_date,
                    "Normalized Date": normalized_date,
                })

            include_course = st.checkbox(
                "Include this course in import",
                value=bool(course_name.strip()),
                key=f"include_{file_index}",
            )

            course_entries.append(
                {
                    "filename": filename,
                    "course_name": course_name,
                    "course_code": course_code,
                    "semester": semester,
                    "year": int(year),
                    "deadlines": deadlines,
                    "review_errors": review_errors,
                    "include": include_course,
                }
            )

            if include_course:
                valid_course_count += 1

        submitted = st.form_submit_button(
            f"Import {valid_course_count} course(s)"
        )

    if not submitted:
        return

    imported_courses = 0
    imported_deadlines = 0
    errors = []

    for entry in course_entries:
        if not entry["include"]:
            continue

        if not entry["course_name"].strip():
            errors.append(
                f"{entry['filename']}: course name is required."
            )
            continue

        if entry["review_errors"]:
            for review_error in entry["review_errors"]:
                errors.append(
                    f"{entry['filename']}: {review_error}."
                )
            continue

        try:
            course_id = save_course(
                entry["course_name"].strip(),
                entry["course_code"].strip() or None,
                entry["semester"],
                entry["year"],
            )

            if entry["deadlines"]:
                save_deadlines(course_id, entry["deadlines"])

            imported_courses += 1
            imported_deadlines += len(
                entry["deadlines"]
            )

        except Exception as error:
            errors.append(
                f"{entry['filename']}: {error}"
            )

    if imported_courses:
        reset_deadline_and_export_state(st.session_state)
        st.success(
            f"Imported {imported_courses} course(s) "
            f"and {imported_deadlines} deadline(s)."
        )

    for error in errors:
        st.error(error)

    if imported_courses and not errors:
        st.session_state.processed_syllabi = []
        st.session_state.uploaded_file_names = []
        st.rerun()


def display_manual_import():
    with st.expander(
        "Paste syllabus text instead"
    ):
        with st.form("manual_import_form"):
            course_name = st.text_input(
                "Course name"
            )

            course_code = st.text_input(
                "Course code"
            )

            semester = st.selectbox(
                "Semester",
                SEMESTERS,
                key="manual_semester",
            )

            course_year = st.number_input(
                "Course year",
                min_value=2000,
                max_value=2100,
                value=2026,
                step=1,
            )

            syllabus_text = st.text_area(
                "Syllabus text",
                height=220,
            )

            submitted = st.form_submit_button(
                "Extract and save"
            )

        if not submitted:
            return

        if not course_name.strip():
            st.error("Course name is required.")
            return

        if not syllabus_text.strip():
            st.error("Syllabus text is required.")
            return

        deadlines = extract_deadlines(
            syllabus_text,
            int(course_year),
        )

        if not deadlines:
            st.warning(
                "No supported deadlines were found. The course will be saved "
                "without deadlines."
            )

        course_id = save_course(
            course_name.strip(),
            course_code.strip() or None,
            semester,
            int(course_year),
        )

        if deadlines:
            save_deadlines(course_id, deadlines)

        st.success(
            f"Saved {len(deadlines)} deadlines."
        )
        reset_deadline_and_export_state(st.session_state)
        st.rerun()


def display_saved_courses():
    st.subheader("Saved Courses")

    course_options = get_course_options()

    if not course_options:
        st.info("No saved courses yet.")
        return

    course_labels = {}
    label_counts = {}

    for course_id, course_name in course_options:
        label_counts[course_name] = (
            label_counts.get(course_name, 0) + 1
        )

        count = label_counts[course_name]

        if count == 1:
            label = course_name
        else:
            label = f"{course_name} ({count})"

        course_labels[label] = course_id

    selected_label = st.selectbox(
        "Choose a course",
        list(course_labels.keys()),
    )

    selected_course_id = course_labels[
        selected_label
    ]

    deadlines = get_deadlines(
        selected_course_id
    )

    if not deadlines:
        st.info(
            "No deadlines are saved for this course."
        )
        return

    deadline_dataframe = pd.DataFrame(
        deadlines,
        columns=[
            "Deadline ID",
            "Course ID",
            "Item",
            "Raw Date",
            "Due Date",
            "Completed",
            "Created At",
            "Completed At",
        ],
    )

    completed_count = int(
        deadline_dataframe["Completed"].sum()
    )

    total_count = len(deadline_dataframe)

    st.caption(
        f"{completed_count} of {total_count} completed"
    )
    st.caption(COMPLETION_INSTRUCTION)

    for _, row in deadline_dataframe.iterrows():
        deadline_id = int(row["Deadline ID"])
        is_completed = bool(row["Completed"])
        widget_key, sync_key = synchronize_deadline_widget_state(
            st.session_state,
            deadline_id,
            is_completed,
        )

        checked = st.checkbox(
            f"{row['Item']} — {row['Due Date']}",
            key=widget_key,
        )

        if checked != is_completed:
            update_deadline_status(
                deadline_id,
                checked,
            )
            st.session_state[sync_key] = checked
            st.rerun()


def display_calendar_export():
    st.subheader("Export Calendar")
    st.caption(
        "Download incomplete deadlines for Google Calendar, "
        "Apple Calendar, or Outlook."
    )
    if st.session_state.pop("calendar_export_completed", False):
        st.success("Calendar downloaded. The export selection was cleared.")

    courses = get_courses_for_export()
    if not courses:
        st.info("Save a course before exporting a calendar.")
        return

    course_labels = {}
    for course in courses:
        identity = course["course_code"] or course["course_name"]
        if identity == course["course_name"]:
            base_label = (
                f"{course['course_name']} "
                f"({course['semester']} {course['year']})"
            )
        else:
            base_label = (
                f"{identity} — {course['course_name']} "
                f"({course['semester']} {course['year']})"
            )
        label = base_label
        if label in course_labels:
            label = f"{base_label} — Course {course['course_id']}"
        course_labels[label] = course["course_id"]

    initialize_calendar_export_selection(
        st.session_state,
        course_labels,
    )
    selected_labels = st.multiselect(
        "Choose courses",
        list(course_labels),
        key="calendar_export_courses",
    )
    selected_ids = [course_labels[label] for label in selected_labels]
    deadlines = get_deadlines_for_export(selected_ids)

    if selected_labels:
        if deadlines:
            st.caption(f"{len(deadlines)} incomplete deadlines ready to export.")
        else:
            st.info("The selected courses have no incomplete deadlines to export.")

    calendar_data = build_ics_calendar(deadlines) if deadlines else ""
    st.download_button(
        "Download calendar (.ics)",
        data=calendar_data,
        file_name=f"syllasift-deadlines-{date.today().isoformat()}.ics",
        mime="text/calendar; charset=utf-8",
        on_click=finish_calendar_export,
        disabled=not selected_ids or not deadlines,
        use_container_width=False,
    )


def clear_app_session_state():
    """Remove state tied to imported or saved syllabus data."""
    exact_keys = {
        "uploaded_file_names",
        "processed_syllabi",
        "clear_all_confirmation",
        "calendar_export_courses",
        "calendar_export_selection_initialized",
        "calendar_export_completed",
    }
    key_prefixes = (
        "course_name_",
        "course_code_",
        "semester_",
        "year_",
        "include_",
        "deadline_",
        "deadline_editor_",
    )

    for key in list(st.session_state):
        if key in exact_keys or key.startswith(key_prefixes):
            del st.session_state[key]


def display_clear_all_data():
    st.subheader("Clear All Data")
    st.warning(
        "This permanently removes every saved course and deadline."
    )

    confirmed = st.checkbox(
        "I understand that all saved data will be deleted.",
        key="clear_all_confirmation",
    )

    if st.button(
        "Clear all data",
        disabled=not confirmed,
        type="primary",
    ):
        clear_all_data()
        clear_app_session_state()
        st.rerun()


def main():
    initialize_database()

    st.title("SyllaSift")
    st.caption(
        "Upload syllabus PDFs, extract deadlines, "
        "and track course progress."
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

    display_clear_all_data()


if __name__ == "__main__":
    main()
