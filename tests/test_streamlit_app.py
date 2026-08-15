from streamlit.testing.v1 import AppTest

from syllasift.auth import AUTH_CHOICE_RESOLVED_KEY, CurrentUser
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
    app.session_state[AUTH_CHOICE_RESOLVED_KEY] = True
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
    monkeypatch.setattr("syllasift.auth.auth_is_configured", lambda: False)

    app = AppTest.from_file("app.py").run(timeout=30)

    assert not app.exception
    buttons = {button.label: button for button in app.button}
    assert "Clear all uploaded syllabi" in buttons
    assert buttons["Clear all uploaded syllabi"].disabled
    assert "Clear saved data" not in buttons
    assert "Dashboard" not in [heading.value for heading in app.subheader]
    assert any("extract and export" in info.value for info in app.info)
    assert app.get("dialog")[0].type == "dialog"
    assert app.button(key="auth_dialog_google_sign_in").disabled
    assert any(
        "isn't set up on this installation" in info.value
        for info in app.info
    )


def test_guest_can_close_welcome_and_reopen_it_from_header(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(database, "DATABASE_NAME", str(tmp_path / "app.db"))
    app = AppTest.from_file("app.py").run(timeout=30)

    app.button(key="auth_dialog_continue_as_guest").click().run(timeout=30)

    assert app.session_state[AUTH_CHOICE_RESOLVED_KEY]
    assert app.button(key="guest_header_sign_in").label == "Sign in"

    app.button(key="guest_header_sign_in").click().run(timeout=30)

    assert app.button(key="auth_dialog_google_sign_in").label == (
        "Sign in with Google"
    )


def test_configured_google_action_is_enabled_and_starts_login(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(database, "DATABASE_NAME", str(tmp_path / "app.db"))
    login_calls = []
    monkeypatch.setattr("syllasift.auth.auth_is_configured", lambda: True)
    monkeypatch.setattr(
        "syllasift.auth.st.login", lambda: login_calls.append(True)
    )
    app = AppTest.from_file("app.py").run(timeout=30)

    google_button = app.button(key="auth_dialog_google_sign_in")
    assert not google_button.disabled

    google_button.click().run(timeout=30)

    assert login_calls == [True]


def test_authenticated_user_bypasses_welcome_dialog(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_NAME", str(tmp_path / "app.db"))
    database.initialize_database()
    user = authenticated_user()
    monkeypatch.setattr("syllasift.auth.resolve_current_user", lambda: user)

    app = AppTest.from_file("app.py").run(timeout=30)

    assert not app.exception
    assert not any(
        button.key == "auth_dialog_google_sign_in" for button in app.button
    )
    assert any(button.label == "Sign out" for button in app.button)


def test_saved_calendar_export_is_ready_on_first_render_and_survives_reruns(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(database, "DATABASE_NAME", str(tmp_path / "app.db"))
    database.initialize_database()
    user = authenticated_user()
    monkeypatch.setattr(
        "syllasift.ui.app.display_authentication", lambda: user
    )
    course_id = database.save_course(
        user.user_id, "Physical Activity", "APPH 1050", "Fall", 2026,
    )
    database.save_deadlines(user.user_id, course_id, [{
        "Item": "Extra Credit",
        "Date": "December 2",
        "Normalized Date": "2026-12-02",
    }])
    captured_exports = []

    def capture_calendar(deadlines):
        captured_exports.append(list(deadlines))
        return "BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n"

    monkeypatch.setattr(
        "syllasift.ui.calendar_export.build_ics_calendar", capture_calendar,
    )
    app = AppTest.from_file("app.py").run(timeout=30)

    download = next(
        item for item in app.get("download_button")
        if item.label == "Download calendar (.ics)"
    )
    assert not download.disabled
    assert app.multiselect[0].value == [course_id]
    assert captured_exports[-1][0]["item"] == "Extra Credit"

    app.run(timeout=30)
    assert app.multiselect[0].value == [course_id]
    assert not next(
        item for item in app.get("download_button")
        if item.label == "Download calendar (.ics)"
    ).disabled

    connection = database.get_connection()
    try:
        connection.execute(
            "UPDATE courses SET course_name = ? WHERE course_id = ?",
            ("Science of Physical Activity and Health", course_id),
        )
        connection.commit()
    finally:
        connection.close()

    app.run(timeout=30)
    assert app.multiselect[0].value == [course_id]
    assert not next(
        item for item in app.get("download_button")
        if item.label == "Download calendar (.ics)"
    ).disabled


def test_saved_calendar_export_explains_when_no_deadlines_are_available(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(database, "DATABASE_NAME", str(tmp_path / "app.db"))
    database.initialize_database()
    user = authenticated_user()
    monkeypatch.setattr(
        "syllasift.ui.app.display_authentication", lambda: user
    )
    database.save_course(
        user.user_id, "Course Without Deadlines", "NONE 1000", "Fall", 2026,
    )

    app = AppTest.from_file("app.py").run(timeout=30)

    download = next(
        item for item in app.get("download_button")
        if item.label == "Download calendar (.ics)"
    )
    assert download.disabled
    assert any(
        info.value == "The selected courses have no incomplete deadlines to export."
        for info in app.info
    )


def test_remove_one_preview_leaves_other_temporary_courses(tmp_path, monkeypatch):
    app = app_with_pending(tmp_path, monkeypatch, ["one", "two", "three"])

    app.button(key="remove_two").click().run(timeout=30)

    assert app.session_state["pending_syllabus_order"] == ["one", "three"]
    assert [heading.value for heading in app.subheader if heading.value.endswith(".pdf")] == [
        "one.pdf", "three.pdf",
    ]


def test_pdf_save_prompt_opens_shared_sign_in_dialog(tmp_path, monkeypatch):
    app = app_with_pending(tmp_path, monkeypatch, ["one"])

    app.button(key="pdf_guest_sign_in").click().run(timeout=30)

    assert app.get("dialog")[0].type == "dialog"
    assert app.button(key="auth_dialog_google_sign_in").label == (
        "Sign in with Google"
    )


def test_pdf_review_requires_one_date_choice_and_warns_for_ranges(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(
        "syllasift.ui.imports.extract_deadline_review",
        lambda document, year: {
            "candidates": [],
            "multiple_date_assessments": [{
                "item": "Midterm",
                "choices": [
                    {"label": "June 30", "normalized_date": "2026-06-30"},
                    {"label": "July 2", "normalized_date": "2026-07-02"},
                ],
                "page": 4,
                "source": "TEXT",
            }],
            "unresolved_assessments": [{
                "item": "Final Exam",
                "date_range": "Aug 3 – Aug 6",
                "page": 4,
                "source": "TEXT",
                "message": (
                    "An exact deadline is not provided for this assessment. "
                    "Check Canvas."
                ),
            }, {
                "item": "Project 1",
                "date_range": "Aug 3 – Aug 6",
                "page": 4,
                "source": "TEXT",
                "message": (
                    "An exact deadline is not provided for this assessment. "
                    "Check Canvas."
                ),
            }],
        },
    )
    app = app_with_pending(tmp_path, monkeypatch, ["urban"])

    assert [warning.value for warning in app.warning] == [
        "Some assignments do not have specific dates in this syllabus. "
        "Check Canvas for the specific due dates."
    ]
    assert "Final Exam" not in app.warning[0].value
    choice = app.selectbox(key="deadline_choice_0_urban")
    assert choice.value is None
    reviewed_download = next(
        item for item in app.get("download_button")
        if item.label == "Download reviewed deadlines (.ics)"
    )
    assert reviewed_download.disabled

    choice.select("June 30 (2026-06-30)").run(timeout=30)

    assert app.selectbox(key="deadline_choice_0_urban").value == (
        "June 30 (2026-06-30)"
    )
    reviewed_download = next(
        item for item in app.get("download_button")
        if item.label == "Download reviewed deadlines (.ics)"
    )
    assert not reviewed_download.disabled


def test_structured_calendar_assignments_reach_export_and_saved_course(
    tmp_path, monkeypatch,
):
    assignment_dates = [
        ("Article Review 1", "2026-02-03"),
        ("Portfolio 1", "2026-02-05"),
        ("Article Review 2", "2026-02-26"),
        ("Portfolio 2", "2026-03-03"),
        ("Article Review 3", "2026-03-19"),
        ("Portfolio 3", "2026-04-02"),
        ("Article Review 4", "2026-04-21"),
        ("Portfolio 4", "2026-04-23"),
    ]
    monkeypatch.setattr(
        "syllasift.ui.imports.extract_deadline_review",
        lambda document, year: {
            "candidates": [
                {
                    "Item": item,
                    "Normalized Date": due_date,
                    "Include": True,
                    "Page": 5,
                }
                for item, due_date in assignment_dates
            ],
            "multiple_date_assessments": [],
            "unresolved_assessments": [],
        },
    )
    app = app_with_pending(
        tmp_path, monkeypatch, ["social"], signed_in=True,
    )

    reviewed_download = next(
        item for item in app.get("download_button")
        if item.label == "Download reviewed deadlines (.ics)"
    )
    assert not reviewed_download.disabled

    next(
        button for button in app.button
        if button.label == "Import 1 course(s)"
    ).click().run(timeout=30)

    user = authenticated_user()
    course_id = database.get_course_options(user.user_id)[0][0]
    saved = database.get_deadlines(user.user_id, course_id)
    assert [(row[2], row[4]) for row in saved] == assignment_dates


def test_guest_manual_extract_enables_ics_without_saving(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_NAME", str(tmp_path / "guest.db"))
    app = AppTest.from_file("app.py")
    app.session_state[AUTH_CHOICE_RESOLVED_KEY] = True
    app = app.run(timeout=30)
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

    app.button(key="manual_guest_sign_in").click().run(timeout=30)
    assert app.get("dialog")[0].type == "dialog"
    assert app.button(key="auth_dialog_google_sign_in").label == (
        "Sign in with Google"
    )


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
