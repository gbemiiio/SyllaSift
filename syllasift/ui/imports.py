import uuid

import pandas as pd
import streamlit as st

from syllasift.auth import request_sign_in_dialog
from syllasift.calendar.ics import build_ics_calendar
from syllasift.parsing import extract_deadline_review, extract_deadlines
from syllasift.parsing.dates import course_year_context
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
from syllasift.storage.database import upsert_course_with_deadlines


def clean_uploaded_filename(filename: str) -> str:
    first_pdf_end = filename.lower().find(".pdf")
    return filename[:first_pdf_end + 4] if first_pdf_end >= 0 else filename


def _guest_uid(*parts) -> str:
    identity = "|".join(str(part).strip().casefold() for part in parts)
    return f"guest-{uuid.uuid5(uuid.NAMESPACE_URL, identity)}@syllasift.local"


def _clear_uploaded_syllabi() -> None:
    clear_pending_syllabi(st.session_state)
    st.session_state["upload_notice"] = "All unsaved PDF uploads were cleared."


def _display_import_result() -> None:
    result = st.session_state.pop("pdf_import_result", None)
    if not result:
        return
    if result["courses"]:
        course_summary = f"Imported {result['courses']} course(s)"
        if result.get("reused_courses"):
            course_summary += f" ({result['reused_courses']} merged)"
        st.success(
            f"{course_summary} and {result['deadlines']} new deadline(s)."
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

        review = extract_deadline_review(
            syllabus["document"], course_year_context(int(year), semester)
        )
        candidates = review["candidates"]
        multiple_date_assessments = review["multiple_date_assessments"]
        unresolved_assessments = review["unresolved_assessments"]
        for notice in syllabus["document"].get("notices", []):
            st.info(notice)

        if candidates or multiple_date_assessments:
            reviewable_count = len(candidates) + len(multiple_date_assessments)
            st.caption(
                f"{reviewable_count} deadline(s) found. "
                "Review or edit them before importing."
            )
        elif not unresolved_assessments:
            st.info(NO_DATED_ASSIGNMENTS_MESSAGE)

        if unresolved_assessments:
            st.warning(
                "Some assignments do not have specific dates in this syllabus. "
                "Check Canvas for the specific due dates."
            )

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

        for choice_index, assessment in enumerate(multiple_date_assessments):
            option_labels = [
                f"{choice['label']} ({choice['normalized_date']})"
                for choice in assessment["choices"]
            ]
            selected_label = st.selectbox(
                f"Choose one date for {assessment['item']}",
                options=option_labels,
                index=None,
                placeholder="Select the date to keep",
                key=f"deadline_choice_{choice_index}_{upload_id}",
            )
            st.caption(
                "The syllabus lists multiple possible dates. "
                "Only the date you choose will be saved or exported."
            )
            if selected_label is None:
                review_errors.append(
                    f"choose one date for {assessment['item']}"
                )
                continue
            selected_index = option_labels.index(selected_label)
            selected = assessment["choices"][selected_index]
            deadlines.append({
                "Item": assessment["item"],
                "Date": selected["label"],
                "Normalized Date": selected["normalized_date"],
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


def _calendar_deadlines(entries):
    calendar_rows = []
    for entry in entries:
        if (
            not _entry_is_importable(entry)
        ):
            continue
        for deadline in entry["deadlines"]:
            course_identity = (
                entry["course_code"] or entry["course_name"]
            ).strip().casefold()
            event_uid = _guest_uid(
                entry["upload_id"],
                course_identity,
                entry["semester"],
                entry["year"],
                deadline["Item"],
                deadline["Normalized Date"],
            )
            calendar_rows.append({
                "event_uid": event_uid,
                "course_name": entry["course_name"].strip(),
                "course_code": entry["course_code"].strip() or None,
                "semester": entry["semester"],
                "year": entry["year"],
                "item": deadline["Item"],
                "due_date": deadline["Normalized Date"],
            })
    return calendar_rows


def _entry_is_importable(entry):
    return bool(
        entry
        and entry["include"]
        and entry["course_name"].strip()
        and not entry["review_errors"]
    )


def _import_entries(entries, user_id) -> None:
    imported_ids = []
    imported_courses = 0
    imported_deadlines = 0
    reused_courses = 0
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
            result = upsert_course_with_deadlines(
                user_id,
                entry["course_name"].strip(),
                entry["course_code"].strip() or None,
                entry["semester"],
                entry["year"],
                entry["deadlines"],
            )
            imported_ids.append(entry["upload_id"])
            imported_courses += 1
            imported_deadlines += result["deadlines_inserted"]
            reused_courses += int(not result["course_created"])
        except Exception as error:
            errors.append(f"{entry['filename']}: {error}")

    for upload_id in imported_ids:
        remove_pending_syllabus(st.session_state, upload_id)
    if imported_ids:
        reset_deadline_and_export_state(st.session_state)
    st.session_state["pdf_import_result"] = {
        "courses": imported_courses,
        "deadlines": imported_deadlines,
        "reused_courses": reused_courses,
        "errors": errors,
    }
    st.rerun()


def display_pdf_import(user) -> None:
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

    action_row.button(
        "Clear all uploaded syllabi",
        disabled=not uploaded_files and not pending,
        on_click=_clear_uploaded_syllabi,
    )

    pending = get_pending_syllabi(st.session_state)
    if not pending:
        return
    entries = [_render_pending_syllabus(syllabus) for syllabus in pending]
    selected_count = sum(_entry_is_importable(entry) for entry in entries)
    calendar_deadlines = _calendar_deadlines(entries)
    st.download_button(
        "Download reviewed deadlines (.ics)",
        data=build_ics_calendar(calendar_deadlines) if calendar_deadlines else "",
        file_name="syllasift-reviewed-deadlines.ics",
        mime="text/calendar; charset=utf-8",
        disabled=not calendar_deadlines,
    )
    if user.is_authenticated:
        if st.button(
            f"Import {selected_count} course(s)",
            disabled=selected_count == 0,
            type="primary",
        ):
            _import_entries(entries, user.user_id)
    else:
        st.caption(
            "Guest work is not saved. Sign in before importing to keep courses "
            "and track completion; the Google redirect may clear this upload."
        )
        st.button(
            "Sign in with Google to save",
            key="pdf_guest_sign_in",
            on_click=request_sign_in_dialog,
        )


def _manual_calendar_deadlines(draft, deadlines):
    return [
        {
            "event_uid": _guest_uid(
                draft["draft_id"],
                draft.get("course_code") or draft["course_name"],
                draft["semester"],
                draft["year"],
                deadline["Item"],
                deadline["Normalized Date"],
            ),
            "course_name": draft["course_name"],
            "course_code": draft["course_code"],
            "semester": draft["semester"],
            "year": draft["year"],
            "item": deadline["Item"],
            "due_date": deadline["Normalized Date"],
        }
        for deadline in deadlines
    ]


def display_manual_import(user) -> None:
    if st.session_state.pop("clear_manual_form_on_next_run", False):
        for key in (
            "manual_course_name",
            "manual_course_code",
            "manual_semester",
            "manual_year",
            "manual_syllabus_text",
            "manual_deadline_editor",
        ):
            st.session_state.pop(key, None)
    if notice := st.session_state.pop("manual_import_notice", None):
        st.success(notice)
    with st.expander("Paste syllabus text instead"):
        with st.form("manual_import_form", clear_on_submit=False):
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
            submitted = st.form_submit_button("Extract deadlines")

        if submitted:
            if not course_name.strip():
                st.error("Course name is required.")
                return
            if not syllabus_text.strip():
                st.error("Syllabus text is required.")
                return
            st.session_state["manual_import_draft"] = {
                "draft_id": str(uuid.uuid4()),
                "course_name": course_name.strip(),
                "course_code": course_code.strip() or None,
                "semester": semester,
                "year": int(course_year),
                "deadlines": extract_deadlines(
                    syllabus_text, int(course_year), semester
                ),
            }
            st.session_state.pop("manual_deadline_editor", None)

        draft = st.session_state.get("manual_import_draft")
        if not draft:
            return

        st.caption(
            f"Review {len(draft['deadlines'])} extracted deadline(s) before "
            "downloading or saving."
        )
        review_frame = pd.DataFrame([
            {
                "Item": row["Item"],
                "Due Date": row["Normalized Date"],
            }
            for row in draft["deadlines"]
        ], columns=["Item", "Due Date"])
        if not review_frame.empty:
            review_frame["Due Date"] = pd.to_datetime(
                review_frame["Due Date"]
            ).dt.date
        edited = st.data_editor(
            review_frame,
            width="stretch",
            hide_index=True,
            num_rows="dynamic",
            column_config={
                "Due Date": st.column_config.DateColumn(
                    "Due Date", format="YYYY-MM-DD",
                ),
            },
            key="manual_deadline_editor",
        )
        reviewed_deadlines = []
        invalid_rows = False
        for _, row in edited.iterrows():
            item = str(row.get("Item", "")).strip()
            due_date = row.get("Due Date")
            if not item or pd.isna(due_date):
                invalid_rows = True
                continue
            normalized = pd.Timestamp(due_date).strftime("%Y-%m-%d")
            reviewed_deadlines.append({
                "Item": item,
                "Date": normalized,
                "Normalized Date": normalized,
            })
        if invalid_rows:
            st.error("Every reviewed row needs an item and due date.")

        calendar_rows = _manual_calendar_deadlines(draft, reviewed_deadlines)
        st.download_button(
            "Download manual deadlines (.ics)",
            data=build_ics_calendar(calendar_rows) if calendar_rows else "",
            file_name="syllasift-manual-deadlines.ics",
            mime="text/calendar; charset=utf-8",
            disabled=invalid_rows or not calendar_rows,
        )
        if user.is_authenticated:
            if st.button(
                "Save manual course",
                disabled=invalid_rows,
                type="primary",
            ):
                result = upsert_course_with_deadlines(
                    user.user_id,
                    draft["course_name"],
                    draft["course_code"],
                    draft["semester"],
                    draft["year"],
                    reviewed_deadlines,
                )
                reset_deadline_and_export_state(st.session_state)
                st.session_state.pop("manual_import_draft", None)
                st.session_state["clear_manual_form_on_next_run"] = True
                st.session_state["manual_import_notice"] = (
                    f"Saved {result['deadlines_inserted']} new deadlines."
                )
                st.rerun()
        else:
            st.caption("Sign in before saving this manual course.")
            st.button(
                "Sign in with Google to save manual course",
                key="manual_guest_sign_in",
                on_click=request_sign_in_dialog,
            )
