import re

from .common import get_lines
from .patterns import (
    ASSESSMENT_WORDS,
    DATE_PATTERN,
    EXCLUDED_CONTEXTS,
    EXCLUDED_HEADINGS,
    WEEKDAY_PATTERN,
)


def line_is_excluded(line):
    lowered = line.lower()

    return any(
        excluded_context in lowered
        for excluded_context in EXCLUDED_CONTEXTS
    )


def nearby_context_is_excluded(lines, line_index):
    """Catch policy headings split from their dated text by PDF extraction."""
    for nearby_line in lines[max(0, line_index - 2):line_index]:
        lowered = nearby_line.lower().strip(" .:;-–—")

        if any(
            heading == lowered or lowered.startswith(f"{heading} ")
            for heading in EXCLUDED_HEADINGS
        ):
            return True

    return False


def line_looks_like_assessment(line):
    lowered = line.lower()

    has_assessment_word = any(
        re.search(rf"\b{re.escape(word)}\b", lowered)
        for word in ASSESSMENT_WORDS
    )

    has_deadline_language = bool(
        re.search(
            r"\b("
            r"is due|due on|due by|deadline|"
            r"submit by|submitted by|takes place|"
            r"scheduled for"
            r")\b",
            lowered,
        )
    )

    return has_assessment_word or has_deadline_language


def clean_schedule_item(text):
    """Choose the assignment portion of a schedule cell or line block."""
    lines = get_lines(text)
    useful_lines = []

    for line in lines:
        line = re.sub(r"\(Canvas\)", "", line, flags=re.IGNORECASE)
        line = re.sub(r"^Due\s*:.*$", "", line, flags=re.IGNORECASE)
        line = line.strip(" .,:;-–—")

        if not line:
            continue

        lowered = line.lower()
        if (
            lowered == "class notes"
            or lowered.startswith("chapter ")
            or lowered.startswith("watch ")
            or lowered in {"readings and assignments", "worksheet"}
        ):
            continue

        useful_lines.append(line)

    if not useful_lines:
        return ""

    assessment_indexes = [
        index
        for index, line in enumerate(useful_lines)
        if line_looks_like_assessment(line)
    ]

    if assessment_indexes:
        selected_index = assessment_indexes[-1]
        selected_lines = useful_lines[selected_index:]

        if selected_index > 0:
            previous_line = useful_lines[selected_index - 1]
            if (
                previous_line.endswith("-")
                or "(part " in previous_line.lower()
                or previous_line.lower().endswith(" of")
            ):
                selected_lines.insert(0, previous_line)
    else:
        selected_lines = useful_lines[-2:]

    item = " ".join(selected_lines)
    item = re.sub(r"-\s+", "-", item)
    return re.sub(r"\s+", " ", item).strip(" .,:;-–—")


def clean_explicit_item(item):
    item = re.sub(r"^[\s•*\-]+", "", item)
    item = re.sub(
        r"\b(?:assignment|assigment)\s+(\d+)\s+release\s*:",
        r"Assignment \1: ",
        item,
        flags=re.IGNORECASE,
    )
    item = re.sub(r"\brelease\s*:\s*", "", item, flags=re.IGNORECASE)
    item = re.sub(r"\(\s*$", "", item)
    item = re.sub(r"\(\s*:\s*\)", "", item)
    item = re.sub(r"\br\s+egister\b", "register", item, flags=re.IGNORECASE)
    item = re.sub(r"(?<=\d)-\s+(?=[A-Za-z])", "-", item)
    item = re.sub(
        r"^\d{1,2}:\d{2}\s*(?:AM|PM)\s*[-–—]\s*"
        r"\d{1,2}:\d{2}\s*(?:AM|PM)\s*",
        "",
        item,
        flags=re.IGNORECASE,
    )
    item = re.sub(r"\s+", " ", item)
    return item.strip(" .,:;-–—")


def scheduled_event_kind(item):
    lowered = item.lower().strip()

    if re.search(r"\bno\s+(?:final\s+)?exam\b", lowered):
        return ""
    if re.search(r"\bexam\s*#?\s*\d+\s+review\b", lowered):
        return ""

    if any(
        excluded in lowered
        for excluded in (
            "review session",
            "exam review",
            "q&a",
            "debrief",
            "lecture",
            "guest lecture",
            "no class",
            "break",
            "makeup",
            "make-up",
        )
    ):
        return ""

    if re.match(r"^(?:exam|test|quiz|midterm|final)(?:\b|(?=\d))", lowered):
        return "exam"

    if any(
        phrase in lowered
        for phrase in ("pitch session", "peer review", "presentation", "test-in")
    ):
        return "actionable"

    return ""


def clean_assignment_due_item(text, raw_date=""):
    """Clean one entry from an authoritative Assignments Due column."""
    item = re.sub(r"\b([IL])\s+(?=[a-z])", r"\1", text.strip())
    if raw_date:
        item = item.replace(raw_date, " ")
    item = re.sub(
        r"\(\s*Due\s+[^)]*\)",
        " ",
        item,
        flags=re.IGNORECASE,
    )
    item = re.sub(
        r"\(\s*end\s+of\s+(?:the\s+)?lab\s*\)",
        " ",
        item,
        flags=re.IGNORECASE,
    )
    item = re.sub(
        r"\s+Due\s+by\s+end\s+of\s+(?:the\s+)?Lab\b.*$",
        "",
        item,
        flags=re.IGNORECASE,
    )
    item = re.sub(r"\bDue\b", " ", item, flags=re.IGNORECASE)
    item = re.sub(
        r"\bby\s+\d{1,2}(?::\d{2})?\s*(?:AM|PM)\b.*$",
        "",
        item,
        flags=re.IGNORECASE,
    )
    item = re.sub(r"\s*[–—-]\s*$", "", item)
    item = re.sub(r"\s*([–—])\s*", r" \1 ", item)
    return re.sub(r"\s+", " ", item).strip(" .,:;-–—")


def candidate_item_tokens(item):
    normalized = re.sub(r"[^a-z0-9]+", " ", item.lower())
    normalized = re.sub(r"\bintro\b", "introduction", normalized)
    normalized = re.sub(r"\b(?:midterm|test)\b", "exam", normalized)
    ignored = {"the", "of", "and", "week", "given"}
    return {
        token
        for token in normalized.split()
        if token not in ignored
    }


def candidate_is_duplicate(candidates, row):
    row_tokens = candidate_item_tokens(row["Item"])

    for candidate in candidates:
        if candidate["Normalized Date"] != row["Normalized Date"]:
            continue

        candidate_tokens = candidate_item_tokens(candidate["Item"])
        smaller = min(len(row_tokens), len(candidate_tokens))

        if smaller and len(row_tokens & candidate_tokens) / smaller >= 0.8:
            return True

    return False


def candidate_item_is_excluded(item):
    lowered = item.lower().lstrip(" •*-")
    return (
        re.match(r"^(?:lecture|guest lecture|review(?: session)?|exam review)\b", lowered)
        is not None
        or "date of the final" in lowered
        or lowered == "course wrap-up"
        or re.match(r"^from\s+\d", lowered) is not None
        or (len(item) > 50 and item.lstrip(" •*-")[:1].islower())
        or "welcome and course plan" in lowered
        or "verification of student participation" in lowered
        or "grades for 2000-level courses" in lowered
        or "no final" in lowered and "no assignments" in lowered
        or "withdrawal deadline" in lowered
        or lowered.startswith("last week of")
        or "final instructional class day" in lowered
    )


def clean_candidate_label(item):
    item = clean_explicit_item(item)
    item = re.sub(r"\s*[–—]\s*", " - ", item)
    item = re.sub(r"^[MTWRF](?=\s+(?:Exam|Optional Final))\s+", "", item)
    item = re.sub(r"^\d+\.\s*", "", item)
    item = re.sub(
        r"^(Exam\s*#?\s*\d+)\s+on\s*(?:\[[^]]*\])?$",
        r"\1",
        item,
        flags=re.IGNORECASE,
    )
    item = re.sub(
        r"^(Exam\s*#?\s*\d+)\s+Chapters?\s+.*$",
        r"\1",
        item,
        flags=re.IGNORECASE,
    )
    item = re.sub(
        r"^Optional Final(?:,?\s*\d{1,2}:\d{2}\s*[-–—]\s*\d{1,2}:\d{2})?"
        r"(?:\s+Chapters?\s+.*)?$",
        "Optional Final Exam",
        item,
        flags=re.IGNORECASE,
    )
    if (
        "final" in item.lower()
        and not item.lower().startswith("final exam -")
        and re.search(r"\b(?:cumulative final|our final will be)\b", item, re.IGNORECASE)
    ):
        item = "Final Exam"
    return re.sub(r"\s+", " ", item).strip(" .,:;-–—")


def clean_item_name(line, date_text):
    item = line.replace(date_text, " ")

    item = re.sub(
        r"^\s*\d{1,2}:\d{2}\s*(?:AM|PM)\s*[-–—]\s*"
        r"\d{1,2}:\d{2}\s*(?:AM|PM)\s*",
        "",
        item,
        flags=re.IGNORECASE,
    )

    item = re.sub(
        WEEKDAY_PATTERN + r"\s*,?",
        " ",
        item,
        flags=re.IGNORECASE,
    )

    junk_phrases = [
        r"\bis due on\b",
        r"\bis due by\b",
        r"\bis due\b",
        r"\bdue on\b",
        r"\bdue by\b",
        r"\bdue\b",
        r"\bscheduled for\b",
        r"\bwill take place on\b",
        r"\btakes place on\b",
        r"\bmust be submitted by\b",
        r"\bsubmit by\b",
    ]

    for phrase in junk_phrases:
        item = re.sub(
            phrase,
            " ",
            item,
            flags=re.IGNORECASE,
        )

    # Remove times after the assignment name.
    item = re.sub(
        r"\bfrom\s+\d{1,2}:\d{2}\s*(?:AM|PM).*",
        "",
        item,
        flags=re.IGNORECASE,
    )

    item = re.sub(
        r"\bat\s+\d{1,2}(?::\d{2})?\s*(?:AM|PM).*",
        "",
        item,
        flags=re.IGNORECASE,
    )

    item = re.sub(r"\s+", " ", item)

    return item.strip(" .,:;-–—")
