import io
import re
from datetime import datetime, timedelta

from pypdf import PdfReader

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

try:
    import numpy as np
    import pypdfium2 as pdfium
    from rapidocr_onnxruntime import RapidOCR
except ImportError:
    np = None
    pdfium = None
    RapidOCR = None


_OCR_ENGINE = None


DATE_PATTERN = (
    r"\b(?:January|Jan\.?|February|Feb\.?|March|Mar\.?|April|Apr\.?|"
    r"May|June|Jun\.?|July|Jul\.?|August|Aug\.?|September|Sept\.?|"
    r"Sep\.?|October|Oct\.?|November|Nov\.?|December|Dec\.?)"
    r"\s+\d{1,2}(?:st|nd|rd|th)?(?:,\s+\d{4})?\b"
    r"|\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b"
    r"|\b\d{1,2}-(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b"
)

DAY_FIRST_DATE_PATTERN = (
    r"\b\d{1,2}\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|"
    r"May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|"
    r"Nov(?:ember)?|Dec(?:ember)?)\.?(?:\s+\d{4})?\b"
)

COURSE_CODE_PATTERN = r"\b[A-Z]{2,5}\s*-?\s*\d{3,4}[A-Z]?\b"

TERM_PATTERN = (
    r"\b(Spring|Summer|Fall|Autumn|Winter)\s+(20\d{2})\b"
)

WEEKDAY_PATTERN = (
    r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)"
)


ASSESSMENT_WORDS = [
    "assignment",
    "homework",
    "quiz",
    "exam",
    "midterm",
    "final",
    "project",
    "paper",
    "presentation",
    "test",
    "lab",
    "report",
    "proposal",
    "demo",
    "reflection",
    "log",
    "extra credit",
    "syllabus",
    "class work",
    "peer review",
    "pitch",
    "spotlight",
]


EXCLUDED_CONTEXTS = [
    "course policy",
    "attendance",
    "absence",
    "religious holiday",
    "accommodation",
    "notify your instructor",
    "instructor notice",
    "cios",
    "office hours",
    "regrade",
    "rubric",
    "deduction",
    "grade breakdown",
    "testing center",
    "starting the week",
    "specific dates",
    "makeup exam",
    "makeup quiz",
    "course calendar",
    "registrar",
    "conflict period",
    "general information",
    "no class",
    "review session",
    "exam review",
    "q&a session",
    "debrief",
    "progress report",
    "withdraw",
    "make-up",
    "makeup",
    "grades will be",
    "scheduled on the following",
]


EXCLUDED_HEADINGS = [
    "attendance",
    "accommodations",
    "religious holidays",
    "regrade requests",
    "makeup quizzes and exams",
    "office hours",
    "general information",
]


def get_lines(text):
    return [
        re.sub(r"\s+", " ", line).strip()
        for line in text.splitlines()
        if line.strip()
    ]


def get_ocr_engine():
    global _OCR_ENGINE

    if RapidOCR is None:
        return None

    if _OCR_ENGINE is None:
        _OCR_ENGINE = RapidOCR()

    return _OCR_ENGINE


def page_needs_ocr(page, page_text):
    if len(page_text.strip()) >= 80 or not page.images:
        return False

    page_area = float(page.width * page.height)
    image_area = sum(
        max(0, image["x1"] - image["x0"])
        * max(0, image["y1"] - image["y0"])
        for image in page.images
    )

    return page_area > 0 and image_area / page_area >= 0.25


def extract_ocr_page(pdf_bytes, page_index):
    engine = get_ocr_engine()

    if engine is None or pdfium is None or np is None:
        return "", []

    pdf = pdfium.PdfDocument(pdf_bytes)
    image = pdf[page_index].render(scale=2.5).to_pil()
    result, _ = engine(np.array(image))
    words = []

    for box, text, score in result or []:
        x_values = [point[0] for point in box]
        y_values = [point[1] for point in box]
        words.append(
            {
                "text": text.strip(),
                "score": float(score),
                "x0": min(x_values),
                "x1": max(x_values),
                "top": min(y_values),
                "bottom": max(y_values),
            }
        )

    words.sort(key=lambda word: (word["top"], word["x0"]))
    return "\n".join(word["text"] for word in words), words


def extract_pdf_document(uploaded_file):
    """Extract page text and tables while keeping a pypdf fallback."""
    pages = []
    uploaded_file.seek(0)
    pdf_bytes = uploaded_file.read()

    if pdfplumber is not None:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                page_text = page.extract_text() or ""
                tables = page.extract_tables() or []
                source = "text"
                ocr_words = []

                if page_needs_ocr(page, page_text):
                    ocr_text, ocr_words = extract_ocr_page(
                        pdf_bytes,
                        page_number - 1,
                    )
                    if ocr_text.strip():
                        page_text = ocr_text
                        source = "ocr"

                pages.append(
                    {
                        "page": page_number,
                        "text": page_text,
                        "tables": tables,
                        "source": source,
                        "ocr_words": ocr_words,
                    }
                )

    if not pages:
        reader = PdfReader(io.BytesIO(pdf_bytes))

        for page_number, page in enumerate(reader.pages, start=1):
            page_text = page.extract_text() or ""
            pages.append(
                {
                    "page": page_number,
                    "text": page_text,
                    "tables": [],
                    "source": "text",
                    "ocr_words": [],
                }
            )

    combined_text = "\n".join(page["text"] for page in pages)
    notices = detect_platform_notices(combined_text)

    return {
        "text": combined_text,
        "pages": pages,
        "notices": notices,
    }


def extract_pdf_text(uploaded_file):
    """Backward-compatible text-only PDF extraction helper."""
    return extract_pdf_document(uploaded_file)["text"]


def detect_platform_notices(text):
    """Describe dated work maintained on a course platform, without guessing dates."""
    compact = re.sub(r"\s+", " ", text).lower()
    signals = (
        "due dates will be announced",
        "assignment due dates",
        "date provided in the canvas assignment",
        "dates are posted",
        "deadlines specified above",
        "posted deadline",
        "living schedule is linked",
        "see course assignments for additional instructions",
        "about one per week",
    )
    recurring_platform_work = bool(
        re.search(
            r"(?:weekly\s+homework|homework assignments?).{0,100}"
            r"(?:canvas|learning catalytics|webwork|mylab|mystatlab|launchpad)",
            compact,
        )
    )
    if not recurring_platform_work and not any(signal in compact for signal in signals):
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
        label
        for label, pattern in platform_patterns
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

    course_code = course_code.upper()
    course_code = course_code.replace("-", " ")

    return re.sub(r"\s+", " ", course_code).strip()


def detect_course_code(text):
    vip_match = re.search(
        r"\bVIP\s+Section\s+([A-Z]{1,4}\d{1,3})\b",
        text,
        re.IGNORECASE,
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

    match = re.search(
        COURSE_CODE_PATTERN,
        text,
        re.IGNORECASE,
    )

    if not match:
        return ""

    return normalize_course_code(match.group())


def clean_course_title(title):
    title = title.strip(" ,:;-–—|")

    title = re.sub(
        r"^(course title|course name)\s*[:\-]\s*",
        "",
        title,
        flags=re.IGNORECASE,
    )
    title = re.sub(
        r"^Syllabus\s+for\s+the\s+",
        "",
        title,
        flags=re.IGNORECASE,
    )

    title = re.sub(
        r"\(?\b(?:Spring|Summer|Fall|Autumn|Winter)\s+20\d{2}\b\)?",
        "",
        title,
        flags=re.IGNORECASE,
    )
    title = re.sub(r"\(\s*\)", "", title)
    title = re.sub(
        r"\bCourse\s+Mode\s+Information\b.*$",
        "",
        title,
        flags=re.IGNORECASE,
    )
    title = re.sub(
        r",?\s*Section\s+[A-Z0-9-]+"
        r"(?:\s*,\s*\d+\s*Credits?)?\s*,?$",
        "",
        title,
        flags=re.IGNORECASE,
    )
    title = re.sub(
        r",?\s*\d+\s*Credits?\s*,?$",
        "",
        title,
        flags=re.IGNORECASE,
    )

    title = re.sub(r"\s+", " ", title).strip(" ,:;-–—|")
    if title.isupper():
        title = " ".join(
            word if len(re.sub(r"[^A-Z]", "", word)) <= 3 else word.title()
            for word in title.split()
        )
    return title


def looks_like_course_title(line):
    if not line:
        return False

    if len(line) < 4 or len(line) > 100:
        return False

    lowered = line.lower()

    rejected_words = [
        "syllabus",
        "instructor",
        "professor",
        "office hours",
        "email",
        "course description",
        "grading",
        "schedule",
        "semester",
        "department",
        "university",
        "college",
        "meeting time",
        "meeting times",
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

    # Best case:
    # Course Number and Title: MATH 1553, Introduction to Linear Algebra
    explicit_match = re.search(
        r"Course Number and Title\s*:\s*"
        r"[A-Z]{2,5}\s*-?\s*\d{3,4}[A-Z]?"
        r"\s*[,;:\-]\s*(.+)",
        text,
        re.IGNORECASE,
    )

    if explicit_match:
        title = clean_course_title(
            explicit_match.group(1).splitlines()[0]
        )

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
        normalized_code = re.sub(
            r"[\s\-]",
            "",
            course_code.upper(),
        )

        for index, line in enumerate(lines[:60]):
            normalized_line = re.sub(
                r"[\s\-]",
                "",
                line.upper(),
            )

            if normalized_code not in normalized_line:
                continue

            same_line_title = re.sub(
                COURSE_CODE_PATTERN,
                "",
                line,
                flags=re.IGNORECASE,
            )

            same_line_title = clean_course_title(
                same_line_title
            )

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

            for nearby_index in [
                index + 1,
                index - 1,
                index + 2,
            ]:
                if 0 <= nearby_index < len(lines):
                    candidate = clean_course_title(
                        lines[nearby_index]
                    )

                    if looks_like_course_title(candidate):
                        return candidate

    return ""


def detect_term(text, filename=""):
    match = re.search(
        TERM_PATTERN,
        text,
        re.IGNORECASE,
    )

    if not match:
        filename_match = re.search(
            r"(Spring|Summer|Fall|Autumn|Winter)[\s_-]*(20\d{2})",
            filename,
            re.IGNORECASE,
        )
        if not filename_match:
            return "", datetime.now().year
        semester = filename_match.group(1).title()
        if semester == "Autumn":
            semester = "Fall"
        return semester, int(filename_match.group(2))

    semester = match.group(1).title()

    if semester == "Autumn":
        semester = "Fall"

    return semester, int(match.group(2))


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


def normalize_date(date_text, course_year):
    date_text = date_text.strip().strip(".,;:")

    day_month_match = re.fullmatch(
        r"(\d{1,2})[\s-]+([A-Za-z]{3,9})\.?(?:\s+(\d{4}))?",
        date_text,
    )

    if day_month_match:
        year = day_month_match.group(3) or str(course_year)
        date_value = (
            f"{day_month_match.group(1)} "
            f"{day_month_match.group(2)} {year}"
        )
        try:
            parsed_date = datetime.strptime(date_value, "%d %b %Y")
        except ValueError:
            parsed_date = datetime.strptime(date_value, "%d %B %Y")

    elif date_text.count("/") == 2:
        month, day, year = date_text.split("/")

        if len(year) == 2:
            year = f"20{year}"

        parsed_date = datetime.strptime(
            f"{month}/{day}/{year}",
            "%m/%d/%Y",
        )

    elif date_text.count("/") == 1:
        parsed_date = datetime.strptime(
            f"{date_text}/{course_year}",
            "%m/%d/%Y",
        )

    else:
        cleaned_date = re.sub(
            r"(\d)(st|nd|rd|th)\b",
            r"\1",
            date_text,
            flags=re.IGNORECASE,
        )

        cleaned_date = cleaned_date.replace(".", "")
        cleaned_date = cleaned_date.replace(",", "")

        if not re.search(r"\b\d{4}\b", cleaned_date):
            cleaned_date = f"{cleaned_date} {course_year}"

        try:
            parsed_date = datetime.strptime(
                cleaned_date,
                "%B %d %Y",
            )
        except ValueError:
            parsed_date = datetime.strptime(
                cleaned_date,
                "%b %d %Y",
            )

    return parsed_date.strftime("%Y-%m-%d")


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
            continue

        append_deadline(
            deadlines,
            seen,
            item,
            due_match.group(1),
            course_year,
        )

    return deadlines


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
    item = re.sub(
        r"^\d{1,2}:\d{2}\s*(?:AM|PM)\s*[-–—]\s*"
        r"\d{1,2}:\d{2}\s*(?:AM|PM)\s*",
        "",
        item,
        flags=re.IGNORECASE,
    )
    item = re.sub(r"\s+", " ", item)
    return item.strip(" .,:;-–—")


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


def scheduled_event_kind(item):
    lowered = item.lower().strip()

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


def candidate_row(item, raw_date, course_year, confidence="High",
                  reason="Explicit due date", include=True):
    """Build a candidate row while safely ignoring impossible dates."""
    try:
        if re.fullmatch(r"20\d{2}-\d{2}-\d{2}", raw_date):
            datetime.strptime(raw_date, "%Y-%m-%d")
            normalized_date = raw_date
        else:
            normalized_date = normalize_date(raw_date, course_year)
    except ValueError:
        return None
    return {
        "Item": item,
        "Date": raw_date,
        "Normalized Date": normalized_date,
        "_confidence": confidence,
        "_reason": reason,
        "_include": include,
    }


def extract_section_final_candidates(text, course_year):
    """Read section-specific finals regardless of date/section ordering."""
    rows = []
    seen = set()
    compact = re.sub(r"\s+", " ", text)

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

        if not inside_table or not line:
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
            item = re.sub(r"\s+\d+(?:\.\d+)?%.*$", "", line).strip()

            if item.lower().startswith("final section"):
                item = "Final Exam"

            if item:
                append_deadline(
                    deadlines,
                    seen,
                    item,
                    pending_date,
                    course_year,
                )
            pending_date = None

    return deadlines


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


def locate_candidate_source(row, pages, course_year):
    """Find the page containing a document-wide candidate's date and item terms."""
    target_date = row["Normalized Date"]
    item_tokens = {
        token
        for token in candidate_item_tokens(row["Item"])
        if len(token) >= 4
    }
    best_match = None

    for page in pages:
        page_text = page.get("text", "")
        page_dates = set()
        for date_match in re.finditer(DATE_PATTERN, page_text, re.IGNORECASE):
            try:
                page_dates.add(normalize_date(date_match.group(), course_year))
            except ValueError:
                continue
        if target_date not in page_dates:
            continue

        lowered = page_text.lower()
        score = 10 + sum(token in lowered for token in item_tokens)
        raw_date = str(row.get("Date", "")).lower()
        if raw_date and raw_date in lowered:
            score += 2
        if best_match is None or score > best_match[0]:
            best_match = (
                score,
                page.get("page"),
                page.get("source", "text").upper(),
            )

    if best_match:
        return best_match[1], best_match[2]
    return None, "TEXT"


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


def word_to_number(value):
    values = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
    }
    return int(value) if value.isdigit() else values.get(value.lower(), 0)


def extract_relative_deadlines(text, candidates):
    generated = []
    exams = {}

    for candidate in candidates:
        match = re.fullmatch(
            r"Exam\s*#?\s*(\d+)(?:\s+.*)?",
            candidate["Item"],
            re.IGNORECASE,
        )
        if match:
            exams[int(match.group(1))] = candidate["Normalized Date"]

    homework_match = re.search(
        r"(?:There are\s+)?(\d+|one|two|three|four|five|six)\s+sets?\s+of\s+homework"
        r".*?corresponding\s+to\s+the\s+(?:\w+\s+)?exams?",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if homework_match:
        count = word_to_number(homework_match.group(1))
        for number in range(1, count + 1):
            if number in exams:
                generated.append(
                    {
                        "Item": f"Homework Set {number}",
                        "Date": exams[number],
                        "Normalized Date": exams[number],
                    }
                )

    submission_match = re.search(
        r"(\d+|one|two|three|four|five|six)\s+submissions?.{0,160}?"
        r"due\s+on\s+each\s+exam\s+day",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if submission_match:
        count = word_to_number(submission_match.group(1))
        prefix_text = text[:submission_match.start()]
        headings = re.findall(
            r"^\s*([A-Z][A-Z\- ]{4,})\s*$",
            prefix_text,
            re.MULTILINE,
        )
        label = headings[-1].title() if headings else "Project Submission"
        for number in range(1, count + 1):
            if number in exams:
                generated.append(
                    {
                        "Item": f"{label} {number}",
                        "Date": exams[number],
                        "Normalized Date": exams[number],
                    }
                )

    return generated


def extract_deadline_candidates(document, course_year):
    """Return reviewable deadline suggestions with source information."""
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

        if assignment_due_deadlines:
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
            (row["Item"].lower(), row["Normalized Date"])
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


def append_deadline(
    deadlines,
    seen,
    item,
    raw_date,
    course_year,
):
    try:
        normalized_date = normalize_date(
            raw_date,
            course_year,
        )
    except ValueError:
        return

    key = (
        item.lower().strip(),
        normalized_date,
    )

    if key in seen:
        return

    seen.add(key)

    deadlines.append(
        {
            "Item": item,
            "Date": raw_date,
            "Normalized Date": normalized_date,
        }
    )


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

            remaining_exam_lines -= 1

            if remaining_exam_lines <= 0:
                inside_exam_list = False

        if (
            inside_exam_list
            and "final exam" in lowered
            and not line_is_excluded(line)
        ):
            date_match = re.search(
                DATE_PATTERN,
                line,
                re.IGNORECASE,
            )

            if date_match:
                append_deadline(
                    deadlines,
                    seen,
                    "Final Exam",
                    date_match.group(),
                    course_year,
                )

    return deadlines


def extract_deadlines(text, course_year):
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
