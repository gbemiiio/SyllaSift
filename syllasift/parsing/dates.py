import re
from datetime import datetime


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
        parsed_date = datetime.strptime(f"{month}/{day}/{year}", "%m/%d/%Y")
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
        try:
            parsed_date = datetime.strptime(cleaned_date, "%B %d %Y")
        except ValueError:
            parsed_date = datetime.strptime(cleaned_date, "%b %d %Y")
    return parsed_date.strftime("%Y-%m-%d")
