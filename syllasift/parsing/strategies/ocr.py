import re

from ..classification import clean_explicit_item, line_is_excluded
from ..common import append_deadline
from ..patterns import DATE_PATTERN


def group_ocr_rows(words, tolerance=14):
    rows = []

    for word in sorted(words, key=lambda value: (value["top"], value["x0"])):
        center = (word["top"] + word["bottom"]) / 2
        matching_row = next(
            (
                row
                for row in rows
                if abs(row["center"] - center) <= tolerance
            ),
            None,
        )
        if matching_row is None:
            matching_row = {"center": center, "words": []}
            rows.append(matching_row)
        matching_row["words"].append(word)

    for row in rows:
        row["words"].sort(key=lambda value: value["x0"])

    return rows


def extract_ocr_column_deadlines(page, course_year):
    words = page.get("ocr_words", [])
    if not words:
        return []

    rows = group_ocr_rows(words)
    header_row = next(
        (
            row
            for row in rows
            if any(word["text"].lower() == "work" for word in row["words"])
            and any("due date" in word["text"].lower() for word in row["words"])
        ),
        None,
    )
    if not header_row:
        return []

    work_word = next(word for word in header_row["words"] if word["text"].lower() == "work")
    due_word = next(word for word in header_row["words"] if "due date" in word["text"].lower())
    work_x = work_word["x0"] - 20
    due_x = due_word["x0"] - 20
    deadlines = []
    seen = set()

    for row in rows:
        if row["center"] <= header_row["center"]:
            continue

        work_text = " ".join(
            word["text"]
            for word in row["words"]
            if work_x <= word["x0"] < due_x
        ).strip()
        due_text = " ".join(
            word["text"]
            for word in row["words"]
            if word["x0"] >= due_x
        ).strip()
        due_match = re.search(DATE_PATTERN, due_text, re.IGNORECASE)

        if work_text and due_match and not line_is_excluded(work_text):
            append_deadline(
                deadlines,
                seen,
                clean_explicit_item(work_text),
                due_match.group(),
                course_year,
            )

    return deadlines
