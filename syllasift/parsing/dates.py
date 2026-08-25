import re
from datetime import datetime

from .patterns import DATE_PATTERN, DAY_FIRST_DATE_PATTERN


class CourseYear(int):
    """Integer-compatible course year carrying optional term context."""

    def __new__(cls, value, semester=None):
        instance = super().__new__(cls, value)
        instance.semester = semester
        return instance


def course_year_context(course_year, semester=None):
    if semester is None and isinstance(course_year, CourseYear):
        return course_year
    return CourseYear(course_year, semester)


def normalize_date(date_text, course_year, semester=None):
    semester = semester if semester is not None else getattr(
        course_year, "semester", None
    )
    original = str(date_text or "").strip().strip(".,;:")
    date_text = re.sub(r"\bSept\b", "Sep", original, flags=re.IGNORECASE)
    try:
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
            parsed_date = _parse_formats(date_value, "%d %b %Y", "%d %B %Y")
        elif date_text.count("/") == 2:
            month, day, year = date_text.split("/")
            if len(year) == 2:
                year = f"20{year}"
            parsed_date = datetime.strptime(
                f"{month}/{day}/{year}", "%m/%d/%Y"
            )
        elif date_text.count("/") == 1:
            parsed_date = datetime.strptime(
                f"{date_text}/{course_year}", "%m/%d/%Y"
            )
        else:
            cleaned_date = re.sub(
                r"(\d)(st|nd|rd|th)\b",
                r"\1",
                date_text,
                flags=re.IGNORECASE,
            ).replace(".", "").replace(",", "")
            if not re.search(r"\b\d{4}\b", cleaned_date):
                cleaned_date = f"{cleaned_date} {course_year}"
            parsed_date = _parse_formats(
                cleaned_date, "%B %d %Y", "%b %d %Y"
            )
    except (TypeError, ValueError):
        raise ValueError(f"Invalid or unsupported date: {original}") from None
    has_explicit_year = bool(re.search(r"\b\d{4}\b", date_text)) or (
        date_text.count("/") == 2
    )
    if (
        not has_explicit_year
        and str(semester or "").strip().lower() in {"fall", "autumn"}
        and parsed_date.month <= 6
    ):
        parsed_date = parsed_date.replace(year=int(course_year) + 1)
    return parsed_date.strftime("%Y-%m-%d")


def _parse_formats(value, *formats):
    for date_format in formats:
        try:
            return datetime.strptime(value, date_format)
        except ValueError:
            continue
    raise ValueError


def find_invalid_date_texts(text, course_year, semester=None):
    """Return unique date-like strings that cannot be normalized."""
    invalid = []
    seen = set()
    for pattern in (DATE_PATTERN, DAY_FIRST_DATE_PATTERN):
        for match in re.finditer(pattern, str(text or ""), re.IGNORECASE):
            raw_date = match.group().strip()
            key = raw_date.casefold()
            if key in seen:
                continue
            seen.add(key)
            try:
                normalize_date(raw_date, course_year, semester)
            except ValueError:
                invalid.append(raw_date)
    return invalid


def invalid_date_warning(invalid_dates):
    if not invalid_dates:
        return ""
    examples = ", ".join(f'"{value}"' for value in invalid_dates[:3])
    suffix = " and others" if len(invalid_dates) > 3 else ""
    return f"Skipped date text that could not be parsed: {examples}{suffix}."
