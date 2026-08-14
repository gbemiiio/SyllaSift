from datetime import datetime, timezone

import pytest

from calendar_export import build_ics_calendar, escape_ics_text


def deadline(**overrides):
    row = {
        "deadline_id": 8,
        "course_id": 3,
        "course_name": "Introduction to Linear Algebra",
        "course_code": "MATH 1553",
        "semester": "Spring",
        "year": 2026,
        "item": "Exam 1",
        "due_date": "2026-02-05",
        "is_completed": False,
    }
    row.update(overrides)
    return row


def test_builds_all_day_event_with_reminder_and_stable_uid():
    generated_at = datetime(2026, 1, 1, 12, 30, tzinfo=timezone.utc)
    calendar = build_ics_calendar([deadline()], generated_at)

    assert calendar.startswith("BEGIN:VCALENDAR\r\n")
    assert calendar.endswith("END:VCALENDAR\r\n")
    assert "UID:course-3-deadline-8@syllasift.local\r\n" in calendar
    assert "DTSTAMP:20260101T123000Z\r\n" in calendar
    assert "DTSTART;VALUE=DATE:20260205\r\n" in calendar
    assert "DTEND;VALUE=DATE:20260206\r\n" in calendar
    assert "SUMMARY:[MATH 1553] Exam 1\r\n" in calendar
    assert "TRIGGER:-P1D\r\n" in calendar
    assert calendar.count("BEGIN:VEVENT") == 1
    assert calendar.count("BEGIN:VALARM") == 1


def test_end_date_crosses_year_boundary_and_name_replaces_missing_code():
    calendar = build_ics_calendar([
        deadline(
            deadline_id=9,
            course_code=None,
            course_name="First-Year Seminar",
            item="Final Reflection",
            due_date="2026-12-31",
        )
    ], datetime(2026, 1, 1))

    assert "DTSTART;VALUE=DATE:20261231" in calendar
    assert "DTEND;VALUE=DATE:20270101" in calendar
    assert "SUMMARY:[First-Year Seminar] Final Reflection" in calendar


def test_multiple_courses_and_text_escaping():
    calendar = build_ics_calendar([
        deadline(item="Project, Part 1; Draft\\Review"),
        deadline(deadline_id=10, course_id=4, course_code="CS 3600", item="Final Exam"),
    ], datetime(2026, 1, 1))

    assert calendar.count("BEGIN:VEVENT") == 2
    assert "Project\\, Part 1\\; Draft\\\\Review" in calendar
    assert "[CS 3600] Final Exam" in calendar
    assert escape_ics_text("one\ntwo") == "one\\ntwo"


def test_content_lines_are_folded_to_75_utf8_bytes():
    calendar = build_ics_calendar([
        deadline(item="Very long résumé assignment " * 8)
    ], datetime(2026, 1, 1))

    assert all(len(line.encode("utf-8")) <= 75 for line in calendar.split("\r\n"))
    assert "\r\n " in calendar


def test_invalid_due_date_is_rejected():
    with pytest.raises(ValueError):
        build_ics_calendar([deadline(due_date="not-a-date")])


def test_unsaved_guest_deadline_gets_stable_uid_without_database_ids():
    guest = deadline()
    guest.pop("course_id")
    guest.pop("deadline_id")

    first = build_ics_calendar([guest], datetime(2026, 1, 1))
    second = build_ics_calendar([guest], datetime(2026, 1, 1))

    first_uid = next(line for line in first.splitlines() if line.startswith("UID:"))
    second_uid = next(line for line in second.splitlines() if line.startswith("UID:"))
    assert first_uid == second_uid
    assert first_uid.startswith("UID:guest-")
