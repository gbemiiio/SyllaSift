from streamlit.testing.v1 import AppTest

from syllasift.auth import CurrentUser
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


def authenticated_user():
    user_id = database.get_or_create_user("streamlit-test", "test@example.com")
    return CurrentUser(
        is_authenticated=True,
        user_id=user_id,
        auth_subject="streamlit-test",
        email="test@example.com",
        name="Test User",
    )


def app_with_pending(tmp_path, monkeypatch, upload_ids, signed_in=False):
    monkeypatch.setattr(database, "DATABASE_NAME", str(tmp_path / "app.db"))
    if signed_in:
        database.initialize_database()
        user = authenticated_user()
        monkeypatch.setattr(
            "syllasift.ui.app.display_authentication", lambda: user
        )
    app = AppTest.from_file("app.py")
    app.session_state["pending_syllabi"] = {
        upload_id: pending(upload_id) for upload_id in upload_ids
    }
    app.session_state["pending_syllabus_order"] = list(upload_ids)
    app.session_state["pdf_uploader_generation"] = 0
    return app.run(timeout=30)


def test_guest_app_hides_saved_data_controls(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(database, "DATABASE_NAME", str(tmp_path / "app.db"))

    app = AppTest.from_file("app.py").run(timeout=30)

    assert not app.exception
    buttons = {button.label: button for button in app.button}
    assert "Clear all uploaded syllabi" in buttons
    assert buttons["Clear all uploaded syllabi"].disabled
    assert "Clear saved data" not in buttons
    assert "Dashboard" not in [heading.value for heading in app.subheader]
    assert any("extract and export" in info.value for info in app.info)


def test_remove_one_preview_leaves_other_temporary_courses(tmp_path, monkeypatch):
    app = app_with_pending(tmp_path, monkeypatch, ["one", "two", "three"])

    app.button(key="remove_two").click().run(timeout=30)

    assert app.session_state["pending_syllabus_order"] == ["one", "three"]
    assert [heading.value for heading in app.subheader if heading.value.endswith(".pdf")] == [
        "one.pdf", "three.pdf",
    ]


def test_guest_manual_extract_enables_ics_without_saving(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_NAME", str(tmp_path / "guest.db"))
    app = AppTest.from_file("app.py").run(timeout=30)
    app.text_input(key="manual_course_name").input("Biology")
    app.text_input(key="manual_course_code").input("BIO 101")
    app.text_area(key="manual_syllabus_text").input(
        "Homework 1 due September 1, 2026"
    )

    next(
        button for button in app.button if button.label == "Extract deadlines"
    ).click().run(timeout=30)

    downloads = app.get("download_button")
    manual_download = next(
        item for item in downloads
        if item.label == "Download manual deadlines (.ics)"
    )
    assert not manual_download.disabled
    assert not app.exception
    connection = database.get_connection()
    try:
        assert connection.execute("SELECT COUNT(*) FROM courses").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM deadlines").fetchone()[0] == 0
    finally:
        connection.close()


def test_confirm_clear_uploads_preserves_saved_database(tmp_path, monkeypatch):
    app = app_with_pending(tmp_path, monkeypatch, ["one", "two"])
    database.initialize_database()
    user = authenticated_user()
    saved_course_id = database.save_course(
        user.user_id, "Saved Course", "SAVE 1000", "Fall", 2026,
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
    assert database.get_course_options(user.user_id) == [
        (saved_course_id, "Saved Course")
    ]


def test_subset_import_removes_only_successfully_imported_previews(
    tmp_path, monkeypatch,
):
    app = app_with_pending(
        tmp_path, monkeypatch, ["one", "two", "three"], signed_in=True
    )
    app.checkbox(key="include_two").uncheck().run(timeout=30)

    next(
        button for button in app.button
        if button.label == "Import 2 course(s)"
    ).click().run(timeout=30)

    assert app.session_state["pending_syllabus_order"] == ["two"]
    user = authenticated_user()
    assert [name for _, name in database.get_course_options(user.user_id)] == [
        "Course one", "Course three",
    ]


def test_completion_persists_when_switching_saved_courses(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_NAME", str(tmp_path / "app.db"))
    database.initialize_database()
    user = authenticated_user()
    monkeypatch.setattr(
        "syllasift.ui.app.display_authentication", lambda: user
    )
    first_course = database.save_course(
        user.user_id, "Course One", "ONE 1000", "Fall", 2026,
    )
    second_course = database.save_course(
        user.user_id, "Course Two", "TWO 2000", "Fall", 2026,
    )
    database.save_deadlines(user.user_id, first_course, [{
        "Item": "First Task",
        "Date": "September 1",
        "Normalized Date": "2026-09-01",
    }])
    database.save_deadlines(user.user_id, second_course, [{
        "Item": "Second Task",
        "Date": "September 2",
        "Normalized Date": "2026-09-02",
    }])

    app = AppTest.from_file("app.py").run(timeout=30)
    first_checkbox = next(
        checkbox for checkbox in app.checkbox
        if checkbox.label.startswith("First Task")
    )

    first_checkbox.check().run(timeout=30)
    completed_row = database.get_deadlines(user.user_id, first_course)[0]
    assert completed_row[5] == 1
    assert completed_row[7] is not None
    assert database.get_dashboard_stats(user.user_id) == (2, 2, 1)

    next(
        selectbox for selectbox in app.selectbox
        if selectbox.label == "Choose a course"
    ).select("Course Two").run(timeout=30)
    next(
        selectbox for selectbox in app.selectbox
        if selectbox.label == "Choose a course"
    ).select("Course One").run(timeout=30)

    first_checkbox = next(
        checkbox for checkbox in app.checkbox
        if checkbox.label.startswith("First Task")
    )
    assert first_checkbox.value is True
    assert database.get_deadlines(user.user_id, first_course)[0][5] == 1

    first_checkbox.uncheck().run(timeout=30)
    next(
        selectbox for selectbox in app.selectbox
        if selectbox.label == "Choose a course"
    ).select("Course Two").run(timeout=30)
    next(
        selectbox for selectbox in app.selectbox
        if selectbox.label == "Choose a course"
    ).select("Course One").run(timeout=30)

    first_checkbox = next(
        checkbox for checkbox in app.checkbox
        if checkbox.label.startswith("First Task")
    )
    incomplete_row = database.get_deadlines(user.user_id, first_course)[0]
    assert first_checkbox.value is False
    assert incomplete_row[5] == 0
    assert incomplete_row[7] is None
    assert database.get_dashboard_stats(user.user_id) == (2, 2, 0)
