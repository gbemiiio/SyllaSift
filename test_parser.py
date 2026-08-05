import pytest
from types import SimpleNamespace

from parser import (
    detect_course_metadata,
    detect_platform_notices,
    extract_deadline_candidates,
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
    assert not page_needs_ocr(large, "x" * 100)
    assert not page_needs_ocr(small, "short")


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
        ("Final Presentations", "2026-04-28", False),
        ("Final Documentation", "2026-04-28", False),
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
