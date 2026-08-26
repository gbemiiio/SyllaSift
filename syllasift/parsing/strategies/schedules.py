import re
from datetime import datetime, timedelta

from ..classification import (
    clean_assignment_due_item,
    clean_explicit_item,
    line_is_excluded,
    line_looks_like_assessment,
    scheduled_event_kind,
)
from ..common import append_deadline, candidate_row, get_lines
from ..dates import normalize_date
from ..patterns import DATE_PATTERN, DAY_FIRST_DATE_PATTERN, WEEKDAY_PATTERN


RANGE_SEPARATOR_PATTERN = r"(?:\s*[–—]\s*|\s+-\s+)"


def _assessment_label(text):
    """Return a concise label only for an assessment-like schedule entry."""
    item = clean_assignment_due_item(text)
    if not (
        line_looks_like_assessment(item)
        or re.search(r"\b(?:midterms|finals)\b", item, re.IGNORECASE)
    ):
        return ""

    lowered = item.lower()
    if lowered in {"midterm", "midterms"}:
        return "Midterm"
    if lowered in {"final", "finals"}:
        return "Final Exam"
    return clean_explicit_item(item)


def _normalized_choices(raw_dates, course_year):
    choices = []
    for raw_date in raw_dates:
        try:
            normalized = normalize_date(raw_date, course_year)
        except ValueError:
            continue
        if normalized not in {choice["normalized_date"] for choice in choices}:
            choices.append({"label": raw_date, "normalized_date": normalized})
    return choices


def extract_assessment_date_review(pages, document_text, course_year):
    """Find user choices and warnings without fabricating range deadlines."""
    multiple_date_assessments = []
    unresolved_assessments = []
    seen_choices = set()
    seen_unresolved = set()

    def add_choice(item, raw_dates, page_number, source):
        choices = _normalized_choices(raw_dates, course_year)
        key = (item.lower(), tuple(choice["normalized_date"] for choice in choices))
        if len(choices) < 2 or key in seen_choices:
            return
        seen_choices.add(key)
        multiple_date_assessments.append({
            "item": item,
            "choices": choices,
            "page": page_number,
            "source": source,
        })

    def add_unresolved(item, date_range, page_number, source):
        key = (item.lower(), date_range.lower())
        if key in seen_unresolved:
            return
        seen_unresolved.add(key)
        unresolved_assessments.append({
            "item": item,
            "date_range": date_range,
            "page": page_number,
            "source": source,
            "message": (
                "An exact deadline is not provided for this assessment. "
                "Check Canvas."
            ),
        })

    # Handle schedule tables such as Week / Uploaded to Canvas / Topic. PDF
    # extraction may spread the three logical columns across empty cells, so
    # use the non-empty values in each row after verifying the headers.
    for page in pages:
        for table in page.get("tables", []):
            if not table or not table[0]:
                continue
            headers = " ".join(str(cell or "") for cell in table[0]).lower()
            if not all(header in headers for header in ("week", "topic")):
                continue

            for row in table[1:]:
                values = [
                    str(cell).strip()
                    for cell in (row or [])
                    if cell is not None and str(cell).strip()
                ]
                if len(values) < 3:
                    continue
                date_text = values[1]
                topic = " ".join(values[2:])
                item = _assessment_label(topic)
                if not item:
                    continue
                raw_dates = [
                    match.group()
                    for match in re.finditer(DATE_PATTERN, date_text, re.IGNORECASE)
                ]
                if "/" in date_text and len(raw_dates) >= 2:
                    add_choice(
                        item, raw_dates, page.get("page"),
                        page.get("source", "text").upper(),
                    )
                elif re.search(RANGE_SEPARATOR_PATTERN, date_text) and raw_dates:
                    add_unresolved(
                        item, date_text, page.get("page"),
                        page.get("source", "text").upper(),
                    )


    # A structured schedule may explicitly leave an assessment date
    # undecided. Keep it visible in review without inventing a date.
    for page in pages:
        for table in page.get("tables", []):
            for row in table or []:
                cells = [str(cell or "").strip() for cell in row or []]
                if not any(
                    re.fullmatch(r"(?:TBD|TBA|To be determined)", cell, re.IGNORECASE)
                    for cell in cells
                ):
                    continue
                for cell in cells:
                    item = _assessment_label(cell)
                    if item:
                        add_unresolved(
                            item, "TBD", page.get("page"),
                            page.get("source", "text").upper(),
                        )

    # Handle outline sections where assessments are listed beneath a module
    # date range, possibly across a PDF page break.
    module_heading = re.compile(
        r"(?im)^\s*Modules?\s+[^\n(]+\(([^)\n]+)\)\s*$"
    )
    headings = list(module_heading.finditer(document_text or ""))
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(document_text)
        block = document_text[heading.end():end]
        date_range = heading.group(1)
        if (
            not re.search(RANGE_SEPARATOR_PATTERN, date_range)
            or not re.search(DATE_PATTERN, date_range, re.IGNORECASE)
        ):
            continue
        for line in get_lines(block):
            item = _assessment_label(line)
            if not item or item.lower().startswith("extra credit"):
                continue
            # Module/lesson prose contains assessment words incidentally; only
            # retain standalone outline bullets for quizzes, projects, or exams.
            cleaned = clean_explicit_item(line)
            if not re.match(
                r"^(?:Quiz|Project|Exam|Midterm|Final)\b",
                cleaned,
                re.IGNORECASE,
            ):
                continue
            page_number = next(
                (
                    page.get("page") for page in pages
                    if any(
                        clean_explicit_item(page_line).lower() == cleaned.lower()
                        for page_line in get_lines(page.get("text", ""))
                    )
                ),
                None,
            )
            add_unresolved(cleaned, date_range, page_number, "TEXT")

    # Catch an assessment written directly after a range outside a table.
    for page in pages:
        for line in get_lines(page.get("text", "")):
            raw_dates = [
                match for match in re.finditer(DATE_PATTERN, line, re.IGNORECASE)
            ]
            if len(raw_dates) < 2 or not re.search(RANGE_SEPARATOR_PATTERN, line):
                continue
            trailing_text = line[raw_dates[1].end():].strip(" .,:;-–—")
            item = _assessment_label(trailing_text)
            if item:
                add_unresolved(
                    item,
                    line[raw_dates[0].start():raw_dates[1].end()],
                    page.get("page"),
                    page.get("source", "text").upper(),
                )

    return multiple_date_assessments, unresolved_assessments


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
                try:
                    normalized = friday_of_week(dates[0], course_year)
                except ValueError:
                    continue
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
                # A range does not identify an exact deadline. The richer
                # review API reports it as an unresolved assessment instead.
                continue
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
