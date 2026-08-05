from app import (
    COMPLETION_INSTRUCTION,
    NO_DATED_ASSIGNMENTS_MESSAGE,
    PREVIEW_COLUMNS,
    clean_uploaded_filename,
    finish_calendar_export,
    initialize_calendar_export_selection,
    reset_deadline_and_export_state,
    synchronize_deadline_widget_state,
)


def test_preview_only_shows_user_facing_columns():
    assert PREVIEW_COLUMNS == ["Include", "Item", "Due Date", "Page"]
    assert "Confidence" not in PREVIEW_COLUMNS
    assert "Reason" not in PREVIEW_COLUMNS
    assert "Source" not in PREVIEW_COLUMNS


def test_zero_deadline_message_is_direct_and_actionable():
    assert NO_DATED_ASSIGNMENTS_MESSAGE == (
        "No dated assignments are listed in this PDF. "
        "You can add rows or import the course without deadlines."
    )


def test_completion_instruction_explains_incomplete_default():
    assert "only after you finish it" in COMPLETION_INSTRUCTION
    assert "New deadlines start incomplete" in COMPLETION_INSTRUCTION


def test_saved_value_replaces_stale_completion_widget_state():
    state = {"deadline_42": True}

    widget_key, sync_key = synchronize_deadline_widget_state(
        state,
        deadline_id=42,
        is_completed=False,
    )

    assert widget_key == "deadline_42"
    assert state[widget_key] is False
    assert state[sync_key] is False


def test_current_widget_interaction_is_not_overwritten():
    state = {
        "deadline_42": True,
        "deadline_42_saved_value": False,
    }

    synchronize_deadline_widget_state(
        state,
        deadline_id=42,
        is_completed=False,
    )

    assert state["deadline_42"] is True


def test_import_reset_clears_deadline_and_export_widgets_only():
    state = {
        "deadline_42": True,
        "deadline_42_saved_value": True,
        "calendar_export_courses": ["MATH 1553"],
        "processed_syllabi": [{"filename": "syllabus.pdf"}],
    }

    reset_deadline_and_export_state(state)

    assert state == {
        "processed_syllabi": [{"filename": "syllabus.pdf"}],
    }


def test_calendar_export_selects_all_courses_once_then_preserves_changes():
    labels = {
        "CS 3600 — Artificial Intelligence": 1,
        "MATH 1553 — Linear Algebra": 2,
    }
    state = {"calendar_export_courses": []}

    initialize_calendar_export_selection(state, labels)
    assert state["calendar_export_courses"] == list(labels)

    state["calendar_export_courses"] = [
        "MATH 1553 — Linear Algebra"
    ]
    initialize_calendar_export_selection(state, labels)

    assert state["calendar_export_courses"] == [
        "MATH 1553 — Linear Algebra"
    ]


def test_accidentally_concatenated_pdf_name_is_readable():
    assert clean_uploaded_filename(
        "1331_Syllabus.pdf 3600Syllabus.pdf Spring2025_Syllabus.pdf"
    ) == "1331_Syllabus.pdf"
    assert clean_uploaded_filename("normal-syllabus.pdf") == "normal-syllabus.pdf"


def test_finished_calendar_export_clears_only_temporary_selection():
    state = {
        "calendar_export_courses": ["MATH 1553 — Linear Algebra"],
        "calendar_export_selection_initialized": True,
        "processed_syllabi": [{"filename": "syllabus.pdf"}],
    }

    finish_calendar_export(state)

    assert state["calendar_export_courses"] == []
    assert state["calendar_export_selection_initialized"] is True
    assert state["calendar_export_completed"] is True
    assert state["processed_syllabi"] == [{"filename": "syllabus.pdf"}]
