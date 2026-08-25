from syllasift.calendar.ics import build_ics_calendar
from syllasift.ui.imports import _calendar_deadlines, _manual_calendar_deadlines


def test_reviewed_pdf_entries_convert_directly_to_calendar_rows():
    entries = [{
        "upload_id": "pdf-content-id",
        "filename": "course.pdf",
        "course_name": "Biology",
        "course_code": "BIO 101",
        "semester": "Fall",
        "year": 2026,
        "include": True,
        "review_errors": [],
        "deadlines": [{
            "Item": "Lab report",
            "Date": "2026-09-01",
            "Normalized Date": "2026-09-01",
        }],
    }]

    rows = _calendar_deadlines(entries)
    calendar = build_ics_calendar(rows)

    assert rows[0]["event_uid"].startswith("guest-")
    assert rows == _calendar_deadlines(entries)
    assert "SUMMARY:[BIO 101] Lab report" in calendar


def test_manual_draft_calendar_uid_is_stable_for_the_session_draft():
    draft = {
        "draft_id": "draft-uuid",
        "course_name": "Biology",
        "course_code": None,
        "semester": "Fall",
        "year": 2026,
    }
    deadlines = [{
        "Item": "Final",
        "Date": "2026-12-01",
        "Normalized Date": "2026-12-01",
    }]

    rows = _manual_calendar_deadlines(draft, deadlines)

    assert rows == _manual_calendar_deadlines(draft, deadlines)


def test_guest_uid_does_not_change_when_neighboring_deadlines_change():
    base = {
        "upload_id": "pdf-content-id", "filename": "course.pdf",
        "course_name": "Biology", "course_code": "BIO 101",
        "semester": "Fall", "year": 2026, "include": True,
        "review_errors": [],
    }
    lab = {"Item": "Lab", "Date": "2026-09-01", "Normalized Date": "2026-09-01"}
    exam = {"Item": "Exam", "Date": "2026-10-01", "Normalized Date": "2026-10-01"}
    one = _calendar_deadlines([{**base, "deadlines": [lab]}])[0]["event_uid"]
    two = _calendar_deadlines([{**base, "deadlines": [exam, lab]}])[1]["event_uid"]
    assert one == two
