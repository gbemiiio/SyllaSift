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


def _coalesce_fragmented_calendar_rows(table, date_index):
    """Rebuild logical rows when PDF extraction splits one row vertically.

    Some visually ordinary course calendars are emitted as several physical
    rows (topic, date, and each assignment land on separate lines), with an
    empty physical row between class meetings.  Joining each such block by
    column restores the table the reader sees on the page.
    """
    body = list(table[1:])
    if not any(
        not any(str(cell or "").strip() for cell in row or [])
        for row in body
    ):
        return table
    nonempty_rows = [row for row in body if any(str(cell or "").strip() for cell in row or [])]
    dated_rows = [
        row for row in nonempty_rows
        if date_index < len(row or [])
        and re.search(DATE_PATTERN, str((row or [])[date_index] or ""), re.IGNORECASE)
    ]
    if not dated_rows or len(nonempty_rows) <= len(dated_rows) * 2:
        return table

    width = max((len(row or []) for row in table), default=0)
    date_positions = [
        position for position, row in enumerate(body)
        if date_index < len(row or [])
        and re.search(DATE_PATTERN, str((row or [])[date_index] or ""), re.IGNORECASE)
    ]
    grouped = {position: [] for position in date_positions}
    for position, row in enumerate(body):
        if not any(str(cell or "").strip() for cell in row or []):
            continue
        # PDF text is emitted top-to-bottom.  A fragment belongs to the
        # visually nearest row carrying a date; ties favor the following date.
        owner = min(date_positions, key=lambda anchor: (abs(anchor - position), -anchor))
        grouped[owner].append(list(row or []))

    logical_rows = [table[0]]
    for anchor in date_positions:
        logical_rows.append([
            "\n".join(
                str(row[index]).strip()
                for row in grouped[anchor]
                if index < len(row) and str(row[index] or "").strip()
            )
            for index in range(width)
        ])
    return logical_rows


def _calendar_assignment_entries(text):
    """Keep wrapped bullet text together while preserving separate bullets."""
    lines = get_lines(text)
    if not any(re.match(r"^\s*[§•]", line) for line in lines):
        return lines

    entries = []
    current = []
    for line in lines:
        if re.match(r"^\s*[§•]", line):
            if current:
                entries.append(" ".join(current))
            current = [re.sub(r"^\s*[§•]\s*", "", line)]
        elif current:
            current.append(line)
    if current:
        entries.append(" ".join(current))
    return entries


def _marked_due_entries(text):
    """Split a compound due cell at its HW/IC/PMIP/AC markers."""
    compact = re.sub(r"\s+", " ", text).strip()
    matches = list(re.finditer(
        r".+?\((?:HW|IC|PMIP|AC)\)",
        compact,
        re.IGNORECASE,
    ))
    if not matches:
        return _calendar_assignment_entries(text)
    return [match.group().strip() for match in matches]


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
            if (
                header in {
                    "topic", "topics", "text", "description", "descriptions",
                }
                or "topic" in header
            )
        ]
        assignment_indexes = [
            index for index, header in enumerate(headers)
            if (
                header in {"assignment", "assignments"}
                or "due" in header
            )
        ]
        if not date_indexes or not topic_indexes or not assignment_indexes:
            continue

        date_index = date_indexes[0]
        assignment_index = assignment_indexes[0]
        compound_due_mode = bool(re.search(
            r"\b(?:HW|IC|PMIP|AC)\b|reports?\s+due",
            headers[assignment_index],
            re.IGNORECASE,
        ))
        # "Due / Notes" is a mixed notes column where only explicit Due:
        # entries count.  "Assignment Due" is instead an authoritative list
        # of everything due for that class meeting.
        due_notes_mode = "notes" in headers[assignment_index]
        table = _coalesce_fragmented_calendar_rows(table, date_index)

        def column_cell(cells, target_index):
            if target_index < len(cells) and cells[target_index]:
                return cells[target_index]
            nearby = [
                (abs(index - target_index), index, cell)
                for index, cell in enumerate(cells)
                if (
                    cell
                    and abs(index - target_index) == 1
                    and (index >= len(headers) or not headers[index])
                )
            ]
            return min(nearby)[2] if nearby else ""

        for row in table[1:]:
            cells = [str(cell or "").strip() for cell in (row or [])]
            raw_date = column_cell(cells, date_index)
            if re.search(
                r"\b[A-Za-z]{3,9}\.?\s+\d{1,2}\s*[-–—]\s*\d{1,2}\b",
                re.sub(r"\s+", " ", raw_date),
                re.IGNORECASE,
            ):
                # A calendar span (for example, finals week) is not an exact
                # deadline. Section-specific dates are extracted separately.
                continue
            date_match = re.search(DATE_PATTERN, raw_date, re.IGNORECASE)
            raw_date = date_match.group() if date_match else ""
            if not raw_date:
                continue

            topic_parts = list(dict.fromkeys(
                column_cell(cells, topic_index)
                for topic_index in topic_indexes
                if column_cell(cells, topic_index)
            ))
            topic_text = " ".join(topic_parts)
            item = clean_explicit_item(topic_text)
            presentation_match = re.search(
                r"\bProject\s+Presentation\s*#?\s*(\d+)\b",
                item,
                re.IGNORECASE,
            )
            if presentation_match:
                item = f"Project Presentation {presentation_match.group(1)}"
            if (
                not compound_due_mode
                and scheduled_event_kind(item)
                and not line_is_excluded(item)
            ):
                item = re.sub(r"\s*[–—]\s*", " - ", item)
                append_deadline(
                    deadlines, seen, item, raw_date, course_year,
                )

            # Exams sometimes appear in a lesson-prep column rather than the
            # topic column. Only assessment-like scheduled events are admitted.
            for index, header in enumerate(headers):
                if "lesson prep" not in header or index >= len(cells):
                    continue
                prep_item = clean_explicit_item(cells[index])
                if (
                    re.match(
                        r"^(?:Exam|Test|Quiz|Midterm|Final)\b",
                        prep_item,
                        re.IGNORECASE,
                    )
                    and scheduled_event_kind(prep_item)
                    and not line_is_excluded(prep_item)
                ):
                    append_deadline(
                        deadlines, seen, prep_item, raw_date, course_year,
                    )

            assignment_text = column_cell(cells, assignment_index)
            for assignment in _marked_due_entries(assignment_text):
                if due_notes_mode:
                    due_match = re.match(
                        r"^\s*Due\s*:\s*(.+)$", assignment, re.IGNORECASE,
                    )
                    trailing_due = re.match(
                        r"^(.+?)\s+due\s*[.]*$", assignment, re.IGNORECASE,
                    )
                    if due_match:
                        assignment = due_match.group(1)
                    elif trailing_due:
                        assignment = trailing_due.group(1)
                    else:
                        continue
                    item = clean_assignment_due_item(assignment, raw_date)
                    if item.lower().startswith("project "):
                        item = item.title()
                else:
                    item = clean_explicit_item(assignment)
                if item and not line_is_excluded(item):
                    append_deadline(
                        deadlines, seen, item, raw_date, course_year,
                    )

    return deadlines


def enrich_course_calendar_tables(pages):
    """Carry recognized course-calendar headers onto continuation pages."""
    enriched = {}
    active_headers = {}

    for page_position, page in enumerate(pages):
        page_tables = []
        next_headers = {}
        for table in page.get("tables", []):
            table = table or []
            width = max((len(row or []) for row in table), default=0)
            first_row = list(table[0] or []) if table else []
            headers = [str(cell or "").strip().lower() for cell in first_row]
            has_date = any(header in {"date", "dates"} for header in headers)
            has_due = any(
                header in {"assignment", "assignments"} or "due" in header
                for header in headers
            )
            has_topic = any(
                header in {
                    "topic", "topics", "text", "description", "descriptions",
                }
                or "topic" in header
                for header in headers
            )

            if has_date and has_due and has_topic:
                header = first_row
                next_headers[width] = header
                page_tables.append(table)
            elif width in active_headers and table:
                header = active_headers[width]
                date_index = next(
                    index for index, cell in enumerate(header)
                    if str(cell or "").strip().lower() in {"date", "dates"}
                )
                contains_calendar_date = any(
                    date_index < len(row or [])
                    and re.search(
                        DATE_PATTERN,
                        str((row or [])[date_index] or ""),
                        re.IGNORECASE,
                    )
                    for row in table
                )
                if contains_calendar_date:
                    page_tables.append([header] + table)
                    next_headers[width] = header
                else:
                    page_tables.append(table)
            else:
                page_tables.append(table)
        enriched[page_position] = page_tables
        active_headers = next_headers

    return enriched


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
                    topic_lines = get_lines(row[2])
                    topic = topic_lines[0] if topic_lines else ""

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
