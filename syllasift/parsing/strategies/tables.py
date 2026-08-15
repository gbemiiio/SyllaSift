import re

from ..classification import (
    clean_assignment_due_item,
    clean_explicit_item,
    clean_item_name,
    clean_schedule_item,
    line_is_excluded,
    scheduled_event_kind,
)
from ..common import append_deadline, get_lines
from ..patterns import DATE_PATTERN, DAY_FIRST_DATE_PATTERN


def extract_course_calendar_deadlines(tables, course_year):
    """Read authoritative Date / Topic / Assignment course calendars."""
    deadlines = []
    seen = set()

    for table in tables:
        if not table or not table[0]:
            continue

        headers = [str(cell or "").strip().lower() for cell in table[0]]
        date_indexes = [
            index for index, header in enumerate(headers)
            if header in {"date", "dates"}
        ]
        topic_indexes = [
            index for index, header in enumerate(headers)
            if header in {"topic", "topics"}
        ]
        assignment_indexes = [
            index for index, header in enumerate(headers)
            if header in {"assignment", "assignments"}
        ]
        if not date_indexes or not topic_indexes or not assignment_indexes:
            continue

        date_index = date_indexes[0]
        topic_index = topic_indexes[0]
        assignment_index = assignment_indexes[0]
        topic_start = (date_index + topic_index) // 2 + 1
        assignment_start = (topic_index + assignment_index) // 2 + 1

        for row in table[1:]:
            cells = [str(cell or "").strip() for cell in (row or [])]
            raw_date = next(
                (
                    cell for cell in cells
                    if re.fullmatch(DATE_PATTERN, cell, re.IGNORECASE)
                ),
                "",
            )
            if not raw_date:
                continue

            assignment_text = "\n".join(
                cell for cell in cells[assignment_start:] if cell
            )
            for assignment in get_lines(assignment_text):
                item = clean_explicit_item(assignment)
                if item and not line_is_excluded(item):
                    append_deadline(
                        deadlines, seen, item, raw_date, course_year,
                    )

            topic_text = " ".join(
                cell for cell in cells[topic_start:assignment_start] if cell
            )
            item = clean_explicit_item(topic_text)
            if scheduled_event_kind(item) == "exam":
                item = re.sub(r"\s*[–—]\s*", " - ", item)
                append_deadline(
                    deadlines, seen, item, raw_date, course_year,
                )

    return deadlines


def extract_assignment_due_table_deadlines(tables, course_year):
    """Split each deliverable in an Assignments Due table into its own row."""
    deadlines = []
    seen = set()

    for table in tables:
        if not table or not table[0]:
            continue
        headers = [str(cell or "").strip().lower() for cell in table[0]]
        due_indexes = [
            index
            for index, header in enumerate(headers)
            if "assignment" in header and "due" in header
        ]
        if not due_indexes:
            continue

        due_index = due_indexes[0]
        for row in table[1:]:
            row = row or []
            if due_index >= len(row) or not row[due_index]:
                continue

            row_date = ""
            for index, cell in enumerate(row):
                if index == due_index or not cell:
                    continue
                date_match = re.search(DATE_PATTERN, str(cell), re.IGNORECASE)
                if date_match:
                    row_date = date_match.group()
                    break
            if not row_date:
                continue

            for entry in get_lines(str(row[due_index])):
                if line_is_excluded(entry):
                    continue
                explicit_date = re.search(DATE_PATTERN, entry, re.IGNORECASE)
                raw_date = explicit_date.group() if explicit_date else row_date
                item = clean_assignment_due_item(entry, raw_date)
                if not item:
                    continue
                append_deadline(
                    deadlines,
                    seen,
                    item,
                    raw_date,
                    course_year,
                )

    return deadlines


def extract_table_deadlines(tables, course_year):
    deadlines = []
    seen = set()

    for table in tables:
        if not table:
            continue

        header = table[0] or []
        assignment_indexes = [
            index
            for index, cell in enumerate(header)
            if cell
            and any(
                heading in cell.lower()
                for heading in ("assignment", "deliverable", "coursework")
            )
        ]

        if not assignment_indexes:
            continue

        assignment_index = assignment_indexes[-1]

        if "deliverable" in (header[assignment_index] or "").lower():
            for row in table[1:]:
                row = row or []
                if assignment_index >= len(row):
                    continue

                deliverables = row[assignment_index] or ""
                row_date = ""
                topic = ""

                for cell in row:
                    if cell and re.fullmatch(
                        DATE_PATTERN,
                        cell.strip(),
                        re.IGNORECASE,
                    ):
                        row_date = cell.strip()
                        break

                if len(row) > 2 and row[2]:
                    topic = get_lines(row[2])[0]

                for deliverable in get_lines(deliverables):
                    if line_is_excluded(deliverable):
                        continue

                    date_match = re.search(
                        DATE_PATTERN,
                        deliverable,
                        re.IGNORECASE,
                    )

                    if date_match:
                        item = clean_item_name(
                            deliverable,
                            date_match.group(),
                        )
                        append_deadline(
                            deadlines,
                            seen,
                            item,
                            date_match.group(),
                            course_year,
                        )
                    elif (
                        row_date
                        and deliverable.lower().startswith("exam")
                        and "exam" in topic.lower()
                    ):
                        append_deadline(
                            deadlines,
                            seen,
                            deliverable,
                            row_date,
                            course_year,
                        )

            continue

        current_cells = []

        def flush_current_row():
            if not current_cells:
                return

            cell_text = "\n".join(dict.fromkeys(current_cells))
            due_matches = list(
                re.finditer(
                    rf"\bDue\s*:\s*({DATE_PATTERN})",
                    cell_text,
                    re.IGNORECASE,
                )
            )

            for due_match in due_matches:
                item = clean_schedule_item(cell_text[:due_match.start()])
                if not item:
                    continue

                append_deadline(
                    deadlines,
                    seen,
                    item,
                    due_match.group(1),
                    course_year,
                )

        for row in table[1:]:
            row = row or []
            begins_new_row = any(
                cell
                and re.fullmatch(DATE_PATTERN, cell.strip(), re.IGNORECASE)
                for cell in row
            )

            if begins_new_row:
                flush_current_row()
                current_cells = []

            first_index = max(0, assignment_index - 1)
            last_index = min(len(row), assignment_index + 2)
            for cell in row[first_index:last_index]:
                if cell and cell.strip():
                    current_cells.append(cell.strip())

        flush_current_row()

    return deadlines


def extract_calendar_table_deadlines(tables, course_year):
    deadlines = []
    seen = set()

    for table in tables:
        if not table or max((len(row or []) for row in table), default=0) < 6:
            continue

        for row in table:
            for cell in row or []:
                if not cell:
                    continue

                lines = get_lines(cell)
                date_match = re.search(DATE_PATTERN, lines[0], re.IGNORECASE) if lines else None
                if not date_match:
                    continue

                raw_date = date_match.group()
                for line in lines[1:]:
                    cleaned = clean_explicit_item(line)
                    lowered = cleaned.lower()

                    if line_is_excluded(cleaned):
                        continue

                    item_match = re.search(
                        r"\b(HW\s*#?\s*\d+|Homework\s*#?\s*\d+)\s+Due\b",
                        cleaned,
                        re.IGNORECASE,
                    )
                    if item_match:
                        item = re.sub(
                            r"\s+Due\b.*$",
                            "",
                            item_match.group(),
                            flags=re.IGNORECASE,
                        )
                    elif re.search(r"\b(?:Midterm|Exam|Test)\s*#?\s*\d+\b", cleaned, re.IGNORECASE):
                        item = cleaned
                    elif re.fullmatch(r"Test-In", cleaned, re.IGNORECASE):
                        item = cleaned
                    else:
                        continue

                    append_deadline(
                        deadlines,
                        seen,
                        item,
                        raw_date,
                        course_year,
                    )

    return deadlines


def enrich_calendar_tables(pages):
    """Carry weekday-column dates into a headerless continuation page."""
    enriched = {}
    carry_dates = {}

    for page_position, page in enumerate(pages):
        page_tables = []
        for table in page.get("tables", []):
            if max((len(row or []) for row in table or []), default=0) < 6:
                page_tables.append(table)
                continue

            copied_table = []
            for row in table:
                copied_row = list(row or [])
                for column, cell in enumerate(copied_row):
                    if not cell:
                        continue
                    date_match = re.search(DATE_PATTERN, cell, re.IGNORECASE)
                    if date_match:
                        carry_dates[column] = date_match.group()
                    elif (
                        column in carry_dates
                        and re.search(r"\b(?:HW|Homework)\s*#?\s*\d+\s+Due\b", cell, re.IGNORECASE)
                    ):
                        copied_row[column] = f"{carry_dates[column]}\n{cell}"
                copied_table.append(copied_row)
            page_tables.append(copied_table)
        enriched[page_position] = page_tables

    return enriched


def extract_date_topic_table_events(tables, course_year):
    deadlines = []
    seen = set()

    for table in tables:
        if not table or not table[0]:
            continue

        headers = [str(cell or "").lower() for cell in table[0]]
        date_indexes = [i for i, cell in enumerate(headers) if cell.strip() == "date"]
        if (
            not date_indexes
            and headers
            and not headers[0].strip()
            and any(
                row
                and re.fullmatch(DATE_PATTERN, str(row[0] or "").strip(), re.IGNORECASE)
                for row in table[1:]
            )
        ):
            date_indexes = [0]
        topic_indexes = [
            i for i, cell in enumerate(headers)
            if cell.strip() in {"topic", "event", "class"}
        ]
        if not date_indexes or not topic_indexes:
            continue

        date_index = date_indexes[0]
        topic_index = topic_indexes[0]
        for row in table[1:]:
            row = row or []
            if max(date_index, topic_index) >= len(row):
                continue

            raw_date = str(row[date_index] or "").strip()
            item = clean_explicit_item(str(row[topic_index] or ""))
            date_match = re.search(DATE_PATTERN, raw_date, re.IGNORECASE)
            if not date_match or not scheduled_event_kind(item):
                continue

            append_deadline(
                deadlines,
                seen,
                item,
                date_match.group(),
                course_year,
            )

    return deadlines
