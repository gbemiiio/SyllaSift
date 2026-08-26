import re
from datetime import datetime

from .common import get_lines
from .patterns import COURSE_CODE_PATTERN, TERM_PATTERN


def detect_platform_notices(text):
    compact = re.sub(r"\s+", " ", text).lower()
    signals = (
        "due dates will be announced", "assignment due dates",
        "date provided in the canvas assignment", "dates are posted",
        "deadlines specified above", "posted deadline",
        "living schedule is linked",
        "see course assignments for additional instructions",
        "about one per week",
    )
    recurring_platform_work = bool(re.search(
        r"(?:weekly\s+homework|homework assignments?).{0,100}"
        r"(?:canvas|learning catalytics|webwork|mylab|mystatlab|launchpad)",
        compact,
    ))
    if not recurring_platform_work and not any(
        signal in compact for signal in signals
    ):
        return []
    platform_patterns = (
        ("Canvas", r"\bcanvas\b"),
        ("Gradescope", r"\bgradescope\b"),
        ("WeBWorK", r"\bwebwork\b"),
        ("MyLab Statistics", r"\b(?:mylab statistics|mystatlab)\b"),
        ("Learning Catalytics", r"\blearning catalytics\b"),
        ("LaunchPad", r"\blaunchpad\b"),
    )
    platforms = [
        label for label, pattern in platform_patterns
        if re.search(pattern, compact, re.IGNORECASE)
    ]
    location = format_readable_list(platforms) if platforms else "the course platform"
    return [
        f"Some assignment dates are maintained in {location}. "
        "Add them manually when they become available."
    ]


def format_readable_list(values):
    if len(values) < 2:
        return values[0] if values else ""
    if len(values) == 2:
        return f"{values[0]} and {values[1]}"
    return f"{', '.join(values[:-1])}, and {values[-1]}"


def normalize_course_code(course_code):
    if not course_code:
        return ""
    return re.sub(
        r"\s+", " ", course_code.upper().replace("-", " ")
    ).strip()


def detect_course_code(text):
    vip_match = re.search(
        r"\bVIP\s+Section\s+([A-Z]{1,4}\d{1,3})\b", text, re.IGNORECASE
    )
    if vip_match:
        return f"VIP {vip_match.group(1).upper()}"
    explicit_match = re.search(
        r"Course Number and Title\s*:\s*"
        r"([A-Z]{2,5}\s*-?\s*\d{3,4}[A-Z]?)",
        text,
        re.IGNORECASE,
    )
    if explicit_match:
        return normalize_course_code(explicit_match.group(1))
    rejected_context = re.compile(
        r"\b(?:prerequisites?|corequisites?|office|room|location|meets?|"
        r"meeting|classroom|web)\b",
        re.IGNORECASE,
    )
    preferred_context = re.compile(
        r"\b(?:course|syllabus|section|catalog|title)\b",
        re.IGNORECASE,
    )
    candidates = []
    offset = 0
    for line_number, line in enumerate(text.splitlines()[:250]):
        for match in re.finditer(COURSE_CODE_PATTERN, line, re.IGNORECASE):
            prefix = line[:match.start()]
            if rejected_context.search(prefix):
                continue
            score = 0
            if line_number < 15:
                score += 100 - line_number
            elif line_number < 60:
                score += 30
            if preferred_context.search(line):
                score += 75
            if re.search(r"^\s*" + COURSE_CODE_PATTERN, line, re.IGNORECASE):
                score += 40
            candidates.append((score, -(offset + match.start()), match.group()))
        offset += len(line) + 1
    if not candidates:
        return ""
    return normalize_course_code(max(candidates)[2])


def clean_course_title(title):
    title = title.strip(" ,:;-–—|")
    title = re.sub(
        r"^(course title|course name)\s*[:\-]\s*", "", title,
        flags=re.IGNORECASE,
    )
    title = re.sub(
        r"^Syllabus\s+for\s+the\s+", "", title, flags=re.IGNORECASE,
    )
    title = re.sub(
        r"\(?\b(?:Spring|Summer|Fall|Autumn|Winter)\s+20\d{2}\b\)?",
        "", title, flags=re.IGNORECASE,
    )
    title = re.sub(r"\(\s*\)", "", title)
    title = re.sub(
        r"\bCourse\s+Mode\s+Information\b.*$", "", title,
        flags=re.IGNORECASE,
    )
    title = re.sub(
        r",?\s*Section\s+[A-Z0-9-]+(?:\s*,\s*\d+\s*Credits?)?\s*,?$",
        "", title, flags=re.IGNORECASE,
    )
    title = re.sub(
        r",?\s*\d+\s*Credits?\s*,?$", "", title, flags=re.IGNORECASE,
    )
    title = re.sub(r"\s+", " ", title).strip(" ,:;-–—|")
    if title.isupper():
        title = " ".join(
            word if len(re.sub(r"[^A-Z]", "", word)) <= 3 else word.title()
            for word in title.split()
        )
    return title


def looks_like_course_title(line):
    if not line or len(line) < 4 or len(line) > 100:
        return False
    lowered = line.lower()
    rejected_words = [
        "syllabus", "instructor", "professor", "office hours", "email",
        "course description", "grading", "schedule", "semester",
        "department", "university", "college", "meeting time",
        "institute", "school of", "meeting times",
        "course mode information",
    ]
    if any(word in lowered for word in rejected_words):
        return False
    if re.fullmatch(COURSE_CODE_PATTERN, line, re.IGNORECASE):
        return False
    return sum(character.isalpha() for character in line) >= 4


def detect_course_name(text, course_code=""):
    syllabus_title = re.search(
        r"^\s*Syllabus\s+for\s+the\s+"
        r"(?:Spring|Summer|Fall|Autumn|Winter)\s+20\d{2}\s+(.+)$",
        text,
        re.IGNORECASE | re.MULTILINE,
    )
    if syllabus_title:
        title = clean_course_title(syllabus_title.group(1))
        if looks_like_course_title(title):
            return title
    explicit_match = re.search(
        r"Course Number and Title\s*:\s*"
        r"[A-Z]{2,5}\s*-?\s*\d{3,4}[A-Z]?\s*[,;:\-]\s*(.+)",
        text,
        re.IGNORECASE,
    )
    if explicit_match:
        title = clean_course_title(explicit_match.group(1).splitlines()[0])
        if title:
            return title
    lines = get_lines(text)
    for line in lines[:250]:
        if (
            re.fullmatch(r".{3,70}\bActivity", line, re.IGNORECASE)
            and "activity section" not in line.lower()
        ):
            return clean_course_title(line)
    if course_code:
        normalized_code = re.sub(r"[\s\-]", "", course_code.upper())
        code_line_indexes = []
        for index, line in enumerate(lines[:60]):
            normalized_line = re.sub(r"[\s\-]", "", line.upper())
            if normalized_code not in normalized_line:
                continue
            code_line_indexes.append(index)

        # Prefer titles attached to any occurrence of the selected code before
        # considering nearby header text such as an institution name.
        for index in code_line_indexes:
            line = lines[index]
            same_line_title = clean_course_title(re.sub(
                COURSE_CODE_PATTERN, "", line, flags=re.IGNORECASE,
            ))
            if looks_like_course_title(same_line_title):
                if index + 1 < len(lines):
                    continuation = clean_course_title(lines[index + 1])
                    if (
                        len(same_line_title) <= 30
                        and len(continuation.split()) <= 3
                        and looks_like_course_title(continuation)
                    ):
                        combined = f"{same_line_title} {continuation}"
                        if looks_like_course_title(combined):
                            return combined
                return same_line_title

        for index in code_line_indexes:
            for nearby_index in (index + 1, index - 1, index + 2):
                if 0 <= nearby_index < len(lines):
                    candidate = clean_course_title(lines[nearby_index])
                    if looks_like_course_title(candidate):
                        return candidate
    return ""


def detect_term(text, filename=""):
    match = re.search(TERM_PATTERN, text, re.IGNORECASE)
    year_first = False
    if not match:
        match = re.search(
            r"\b(20\d{2})[\s_-]+(Spring|Summer|Fall|Autumn|Winter)"
            r"(?:\s+Semester)?\b",
            text,
            re.IGNORECASE,
        )
        year_first = bool(match)
    if not match:
        match = re.search(
            r"(Spring|Summer|Fall|Autumn|Winter)[\s_-]*(20\d{2})",
            filename,
            re.IGNORECASE,
        )
        if not match:
            match = re.search(
                r"(20\d{2})[\s_-]+(Spring|Summer|Fall|Autumn|Winter)",
                filename,
                re.IGNORECASE,
            )
            year_first = bool(match)
            if not match:
                return "", datetime.now().year
    semester_group, year_group = ((2, 1) if year_first else (1, 2))
    semester = match.group(semester_group).title()
    return ("Fall" if semester == "Autumn" else semester), int(
        match.group(year_group)
    )


def detect_course_metadata(text, filename=""):
    course_code = detect_course_code(text)
    course_name = detect_course_name(text, course_code)
    semester, year = detect_term(text, filename)
    return {
        "course_name": course_name,
        "course_code": course_code,
        "semester": semester,
        "year": year,
    }
