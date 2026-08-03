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
