import re

from .dates import (
    course_year_context,
    find_invalid_date_texts,
    invalid_date_warning,
)
from .classification import (
    candidate_is_duplicate,
    candidate_item_is_excluded,
    clean_candidate_label,
)
from .provenance import locate_candidate_source
from .strategies.exams import (
    extract_authoritative_finals,
    extract_section_final_candidates,
)
from .strategies.ocr import extract_ocr_column_deadlines
from .strategies.relative import extract_relative_deadlines
from .strategies.schedules import (
    extract_assessment_date_review,
    extract_day_first_schedule_deadlines,
    extract_scheduled_events,
    extract_whitespace_schedule_candidates,
)
from .strategies.tables import (
    enrich_calendar_tables,
    extract_assignment_due_table_deadlines,
    extract_calendar_table_deadlines,
    extract_course_calendar_deadlines,
    extract_date_topic_table_events,
    extract_table_deadlines,
)
from .strategies.text import (
    extract_deadlines,
    extract_document_requirement_candidates,
    extract_due_markers,
    extract_explicit_due_lines,
    extract_release_due_deadlines,
)


def extract_deadline_review(document, course_year, semester=None):
    """Return exact candidates plus choices and unresolved date warnings."""
    course_year = course_year_context(course_year, semester)
    candidates = extract_deadline_candidates(document, course_year)
    if isinstance(document, str):
        pages = [{
            "page": None,
            "text": document,
            "tables": [],
            "source": "text",
        }]
        document_text = document
    else:
        pages = document.get("pages", [])
        document_text = document.get("text", "") or "\n".join(
            page.get("text", "") for page in pages
        )
    warning_parts = [document_text]
    for page in pages:
        for table in page.get("tables", []):
            for row in table or []:
                warning_parts.extend(str(cell) for cell in row or [] if cell)
        warning_parts.extend(
            str(word.get("text", ""))
            for word in page.get("ocr_words", [])
        )
    multiple, unresolved = extract_assessment_date_review(
        pages, document_text, course_year,
    )
    warning = invalid_date_warning(
        find_invalid_date_texts("\n".join(warning_parts), course_year)
    )
    return {
        "candidates": candidates,
        "multiple_date_assessments": multiple,
        "unresolved_assessments": unresolved,
        "warnings": [warning] if warning else [],
    }


def extract_deadline_candidates(document, course_year, semester=None):
    """Return reviewable deadline suggestions with source information."""
    course_year = course_year_context(course_year, semester)
    if isinstance(document, str):
        pages = [{"page": None, "text": document, "tables": []}]
    else:
        pages = document.get("pages", [])

    candidates = []
    seen = set()
    calendar_tables_by_page = enrich_calendar_tables(pages)

    for page_position, page in enumerate(pages):
        page_number = page.get("page")
        tables = page.get("tables", [])
        assignment_due_deadlines = extract_assignment_due_table_deadlines(
            tables,
            course_year,
        )
        table_deadlines = extract_table_deadlines(
            tables,
            course_year,
        )
        if assignment_due_deadlines:
            table_deadlines = []
        calendar_deadlines = extract_calendar_table_deadlines(
            calendar_tables_by_page.get(page_position, tables),
            course_year,
        )
        course_calendar_deadlines = extract_course_calendar_deadlines(
            tables,
            course_year,
        )
        event_table_deadlines = extract_date_topic_table_events(
            tables,
            course_year,
        )
        ocr_deadlines = extract_ocr_column_deadlines(page, course_year)
        release_due_deadlines = extract_release_due_deadlines(
            page.get("text", ""),
            course_year,
        )
        explicit_due_deadlines = extract_explicit_due_lines(
            page.get("text", ""),
            course_year,
        )
        scheduled_deadlines = extract_scheduled_events(
            page.get("text", ""),
            course_year,
        )
        authoritative_finals = extract_authoritative_finals(
            page.get("text", ""),
            course_year,
        )
        section_finals = extract_section_final_candidates(
            page.get("text", ""), course_year,
        )
        whitespace_schedule = extract_whitespace_schedule_candidates(
            page.get("text", ""), course_year,
        )
        dated_schedule = extract_day_first_schedule_deadlines(
            page.get("text", ""), course_year,
        )

        if course_calendar_deadlines:
            due_deadlines = []
            ordinary_deadlines = []
        elif assignment_due_deadlines:
            due_deadlines = []
            ordinary_deadlines = []
        elif calendar_deadlines or ocr_deadlines:
            due_deadlines = []
            ordinary_deadlines = []
        elif table_deadlines:
            due_deadlines = []
            ordinary_deadlines = []
        elif release_due_deadlines:
            due_deadlines = []
            ordinary_deadlines = []
        elif dated_schedule:
            due_deadlines = []
            ordinary_deadlines = []
        else:
            due_deadlines = extract_due_markers(
                page.get("text", ""),
                course_year,
                page_number,
            )
            ordinary_deadlines = extract_deadlines(
                page.get("text", ""),
                course_year,
            )

        strong_deadlines = (
            event_table_deadlines
            + course_calendar_deadlines
            + calendar_deadlines
            + ocr_deadlines
            + release_due_deadlines
            + explicit_due_deadlines
            + scheduled_deadlines
            + section_finals
            + whitespace_schedule
            + dated_schedule
            + authoritative_finals
            + due_deadlines
            + assignment_due_deadlines
            + table_deadlines
        )
        explicit_keys = {
            (
                clean_candidate_label(row["Item"]).lower(),
                row["Normalized Date"],
            )
            for row in strong_deadlines
        }

        for row in (
            strong_deadlines
            + ordinary_deadlines
        ):
            row = dict(row)
            row["Item"] = clean_candidate_label(row["Item"])
            if candidate_item_is_excluded(row["Item"]):
                continue
            key = (row["Item"].lower(), row["Normalized Date"])
            if key in seen or candidate_is_duplicate(candidates, row):
                continue

            seen.add(key)
            is_explicit = key in explicit_keys
            is_structured_exam = bool(
                re.fullmatch(
                    r"(?:Midterm Exam \d+|Final Exam)",
                    row["Item"],
                    re.IGNORECASE,
                )
            )
            candidate = dict(row)
            candidate.update(
                {
                    "Confidence": (
                        row.get("_confidence")
                        or ("High" if is_explicit or is_structured_exam else "Medium")
                    ),
                    "Reason": (
                        row.get("_reason")
                        or ("Explicit due date" if is_explicit
                        else (
                            "Structured exam list"
                            if is_structured_exam
                            else "Assessment and date appear together"
                        ))
                    ),
                    "Page": page_number,
                    "Source": page.get("source", "text").upper(),
                    "Include": row.get("_include", True),
                }
            )
            for internal_key in ("_confidence", "_reason", "_include"):
                candidate.pop(internal_key, None)
            candidates.append(candidate)

    authoritative_dates = {
        candidate["Normalized Date"]
        for candidate in candidates
        if candidate["Item"].lower().startswith("final exam")
        and candidate["Reason"] == "Explicit due date"
    }
    if authoritative_dates:
        candidates = [
            candidate
            for candidate in candidates
            if candidate["Item"].lower() != "final exam"
            or candidate["Normalized Date"] in authoritative_dates
        ]

    document_text = document if isinstance(document, str) else (
        document.get("text", "")
        or "\n".join(page.get("text", "") for page in pages)
    )
    document_requirements = extract_document_requirement_candidates(
        document_text, course_year,
    )
    for row in document_requirements:
        duplicate_candidates = [
            candidate for candidate in candidates
            if candidate_is_duplicate([candidate], row)
        ]
        if duplicate_candidates:
            candidates = [
                candidate for candidate in candidates
                if candidate not in duplicate_candidates
            ]
        candidate = dict(row)
        page_number, source = locate_candidate_source(
            row,
            pages,
            course_year,
        )
        candidate.update({
            "Confidence": row.get("_confidence", "High"),
            "Reason": row.get("_reason", "Explicit due date"),
            "Page": page_number,
            "Source": source,
            "Include": row.get("_include", True),
        })
        for internal_key in ("_confidence", "_reason", "_include"):
            candidate.pop(internal_key, None)
        candidates.append(candidate)

    for row in extract_relative_deadlines(document_text, candidates):
        if candidate_is_duplicate(candidates, row):
            continue
        candidate = dict(row)
        page_number, source = locate_candidate_source(
            row,
            pages,
            course_year,
        )
        candidate.update(
            {
                "Confidence": "High",
                "Reason": "Due on corresponding exam date",
                "Page": page_number,
                "Source": source,
                "Include": True,
            }
        )
        candidates.append(candidate)

    candidates = [
        candidate for candidate in candidates
        if candidate["Item"].lower() != "final exam - section exam"
    ]
    section_final_candidates = [
        candidate for candidate in candidates
        if candidate["Item"].startswith("Final Exam - ")
    ]
    if section_final_candidates:
        section_dates = {
            candidate["Normalized Date"] for candidate in section_final_candidates
        }
        candidates = [
            candidate for candidate in candidates
            if candidate in section_final_candidates
            or not (
                candidate["Normalized Date"] in section_dates
                and ("final" in candidate["Item"].lower()
                     or "section exam" in candidate["Item"].lower())
            )
        ]

    candidates.sort(key=lambda row: row["Normalized Date"])
    return candidates
