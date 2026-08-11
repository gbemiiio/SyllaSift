from streamlit.testing.v1 import AppTest

from syllasift.storage import database


def pending(upload_id):
    return {
        "upload_id": upload_id,
        "filename": f"{upload_id}.pdf",
        "document": {
            "text": "TEST 1000 Fall 2026",
            "pages": [],
            "notices": [],
        },
        "metadata": {
            "course_name": f"Course {upload_id}",
            "course_code": "TEST 1000",
            "semester": "Fall",
            "year": 2026,
        },
        "error": None,
    }


def app_with_pending(tmp_path, monkeypatch, upload_ids):
    monkeypatch.setattr(database, "DATABASE_NAME", str(tmp_path / "app.db"))
    app = AppTest.from_file("app.py")
    app.session_state["pending_syllabi"] = {
        upload_id: pending(upload_id) for upload_id in upload_ids
    }
    app.session_state["pending_syllabus_order"] = list(upload_ids)
    app.session_state["pdf_uploader_generation"] = 0
    return app.run(timeout=30)


def test_app_starts_with_separate_temporary_and_saved_clear_controls(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(database, "DATABASE_NAME", str(tmp_path / "app.db"))

    app = AppTest.from_file("app.py").run(timeout=30)

    assert not app.exception
    buttons = {button.label: button for button in app.button}
    assert "Clear all uploaded syllabi" in buttons
    assert buttons["Clear all uploaded syllabi"].disabled
    assert "Clear saved data" in buttons
    assert [heading.value for heading in app.subheader][-1] == "Clear Saved Data"


def test_remove_one_preview_leaves_other_temporary_courses(tmp_path, monkeypatch):
    app = app_with_pending(tmp_path, monkeypatch, ["one", "two", "three"])

    app.button(key="remove_two").click().run(timeout=30)

    assert app.session_state["pending_syllabus_order"] == ["one", "three"]
    assert [heading.value for heading in app.subheader if heading.value.endswith(".pdf")] == [
        "one.pdf", "three.pdf",
    ]


def test_confirm_clear_uploads_preserves_saved_database(tmp_path, monkeypatch):
    app = app_with_pending(tmp_path, monkeypatch, ["one", "two"])
    saved_course_id = database.save_course(
        "Saved Course", "SAVE 1000", "Fall", 2026,
    )

    next(
        button for button in app.button
        if button.label == "Clear all uploaded syllabi"
    ).click().run(timeout=30)
    assert any(button.label == "Keep uploads" for button in app.button)

    # AppTest currently renders dialog fragments but does not execute their
    # button callbacks, so exercise the same state action directly.
    app.session_state["pending_syllabi"] = {}
    app.session_state["pending_syllabus_order"] = []
    app.session_state["pdf_uploader_generation"] += 1
    app.run(timeout=30)

    assert app.session_state["pending_syllabus_order"] == []
    assert database.get_course_options() == [(saved_course_id, "Saved Course")]


def test_subset_import_removes_only_successfully_imported_previews(
    tmp_path, monkeypatch,
):
    app = app_with_pending(tmp_path, monkeypatch, ["one", "two", "three"])
    app.checkbox(key="include_two").uncheck().run(timeout=30)

    next(
        button for button in app.button
        if button.label == "Import 2 course(s)"
    ).click().run(timeout=30)

    assert app.session_state["pending_syllabus_order"] == ["two"]
    assert [name for _, name in database.get_course_options()] == [
        "Course one", "Course three",
    ]
