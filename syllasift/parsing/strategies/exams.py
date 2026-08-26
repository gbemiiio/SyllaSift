import re

from ..classification import line_is_excluded
from ..common import append_deadline, candidate_row, get_lines
from ..patterns import DATE_PATTERN, WEEKDAY_PATTERN


def extract_authoritative_finals(text, course_year):
    deadlines = []
    seen = set()
    lines = get_lines(text)

    for index, line in enumerate(lines):
        context = " ".join(lines[max(0, index - 2):index + 2])
        lowered = context.lower()

        if "final exam" not in lowered or not any(
            phrase in lowered
            for phrase in (
                "will be administered",
                "is on",
                "held during",
                "final exam period on",
            )
        ):
            continue

        section_matches = list(
            re.finditer(
                rf"Section\s+([A-Z0-9]+).*?({DATE_PATTERN})",
                context,
                re.IGNORECASE,
            )
        )
        if section_matches:
            for section_match in section_matches:
                append_deadline(
                    deadlines,
                    seen,
                    f"Final Exam - Section {section_match.group(1).upper()}",
                    section_match.group(2),
                    course_year,
                )
            continue

        dates = list(re.finditer(DATE_PATTERN, context, re.IGNORECASE))
        if dates:
            append_deadline(
                deadlines,
                seen,
                "Final Exam",
                dates[-1].group(),
                course_year,
            )

    if any("Section" in deadline["Item"] for deadline in deadlines):
        return [
            deadline
            for deadline in deadlines
            if "Section" in deadline["Item"]
        ]

    return deadlines


def extract_section_final_candidates(text, course_year):
    """Read section-specific finals regardless of date/section ordering."""
    rows = []
    seen = set()
    compact = re.sub(r"\s+", " ", text)

    for match in re.finditer(
        rf"Section\s+([A-Z0-9]+)\s*:\s*(?:{WEEKDAY_PATTERN})\s*,?\s*"
        rf"({DATE_PATTERN})",
        compact,
        re.IGNORECASE,
    ):
        row = candidate_row(
            f"Final Exam - Section {match.group(1).upper()}",
            match.group(2),
            course_year,
        )
        if row and (row["Item"], row["Normalized Date"]) not in seen:
            seen.add((row["Item"], row["Normalized Date"]))
            rows.append(row)

    for match in re.finditer(
        rf"({DATE_PATTERN}).{{0,100}}?for\s+Section\s+([A-Z0-9]+)",
        compact,
        re.IGNORECASE,
    ):
        if match.group(2).lower() == "exam":
            continue
        row = candidate_row(
            f"Final Exam - Section {match.group(2).upper()}",
            match.group(1),
            course_year,
        )
        if row and (row["Item"], row["Normalized Date"]) not in seen:
            seen.add((row["Item"], row["Normalized Date"]))
            rows.append(row)

    for match in re.finditer(
        rf"(\d{{1,2}}:\d{{2}}\s*(?:am|pm))\s+section\s+exam\s+is\s+on\s+"
        rf"(?:{WEEKDAY_PATTERN})?\s*,?\s*({DATE_PATTERN})",
        compact,
        re.IGNORECASE,
    ):
        label = re.sub(r"\s+", " ", match.group(1)).upper()
        row = candidate_row(
            f"Final Exam - {label} Section",
            match.group(2),
            course_year,
        )
        if row and (row["Item"], row["Normalized Date"]) not in seen:
            seen.add((row["Item"], row["Normalized Date"]))
            rows.append(row)

    return rows


def extract_exam_list(lines, course_year):
    deadlines = []
    seen = set()

    inside_exam_list = False
    remaining_exam_lines = 0

    for line_index, line in enumerate(lines):
        lowered = line.lower()
        previous = lines[line_index - 1].lower() if line_index else ""

        if (
            (("exam" in lowered or "midterm" in lowered) and any(
                phrase in lowered for phrase in
                ("following dates", "exam dates", "midterm dates")
            ))
            or (
                lowered.strip(" :") == "dates"
                and ("exam" in previous or "midterm" in previous)
            )
        ):
            inside_exam_list = True
            remaining_exam_lines = 5
            continue

        if inside_exam_list:
            exam_match = re.match(
                rf"^\s*(\d+)\.\s*"
                rf"(?:{WEEKDAY_PATTERN}\s*,?\s*)?"
                rf"({DATE_PATTERN})\s*$",
                line,
                re.IGNORECASE,
            )

            if exam_match:
                exam_number = exam_match.group(1)
                raw_date = exam_match.group(2)

                append_deadline(
                    deadlines,
                    seen,
                    f"Midterm Exam {exam_number}",
                    raw_date,
                    course_year,
                )

                continue

            if "final exam" in lowered and not line_is_excluded(line):
                date_match = re.search(DATE_PATTERN, line, re.IGNORECASE)
                if date_match:
                    append_deadline(
                        deadlines,
                        seen,
                        "Final Exam",
                        date_match.group(),
                        course_year,
                    )
                    continue

            remaining_exam_lines -= 1

            if remaining_exam_lines <= 0:
                inside_exam_list = False

    return deadlines
