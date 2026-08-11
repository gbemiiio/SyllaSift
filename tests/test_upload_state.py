from syllasift.state.uploads import (
    advance_uploader_generation,
    clear_pending_syllabi,
    get_pending_syllabi,
    has_unsaved_work,
    register_pending_syllabi,
    remove_pending_syllabus,
    uploader_widget_key,
)


def pending(upload_id):
    return {
        "upload_id": upload_id,
        "filename": f"{upload_id}.pdf",
        "document": {"text": upload_id, "pages": [], "notices": []},
        "metadata": {
            "course_name": upload_id,
            "course_code": "",
            "semester": "Fall",
            "year": 2026,
        },
        "error": None,
    }


def test_remove_middle_upload_preserves_other_records_and_edits():
    state = {}
    register_pending_syllabi(
        state, [pending(str(number)) for number in range(1, 6)]
    )
    state["course_name_2"] = "Edited second course"
    state["course_name_3"] = "Edited third course"
    state["deadline_editor_3"] = {"edited_rows": {}}

    remove_pending_syllabus(state, "3")

    assert [item["upload_id"] for item in get_pending_syllabi(state)] == [
        "1", "2", "4", "5",
    ]
    assert state["course_name_2"] == "Edited second course"
    assert "course_name_3" not in state
    assert "deadline_editor_3" not in state


def test_clear_uploads_resets_temporary_state_but_not_saved_widgets():
    state = {"deadline_99": True}
    register_pending_syllabi(state, [pending("one"), pending("two")])
    old_key = uploader_widget_key(state)

    clear_pending_syllabi(state)

    assert get_pending_syllabi(state) == []
    assert uploader_widget_key(state) != old_key
    assert state["deadline_99"] is True


def test_analyze_rotation_keeps_pending_queue_and_deduplicates_content():
    state = {}
    record = pending("same-content")
    register_pending_syllabi(state, [record, record])
    old_key = uploader_widget_key(state)
    advance_uploader_generation(state)

    assert get_pending_syllabi(state) == [record]
    assert uploader_widget_key(state) != old_key


def test_unsaved_work_tracks_pending_selected_and_manual_content():
    assert not has_unsaved_work({})
    assert has_unsaved_work({}, has_selected_files=True)

    pending_state = {}
    register_pending_syllabi(pending_state, [pending("one")])
    assert has_unsaved_work(pending_state)

    assert has_unsaved_work({"manual_syllabus_text": "Homework due Friday"})
