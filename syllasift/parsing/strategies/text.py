import re

from ..classification import (
    clean_explicit_item,
    clean_item_name,
    clean_schedule_item,
    line_is_excluded,
    line_looks_like_assessment,
    nearby_context_is_excluded,
)
from ..common import append_deadline, candidate_row, get_lines
from ..dates import course_year_context
from ..patterns import (
    ASSESSMENT_WORDS,
    DATE_PATTERN,
    EXCLUDED_HEADINGS,
    WEEKDAY_PATTERN,
)
from .exams import extract_exam_list


def extract_due_markers(text, course_year, page_number=None):
    """Extract assignments whose explicit due date is on a later line."""
    lines = get_lines(text)
    deadlines = []
    seen = set()

    for line_index, line in enumerate(lines):
        due_match = re.search(
            rf"\bDue\s*:\s*({DATE_PATTERN})",
            line,
            re.IGNORECASE,
        )

        if not due_match:
            continue

        block = []
        for previous_index in range(line_index - 1, max(-1, line_index - 8), -1):
            previous_line = lines[previous_index]

            if re.search(r"\bDue\s*:", previous_line, re.IGNORECASE):
                break

            if re.match(rf"^(?:{DATE_PATTERN})\b", previous_line, re.IGNORECASE):
                remainder = re.sub(
                    rf"^(?:{DATE_PATTERN})\s*",
                    "",
                    previous_line,
                    count=1,
                    flags=re.IGNORECASE,
                )
                if remainder:
                    block.insert(0, remainder)
                break

            block.insert(0, previous_line)

        item = clean_schedule_item("\n".join(block))
        if not item:
            if clean_schedule_item(line[:due_match.start()]):
                continue
            row = candidate_row(
                "Unlabeled deadline",
                due_match.group(1),
                course_year,
                "Low",
                "Due date has no assignment context",
                False,
            )
            if row:
                key = (row["Item"].lower(), row["Normalized Date"])
                if key not in seen:
                    seen.add(key)
                    deadlines.append(row)
            continue

        append_deadline(
            deadlines,
            seen,
            item,
            due_match.group(1),
            course_year,
        )

    return deadlines


def extract_explicit_due_lines(text, course_year):
    deadlines = []
    seen = set()
    lines = get_lines(text)

    for line_index, line in enumerate(lines):
        due_match = re.search(
            rf"\(?(?:is\s+)?(?:Due|Deadline)(?:\s+on|\s+by)?\s*:?\s*"
            rf"(?:{WEEKDAY_PATTERN}\s*,?\s*)?({DATE_PATTERN})",
            line,
            re.IGNORECASE,
        )

        if not due_match or line_is_excluded(line):
            continue

        item = clean_explicit_item(line[:due_match.start()])
        if (len(item) > 80 or (item and item[0].islower())) and line_index > 0:
            heading_match = re.search(
                r"([A-Z][A-Z /&-]{2,}(?:QUIZ|EXAM|PROJECT|ASSIGNMENT))",
                lines[line_index - 1],
            )
            if heading_match:
                item = heading_match.group(1).title()
        if not item:
            continue

        append_deadline(
            deadlines,
            seen,
            item,
            due_match.group(1),
            course_year,
        )

    return deadlines


def extract_document_requirement_candidates(text, course_year):
    """Extract dated requirements described outside schedules."""
    rows = []
    article_match = re.search(
        rf"until\s+\d{{1,2}}(?::\d{{2}})?\s*(?:am|pm)\s+on\s+({DATE_PATTERN})"
        rf".{{0,100}}?article critiques",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if article_match:
        row = candidate_row(
            "Alternative Assignment - Journal Article Critiques",
            article_match.group(1), course_year,
        )
        if row:
            rows.append(row)

    if re.search(r"research credit.{0,250}?last day of class", text,
                 re.IGNORECASE | re.DOTALL):
        class_day = re.search(
            rf"({DATE_PATTERN})\s+Final Instructional Class Day",
            text,
            re.IGNORECASE,
        )
        if class_day:
            row = candidate_row(
                "Research Participation Credit",
                class_day.group(1), course_year, "Low",
                "Inferred from last instructional class day", False,
            )
            if row:
                rows.append(row)

    tournament_match = re.search(
        rf"submit\s+(?:your|the)\s+agent\s+by\s+"
        rf"(?:\d{{1,2}}(?::\d{{2}})?\s*(?:am|pm)\s+on\s+)?({DATE_PATTERN})",
        text,
        re.IGNORECASE,
    )
    if tournament_match:
        row = candidate_row(
            "Tournament Agent Submission",
            tournament_match.group(1), course_year,
        )
        if row:
            rows.append(row)

    midterm_match = re.search(
        rf"(?:in-class\s+)?midterm\s+exam.{{0,220}}?\bon\s+({DATE_PATTERN})",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if midterm_match:
        row = candidate_row("Midterm Exam", midterm_match.group(1), course_year)
        if row:
            rows.append(row)
    return rows


def extract_release_due_deadlines(text, course_year):
    """Read borderless Assignment / Release Date / Due Date tables."""
    deadlines = []
    seen = set()
    inside_table = False
    pending_date = None

    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        lowered = line.lower()

        if (
            "assignment" in lowered
            and "release date" in lowered
            and "due date" in lowered
        ):
            inside_table = True
            pending_date = None
            continue

        if not inside_table:
            continue
        if not line:
            pending_date = None
            continue

        date_matches = list(
            re.finditer(DATE_PATTERN, line, re.IGNORECASE)
        )

        if len(date_matches) >= 2:
            item = line[:date_matches[0].start()].strip(" .,:;-–—")
            raw_date = date_matches[1].group()

            if item:
                append_deadline(
                    deadlines,
                    seen,
                    item,
                    raw_date,
                    course_year,
                )
                pending_date = None
            else:
                pending_date = raw_date
            continue

        if pending_date:
            if date_matches or re.fullmatch(r"[A-Z][A-Z /&-]{3,}", line):
                pending_date = None
                continue
            item = re.sub(r"\s+\d+(?:\.\d+)?%.*$", "", line).strip()

            if item.lower().startswith("final section"):
                item = "Final Exam"

            if item and (
                line_looks_like_assessment(item)
                or item.lower().startswith("final section")
            ):
                append_deadline(
                    deadlines,
                    seen,
                    item,
                    pending_date,
                    course_year,
                )
            pending_date = None

    return deadlines


def extract_deadlines(text, course_year, semester=None):
    course_year = course_year_context(course_year, semester)
    lines = get_lines(text)

    # First extract structured exam lists.
    deadlines = extract_exam_list(
        lines,
        course_year,
    )

    seen = {
        (
            deadline["Item"].lower(),
            deadline["Normalized Date"],
        )
        for deadline in deadlines
    }

    for line_index, line in enumerate(lines):
        if line_is_excluded(line) or nearby_context_is_excluded(
            lines,
            line_index,
        ):
            continue

        # These are handled by extract_exam_list().
        if re.match(
            rf"^\s*\d+\.\s*"
            rf"(?:{WEEKDAY_PATTERN}\s*,?\s*)?"
            rf"(?:{DATE_PATTERN})\s*$",
            line,
            re.IGNORECASE,
        ):
            continue

        if not line_looks_like_assessment(line):
            continue

        date_matches = list(
            re.finditer(
                DATE_PATTERN,
                line,
                re.IGNORECASE,
            )
        )

        if not date_matches:
            continue

        # Usually the first valid date on an assessment line
        # is the actual assessment date.
        raw_date = date_matches[0].group()

        item = clean_item_name(
            line,
            raw_date,
        )

        if not item:
            continue

        # Avoid duplicate final exams extracted from explanatory text.
        if "final exam" in item.lower():
            item = "Final Exam"

        append_deadline(
            deadlines,
            seen,
            item,
            raw_date,
            course_year,
        )

    deadlines.sort(
        key=lambda deadline: deadline[
            "Normalized Date"
        ]
    )

    return deadlines
