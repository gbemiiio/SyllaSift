import pandas as pd
import streamlit as st

from syllasift.parsing import extract_deadline_candidates, extract_deadlines
from syllasift.config import (
    NO_DATED_ASSIGNMENTS_MESSAGE,
    PREVIEW_COLUMNS,
    SEMESTERS,
)
from syllasift.services.uploads import analyze_uploaded_files
from syllasift.state.uploads import (
    advance_uploader_generation,
    clear_pending_syllabi,
    get_pending_syllabi,
    prune_stale_uploader_widgets,
    register_pending_syllabi,
    remove_pending_syllabus,
    uploader_widget_key,
)
from syllasift.state.widgets import reset_deadline_and_export_state
from syllasift.storage.database import save_course, save_deadlines


def clean_uploaded_filename(filename: str) -> str:
    first_pdf_end = filename.lower().find(".pdf")
    return filename[:first_pdf_end + 4] if first_pdf_end >= 0 else filename


@st.dialog("Clear all uploaded syllabi?")
def confirm_clear_uploaded_syllabi() -> None:
    st.write(
        "This discards every unsaved PDF and all edits in their previews. "
        "Saved courses will not be changed."
    )
    keep_column, clear_column = st.columns(2)
    if keep_column.button("Keep uploads", width="stretch"):
        st.rerun()
    if clear_column.button(
        "Clear uploaded syllabi", type="primary", width="stretch",
    ):
        clear_pending_syllabi(st.session_state)
        st.session_state["upload_notice"] = "All unsaved PDF uploads were cleared."
        st.rerun()


def _display_import_result() -> None:
    result = st.session_state.pop("pdf_import_result", None)
    if not result:
        return
    if result["courses"]:
        st.success(
            f"Imported {result['courses']} course(s) and "
            f"{result['deadlines']} deadline(s)."
        )
    for error in result["errors"]:
        st.error(error)


def _preview_frame(candidates) -> pd.DataFrame:
    if not candidates:
        return pd.DataFrame(columns=PREVIEW_COLUMNS)
    frame = pd.DataFrame(candidates).rename(
        columns={"Normalized Date": "Due Date"}
    )[PREVIEW_COLUMNS]
    frame["Due Date"] = pd.to_datetime(frame["Due Date"]).dt.date
    frame["Page"] = pd.array(frame["Page"], dtype="Int64")
    return frame


def _render_pending_syllabus(syllabus):
    upload_id = syllabus["upload_id"]
    with st.container(border=True):
        heading_column, remove_column = st.columns([5, 1])
        heading_column.subheader(clean_uploaded_filename(syllabus["filename"]))
        if remove_column.button(
            "Remove this syllabus",
            key=f"remove_{upload_id}",
            width="stretch",
        ):
            remove_pending_syllabus(st.session_state, upload_id)
            st.rerun()

        if syllabus["error"]:
            st.error(syllabus["error"])
            return None

        metadata = syllabus["metadata"]
        default_semester = metadata["semester"]
        if default_semester not in SEMESTERS:
            default_semester = "Fall"

        left_column, right_column = st.columns(2)
        with left_column:
            course_name = st.text_input(
                "Course name",
                value=metadata["course_name"],
                key=f"course_name_{upload_id}",
            )
            course_code = st.text_input(
                "Course code",
                value=metadata["course_code"],
                key=f"course_code_{upload_id}",
            )
        with right_column:
            semester = st.selectbox(
                "Semester",
                SEMESTERS,
                index=SEMESTERS.index(default_semester),
                key=f"semester_{upload_id}",
            )
            year = st.number_input(
                "Year",
                min_value=2000,
                max_value=2100,
                value=int(metadata["year"]),
                step=1,
                key=f"year_{upload_id}",
            )

        candidates = extract_deadline_candidates(syllabus["document"], int(year))
        for notice in syllabus["document"].get("notices", []):
            st.info(notice)

        if candidates:
            st.caption(
                f"{len(candidates)} deadlines found. "
                "Review or edit them before importing."
            )
        else:
            st.info(NO_DATED_ASSIGNMENTS_MESSAGE)

        edited = st.data_editor(
            _preview_frame(candidates),
            width="stretch",
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
                "Page": st.column_config.NumberColumn(
                    "Page", format="%d",
                ),
            },
            key=f"deadline_editor_{upload_id}",
        )

        deadlines = []
        review_errors = []
        for row_number, row in edited.iterrows():
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
            key=f"include_{upload_id}",
        )
        return {
            "upload_id": upload_id,
            "filename": syllabus["filename"],
            "course_name": course_name,
            "course_code": course_code,
            "semester": semester,
            "year": int(year),
            "deadlines": deadlines,
            "review_errors": review_errors,
            "include": include_course,
        }


def _import_entries(entries) -> None:
    imported_ids = []
    imported_courses = 0
    imported_deadlines = 0
    errors = []
    for entry in entries:
        if not entry or not entry["include"]:
            continue
        if not entry["course_name"].strip():
            errors.append(f"{entry['filename']}: course name is required.")
            continue
        if entry["review_errors"]:
            errors.extend(
                f"{entry['filename']}: {message}."
                for message in entry["review_errors"]
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
            imported_ids.append(entry["upload_id"])
            imported_courses += 1
            imported_deadlines += len(entry["deadlines"])
        except Exception as error:
            errors.append(f"{entry['filename']}: {error}")

    for upload_id in imported_ids:
        remove_pending_syllabus(st.session_state, upload_id)
    if imported_ids:
        reset_deadline_and_export_state(st.session_state)
    st.session_state["pdf_import_result"] = {
        "courses": imported_courses,
        "deadlines": imported_deadlines,
        "errors": errors,
    }
    st.rerun()


def display_pdf_import() -> None:
    st.subheader("Import Syllabi")
    st.caption(
        "Upload one or more syllabus PDFs. "
        "Review the detected course information before saving."
    )
    _display_import_result()
    if notice := st.session_state.pop("upload_notice", None):
        st.success(notice)

    prune_stale_uploader_widgets(st.session_state)
    uploaded_files = st.file_uploader(
        "Upload syllabus PDFs",
        type=["pdf"],
        accept_multiple_files=True,
        key=uploader_widget_key(st.session_state),
    )
    pending = get_pending_syllabi(st.session_state)
    action_row = st.container(
        horizontal=True,
        horizontal_alignment="distribute",
    )
    if action_row.button(
        "Analyze uploaded syllabi", disabled=not uploaded_files,
    ):
        with st.spinner("Reading syllabi..."):
            register_pending_syllabi(
                st.session_state, analyze_uploaded_files(uploaded_files),
            )
        advance_uploader_generation(st.session_state)
        st.rerun()

    if action_row.button(
        "Clear all uploaded syllabi",
        disabled=not uploaded_files and not pending,
    ):
        confirm_clear_uploaded_syllabi()

    pending = get_pending_syllabi(st.session_state)
    if not pending:
        return
    entries = [_render_pending_syllabus(syllabus) for syllabus in pending]
    selected_count = sum(bool(entry and entry["include"]) for entry in entries)
    if st.button(
        f"Import {selected_count} course(s)",
        disabled=selected_count == 0,
        type="primary",
    ):
        _import_entries(entries)


def display_manual_import() -> None:
    if notice := st.session_state.pop("manual_import_notice", None):
        st.success(notice)
    with st.expander("Paste syllabus text instead"):
        with st.form("manual_import_form", clear_on_submit=True):
            course_name = st.text_input("Course name", key="manual_course_name")
            course_code = st.text_input("Course code", key="manual_course_code")
            semester = st.selectbox(
                "Semester", SEMESTERS, key="manual_semester",
            )
            course_year = st.number_input(
                "Course year",
                min_value=2000,
                max_value=2100,
                value=2026,
                step=1,
                key="manual_year",
            )
            syllabus_text = st.text_area(
                "Syllabus text", height=220, key="manual_syllabus_text",
            )
            submitted = st.form_submit_button("Extract and save")

        if not submitted:
            return
        if not course_name.strip():
            st.error("Course name is required.")
            return
        if not syllabus_text.strip():
            st.error("Syllabus text is required.")
            return

        deadlines = extract_deadlines(syllabus_text, int(course_year))
        course_id = save_course(
            course_name.strip(),
            course_code.strip() or None,
            semester,
            int(course_year),
        )
        if deadlines:
            save_deadlines(course_id, deadlines)
        reset_deadline_and_export_state(st.session_state)
        st.session_state["manual_import_notice"] = (
            f"Saved {len(deadlines)} deadlines."
        )
        st.rerun()
