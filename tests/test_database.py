import sqlite3
import uuid

import pytest

import database


def initialized_database(tmp_path, monkeypatch, name="test.db"):
    test_database = tmp_path / name
    monkeypatch.setattr(database, "DATABASE_NAME", str(test_database))
    database.initialize_database()
    first_user = database.get_or_create_user("google-first", "first@example.com")
    second_user = database.get_or_create_user("google-second", "second@example.com")
    return test_database, first_user, second_user


def deadline(item="Homework 1", due_date="2026-09-01"):
    return {
        "Item": item,
        "Date": due_date,
        "Normalized Date": due_date,
    }


def test_user_creation_is_idempotent_and_uses_uuid(tmp_path, monkeypatch):
    _, first_user, _ = initialized_database(tmp_path, monkeypatch)

    repeated = database.get_or_create_user(
        "google-first", "new-address@example.com"
    )

    assert repeated == first_user
    assert str(uuid.UUID(first_user)) == first_user


def test_clear_user_data_preserves_other_users(tmp_path, monkeypatch):
    _, first_user, second_user = initialized_database(tmp_path, monkeypatch)
    first_course = database.save_course(
        first_user, "First Course", "ONE 1000", "Fall", 2026
    )
    second_course = database.save_course(
        second_user, "Second Course", "TWO 1000", "Fall", 2026
    )
    database.save_deadlines(first_user, first_course, [deadline()])
    database.save_deadlines(second_user, second_course, [deadline("Exam")])

    database.clear_user_data(first_user)

    assert database.get_dashboard_stats(first_user) == (0, 0, 0)
    assert database.get_dashboard_stats(second_user) == (1, 1, 0)


def test_new_deadlines_are_incomplete_and_owner_scoped(tmp_path, monkeypatch):
    _, first_user, second_user = initialized_database(tmp_path, monkeypatch)
    course_id = database.save_course(
        first_user, "Test Course", "TEST 1000", "Fall", 2026
    )
    database.save_deadlines(first_user, course_id, [deadline()])

    saved_deadline = database.get_deadlines(first_user, course_id)[0]

    assert saved_deadline[5] == 0
    assert saved_deadline[7] is None
    assert database.get_deadlines(second_user, course_id) == []
    assert database.get_deadlines_for_export(second_user, [course_id]) == []


def test_cross_user_writes_are_rejected_without_disclosure(tmp_path, monkeypatch):
    _, first_user, second_user = initialized_database(tmp_path, monkeypatch)
    course_id = database.save_course(
        first_user, "Private Course", None, "Fall", 2026
    )
    database.save_deadlines(first_user, course_id, [deadline()])
    deadline_id = database.get_deadlines(first_user, course_id)[0][0]

    with pytest.raises(ValueError, match="Course not found"):
        database.save_deadlines(second_user, course_id, [deadline("Intrusion")])
    assert not database.update_deadline_status(second_user, deadline_id, True)
    assert database.get_deadlines(first_user, course_id)[0][5] == 0


def test_new_ownerless_rows_and_owner_changes_are_blocked(tmp_path, monkeypatch):
    _, first_user, second_user = initialized_database(tmp_path, monkeypatch)
    course_id = database.save_course(
        first_user, "Owned Course", None, "Fall", 2026
    )
    connection = database.get_connection()
    try:
        with pytest.raises(sqlite3.IntegrityError, match="require an owner"):
            connection.execute(
                """
                INSERT INTO courses (course_name, semester, year)
                VALUES ('Ownerless', 'Fall', 2026)
                """
            )
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE courses SET user_id = ? WHERE course_id = ?",
                (second_user, course_id),
            )
    finally:
        connection.close()


def test_exports_and_dashboard_are_isolated_and_exclude_completed(
    tmp_path, monkeypatch,
):
    _, first_user, second_user = initialized_database(tmp_path, monkeypatch)
    first_course = database.save_course(
        first_user, "Linear Algebra", "MATH 1553", "Spring", 2026
    )
    second_course = database.save_course(
        second_user, "Seminar", None, "Fall", 2026
    )
    database.save_deadlines(first_user, first_course, [
        deadline("Exam 1", "2026-02-05"),
        deadline("Exam 2", "2026-03-05"),
    ])
    database.save_deadlines(
        second_user, second_course, [deadline("Reflection")]
    )
    first_deadline = database.get_deadlines(first_user, first_course)[0][0]
    assert database.update_deadline_status(first_user, first_deadline, True)

    courses = database.get_courses_for_export(first_user)
    exported = database.get_deadlines_for_export(
        first_user, [first_course, second_course]
    )

    assert [course["course_id"] for course in courses] == [first_course]
    assert [row["item"] for row in exported] == ["Exam 2"]
    assert database.get_dashboard_stats(first_user) == (1, 2, 1)
    assert database.get_dashboard_stats(second_user) == (1, 1, 0)
    assert database.get_deadlines_for_export(first_user, []) == []


def test_legacy_rows_are_preserved_but_hidden_after_migration(
    tmp_path, monkeypatch,
):
    test_database = tmp_path / "legacy.db"
    connection = sqlite3.connect(str(test_database))
    connection.executescript(
        """
        CREATE TABLE courses (
            course_id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_name TEXT NOT NULL,
            course_code TEXT,
            semester TEXT NOT NULL,
            year INTEGER NOT NULL
        );
        CREATE TABLE deadlines (
            deadline_id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id INTEGER NOT NULL,
            item TEXT NOT NULL,
            raw_date TEXT,
            due_date TEXT NOT NULL,
            is_completed INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT,
            FOREIGN KEY (course_id) REFERENCES courses(course_id)
        );
        INSERT INTO courses (course_name, semester, year)
        VALUES ('Legacy Course', 'Fall', 2025);
        INSERT INTO deadlines (course_id, item, due_date)
        VALUES (1, 'Legacy Exam', '2025-10-01');
        """
    )
    connection.commit()
    connection.close()
    monkeypatch.setattr(database, "DATABASE_NAME", str(test_database))

    database.initialize_database()
    user_id = database.get_or_create_user("google-new")

    assert database.get_course_options(user_id) == []
    connection = database.get_connection()
    try:
        assert connection.execute(
            "SELECT course_name, user_id FROM courses"
        ).fetchall() == [("Legacy Course", None)]
        assert connection.execute(
            "SELECT item, user_id FROM deadlines"
        ).fetchall() == [("Legacy Exam", None)]
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
    finally:
        connection.close()


def test_reimport_merges_deadlines_and_preserves_completion(tmp_path, monkeypatch):
    _, user_id, _ = initialized_database(tmp_path, monkeypatch)
    first = database.upsert_course_with_deadlines(
        user_id, "Biology", "BIO-101", "Fall", 2026,
        [deadline("Lab", "2026-09-01")],
    )
    saved_id = database.get_deadlines(user_id, first["course_id"])[0][0]
    assert database.update_deadline_status(user_id, saved_id, True)

    second = database.upsert_course_with_deadlines(
        user_id, "Biology renamed", "BIO 101", "fall", 2026,
        [deadline("Lab", "2026-09-01"), deadline("Exam", "2026-10-01")],
    )

    assert not second["course_created"]
    assert second["deadlines_inserted"] == 1
    assert database.get_dashboard_stats(user_id) == (1, 2, 1)


def test_legacy_save_helpers_are_idempotent(tmp_path, monkeypatch):
    _, user_id, _ = initialized_database(tmp_path, monkeypatch)
    first_course = database.save_course(
        user_id, "Biology", "BIO-101", "Fall", 2026
    )
    second_course = database.save_course(
        user_id, "Renamed Biology", "BIO 101", "fall", 2026
    )
    assert second_course == first_course

    database.save_deadlines(user_id, first_course, [deadline("Exam")])
    deadline_id = database.get_deadlines(user_id, first_course)[0][0]
    assert database.update_deadline_status(user_id, deadline_id, True)
    database.save_deadlines(user_id, first_course, [deadline(" exam ")])

    assert database.get_dashboard_stats(user_id) == (1, 1, 1)


def test_v1_migration_consolidates_owned_duplicates(tmp_path, monkeypatch):
    test_database, user_id, _ = initialized_database(tmp_path, monkeypatch)
    connection = sqlite3.connect(str(test_database))
    connection.execute("DROP INDEX uq_courses_owned_identity")
    connection.execute("DROP INDEX uq_deadlines_owned_identity")
    connection.execute("PRAGMA user_version = 1")
    first = connection.execute(
        "INSERT INTO courses (user_id, course_name, course_code, semester, year) VALUES (?, 'Biology', 'BIO 101', 'Fall', 2026)",
        (user_id,),
    ).lastrowid
    second = connection.execute(
        "INSERT INTO courses (user_id, course_name, course_code, semester, year) VALUES (?, 'Biology', 'BIO-101', 'fall', 2026)",
        (user_id,),
    ).lastrowid
    connection.execute(
        "INSERT INTO deadlines (user_id, course_id, item, due_date) VALUES (?, ?, 'Exam', '2026-10-01')",
        (user_id, first),
    )
    connection.execute(
        "INSERT INTO deadlines (user_id, course_id, item, due_date, is_completed, completed_at) VALUES (?, ?, ' exam ', '2026-10-01', 1, '2026-09-30 12:00:00')",
        (user_id, second),
    )
    connection.commit()
    connection.close()

    database.initialize_database()

    assert database.get_dashboard_stats(user_id) == (1, 1, 1)
    course_id = database.get_course_options(user_id)[0][0]
    assert database.get_deadlines(user_id, course_id)[0][7] == "2026-09-30 12:00:00"
