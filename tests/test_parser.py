import pytest
import io
import importlib
from types import SimpleNamespace

from parser import (
    detect_course_metadata,
    detect_platform_notices,
    extract_deadline_candidates,
    extract_deadline_review,
    extract_deadlines,
    extract_ocr_column_deadlines,
    normalize_date,
    page_needs_ocr,
)


@pytest.mark.parametrize(
    ("date_text", "course_year", "expected"),
    [
        ("January 7th", 2026, "2026-01-07"),
        ("Jan. 10", 2026, "2026-01-10"),
        ("Feb 6", 2026, "2026-02-06"),
        ("March 20, 2027", 2026, "2027-03-20"),
        ("01/13", 2026, "2026-01-13"),
        ("01/13/26", 2025, "2026-01-13"),
        ("17 Sep", 2021, "2021-09-17"),
        ("15 December 2022", 2021, "2022-12-15"),
    ],
)
def test_date_normalization(date_text, course_year, expected):
    assert normalize_date(date_text, course_year) == expected


@pytest.mark.parametrize(
    "date_text",
    ["February 30", "13/10/2025", "04/31/2025"],
)
def test_invalid_dates_raise_value_error(date_text):
    with pytest.raises(ValueError):
        normalize_date(date_text, 2025)


def test_fall_yearless_dates_roll_into_next_calendar_year():
    assert normalize_date("January 5", 2026, "Fall") == "2027-01-05"
    assert normalize_date("December 5", 2026, "Fall") == "2026-12-05"
    assert normalize_date("January 5, 2026", 2026, "Fall") == "2026-01-05"
    assert normalize_date("January 5", 2026, "Spring") == "2026-01-05"


def test_metadata_ignores_contextual_codes_and_accepts_year_first_term():
    text = """
    Prerequisite: CS 100
    Office: COE 301
    Meets in WEB 123
    CS 3600 Introduction to Artificial Intelligence
    2019 Fall Semester
    """
    metadata = detect_course_metadata(text)
    assert metadata["course_code"] == "CS 3600"
    assert metadata["course_name"] == "Introduction to Artificial Intelligence"
    assert metadata["semester"] == "Fall"
    assert metadata["year"] == 2019


def test_course_title_prefers_later_same_line_code_over_institution_header():
    text = """
    MGT 4058 Fall 2026
    Scheller College of Business
    Georgia Institute of Technology
    Database Management (MGT 4058)
    Fall 2026
    """
    assert detect_course_metadata(text)["course_name"] == "Database Management"


def test_noncontiguous_course_calendar_columns_do_not_mix_cells():
    document = {"text": "", "pages": [{"page": 1, "text": "", "tables": [[
        ["Date", "Week", "Topic", "Notes", "Assignment"],
        ["September 5", "2", "Exam 1", "Bring pencil", "Homework 1"],
    ]]}]}
    rows = extract_deadline_candidates(document, 2026)
    assert [(row["Item"], row["Normalized Date"]) for row in rows] == [
        ("Exam 1", "2026-09-05"),
        ("Homework 1", "2026-09-05"),
    ]


def test_due_notes_calendar_and_headerless_continuation_are_structured():
    first_page = [
        ["Week", "Date", "Text", "Descriptions", "Due / Notes"],
        ["2", "9/1", "Ch. 2", "Entity-Relationship Modeling", "Post: HW1"],
        ["2", "9/3", "Ch. 2", "Entity-Relationship Modeling", "Start: Project team formation"],
        ["3", "9/10", "", "Entity-Relationship Modeling", "Due: Project team formation"],
        ["4", "9/15", "Ch. 3", "Relational Database", "Due: HW1"],
        ["6", "10/1", "Ch. 4", "Normalization 2", "Due: Project Deliverable 1"],
    ]
    continuation = [
        ["8", "10/13", "", "Exam 1 Review", "Due: HW2"],
        ["8", "10/15", "", "Exam 1", "Post: HW3"],
        ["10", "10/29", "Ch. 5", "SQL 4", "Due: Project Deliverable 2"],
        ["12", "11/10", "", "Exam 2 Review", "Due: HW3"],
        ["12", "11/12", "", "Exam 2", ""],
        ["15", "12/1", "", "Project Presentation 1\n(five teams)", "Project presentation slides due"],
        ["15", "11/27", "", "Project Presentation 1\n(five teams)", ""],
        ["16", "12/3", "", "Project Presentation 3 (if\nneed ed)", ""],
        ["16", "12/6", "", "(No final exam)", "Due: Project Deliverable 3"],
    ]
    document = {
        "text": "",
        "pages": [
            {"page": 6, "text": "3 9/10 Entity Modeling Due: Project team formation", "tables": [first_page]},
            {"page": 7, "text": "8 10/13 Exam 1 Review Due: HW2\n16 12/6 (No final exam) Due: Project Deliverable 3", "tables": [continuation]},
        ],
    }

    candidates = extract_deadline_candidates(document, 2026)

    assert [(row["Item"], row["Normalized Date"]) for row in candidates] == [
        ("Project Team Formation", "2026-09-10"),
        ("HW1", "2026-09-15"),
        ("Project Deliverable 1", "2026-10-01"),
        ("HW2", "2026-10-13"),
        ("Exam 1", "2026-10-15"),
        ("Project Deliverable 2", "2026-10-29"),
        ("HW3", "2026-11-10"),
        ("Exam 2", "2026-11-12"),
        ("Project Presentation 1", "2026-11-27"),
        ("Project Presentation 1", "2026-12-01"),
        ("Project Presentation Slides", "2026-12-01"),
        ("Project Presentation 3", "2026-12-03"),
        ("Project Deliverable 3", "2026-12-06"),
    ]
    assert all(row["Confidence"] == "High" for row in candidates)
    labels = {row["Item"] for row in candidates}
    assert "Final Exam" not in labels
    assert not any("Review" in label or label[:1].isdigit() for label in labels)


def test_whitespace_only_deliverable_topic_does_not_crash():
    document = {"text": "", "pages": [{"page": 1, "text": "", "tables": [[
        ["Date", "Week", "Topic", "Deliverable"],
        ["September 5", "2", "   ", "Exam 1 September 5"],
    ]]}]}
    rows = extract_deadline_candidates(document, 2026)
    assert [(row["Item"], row["Normalized Date"]) for row in rows] == [
        ("Exam 1", "2026-09-05")
    ]


def test_unlabeled_due_marker_is_visible_but_unchecked():
    rows = extract_deadline_candidates("Due: September 5", 2026)
    assert rows[0]["Item"] == "Unlabeled deadline"
    assert rows[0]["Confidence"] == "Low"
    assert rows[0]["Include"] is False


def test_invalid_date_is_skipped_with_warning_while_valid_date_survives():
    review = extract_deadline_review(
        "Exam 1 September 5\nExam 2 13/45/2026", 2026
    )
    assert [(row["Item"], row["Normalized Date"]) for row in review["candidates"]] == [
        ("Exam 1", "2026-09-05")
    ]
    assert review["warnings"] == [
        'Skipped date text that could not be parsed: "13/45/2026".'
    ]


def test_explicit_ocr_label_keeps_high_confidence_after_cleanup():
    def word(text, x0, top):
        return {"text": text, "x0": x0, "top": top, "bottom": top + 8}

    document = {"text": "", "pages": [{
        "page": 1,
        "text": "",
        "tables": [],
        "ocr_words": [
            word("Work", 100, 10), word("Due Date", 300, 10),
            word("M Exam", 100, 40), word("Sept 5", 300, 40),
        ],
    }]}
    candidate = extract_deadline_candidates(document, 2026)[0]
    assert candidate["Item"] == "Exam"
    assert candidate["Confidence"] == "High"
    assert candidate["Reason"] == "Explicit due date"


def test_ordinary_deadline_lines():
    text = """
    Homework 1 is due January 5
    Quiz 1 Jan. 19
    Final Project April 28
    """

    assert extract_deadlines(text, 2025) == [
        {
            "Item": "Homework 1",
            "Date": "January 5",
            "Normalized Date": "2025-01-05",
        },
        {
            "Item": "Quiz 1",
            "Date": "Jan. 19",
            "Normalized Date": "2025-01-19",
        },
        {
            "Item": "Final Project",
            "Date": "April 28",
            "Normalized Date": "2025-04-28",
        },
    ]


def test_structured_math_1553_exam_list():
    text = """
    We will have three in-person exams on the following dates:
    1. Wednesday, February 5
    2. Wednesday, March 5
    3. Wednesday, April 9
    Cumulative in-person Final exam: Tuesday, April 29, from 6 PM - 9 PM.
    """

    deadlines = extract_deadlines(text, 2025)

    assert [(row["Item"], row["Normalized Date"]) for row in deadlines] == [
        ("Midterm Exam 1", "2025-02-05"),
        ("Midterm Exam 2", "2025-03-05"),
        ("Midterm Exam 3", "2025-04-09"),
        ("Final Exam", "2025-04-29"),
    ]


def test_policy_and_informational_dates_are_excluded():
    text = """
    Attendance
    Starting Friday, January 17, attendance will be recorded.
    Students with accommodations must notify the instructor by February 2.
    Religious holiday notice is due January 17.
    Regrade requests must be submitted by March 12.
    Office hours begin January 8.
    Makeup exams are held Monday, February 10.
    Registrar information for the final exam is available April 1.
    General information: the course calendar begins January 6.
    """

    assert extract_deadlines(text, 2025) == []


def test_math_1553_course_metadata():
    text = """
    Syllabus, Math 1553 (Introduction to Linear Algebra), Spring 2025
    Course Number and Title: MATH 1553, Introduction to Linear Algebra
    """

    assert detect_course_metadata(text) == {
        "course_name": "Introduction to Linear Algebra",
        "course_code": "MATH 1553",
        "semester": "Spring",
        "year": 2025,
    }


def test_assessment_words_are_matched_as_whole_words():
    text = "August 22 Orientation and General Expectations"

    assert extract_deadlines(text, 2024) == []


def test_layout_table_with_wrapped_due_date_rows():
    document = {
        "text": "APPH 1050 Fall 2024",
        "pages": [
            {
                "page": 7,
                "text": "",
                "tables": [
                    [
                        ["Date", "Topic", "Readings and Assignments"],
                        ["August 29", "Well-being", "Tiny Habits Assignment"],
                        [None, None, "Due: September 11 (11:59 pm)"],
                        ["October 3", "Stress", "Behavior Change (Part 2): Mid-"],
                        [None, None, "Semester Check-In Assignment (Canvas)"],
                        [None, None, "Due: October 9 (11:59 pm)"],
                        ["November 28", "No Class- Holiday Break", None],
                    ]
                ],
            }
        ],
    }

    candidates = extract_deadline_candidates(document, 2024)

    assert [
        (row["Item"], row["Normalized Date"], row["Confidence"])
        for row in candidates
    ] == [
        ("Tiny Habits Assignment", "2024-09-11", "High"),
        (
            "Behavior Change (Part 2): Mid Semester Check-In Assignment",
            "2024-10-09",
            "High",
        ),
    ]


def test_release_due_columns_use_second_date():
    document = {
        "text": "",
        "pages": [
            {
                "page": 4,
                "text": """
                Assignment Release Date Due Date Weight
                Introduction (Discussion) Aug 18 Aug 24 1.0%
                Syllabus/Expectations Quiz Aug 18 Aug 24 1.0%
                Exam #1 Sep 22 Sep 22 17%
                """,
                "tables": [],
            }
        ],
    }

    candidates = extract_deadline_candidates(document, 2025)

    assert [(row["Item"], row["Normalized Date"]) for row in candidates] == [
        ("Introduction (Discussion)", "2025-08-24"),
        ("Syllabus/Expectations Quiz", "2025-08-24"),
        ("Exam #1", "2025-09-22"),
    ]


def test_deliverables_column_splits_multiple_assignments():
    document = {
        "text": "",
        "pages": [
            {
                "page": 14,
                "text": "",
                "tables": [
                    [
                        ["Week", "Date", "Topic", "Deliverables"],
                        [
                            "1",
                            "Aug 18",
                            "Review Syllabus",
                            (
                                "Video Assignment Week 1 August 24\n"
                                "Video Assignment Week 2 August 24\n"
                                "Class work Week 1 August 24"
                            ),
                        ],
                        ["6", "Sep 22", "Exam #1", "Exam #1"],
                    ]
                ],
            }
        ],
    }

    candidates = extract_deadline_candidates(document, 2025)

    assert [(row["Item"], row["Normalized Date"]) for row in candidates] == [
        ("Video Assignment Week 1", "2025-08-24"),
        ("Video Assignment Week 2", "2025-08-24"),
        ("Class work Week 1", "2025-08-24"),
        ("Exam #1", "2025-09-22"),
    ]


def test_explicit_due_dates_accept_misspelling_and_filter_reviews():
    document = {"text": "", "pages": [{"page": 5, "tables": [], "text": """
    Assigment 3 Release: Real Option & Queue (:) Due: February 7
    Review session for Exam 1 February 10
    Exam 1: Covers Lectures 1-8 February 12
    Lecture 9: Exam 1 debrief February 17
    """}]}

    candidates = extract_deadline_candidates(document, 2026)

    assert [(row["Item"], row["Normalized Date"]) for row in candidates] == [
        ("Assignment 3: Real Option & Queue", "2026-02-07"),
        ("Exam 1: Covers Lectures 1-8", "2026-02-12"),
    ]


def test_ocr_work_and_due_date_columns_are_reconstructed():
    def word(text, x0, top):
        return {"text": text, "x0": x0, "top": top, "bottom": top + 8}

    page = {"ocr_words": [
        word("Work", 100, 10), word("Due Date", 300, 10),
        word("HW1", 100, 40), word("Feb 10", 300, 40),
        word("Test1", 100, 70), word("Mar 3", 300, 70),
    ]}

    assert [(row["Item"], row["Normalized Date"]) for row in
            extract_ocr_column_deadlines(page, 2026)] == [
        ("HW1", "2026-02-10"),
        ("Test1", "2026-03-03"),
    ]


def test_ocr_detection_requires_little_text_and_large_image():
    large = SimpleNamespace(
        width=100, height=100,
        images=[{"x0": 0, "x1": 80, "y0": 0, "y1": 80}],
    )
    small = SimpleNamespace(
        width=100, height=100,
        images=[{"x0": 0, "x1": 20, "y0": 0, "y1": 20}],
    )
    assert page_needs_ocr(large, "short")
    assert page_needs_ocr(large, "x" * 100)
    assert not page_needs_ocr(small, "short")


@pytest.mark.parametrize("render_fails", [False, True])
def test_ocr_pdfium_document_is_always_closed(monkeypatch, render_fails):
    pdf_module = importlib.import_module("syllasift.parsing.pdf")
    closed = []

    class RenderedPage:
        def render(self, scale):
            if render_fails:
                raise RuntimeError("render failed")
            return SimpleNamespace(to_pil=lambda: "image")

    class FakeDocument:
        def __getitem__(self, _index):
            return RenderedPage()

        def close(self):
            closed.append(True)

    monkeypatch.setattr(
        pdf_module, "pdfium",
        SimpleNamespace(PdfDocument=lambda _bytes: FakeDocument()),
    )
    monkeypatch.setattr(pdf_module, "np", SimpleNamespace(array=lambda image: image))
    monkeypatch.setattr(
        pdf_module, "get_ocr_engine",
        lambda: (lambda _image: ([], None)),
    )
    if render_fails:
        with pytest.raises(RuntimeError, match="render failed"):
            pdf_module.extract_ocr_page(b"pdf", 0)
    else:
        assert pdf_module.extract_ocr_page(b"pdf", 0) == ("", [])
    assert closed == [True]


def test_pdfplumber_failure_falls_back_to_pypdf(monkeypatch):
    pdf_module = importlib.import_module("syllasift.parsing.pdf")

    def fail_open(_stream):
        raise RuntimeError("plumber failed")

    fallback_page = SimpleNamespace(extract_text=lambda: "CS 101 Fall 2026")
    monkeypatch.setattr(pdf_module, "pdfplumber", SimpleNamespace(open=fail_open))
    monkeypatch.setattr(
        pdf_module, "PdfReader", lambda _stream: SimpleNamespace(pages=[fallback_page])
    )
    document = pdf_module.extract_pdf_document(io.BytesIO(b"pdf"))
    assert document["text"] == "CS 101 Fall 2026"


def test_pdf_reader_failures_raise_concise_error(monkeypatch):
    pdf_module = importlib.import_module("syllasift.parsing.pdf")
    monkeypatch.setattr(
        pdf_module, "pdfplumber",
        SimpleNamespace(open=lambda _stream: (_ for _ in ()).throw(RuntimeError("bad"))),
    )
    monkeypatch.setattr(
        pdf_module, "PdfReader",
        lambda _stream: (_ for _ in ()).throw(RuntimeError("encrypted")),
    )
    with pytest.raises(ValueError, match="Unable to read this PDF"):
        pdf_module.extract_pdf_document(io.BytesIO(b"pdf"))


def test_embedded_image_ocr_is_merged_with_native_text(monkeypatch):
    pdf_module = importlib.import_module("syllasift.parsing.pdf")
    page = SimpleNamespace(
        width=100, height=100,
        images=[{"x0": 0, "x1": 80, "y0": 0, "y1": 80}],
        extract_text=lambda: "Native syllabus text " * 8,
        extract_tables=lambda: [],
    )

    class FakePdf:
        pages = [page]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(pdf_module, "pdfplumber", SimpleNamespace(open=lambda _: FakePdf()))
    monkeypatch.setattr(
        pdf_module, "extract_ocr_page", lambda *_args: ("Final Exam January 5", [])
    )
    document = pdf_module.extract_pdf_document(io.BytesIO(b"pdf"))
    assert "Native syllabus text" in document["text"]
    assert "Final Exam January 5" in document["text"]
    assert document["pages"][0]["source"] == "mixed"


def test_relative_assignments_use_corresponding_exam_dates():
    document = {"text": """
    There are four sets of homework corresponding to the four exams.
    Each set of homework is due by the corresponding exam date.
    REAL-WORLD APPLICATION
    Complete four submissions throughout the semester, due on each exam day.
    Exam 1 September 16
    Exam 2 October 23
    Exam 3 November 11
    Exam 4 December 8
    """, "pages": [{"page": 1, "tables": [], "text": """
    Exam 1 September 16
    Exam 2 October 23
    Exam 3 November 11
    Exam 4 December 8
    """}]}

    candidates = extract_deadline_candidates(document, 2025)

    assert len(candidates) == 12
    assert ("Homework Set 4", "2025-12-08") in [
        (row["Item"], row["Normalized Date"]) for row in candidates
    ]
    assert ("Real-World Application 4", "2025-12-08") in [
        (row["Item"], row["Normalized Date"]) for row in candidates
    ]


def test_seven_relative_homework_sets_are_not_dropped():
    exam_lines = "\n".join(
        f"Exam {number} September {number}" for number in range(1, 8)
    )
    document = {
        "text": "There are seven sets of homework corresponding to the exams.",
        "pages": [{"page": 1, "tables": [], "text": exam_lines}],
    }
    candidates = extract_deadline_candidates(document, 2026)
    assert "Homework Set 7" in {row["Item"] for row in candidates}


def test_final_exam_on_last_lookahead_line_is_retained():
    text = """
    Midterm exams are on the following dates:
    filler one
    filler two
    filler three
    filler four
    Final Exam December 12
    """
    rows = extract_deadlines(text, 2026)
    assert ("Final Exam", "2026-12-12") in [
        (row["Item"], row["Normalized Date"]) for row in rows
    ]


def test_blank_date_header_and_activity_title_cleanup():
    document = {"text": "", "pages": [{"page": 2, "text": "", "tables": [[
        ["", "Class", "Description", "Location"],
        ["27-Aug", "Test-In", "Dead Hang, Plank", "Fitness Floor"],
        ["3-Sep", "Proper Warm Up", "Stretching", "Studio B"],
    ]]}]}

    candidates = extract_deadline_candidates(document, 2024)

    assert [(row["Item"], row["Normalized Date"]) for row in candidates] == [
        ("Test-In", "2024-08-27")
    ]
    metadata = detect_course_metadata(
        "APPH 1050 Weight Training Activity (Fall 2024)\n"
        "The Science of Physical Activity and Health"
    )
    assert metadata["course_name"] == "Weight Training Activity"


def test_labeled_vip_metadata_beats_meeting_location():
    text = """
    Syllabus for the Spring 2026 Smart Stadium VIP Team
    VIP Section VP3, Variable Credits
    Primary Team Meeting Time: Thursday at 3:30 in VL-465
    """

    assert detect_course_metadata(text) == {
        "course_name": "Smart Stadium VIP Team",
        "course_code": "VIP VP3",
        "semester": "Spring",
        "year": 2026,
    }


def test_section_finals_replace_sentence_fragments():
    document = {"text": "", "pages": [{"page": 4, "tables": [], "text": """
    Jan 29 Exam 1
    Final Exam: as scheduled on the final exam matrix.
    • 9:30 am section exam is on Monday May 4, at 8:00am
    • 12:30 pm section exam is on Thursday May 7, 11:20 am
    """}]}

    candidates = extract_deadline_candidates(document, 2026)

    assert [(row["Item"], row["Normalized Date"]) for row in candidates] == [
        ("Exam 1", "2026-01-29"),
        ("Final Exam - 9:30 AM Section", "2026-05-04"),
        ("Final Exam - 12:30 PM Section", "2026-05-07"),
    ]


def test_date_before_section_produces_two_finals():
    document = {"text": "", "pages": [{"page": 3, "tables": [], "text": """
    Our final will be on Friday, December 5 at 2:40-5:30pm for Section G,
    and Wednesday, December 10 at 2:40-5:30pm for Section J.
    """}]}

    candidates = extract_deadline_candidates(document, 2025)

    assert [(row["Item"], row["Normalized Date"]) for row in candidates] == [
        ("Final Exam - Section G", "2025-12-05"),
        ("Final Exam - Section J", "2025-12-10"),
    ]


def test_whitespace_schedule_relative_and_range_defaults():
    document = {"text": "", "pages": [{"page": 6, "tables": [], "text": """
    Week 3 Jan 27 Assignment: Self-grade of notebooks with rubric
    Week 7 Week of Feb 17 Web-based peer-evaluations released.
    Online form due by end of the day Friday.
    Last week of class Apr 20 - Apr 28 Final presentations
    Turn in individual documentation for final grading.
    Finals Week Apr 30 - May 7 No final. No assignments.
    """}]}

    candidates = extract_deadline_candidates(document, 2026)

    assert [(row["Item"], row["Normalized Date"], row["Include"]) for row in candidates] == [
        ("Self-grade of Notebooks", "2026-01-27", True),
        ("Peer Evaluation", "2026-02-20", True),
    ]


def test_assessment_with_two_discrete_dates_requires_user_choice():
    document = {
        "text": "Semester Schedule\nJune 30 / July 2 MIDTERMS DUE",
        "pages": [{
            "page": 4,
            "source": "text",
            "text": "June 30 / July 2 MIDTERMS DUE",
            "tables": [[
                ["Week", None, "Uploaded to Canvas", None, "Topic"],
                ["1", None, "May 19 / May 21", None, "Overview"],
                ["7", None, "June 30 / July 2", None, "MIDTERMS DUE"],
            ]],
        }],
    }

    review = extract_deadline_review(document, 2026)

    assert review["candidates"] == []
    assert review["multiple_date_assessments"] == [{
        "item": "Midterm",
        "choices": [
            {"label": "June 30", "normalized_date": "2026-06-30"},
            {"label": "July 2", "normalized_date": "2026-07-02"},
        ],
        "page": 4,
        "source": "TEXT",
    }]
    assert review["unresolved_assessments"] == []


def test_assessment_range_warns_without_fabricating_deadline():
    document = {
        "text": "Semester Schedule\nAug 3 – Aug 6 FINALS",
        "pages": [{
            "page": 4,
            "source": "text",
            "text": "Aug 3 – Aug 6 FINALS",
            "tables": [[
                ["Week", "Uploaded to Canvas", "Topic"],
                ["12", "Aug 3 – Aug 6", "FINALS"],
            ]],
        }],
    }

    review = extract_deadline_review(document, 2026)

    assert review["candidates"] == []
    assert review["multiple_date_assessments"] == []
    assert review["unresolved_assessments"] == [{
        "item": "Final Exam",
        "date_range": "Aug 3 – Aug 6",
        "page": 4,
        "source": "TEXT",
        "message": (
            "An exact deadline is not provided for this assessment. "
            "Check Canvas."
        ),
    }]


def test_module_ranges_warn_for_assessments_but_not_lessons():
    document = {"text": """\
Modules 1–3 (August 18 – September 7, 2025)
Module 1: The Basics of Sound
Lesson 1: How to Approach Exams
Quiz 1
Project 1: Sound Collage
Modules 4–5 (September 8 – 21, 2025)
Quiz 2
""", "pages": []}

    review = extract_deadline_review(document, 2025)

    assert [row["item"] for row in review["unresolved_assessments"]] == [
        "Quiz 1", "Project 1: Sound Collage", "Quiz 2",
    ]
    assert review["candidates"] == []


def test_non_assessment_slash_dates_do_not_create_choices():
    document = {"text": "", "pages": [{
        "page": 4,
        "text": "",
        "tables": [[
            ["Week", "Uploaded to Canvas", "Topic"],
            ["1", "May 19 / May 21", "Overview and history"],
        ]],
    }]}

    assert extract_deadline_review(document, 2026) == {
        "candidates": [],
        "multiple_date_assessments": [],
        "unresolved_assessments": [],
        "warnings": [],
    }


def test_three_column_course_calendar_extracts_assignments_and_exams():
    calendar = [[
        ["", "Dates", "", "", "Topics", "", "", "Assignments", ""],
        ["1/13", None, None, "Syllabus and Introduction", None, None, "", None, None],
        ["2/3", None, None, "The Social Self", None, None, "Article Review 1", None, None],
        ["2/5", None, None, "Review", None, None, "Portfolio 1", None, None],
        ["", "2/10", "", "", "Exam 1 – 35 MC", None, None, None, ""],
        ["2/26", None, None, "Group Influence", None, None, "Article Review 2", None, None],
        ["3/3", None, None, "Review", None, None, "Portfolio 2", None, None],
        ["", "3/5", "", "", "Exam 2 - 50 MC", None, None, None, ""],
        ["3/19", None, None, "Aggression", None, None, "Article Review 3", None, None],
        ["", "3/23 – 3/27", "", "", "Spring Break", None, None, None, ""],
        ["", "4/2", "", "", "Asynchronous Day", "", "", "Portfolio 3", ""],
        ["", "4/9", "", "", "Exam 3 - 70 MC", None, None, None, ""],
        ["4/21", None, None, "Emotion", None, None, "Article Review 4", None, None],
        ["", "4/23", "", "", "Optional Make-Up Exam", "", "", "Portfolio 4", ""],
        ["4/28", None, None, "Final Exam Review", None, None, "", None, None],
    ]]
    final_text = "The final exam is on May 7th."
    document = {
        "text": final_text,
        "pages": [
            {"page": 2, "text": final_text, "tables": [], "source": "text"},
            {"page": 5, "text": "", "tables": calendar, "source": "text"},
        ],
    }

    candidates = extract_deadline_candidates(document, 2026)

    assert [(row["Item"], row["Normalized Date"]) for row in candidates] == [
        ("Article Review 1", "2026-02-03"),
        ("Portfolio 1", "2026-02-05"),
        ("Exam 1 - 35 MC", "2026-02-10"),
        ("Article Review 2", "2026-02-26"),
        ("Portfolio 2", "2026-03-03"),
        ("Exam 2 - 50 MC", "2026-03-05"),
        ("Article Review 3", "2026-03-19"),
        ("Portfolio 3", "2026-04-02"),
        ("Exam 3 - 70 MC", "2026-04-09"),
        ("Article Review 4", "2026-04-21"),
        ("Portfolio 4", "2026-04-23"),
        ("Final Exam", "2026-05-07"),
    ]
    assert all(row["Confidence"] == "High" for row in candidates)
    assert "Syllabus and Introduction" not in {
        row["Item"] for row in candidates
    }
    assert "Optional Make-Up Exam" not in {
        row["Item"] for row in candidates
    }


def test_fragmented_assignment_due_calendar_rebuilds_wrapped_rows_and_pages():
    header_page = [[
        ["DAY", "DATE", "TOPIC", "ASSIGNMENT DUE"],
        ["", "", "", ""],
        [None, None, "Human Behavior & Processes:",
         "§ Watch Ted Talk | Susan Cain: The Power of Introverts [18 min]"],
        ["Wednesday", "Aug 26", None, None],
        [None, None, "Personality & Values", "§ Complete Quiz 1"],
        ["", "", "", ""],
        [None, None, None, "§ Listen: Freakonomics | How to Be Less Terrible"],
        ["Wednesday", "Sept 2", "Attribution & Decision Making", None],
        [None, None, None, "at Predicting the Future [52 min]"],
    ]]
    continuation_page = [[
        ["", "", "", ""],
        [None, None, None, "§ Read ‘Using Stretch Goals To Promote Organizational"],
        ["Monday", "Sept 28", "Goal Setting Theory", None],
        [None, None, None, "Effectiveness And Personal Growth’"],
        [None, None, None, "§ Complete Quiz 3"],
    ]]
    document = {"text": "", "pages": [
        {"page": 11, "text": "", "tables": header_page, "source": "text"},
        {"page": 12, "text": "", "tables": continuation_page, "source": "text"},
    ]}

    candidates = extract_deadline_candidates(document, 2026)

    assert [(row["Item"], row["Normalized Date"]) for row in candidates] == [
        ("Watch Ted Talk | Susan Cain: The Power of Introverts [18 min]", "2026-08-26"),
        ("Complete Quiz 1", "2026-08-26"),
        ("Listen: Freakonomics | How to Be Less Terrible at Predicting the Future [52 min]", "2026-09-02"),
        ("Read ‘Using Stretch Goals To Promote Organizational Effectiveness And Personal Growth’", "2026-09-28"),
        ("Complete Quiz 3", "2026-09-28"),
    ]


def test_section_first_final_exam_schedule_uses_exact_section_dates():
    text = (
        "Final Dec 10-17 FINAL EXAM "
        "Section A: Wednesday, Dec 16 at 8:00AM-10:50AM "
        "Section B: Wednesday, Dec 16 at 11:20AM-2:10PM "
        "Section C: Friday, Dec 11 at 2:40PM-5:30PM"
    )

    candidates = extract_deadline_candidates(text, 2026)

    assert [(row["Item"], row["Normalized Date"]) for row in candidates] == [
        ("Final Exam - Section C", "2026-12-11"),
        ("Final Exam - Section A", "2026-12-16"),
        ("Final Exam - Section B", "2026-12-16"),
    ]


@pytest.mark.parametrize("day,date", [("F", "11-Oct"), ("M", "4-Nov")])
def test_schedule_weekday_and_topic_details_are_cleaned(day, date):
    document = {"text": "", "pages": [{"page": 6, "text": "", "tables": [[
        ["Day", "Date", "Topic", "Reading Assignment"],
        [day, date, "Exam 2", "Chapters 5-8"],
    ]]}]}

    candidates = extract_deadline_candidates(document, 2024)

    assert candidates[0]["Item"] == "Exam 2"


def test_filename_term_is_only_used_as_metadata_fallback():
    text = "CS 1100: First-Year\nSeminar"

    assert detect_course_metadata(text, "CS1100_Syllabus_Fall2024.docx.pdf") == {
        "course_name": "First-Year Seminar",
        "course_code": "CS 1100",
        "semester": "Fall",
        "year": 2024,
    }
    assert detect_course_metadata(
        "CS 1100: First-Year\nSeminar\nSpring 2025",
        "CS1100_Syllabus_Fall2024.pdf",
    )["semester"] == "Spring"


def test_heading_then_numbered_midterm_dates():
    document = {"text": "", "pages": [{"page": 3, "tables": [], "text": """
    Midterm Exams will take place during lecture on the following
    dates:
    1. Tuesday, September 16
    2. Tuesday, October 21
    3. Tuesday, November 25
    """}]}

    candidates = extract_deadline_candidates(document, 2025)

    assert [(row["Item"], row["Normalized Date"]) for row in candidates] == [
        ("Midterm Exam 1", "2025-09-16"),
        ("Midterm Exam 2", "2025-10-21"),
        ("Midterm Exam 3", "2025-11-25"),
    ]


def test_project_submission_midterm_and_final_cleanup():
    document = {"text": "", "pages": [{"page": 4, "tables": [], "text": """
    There will be one in-class midterm exam. You will be tested on March 12.
    You will submit your agent by 11:59 pm on April 20.
    There will be a cumulative final on Thursday, April 30 from 6:00 to 8:50 pm.
    """}]}

    candidates = extract_deadline_candidates(document, 2026)

    assert [(row["Item"], row["Normalized Date"]) for row in candidates] == [
        ("Midterm Exam", "2026-03-12"),
        ("Tournament Agent Submission", "2026-04-20"),
        ("Final Exam", "2026-04-30"),
    ]


def test_final_instructional_day_policy_is_not_a_deadline():
    document = {"text": "", "pages": [{"page": 8, "tables": [], "text": """
    Final Instructional Class Days - December 2 & 3, 2024
    Graded assignments may be due during Final Instructional Class Days.
    """}]}

    assert extract_deadline_candidates(document, 2024) == []


def test_day_first_schedule_extracts_only_dated_assessments():
    document = {"text": "", "pages": [{"page": 9, "tables": [], "text": """
    Date Lecture Topics Required Reading
    8 Sep Animals: Invertebrates
    10 Sep Animals: Vertebrates
    Scientist Spotlight 1 due by 11:59pm
    13 Sep The Tree of Life over Geologic Time
    17 Sep Module 1 Exam
    6 Oct Mammalian Cardiac Cycle
    Scientist Spotlight 2 due by 11:59pm
    18 Oct Module 2 Exam
    """}]}

    candidates = extract_deadline_candidates(document, 2021)

    assert [
        (row["Item"], row["Normalized Date"], row["Page"])
        for row in candidates
    ] == [
        ("Scientist Spotlight 1", "2021-09-10", 9),
        ("Module 1 Exam", "2021-09-17", 9),
        ("Scientist Spotlight 2", "2021-10-06", 9),
        ("Module 2 Exam", "2021-10-18", 9),
    ]


def test_assignments_due_column_splits_and_cleans_deliverables():
    document = {"text": "", "pages": [{"page": 6, "text": "", "tables": [[
        ["Week", "Lab Schedule", "Assignments due"],
        [
            "1 May 12",
            "Intro to Stats, Lab Safety",
            (
                "Pre-lab 1: Animal Behavior\n"
                "Biosafety/rDNA Training (Due May 16th)\n"
                "I ntro Stats Assignment Due by end of Lab"
            ),
        ],
        [
            "3 May 26",
            "Animal Behavior: Counting Eggs",
            (
                "Lab Notebook Check 1 (end of lab)\n"
                "Lab Group Member Evaluation 1 (Due May 30th)"
            ),
        ],
    ]]}]}

    candidates = extract_deadline_candidates(document, 2026)

    assert [(row["Item"], row["Normalized Date"]) for row in candidates] == [
        ("Pre-lab 1: Animal Behavior", "2026-05-12"),
        ("Intro Stats Assignment", "2026-05-12"),
        ("Biosafety/rDNA Training", "2026-05-16"),
        ("Lab Notebook Check 1", "2026-05-26"),
        ("Lab Group Member Evaluation 1", "2026-05-30"),
    ]


def test_course_title_suffixes_are_removed_without_course_specific_rules():
    assert detect_course_metadata(
        "BIOS 1108 ORGANISMAL BIOLOGY FALL 2021\nCourse Mode Information:"
    )["course_name"] == "Organismal Biology"
    assert detect_course_metadata(
        "MGT 2250 Syllabus\nManagement Statistics, Section O, 3 Credits\n"
        "Summer 2026"
    )["course_name"] == "Management Statistics"


def test_platform_notice_names_the_relevant_services():
    notices = detect_platform_notices(
        "Homework assignments are posted on the MyLab Statistics website "
        "and are due by the deadlines specified above. Canvas contains the tests."
    )

    assert notices == [
        "Some assignment dates are maintained in Canvas and MyLab Statistics. "
        "Add them manually when they become available."
    ]


def test_document_wide_candidates_recover_page_provenance():
    document = {"text": """
    There will be one in-class midterm exam. You will be tested on March 12.
    You will submit your agent by 11:59 pm on April 20.
    """, "pages": [
        {"page": 3, "tables": [], "source": "text", "text": """
        Tournament: You will submit your agent by 11:59 pm on April 20.
        """},
        {"page": 4, "tables": [], "source": "text", "text": """
        Midterm exam: You will be tested on March 12.
        """},
    ]}

    candidates = extract_deadline_candidates(document, 2026)

    assert [(row["Item"], row["Page"]) for row in candidates] == [
        ("Midterm Exam", 4),
        ("Tournament Agent Submission", 3),
    ]


def test_cs3600_deadlines_keep_all_source_pages():
    page_three = """
    Tournament: You will submit your agent by 11:59 pm on April 20.
    The final tournament will be run on April 21 and 22.
    """
    page_four = """
    Midterm exam: 15%
    There will be one in-class midterm exam. You will be tested on March 12.
    Final: 25%
    There will be a cumulative final on Thursday, April 30 from 6:00 to 8:50 pm.
    """
    document = {
        "text": f"{page_three}\n{page_four}",
        "pages": [
            {"page": 3, "tables": [], "source": "text", "text": page_three},
            {"page": 4, "tables": [], "source": "text", "text": page_four},
        ],
    }

    candidates = extract_deadline_candidates(document, 2026)

    pages_by_item = {row["Item"]: row["Page"] for row in candidates}
    assert pages_by_item["Midterm Exam"] == 4
    assert pages_by_item["Tournament Agent Submission"] == 3
    assert pages_by_item["Final Exam"] == 4
