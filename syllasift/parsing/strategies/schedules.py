import re
from datetime import datetime, timedelta

from ..classification import (
    clean_explicit_item,
    line_is_excluded,
    line_looks_like_assessment,
    scheduled_event_kind,
)
from ..common import append_deadline, candidate_row, get_lines
from ..dates import normalize_date
from ..patterns import DATE_PATTERN, DAY_FIRST_DATE_PATTERN, WEEKDAY_PATTERN


def extract_scheduled_events(text, course_year):
    deadlines = []
    seen = set()

    for line in get_lines(text):
        match = re.match(
            rf"^[\s•*\-]*(.+?)\s*\("
            rf"(?:{WEEKDAY_PATTERN})\s*,?\s*({DATE_PATTERN})\)",
            line,
            re.IGNORECASE,
        )

        if not match:
            continue

        item = clean_explicit_item(match.group(1))
        if not scheduled_event_kind(item):
            continue

        append_deadline(
            deadlines,
            seen,
            item,
            match.group(2),
            course_year,
        )

    return deadlines


def friday_of_week(raw_date, course_year):
    start = datetime.strptime(normalize_date(raw_date, course_year), "%Y-%m-%d")
    return (start + timedelta(days=(4 - start.weekday()) % 7)).strftime("%Y-%m-%d")


def extract_whitespace_schedule_candidates(text, course_year):
    """Interpret schedule blocks whose columns were flattened into text."""
    lines = get_lines(text)
    rows = []
    blocks = []
    current = []

    for line in lines:
        if re.match(r"^Week\b|^Last week of\b|^Finals Week\b", line, re.IGNORECASE):
            if current:
                blocks.append(" ".join(current))
            current = [line]
        elif current:
            current.append(line)
    if current:
        blocks.append(" ".join(current))

    for block in blocks:
        lowered = block.lower()
        if any(phrase in lowered for phrase in (
            "verification of student participation",
            "grades for 2000-level courses",
            "withdrawal deadline",
            "no final. no assignments",
        )):
            continue

        dates = [match.group() for match in re.finditer(DATE_PATTERN, block, re.IGNORECASE)]
        if not dates:
            continue

        items = []
        if "self-grade" in lowered and "notebook" in lowered:
            items.append("Self-grade of Notebooks")
        elif "peer-evaluation" in lowered or "peer evaluation" in lowered:
            items.append("Peer Evaluation")
        elif "individual" in lowered and "documentation" in lowered and "mid-term" in lowered:
            items.append("Midterm Documentation")
        if "final presentations" in lowered:
            items.append("Final Presentations")
        if "individual" in lowered and "documentation" in lowered and "final grading" in lowered:
            items.append("Final Documentation")
        if not items:
            continue

        for item in items:
            if "due by" in lowered and "friday" in lowered:
                normalized = friday_of_week(dates[0], course_year)
                row = candidate_row(
                    item, normalized, course_year, "Medium",
                    "Weekday resolved from schedule week", True,
                )
            elif "closes" in lowered and len(dates) >= 2:
                row = candidate_row(item, dates[-1], course_year)
            elif len(dates) == 1 and "week of" not in lowered:
                row = candidate_row(
                    item, dates[0], course_year, "Medium",
                    "Actionable event on schedule date", True,
                )
            else:
                row = candidate_row(
                    item, dates[-1], course_year, "Low",
                    "Inferred from schedule range", False,
                )
            if row:
                rows.append(row)

    return rows


def extract_day_first_schedule_deadlines(text, course_year):
    """Read schedules whose rows begin with dates such as `17 Sep`."""
    lines = get_lines(text)
    date_starts = [
        re.match(
            rf"^({DAY_FIRST_DATE_PATTERN})\s+(?!\d{{1,2}}\b)",
            line,
            re.IGNORECASE,
        )
        for line in lines
    ]
    if sum(match is not None for match in date_starts) < 3:
        return []

    deadlines = []
    seen = set()
    current_date = ""

    for line in lines:
        date_match = re.match(
            rf"^({DAY_FIRST_DATE_PATTERN})\s+(?!\d{{1,2}}\b)(.*)$",
            line,
            re.IGNORECASE,
        )
        content = line
        if date_match:
            current_date = date_match.group(1)
            content = date_match.group(2)
        if not current_date or line_is_excluded(content):
            continue

        module_exam = re.search(r"\bModule\s+(\d+)\s+Exam\b", content, re.IGNORECASE)
        if module_exam:
            item = f"Module {module_exam.group(1)} Exam"
        elif re.search(r"\bFinal\s+Comprehensive\b", content, re.IGNORECASE):
            item = "Final Exam"
        else:
            due_match = re.search(
                r"\b(?:is\s+)?due(?:\s+by)?\b",
                content,
                re.IGNORECASE,
            )
            if not due_match:
                continue
            item = clean_explicit_item(content[:due_match.start()])
            if not line_looks_like_assessment(item):
                continue

        append_deadline(
            deadlines,
            seen,
            item,
            current_date,
            course_year,
        )

    return deadlines
