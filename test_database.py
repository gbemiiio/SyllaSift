import database


def test_clear_all_data_removes_deadlines_before_courses(tmp_path, monkeypatch):
    test_database = tmp_path / "syllasift-test.db"
    monkeypatch.setattr(database, "DATABASE_NAME", str(test_database))

    database.initialize_database()
    course_id = database.save_course(
        "Test Course",
        "TEST 1000",
        "Fall",
        2026,
    )
    database.save_deadlines(
        course_id,
        [
            {
                "Item": "Homework 1",
                "Date": "September 1",
                "Normalized Date": "2026-09-01",
            }
        ],
    )

    database.clear_all_data()

    assert database.get_dashboard_stats() == (0, 0, 0)
    assert database.get_course_options() == []


def test_new_deadlines_are_explicitly_saved_incomplete(tmp_path, monkeypatch):
    test_database = tmp_path / "incomplete-default.db"
    monkeypatch.setattr(database, "DATABASE_NAME", str(test_database))
    database.initialize_database()

    course_id = database.save_course(
        "Test Course", "TEST 1000", "Fall", 2026,
    )
    database.save_deadlines(course_id, [
        {
            "Item": "Homework 1",
            "Date": "September 1",
            "Normalized Date": "2026-09-01",
        }
    ])

    saved_deadline = database.get_deadlines(course_id)[0]
    assert saved_deadline[5] == 0
    assert saved_deadline[7] is None
    assert [row["item"] for row in database.get_deadlines_for_export([course_id])] == [
        "Homework 1"
    ]


def test_calendar_export_queries_exclude_completed_deadlines(tmp_path, monkeypatch):
    test_database = tmp_path / "calendar-export.db"
    monkeypatch.setattr(database, "DATABASE_NAME", str(test_database))
    database.initialize_database()

    first_course = database.save_course(
        "Linear Algebra", "MATH 1553", "Spring", 2026,
    )
    second_course = database.save_course(
        "Seminar", None, "Fall", 2026,
    )
    database.save_deadlines(first_course, [
        {"Item": "Exam 1", "Date": "February 5", "Normalized Date": "2026-02-05"},
        {"Item": "Exam 2", "Date": "March 5", "Normalized Date": "2026-03-05"},
    ])
    database.save_deadlines(second_course, [
        {"Item": "Reflection", "Date": "September 1", "Normalized Date": "2026-09-01"},
    ])

    first_deadline = database.get_deadlines(first_course)[0][0]
    database.update_deadline_status(first_deadline, True)

    courses = database.get_courses_for_export()
    exported = database.get_deadlines_for_export([first_course, second_course])

    assert {course["course_id"] for course in courses} == {first_course, second_course}
    assert [row["item"] for row in exported] == ["Exam 2", "Reflection"]
    assert all(not row["is_completed"] for row in exported)
    assert database.get_deadlines_for_export([]) == []
